"""Evidence retrieval for the filter: find the works that refute or debate a paper.

Behind the ``Retriever`` Protocol:
  * ``stub`` — offline. Uses the paper's own ``CommentsCorrectionsList`` links as the
    evidence pool: a ``RetractionIn`` becomes a refuting retraction notice, a
    ``CommentIn``/``ErratumIn`` becomes a debating comment. No network, but the signal is
    real structure from the XML, so a retracted paper is correctly flagged.
  * ``live`` — queries PubMed + Europe PMC for the claim and fetches the linked dispute
    PMIDs, reusing the existing Source machinery. Needs network.

The pool is per (paper, claim); the stub returns the same paper-level links for each claim
since it has no claim-level signal offline.
"""

from __future__ import annotations

import os
from typing import Protocol

from .ingest import DISPUTE_REFTYPES
from ..schema import Candidate, ExtractedClaim, PaperRecord

_REFUTING_REFTYPES = {"RetractionIn"}


class Retriever(Protocol):
    name: str

    def retrieve(self, paper: PaperRecord, claim: ExtractedClaim, *, limit: int) -> list[Candidate]:
        """Return candidate evidence works for one claim of a paper."""
        ...


class StubRetriever:
    """Offline retriever built from the paper's own comment/correction links."""

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
            abstract="This article has been retracted and withdrawn; it showed no benefit and increased risk.",
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
    """Network retriever reusing the Source providers plus the paper's dispute links."""

    name = "live"

    def retrieve(self, paper: PaperRecord, claim: ExtractedClaim, *, limit: int = 20) -> list[Candidate]:
        from ..http import make_client
        from ..sources.base import get_sources
        from ..sources.pubmed import efetch

        by_id: dict[str, Candidate] = {}
        with make_client() as client:
            for source in get_sources():
                for c in source.search_claim(claim.normalized, limit=limit, client=client):
                    by_id.setdefault(c.ext_id, c)
            dispute_pmids = [
                pmid for rt in DISPUTE_REFTYPES for pmid in paper.comments_corrections.get(rt, [])
            ]
            for c in efetch(dispute_pmids, client=client):
                c.retrieved_by = sorted(set(c.retrieved_by) | {"links"})
                by_id[c.ext_id] = c
        return list(by_id.values())[:limit]


def get_retriever() -> Retriever:
    """Build the configured retriever. Defaults to the offline stub."""
    backend = os.environ.get("MEDFACT_RETRIEVER", "stub").lower()
    return LiveRetriever() if backend == "live" else StubRetriever()
