"""Sorts the studies a search already found, putting the most relevant ones first.

An embedder is a model that turns a piece of text into a list of numbers that stands in
for what the text means, so two texts with similar meaning end up with similar numbers
even if they do not share the same words. This module embeds the claim and each
retrieved study's title and abstract, then uses how close those numbers are to sort the
studies from most to least relevant.

This module does not search PubMed or Europe PMC itself. It only re-orders the pool of
studies those searches already returned. If a study was never returned by the search in
the first place, no amount of re-ordering can find it (see the ``not_indexed`` failure
bucket).

Why re-order at all? A claim's pool can hold hundreds of studies, and having a language
model read every one to judge its stance would be slow and expensive. The validation tool
(``orchestration.harness``) uses this ranking to pick the top ``STANCE_TOP_K`` (20 by
default) studies to send to that stance step.

In validation, the study already known to disprove each claim is always sent to the
stance step regardless of where this module ranks it, so a bad ranking can never hide it
from the headline recall numbers. The real filter has no such known answer for new
papers, so a future ranking step there would need to be trustworthy on its own; the
``recall@k`` metric (``reporting/metrics.py``) tracks how often the right study would
have landed near the top.

Two ranking backends are available (see ``base.embedder``):
  * ``stub`` (the default) is fast, offline, and does not understand meaning, so its
    order is close to random. It lets tests and offline runs work without a network
    connection or a downloaded model.
  * ``sbert`` is a real, pretrained biomedical language model. Turn it on with the
    ``embed`` optional dependency and ``MEDSCREEN_EMBED_BACKEND=sbert``.

Status: ``sbert`` is optional and off by default (the ``stub`` needs no model or network).
Retrieval recall does not depend on ranking at all. When ``sbert`` is selected
(``MEDSCREEN_EMBED_BACKEND=sbert``) it is used in two places: the harness ranks the pool for the
``recall@k`` metric and to pick the top ``STANCE_TOP_K`` to stance-judge, and the production
filter (``scraping.evidence.LiveRetriever``) ranks a claim's query hits before capping them, so
the studies sent to the stance LLM are the most relevant rather than the first found. Both read
and write the same DuckDB embedding cache (``store.embeddings``, keyed by candidate id and model),
so a study is embedded once and reused across claims, papers, and runs.
"""

from __future__ import annotations

import hashlib
import math
import os

from ..base.embedder import Embedder

_STUB_DIM = 256


class StubEmbedder:
    """Fake, offline ranking based on word hashing. It does not understand meaning, so its
    order is close to random. It exists so tests and offline runs work without a network
    connection or a downloaded model."""

    name = "stub"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * _STUB_DIM
        for token in text.lower().split():
            h = int(hashlib.md5(token.encode()).hexdigest(), 16)
            vec[h % _STUB_DIM] += 1.0
        return vec


def _best_device() -> str:
    """Pick the fastest available torch device: CUDA, then Apple MPS, then CPU.

    Overridable with ``MEDSCREEN_EMBED_DEVICE``. Ranking a large candidate pool per claim is the
    main embedding cost at scale, so using the GPU when present matters.
    """
    override = os.environ.get("MEDSCREEN_EMBED_DEVICE")
    if override:
        return override
    try:
        import torch  # lazy: only when sbert is selected

        if torch.cuda.is_available():
            return "cuda"
        if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
            return "mps"
    except Exception:  # noqa: BLE001 - any torch/probe failure just falls back to CPU
        pass
    return "cpu"


class SentenceTransformerEmbedder:
    """Real ranking using a pretrained biomedical language model, via the sentence-transformers
    package (the optional ``embed`` dependency).

    Runs on the GPU when one is available (CUDA or Apple MPS), falling back to CPU, so ranking a
    large candidate pool stays fast at scale. The sentence-transformers import is lazy, so this
    class and the heavy dependency cost nothing unless ``sbert`` is actually selected."""

    def __init__(self, model_name: str = "pritamdeka/S-PubMedBert-MS-MARCO") -> None:
        # Lazy import: sentence-transformers (and torch) load only when sbert is selected, so the
        # default stub path never touches the optional dependency.
        from sentence_transformers import SentenceTransformer  # lazy import

        self.name = model_name
        self.device = _best_device()
        self._model = SentenceTransformer(model_name, device=self.device)

    def embed(self, texts: list[str]) -> list[list[float]]:
        vecs = self._model.encode(
            texts, normalize_embeddings=False, batch_size=64, show_progress_bar=False
        )
        return [list(map(float, v)) for v in vecs]


def get_embedder() -> Embedder:
    # The stub is the default and is all the POC needs. sbert is opt-in via the `embed` extra plus
    # MEDSCREEN_EMBED_BACKEND=sbert, kept for recall@k and future ranking-based truncation.
    backend = os.environ.get("MEDSCREEN_EMBED_BACKEND", "stub").lower()
    if backend == "sbert":
        return SentenceTransformerEmbedder(
            os.environ.get("MEDSCREEN_EMBED_MODEL", "pritamdeka/S-PubMedBert-MS-MARCO")
        )
    return StubEmbedder()


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def rank_by_similarity(
    query_vec: list[float], pool: list[tuple[str, list[float]]]
) -> list[tuple[str, float]]:
    """Rank an (ext_id, vector) pool by cosine to query_vec, descending."""
    scored = [(ext_id, cosine(query_vec, vec)) for ext_id, vec in pool]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored
