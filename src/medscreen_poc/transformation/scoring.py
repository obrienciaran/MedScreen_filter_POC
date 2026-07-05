"""Turn stance labels into per-claim and per-paper truthfulness verdicts.

The score is grounded in evidence rather than a model opinion. Refutation strength is the
stance confidence weighted by the refuting study's evidence tier, so a high-tier RCT or
guideline that contradicts a claim moves the verdict far more than a case report. A paper
is judged as harshly as its most damning claim, because one confidently wrong central claim
is enough to want the paper down-weighted or dropped from training.

These functions are pure and unit-tested. Thresholds are module constants so the policy is
visible and tunable rather than buried.
"""

from __future__ import annotations

from ..schema import (
    Action,
    Candidate,
    ClaimVerdict,
    ExtractedClaim,
    PaperRecord,
    PaperVerdict,
    Stance,
    StanceLabel,
    Verdict,
)

# A claim is REFUTED (which drops the paper) only when the strongest refutation clears all
# three floors at once, so a DROP is reserved for unambiguous, high-tier, high-confidence
# contradiction. Anything weaker (a low-tier refutation, an unsure judge, or a strength below
# the bar) falls back to CONTESTED, which down-weights rather than drops. This optimises for
# precision on the destructive action: we would rather down-weight a bad paper than drop a
# good one. The floors are separate on purpose (rather than one combined strength) so a very
# confident judgement on a weak study cannot substitute for a strong study, or vice versa.
DROP_MIN_STRENGTH = 0.6  # aggregate refuting strength (see _aggregate_strength)
DROP_MIN_TIER = 0.8  # the single strongest refuting study must be an RCT or higher
DROP_MIN_CONFIDENCE = 0.7  # stance judge must be confident in that strongest refutation

# How much a consistent body of evidence counts beyond its single strongest study. Judging a
# claim by one study alone is fragile: a lone mis-tiered or mis-judged study swings the verdict,
# and genuine corroboration across several studies (which is how medical consensus actually
# forms) is ignored. So refuting and supporting pulls are aggregated rather than reduced to a
# single max. Each agreeing study beyond the strongest closes this fraction of the remaining gap
# to 1.0, scaled by its own pull, so corroboration strengthens the verdict with diminishing
# returns while no pile-up of weak studies can overpower one strong study. At 0.0 this collapses
# back to the old single-strongest-pull behaviour.
CORROBORATION_WEIGHT = 0.5

# Default action per verdict. Neutral is kept, because a missing refutation when neutral
# evidence *was* found is not proof of falsity. Ungrounded is different: no evidence was found
# at all, so the claim has no corroboration in the literature. That is its own signal and is
# flagged for review rather than silently kept. The continuous score is also written so the
# user can set a threshold.
_ACTION_BY_VERDICT = {
    Verdict.REFUTED: Action.DROP,
    Verdict.CONTESTED: Action.DOWNWEIGHT,
    Verdict.SUPPORTED: Action.KEEP,
    Verdict.NEUTRAL: Action.KEEP,
    Verdict.UNGROUNDED: Action.REVIEW,
}


def score_claim(
    claim: ExtractedClaim, candidates: list[Candidate], labels: list[StanceLabel]
) -> ClaimVerdict:
    """Weigh one claim's evidence into a verdict and a 0..1 truthfulness score."""
    tier = {c.ext_id: c.evidence_tier for c in candidates}
    refuting = [l for l in labels if l.stance is Stance.REFUTES]
    supporting = [l for l in labels if l.stance is Stance.SUPPORTS]

    def pull(label: StanceLabel) -> float:
        return tier.get(label.candidate_ext_id, 0.4) * label.confidence

    year_by_id = {c.ext_id: c.year for c in candidates}
    top_refuter = max(refuting, key=pull, default=None)
    # Aggregate the whole body of agreeing evidence, not just the single strongest study, so
    # consistency and volume count (with diminishing returns). The strongest study still sets
    # the floor, so a lone landmark trial refutes on its own.
    refute_strength = _aggregate_strength([pull(l) for l in refuting])
    support_strength = _aggregate_strength([pull(l) for l in supporting])
    top_refuting_tier = max((tier.get(l.candidate_ext_id, 0.4) for l in refuting), default=0.0)
    # Tier and confidence of the single strongest refuter, judged together against the DROP
    # floors below. Kept separate from top_refuting_tier, which is the max tier across all
    # refuters regardless of confidence.
    refuting_tier = tier.get(top_refuter.candidate_ext_id, 0.4) if top_refuter else 0.0
    refuting_confidence = top_refuter.confidence if top_refuter else 0.0
    refuting_year = year_by_id.get(top_refuter.candidate_ext_id) if top_refuter else None

    score = _clamp(0.5 + 0.4 * support_strength - 0.8 * refute_strength)
    verdict = _claim_verdict(
        len(labels), top_refuter is not None, bool(supporting),
        refute_strength, refuting_tier, refuting_confidence,
    )

    return ClaimVerdict(
        claim_id=claim.claim_id, claim_text=claim.claim_text,
        n_evidence=len(labels), n_refuting=len(refuting), n_supporting=len(supporting),
        top_refuting_tier=top_refuting_tier, verdict=verdict, score=score,
        refuting_confidence=refuting_confidence, refuting_year=refuting_year,
        refuting_pmids=[l.candidate_ext_id for l in refuting],
        supporting_pmids=[l.candidate_ext_id for l in supporting],
    )


def _claim_verdict(
    n_evidence: int,
    has_refute: bool,
    has_support: bool,
    refute_strength: float,
    refuting_tier: float,
    refuting_confidence: float,
) -> Verdict:
    if has_refute and has_support:
        return Verdict.CONTESTED  # evidence on both sides is ambiguous, never a drop
    if has_refute:
        unambiguous = (
            refute_strength >= DROP_MIN_STRENGTH
            and refuting_tier >= DROP_MIN_TIER
            and refuting_confidence >= DROP_MIN_CONFIDENCE
        )
        return Verdict.REFUTED if unambiguous else Verdict.CONTESTED
    if has_support:
        return Verdict.SUPPORTED
    if n_evidence == 0:
        return Verdict.UNGROUNDED  # nothing retrieved: the claim is not grounded in the literature
    return Verdict.NEUTRAL  # only neutral evidence: found, but inconclusive


def score_paper(paper: PaperRecord, claim_verdicts: list[ClaimVerdict]) -> PaperVerdict:
    """Roll per-claim verdicts up to the paper, judged by its most damning claim."""
    if not claim_verdicts:
        return PaperVerdict(
            pmid=paper.pmid, title=paper.title, verdict=Verdict.UNGROUNDED, score=0.5,
            action=Action.REVIEW, verdict_basis="none", refutation_timing="unknown",
            n_claims=0, n_refuted_claims=0, top_refuting_tier=0.0, grounded=False,
            notes="no claims extracted",
        )

    score = min(cv.score for cv in claim_verdicts)
    verdict = _paper_verdict(claim_verdicts)
    refuting_pmids = sorted({p for cv in claim_verdicts for p in cv.refuting_pmids})
    return PaperVerdict(
        pmid=paper.pmid, title=paper.title, verdict=verdict, score=score,
        action=_ACTION_BY_VERDICT[verdict], verdict_basis="evidence",
        refutation_timing=_refutation_timing(paper, claim_verdicts),
        n_claims=len(claim_verdicts),
        n_refuted_claims=sum(1 for cv in claim_verdicts if cv.verdict is Verdict.REFUTED),
        top_refuting_tier=max(cv.top_refuting_tier for cv in claim_verdicts),
        grounded=any(cv.n_supporting > 0 for cv in claim_verdicts),
        refuting_pmids=refuting_pmids, claim_verdicts=claim_verdicts,
    )


def _refutation_timing(paper: PaperRecord, claim_verdicts: list[ClaimVerdict]) -> str:
    """Whether the refuting evidence came before or after the paper.

    "prior" if any refuting study predates the paper (it contradicted already-published
    evidence), else "subsequent" (overturned by later evidence, the reversal pattern).
    "unknown" when the paper's year is missing or no refutation carried a year. This is only a
    time ordering, not a claim about whether the paper was ever accepted consensus.
    """
    refuting_years = [cv.refuting_year for cv in claim_verdicts if cv.refuting_year is not None]
    if paper.year is None or not refuting_years:
        return "unknown"
    return "prior" if any(y < paper.year for y in refuting_years) else "subsequent"


def _paper_verdict(claim_verdicts: list[ClaimVerdict]) -> Verdict:
    verdicts = {cv.verdict for cv in claim_verdicts}
    if Verdict.REFUTED in verdicts:
        return Verdict.REFUTED
    if Verdict.CONTESTED in verdicts:
        return Verdict.CONTESTED
    # An ungrounded claim (no evidence at all) is more damning than a supported or merely
    # neutral one, so it surfaces over them in the most-damning-claim rollup.
    if Verdict.UNGROUNDED in verdicts:
        return Verdict.UNGROUNDED
    if Verdict.SUPPORTED in verdicts:
        return Verdict.SUPPORTED
    return Verdict.NEUTRAL


def _aggregate_strength(pulls: list[float]) -> float:
    """Combine the pulls of all studies on one side of a claim into a single strength in [0, 1].

    The strongest study sets the floor, so a lone high-tier trial still carries full weight
    (the WHI trial overturned HRT single-handedly). Each further agreeing study then closes
    ``CORROBORATION_WEIGHT`` of the remaining gap to 1.0, scaled by its own pull, so a consistent
    body of evidence is stronger than any one study while weak studies add little and can never
    overpower a strong one. Pulls already fold in evidence tier, so a case report contributes
    far less than an RCT.
    """
    if not pulls:
        return 0.0
    ordered = sorted(pulls, reverse=True)
    # The strongest study enters at full weight, so a single study reproduces its own pull
    # exactly and the aggregate never drops below the strongest single pull.
    strength = ordered[0]
    for p in ordered[1:]:
        strength += p * (1.0 - strength) * CORROBORATION_WEIGHT
    return min(strength, 1.0)


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))
