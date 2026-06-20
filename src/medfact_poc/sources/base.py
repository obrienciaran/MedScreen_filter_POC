"""The Source interface shared by every evidence provider.

A Source owns one provider end to end: it builds its own queries from a normalized
claim, calls its API, and returns parsed Candidates. The harness depends only on this
interface, so a new provider can be added without touching retrieval logic.

This mirrors the other two plug points in the package (Embedder, StanceBackend), so
all three swappable parts follow the same Protocol shape.
"""

from __future__ import annotations

from typing import Protocol

import httpx

from ..schema import Candidate, NormalizedClaim


class Source(Protocol):
    name: str

    def search_claim(
        self, claim: NormalizedClaim, *, limit: int, client: httpx.Client
    ) -> list[Candidate]:
        """Return candidate evidence for a claim from this provider."""
        ...


def get_sources() -> list[Source]:
    """The active set of evidence providers.

    Add a provider here to include it in retrieval. Order is not significant because
    the harness deduplicates candidates by ext_id across sources.
    """
    from .europepmc import EuropePMCSource
    from .pubmed import PubMedSource

    return [PubMedSource(), EuropePMCSource()]
