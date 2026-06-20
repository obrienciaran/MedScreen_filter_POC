"""Filter orchestration: PubMed paper -> claims -> evidence -> stance -> verdict.

For each paper, extract its claims, retrieve evidence for each claim, judge stance, and
score. Papers are independent, so they run concurrently. The default backends are all
offline stubs, so this runs end to end with no key; swap in real LLM/retriever backends
via env (see ``llm``, ``extract``, ``evidence``, ``stance``).
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from typing import Iterable

from .evidence import Retriever, get_retriever
from .extract import ClaimExtractor, get_extractor
from .scoring import score_claim, score_paper
from ..schema import PaperRecord, PaperVerdict
from ..stance import StanceBackend, classify_batch, get_stance_backend


def run_paper(
    paper: PaperRecord,
    *,
    extractor: ClaimExtractor,
    retriever: Retriever,
    stance_backend: StanceBackend,
    limit: int = 20,
) -> PaperVerdict:
    """Score a single paper end to end."""
    claim_verdicts = []
    for claim in extractor.extract(paper):
        candidates = retriever.retrieve(paper, claim, limit=limit)
        labels = classify_batch(stance_backend, claim.as_gold_entry(), candidates)
        claim_verdicts.append(score_claim(claim, candidates, labels))
    return score_paper(paper, claim_verdicts)


def run_filter(
    papers: Iterable[PaperRecord],
    *,
    extractor: ClaimExtractor | None = None,
    retriever: Retriever | None = None,
    stance_backend: StanceBackend | None = None,
    limit: int = 20,
    max_workers: int | None = None,
) -> list[PaperVerdict]:
    """Score a corpus of papers, concurrently. Returns one PaperVerdict per paper."""
    extractor = extractor or get_extractor()
    retriever = retriever or get_retriever()
    stance_backend = stance_backend or get_stance_backend()
    papers = list(papers)
    if not papers:
        return []
    workers = max_workers or int(os.environ.get("MEDFACT_FILTER_CONCURRENCY", "4"))
    workers = max(1, min(workers, len(papers)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(
            executor.map(
                lambda p: run_paper(
                    p, extractor=extractor, retriever=retriever,
                    stance_backend=stance_backend, limit=limit,
                ),
                papers,
            )
        )
