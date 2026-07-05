"""Shared HTTP client and config for evidence sources.

Centralizes rate limiting and TLS handling. Some environments such as corporate proxies
and sandboxes terminate TLS with a self-signed cert that breaks default verification.
Set ``MEDSCREEN_INSECURE_TLS=1`` or ``MEDSCREEN_CA_BUNDLE=/path/to/ca.pem`` to cope without
editing code. NCBI asks callers to identify themselves with ``NCBI_EMAIL``, and an
``NCBI_API_KEY`` raises the rate limit from 3 to 10 requests per second.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Callable

import httpx

NCBI_EMAIL = os.environ.get("NCBI_EMAIL", "")
NCBI_API_KEY = os.environ.get("NCBI_API_KEY", "")
# 3 req/s without a key, 10 with one (NCBI policy). Stay just under.
_MIN_INTERVAL = 0.34 if not NCBI_API_KEY else 0.11


def _verify() -> bool | str:
    if os.environ.get("MEDSCREEN_INSECURE_TLS") == "1":
        return False
    bundle = os.environ.get("MEDSCREEN_CA_BUNDLE")
    return bundle if bundle else True


class RateLimiter:
    """Process-wide minimum interval between requests, thread-safe."""

    def __init__(self, min_interval: float) -> None:
        self._min_interval = min_interval
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delta = now - self._last
            if delta < self._min_interval:
                time.sleep(self._min_interval - delta)
            self._last = time.monotonic()


_ncbi_limiter = RateLimiter(_MIN_INTERVAL)
_generic_limiter = RateLimiter(0.2)


def make_client(timeout: float = 30.0) -> httpx.Client:
    return httpx.Client(
        timeout=timeout,
        verify=_verify(),
        headers={"User-Agent": f"medscreen-poc-harness ({NCBI_EMAIL or 'anon'})"},
        follow_redirects=True,
    )


def ncbi_params(extra: dict[str, str]) -> dict[str, str]:
    """Augment E-utilities params with identification and key when available."""
    params = dict(extra)
    if NCBI_EMAIL:
        params["email"] = NCBI_EMAIL
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY
    return params


def ncbi_throttle() -> None:
    _ncbi_limiter.wait()


def generic_throttle() -> None:
    _generic_limiter.wait()


def get_with_retry(
    client: httpx.Client,
    url: str,
    params: dict[str, str],
    *,
    throttle: Callable[[], None],
    attempts: int = 5,
    max_delay: float = 15.0,
) -> httpx.Response:
    """GET ``url`` through ``throttle``, retrying on 429/5xx with exponential backoff.

    PubMed and Europe PMC both answer a burst with 429 or a transient 5xx gateway error, so
    back off and retry rather than abort a long run. Any other status raises via
    ``raise_for_status``. Shared by both sources so the backoff policy lives in one place.

    The backoff is a fixed exponential schedule and does not read a ``Retry-After`` header; the
    rate limiter already keeps the request rate under each provider's published ceiling, so a
    429 here is rare and the schedule is enough.
    """
    delay = 1.0
    for attempt in range(attempts):
        throttle()
        r = client.get(url, params=params)
        if (r.status_code == 429 or r.status_code >= 500) and attempt < attempts - 1:
            time.sleep(delay)
            delay = min(delay * 2, max_delay)
            continue
        r.raise_for_status()
        return r
    return r  # unreachable: the final attempt returns or raises inside the loop
