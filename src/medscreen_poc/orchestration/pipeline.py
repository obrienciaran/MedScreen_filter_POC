"""Filter orchestration: PubMed paper, claims, evidence, stance, verdict.

For each paper, extract its claims, retrieve evidence for each claim, judge stance, and
score. Papers are independent, so they run concurrently. The default backends are all
offline stubs, so this runs end to end with no key. Swap in real LLM or retriever backends
via env (see ``llm``, ``transformation.extract``, ``scraping.evidence``,
``transformation.stance``).

Concurrency has two independent bounds so the load on external services is predictable.
Papers fan out across a pool (``MEDSCREEN_FILTER_CONCURRENCY``, default 4) to parallelize
retrieval, while every stance call funnels through one shared pool
(``MEDSCREEN_STANCE_CONCURRENCY``, default 8). Peak worker count is therefore the sum of the
two, not their product, so the stance backend's rate-limit pressure is a single knob.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from typing import Iterable

from ..base.extractor import ClaimExtractor
from ..base.retriever import Retriever
from ..base.stance import StanceBackend
from ..schema import Action, PaperRecord, PaperVerdict, Verdict
from ..scraping.evidence import get_retriever
from ..transformation.extract import get_extractor
from ..transformation.scoring import score_claim, score_paper
from ..transformation.stance import classify_batch, get_stance_backend

# A formal retraction is recorded in the paper's own XML as a RetractionIn link. It is the
# strongest possible refutation and needs no retrieval, so it is checked first and short-
# circuits the paper, skipping extraction, retrieval, and the stance LLM. Matches the
# retraction evidence tier in ``schema.Candidate.evidence_tier``.
RETRACTION_REFTYPE = "RetractionIn"
RETRACTION_TIER = 0.95


def _retracted_verdict(paper: PaperRecord, retraction_pmids: list[str]) -> PaperVerdict:
    """Drop a formally retracted paper without any retrieval or LLM call."""
    return PaperVerdict(
        pmid=paper.pmid, title=paper.title, verdict=Verdict.REFUTED, score=0.0,
        action=Action.DROP, verdict_basis="retraction", refutation_timing="subsequent",
        n_claims=0, n_refuted_claims=0, top_refuting_tier=RETRACTION_TIER, grounded=False,
        refuting_pmids=sorted(retraction_pmids),
        notes="formally retracted (RetractionIn link in the paper's XML)",
    )


def run_paper(
    paper: PaperRecord,
    *,
    extractor: ClaimExtractor,
    retriever: Retriever,
    stance_backend: StanceBackend,
    limit: int = 20,
    stance_executor: ThreadPoolExecutor | None = None,
) -> PaperVerdict:
    """Score a single paper end to end.

    ``stance_executor``, when supplied, is the shared pool every claim's stance calls run
    through, so a batch of papers does not each spin up its own nested pool.
    """
    retraction_pmids = paper.comments_corrections.get(RETRACTION_REFTYPE, [])
    if retraction_pmids:
        return _retracted_verdict(paper, retraction_pmids)

    claim_verdicts = []
    for claim in extractor.extract(paper):
        candidates = retriever.retrieve(paper, claim, limit=limit)
        labels = classify_batch(
            stance_backend, claim.as_gold_entry(), candidates, executor=stance_executor
        )
        claim_verdicts.append(score_claim(claim, candidates, labels))
    return score_paper(paper, claim_verdicts)


def _run_paper_safe(
    paper: PaperRecord,
    *,
    extractor: ClaimExtractor,
    retriever: Retriever,
    stance_backend: StanceBackend,
    limit: int,
    stance_executor: ThreadPoolExecutor | None = None,
) -> PaperVerdict:
    """Run one paper, but turn an unexpected failure into an ``unverified`` row instead of
    aborting the whole batch. A transient network error on one paper should not discard the
    work already done on the others (which matters when those calls cost money)."""
    try:
        return run_paper(
            paper, extractor=extractor, retriever=retriever,
            stance_backend=stance_backend, limit=limit, stance_executor=stance_executor,
        )
    except Exception as exc:  # noqa: BLE001 - isolate one paper's failure from the batch
        print(f"ERROR scoring {paper.pmid}, keeping as unverified. {type(exc).__name__}: {exc}")
        return PaperVerdict(
            pmid=paper.pmid, title=paper.title, verdict=Verdict.UNVERIFIED, score=0.5,
            action=Action.KEEP, verdict_basis="none", refutation_timing="unknown",
            n_claims=0, n_refuted_claims=0, top_refuting_tier=0.0,
            notes=f"error: {type(exc).__name__}: {exc}",
        )


def run_filter(
    papers: Iterable[PaperRecord],
    *,
    extractor: ClaimExtractor | None = None,
    retriever: Retriever | None = None,
    stance_backend: StanceBackend | None = None,
    limit: int = 20,
    max_workers: int | None = None,
) -> list[PaperVerdict]:
    """Score a corpus of papers concurrently. Returns one PaperVerdict per paper."""
    extractor = extractor or get_extractor()
    retriever = retriever or get_retriever()
    stance_backend = stance_backend or get_stance_backend()
    papers = list(papers)
    if not papers:
        return []
    workers = max_workers or int(os.environ.get("MEDSCREEN_FILTER_CONCURRENCY", "4"))
    workers = max(1, min(workers, len(papers)))
    stance_workers = max(1, int(os.environ.get("MEDSCREEN_STANCE_CONCURRENCY", "8")))
    # One shared stance pool for the whole run: paper threads submit into it and block on the
    # results, so total LLM concurrency is bounded by stance_workers rather than
    # workers * stance_workers. No deadlock: stance tasks never submit back to either pool.
    with ThreadPoolExecutor(max_workers=stance_workers) as stance_executor, \
            ThreadPoolExecutor(max_workers=workers) as paper_executor:
        return list(
            paper_executor.map(
                lambda p: _run_paper_safe(
                    p, extractor=extractor, retriever=retriever,
                    stance_backend=stance_backend, limit=limit,
                    stance_executor=stance_executor,
                ),
                papers,
            )
        )
