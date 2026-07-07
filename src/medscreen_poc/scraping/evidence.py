"""Evidence retrieval for the filter: find the works that refute or debate a paper.

Behind the ``Retriever`` Protocol (see ``base.retriever``):
  * ``stub`` is offline. It uses the paper's own ``CommentsCorrectionsList`` links as the
    evidence pool. A ``RetractionIn`` becomes a refuting retraction notice, and a
    ``CommentIn`` or ``ErratumIn`` becomes a debating comment. There is no network, but
    the signal is real structure from the XML, so a retracted paper is correctly flagged.
  * ``live`` queries PubMed and Europe PMC for the claim and fetches the linked dispute
    PMIDs, reusing the existing Source machinery. It needs network access.

The pool is per paper and claim. The stub returns the same paper-level links for each
claim because it has no claim-level signal offline.

Note on the RetractionIn handling below: when driven by ``orchestration.pipeline``, a formally
retracted paper is short-circuited before retrieval is ever called (see ``_retraction_signal``
there), so that path never reaches a retriever. The RetractionIn handling is kept so a retriever
is still correct when used on its own, independent of that upstream fast path.
"""

from __future__ import annotations

import os
import threading

from ..base.retriever import Retriever
from ..schema import Candidate, ExtractedClaim, PaperRecord
from ..transformation.ingest import DISPUTE_REFTYPES

_REFUTING_REFTYPES = {"RetractionIn"}


class StubRetriever:
    """Offline retriever built from the paper's own comment and correction links."""

    name = "stub"

    def retrieve(self, paper: PaperRecord, claim: ExtractedClaim, *, limit: int = 20) -> list[Candidate]:
        out: list[Candidate] = []
        for ref_type in DISPUTE_REFTYPES:
            for pmid in paper.comments_corrections.get(ref_type, []):
                out.append(_synthetic_candidate(pmid, ref_type, paper))
        return out[:limit]


def _synthetic_candidate(pmid: str, ref_type: str, paper: PaperRecord) -> Candidate:
    if ref_type in _REFUTING_REFTYPES:
        return Candidate(
            source="pubmed", ext_id=pmid,
            title=f"Retraction: {paper.title}".strip(),
            abstract="This article has been retracted and withdrawn. It showed no benefit and increased risk.",
            pub_types=["Retraction of Publication"],
            year=paper.year, retrieved_by=["links"], is_retraction_of=[paper.pmid],
        )
    return Candidate(
        source="pubmed", ext_id=pmid,
        title=f"Comment on: {paper.title}".strip(),
        abstract="A published comment debating the findings of the cited article.",
        pub_types=["Comment"], year=paper.year, retrieved_by=["links"],
    )


class LiveRetriever:
    """Network retriever reusing the Source providers plus the paper's dispute links.

    When sbert ranking is selected (``MEDSCREEN_EMBED_BACKEND=sbert``), the query hits are
    re-ranked by semantic similarity to the claim before the pool is capped, so the top ``limit``
    sent to the stance LLM are the most relevant rather than merely the first found. This matters
    at scale, where a claim can match hundreds of studies but only ``limit`` can be judged. Each
    candidate's vector is cached in DuckDB (the same store the harness uses), so a study is
    embedded once and reused across claims, papers, and the harness. Off by default: with the stub
    embedder the pool keeps its cheap link-then-source order and no model is loaded.
    """

    name = "live"

    def __init__(self) -> None:
        self._rerank = os.environ.get("MEDSCREEN_EMBED_BACKEND", "stub").lower() == "sbert"
        self._embedder = None  # lazily loaded on first use (heavy model)
        self._store = None  # shared DuckDB embedding cache
        self._lock = threading.Lock()  # serialises the model and the DuckDB connection

    def _rank_query_hits(self, claim: ExtractedClaim, candidates: list[Candidate]) -> list[Candidate]:
        """Order query-hit candidates by semantic similarity to the claim, most relevant first.

        Vectors are read from and written to the shared DuckDB embedding cache under a lock (the
        model and the DuckDB connection are single-threaded), so each study is embedded once.
        """
        if len(candidates) <= 1:
            return candidates
        from ..store import DEFAULT_DB, Store
        from ..transformation.semantic import get_embedder, rank_by_similarity

        n = claim.normalized
        claim_text = " ".join(
            t for t in (claim.claim_text, n.intervention, n.outcome, n.population) if t
        ).strip()
        with self._lock:
            if self._embedder is None:
                self._embedder = get_embedder()
                self._store = Store(os.environ.get("MEDSCREEN_EMBED_DB", str(DEFAULT_DB)))
            model = self._embedder.name
            vec_by_id: dict[str, list[float]] = {}
            to_embed: list[Candidate] = []
            for c in candidates:
                cached = self._store.get_embedding(c.ext_id, model)
                if cached is None:
                    to_embed.append(c)
                else:
                    vec_by_id[c.ext_id] = cached
            if to_embed:
                for c, vec in zip(to_embed, self._embedder.embed(
                    [f"{c.title} {c.abstract}" for c in to_embed]
                )):
                    self._store.upsert_embedding(c.ext_id, model, vec)
                    vec_by_id[c.ext_id] = vec
            claim_vec = self._embedder.embed([claim_text])[0]
        ranked = rank_by_similarity(
            claim_vec, [(c.ext_id, vec_by_id[c.ext_id]) for c in candidates if c.ext_id in vec_by_id]
        )
        order = {ext_id: i for i, (ext_id, _) in enumerate(ranked)}
        return sorted(candidates, key=lambda c: order.get(c.ext_id, len(candidates)))

    def retrieve(self, paper: PaperRecord, claim: ExtractedClaim, *, limit: int = 20) -> list[Candidate]:
        from .europepmc import enrich_full_text
        from .http import make_client
        from .pubmed import efetch
        from .sources import get_sources

        # Cap and ordering. The pool is capped at `limit` candidates per claim (default 20), which
        # also bounds the downstream stance LLM calls to at most `limit` per claim. When a claim
        # matches more than `limit` candidates, the order that decides who survives the cap is:
        #   1. the paper's own dispute links, retraction notices first (the strongest refutation)
        #      then comment/erratum links, so this highest-signal, lowest-noise evidence is never
        #      truncated by query-hit volume;
        #   2. query hits from the sources, in source order, filling the remaining slots.
        # Query hits are deliberately NOT re-ranked by semantic similarity: that ranking is noisy
        # and would need an embedder or vector index the filter avoids, so cheap and auditable
        # link-then-query order is preferred over an uncertain relevance sort.
        retraction_pmids = [
            pmid for rt in _REFUTING_REFTYPES for pmid in paper.comments_corrections.get(rt, [])
        ]
        other_dispute_pmids = [
            pmid for rt in DISPUTE_REFTYPES if rt not in _REFUTING_REFTYPES
            for pmid in paper.comments_corrections.get(rt, [])
        ]
        # Retraction ahead of comment/erratum, de-duplicated while preserving that order.
        dispute_pmids = list(dict.fromkeys(retraction_pmids + other_dispute_pmids))
        priority: dict[str, Candidate] = {}
        others: dict[str, Candidate] = {}
        with make_client() as client:
            for c in efetch(dispute_pmids, client=client):
                c.retrieved_by = sorted(set(c.retrieved_by) | {"links"})
                priority[c.ext_id] = c
            for source in get_sources():
                try:
                    found = source.search_claim(claim.normalized, limit=limit, client=client)
                except Exception as exc:  # noqa: BLE001 - one source's outage must not unverify the paper
                    print(f"WARN: {source.name} failed for {paper.pmid}, using other sources. "
                        f"{type(exc).__name__}: {exc}")
                    continue
                for c in found:
                    if c.ext_id not in priority:
                        others.setdefault(c.ext_id, c)
            # Dispute links always lead and are never cut. Query hits fill the remaining slots;
            # when sbert ranking is on, order them by semantic relevance to the claim first so the
            # top `limit` are the most relevant, not just the first found.
            query_hits = list(others.values())
            if self._rerank:
                query_hits = self._rank_query_hits(claim, query_hits)
            result = (list(priority.values()) + query_hits)[:limit]
            # Full-text stance is opt-in (network cost). Enrich only the returned pool, and
            # inside the client's lifetime, so the stance judge reads the body where the study
            # is in the open-access subset and the abstract otherwise.
            if os.environ.get("MEDSCREEN_STANCE_FULLTEXT") == "1":
                enrich_full_text(result, client=client)
        return result


def get_retriever() -> Retriever:
    """Build the configured retriever. Defaults to the offline stub."""
    backend = os.environ.get("MEDSCREEN_RETRIEVER", "stub").lower()
    return LiveRetriever() if backend == "live" else StubRetriever()
