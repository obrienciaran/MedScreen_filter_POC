from medscreen_poc.transformation.scoring import score_claim, score_paper
from medscreen_poc.schema import (
    Action,
    Candidate,
    ExtractedClaim,
    NormalizedClaim,
    PaperRecord,
    Stance,
    StanceLabel,
    Verdict,
)


def _claim(pmid: str = "1") -> ExtractedClaim:
    return ExtractedClaim(
        paper_pmid=pmid, index=0, claim_text="Drug X reduces mortality.",
        normalized=NormalizedClaim(intervention="drug x", outcome="mortality"),
    )


def _cand(ext_id: str, pub_types: list[str]) -> Candidate:
    return Candidate(source="pubmed", ext_id=ext_id, pub_types=pub_types)


def test_high_tier_refutation_is_refuted_and_dropped():
    claim = _claim()
    cands = [_cand("R", ["Randomized Controlled Trial"])]
    labels = [StanceLabel(claim_id=claim.claim_id, candidate_ext_id="R",
                          stance=Stance.REFUTES, confidence=0.9)]
    cv = score_claim(claim, cands, labels)
    assert cv.verdict is Verdict.REFUTED
    assert cv.score < 0.4
    assert cv.refuting_pmids == ["R"]

    pv = score_paper(PaperRecord(pmid="1", title="t"), [cv])
    assert pv.verdict is Verdict.REFUTED
    assert pv.action is Action.DROP
    assert pv.refuting_pmids == ["R"]


def test_low_tier_refutation_downweights_not_drops():
    # An observational study refuting at full confidence clears the old single strength
    # threshold, but its tier (0.5) is below the drop floor, so it now contests, not refutes.
    claim = _claim()
    cands = [_cand("R", ["Observational Study"])]
    labels = [StanceLabel(claim_id=claim.claim_id, candidate_ext_id="R",
                          stance=Stance.REFUTES, confidence=1.0)]
    cv = score_claim(claim, cands, labels)
    assert cv.verdict is Verdict.CONTESTED
    assert score_paper(PaperRecord(pmid="1"), [cv]).action is Action.DOWNWEIGHT


def test_low_confidence_high_tier_refutation_downweights_not_drops():
    # A high-tier RCT refuting, but the stance judge is unsure (below the confidence floor),
    # so the paper is down-weighted rather than dropped.
    claim = _claim()
    cands = [_cand("R", ["Randomized Controlled Trial"])]
    labels = [StanceLabel(claim_id=claim.claim_id, candidate_ext_id="R",
                          stance=Stance.REFUTES, confidence=0.6)]
    cv = score_claim(claim, cands, labels)
    assert cv.verdict is Verdict.CONTESTED
    assert cv.refuting_confidence == 0.6
    assert score_paper(PaperRecord(pmid="1"), [cv]).action is Action.DOWNWEIGHT


def test_support_and_refute_is_contested():
    claim = _claim()
    cands = [_cand("S", ["Meta-Analysis"]), _cand("R", ["Case Reports"])]
    labels = [
        StanceLabel(claim_id=claim.claim_id, candidate_ext_id="S", stance=Stance.SUPPORTS, confidence=0.8),
        StanceLabel(claim_id=claim.claim_id, candidate_ext_id="R", stance=Stance.REFUTES, confidence=0.6),
    ]
    cv = score_claim(claim, cands, labels)
    assert cv.verdict is Verdict.CONTESTED
    assert score_paper(PaperRecord(pmid="1"), [cv]).action is Action.DOWNWEIGHT


def test_no_evidence_is_ungrounded_and_flagged_for_review():
    claim = _claim()
    cv = score_claim(claim, [], [])
    assert cv.verdict is Verdict.UNGROUNDED
    pv = score_paper(PaperRecord(pmid="1"), [cv])
    assert pv.verdict is Verdict.UNGROUNDED
    assert pv.action is Action.REVIEW
    assert pv.grounded is False


def test_neutral_evidence_is_neutral_verdict_and_kept():
    claim = _claim()
    cands = [_cand("N", ["Journal Article"])]
    labels = [StanceLabel(claim_id=claim.claim_id, candidate_ext_id="N",
                          stance=Stance.NEUTRAL, confidence=0.2)]
    cv = score_claim(claim, cands, labels)
    assert cv.verdict is Verdict.NEUTRAL
    pv = score_paper(PaperRecord(pmid="1"), [cv])
    assert pv.verdict is Verdict.NEUTRAL
    assert pv.action is Action.KEEP
    assert pv.grounded is False


def test_supporting_evidence_marks_paper_grounded():
    claim = _claim()
    cands = [_cand("S", ["Meta-Analysis"])]
    labels = [StanceLabel(claim_id=claim.claim_id, candidate_ext_id="S",
                          stance=Stance.SUPPORTS, confidence=0.8)]
    pv = score_paper(PaperRecord(pmid="1"), [score_claim(claim, cands, labels)])
    assert pv.verdict is Verdict.SUPPORTED
    assert pv.action is Action.KEEP
    assert pv.grounded is True


def test_refutation_timing_prior_vs_subsequent():
    claim = _claim()
    cands = [Candidate(source="pubmed", ext_id="R",
                       pub_types=["Randomized Controlled Trial"], year=2002)]
    labels = [StanceLabel(claim_id=claim.claim_id, candidate_ext_id="R",
                          stance=Stance.REFUTES, confidence=0.9)]
    cv = score_claim(claim, cands, labels)
    assert cv.refuting_year == 2002
    # Refutation published after the paper is the reversal pattern; before it is more damning.
    assert score_paper(PaperRecord(pmid="1", year=1998), [cv]).refutation_timing == "subsequent"
    assert score_paper(PaperRecord(pmid="1", year=2020), [cv]).refutation_timing == "prior"
    # No paper year means the ordering is unknown.
    assert score_paper(PaperRecord(pmid="1"), [cv]).refutation_timing == "unknown"


def test_corroborating_refuters_strengthen_the_score():
    # Two agreeing refuters push the score lower (a stronger refutation) than one alone, so a
    # consistent body of evidence counts for more than a single study.
    claim = _claim()
    one = score_claim(
        claim, [_cand("R1", ["Randomized Controlled Trial"])],
        [StanceLabel(claim_id=claim.claim_id, candidate_ext_id="R1", stance=Stance.REFUTES, confidence=0.7)],
    )
    two = score_claim(
        claim,
        [_cand("R1", ["Randomized Controlled Trial"]), _cand("R2", ["Randomized Controlled Trial"])],
        [
            StanceLabel(claim_id=claim.claim_id, candidate_ext_id="R1", stance=Stance.REFUTES, confidence=0.7),
            StanceLabel(claim_id=claim.claim_id, candidate_ext_id="R2", stance=Stance.REFUTES, confidence=0.7),
        ],
    )
    assert two.score < one.score


def test_single_strong_refuter_still_drops_alone():
    # Corroboration must not be a prerequisite for a drop: one landmark RCT refutes on its own.
    claim = _claim()
    cv = score_claim(
        claim, [_cand("R", ["Randomized Controlled Trial"])],
        [StanceLabel(claim_id=claim.claim_id, candidate_ext_id="R", stance=Stance.REFUTES, confidence=0.9)],
    )
    assert cv.verdict is Verdict.REFUTED


def test_volume_of_low_tier_refuters_does_not_force_a_drop():
    # Many confident observational studies aggregate in strength but never clear the tier floor,
    # so weak evidence in bulk still contests rather than drops.
    claim = _claim()
    cands = [_cand(f"R{i}", ["Observational Study"]) for i in range(5)]
    labels = [
        StanceLabel(claim_id=claim.claim_id, candidate_ext_id=f"R{i}", stance=Stance.REFUTES, confidence=1.0)
        for i in range(5)
    ]
    cv = score_claim(claim, cands, labels)
    assert cv.verdict is Verdict.CONTESTED


def test_superseded_by_newer_high_tier_neutral_downweights_not_drops():
    # A supported claim with a newer high-tier neutral study on the same topic is superseded:
    # down-weighted (contested), never dropped, and flagged on both the claim and the paper.
    claim = _claim()
    cands = [
        _cand("S", ["Meta-Analysis"]),
        Candidate(source="pubmed", ext_id="M", pub_types=["Meta-Analysis"], year=2020),
    ]
    labels = [
        StanceLabel(claim_id=claim.claim_id, candidate_ext_id="S", stance=Stance.SUPPORTS, confidence=0.8),
        StanceLabel(claim_id=claim.claim_id, candidate_ext_id="M", stance=Stance.NEUTRAL, confidence=0.5),
    ]
    cv = score_claim(claim, cands, labels, paper_year=2005)
    assert cv.superseded is True
    assert cv.verdict is Verdict.CONTESTED
    pv = score_paper(PaperRecord(pmid="1", year=2005), [cv])
    assert pv.action is Action.DOWNWEIGHT
    assert pv.superseded is True


def test_supersession_requires_newer_and_high_tier():
    # Older high-tier neutral, or newer low-tier neutral, does not supersede a supported claim.
    claim = _claim()
    cands = [
        _cand("S", ["Meta-Analysis"]),
        Candidate(source="pubmed", ext_id="OLD", pub_types=["Meta-Analysis"], year=2000),
        Candidate(source="pubmed", ext_id="LOW", pub_types=["Case Reports"], year=2020),
    ]
    labels = [
        StanceLabel(claim_id=claim.claim_id, candidate_ext_id="S", stance=Stance.SUPPORTS, confidence=0.8),
        StanceLabel(claim_id=claim.claim_id, candidate_ext_id="OLD", stance=Stance.NEUTRAL, confidence=0.5),
        StanceLabel(claim_id=claim.claim_id, candidate_ext_id="LOW", stance=Stance.NEUTRAL, confidence=0.5),
    ]
    cv = score_claim(claim, cands, labels, paper_year=2005)
    assert cv.superseded is False
    assert cv.verdict is Verdict.SUPPORTED


def test_supersession_never_upgrades_a_refuted_claim_away_from_drop():
    # Supersession only ever pulls toward contested; a genuinely refuted claim stays refuted.
    claim = _claim()
    cands = [
        _cand("R", ["Randomized Controlled Trial"]),
        Candidate(source="pubmed", ext_id="M", pub_types=["Meta-Analysis"], year=2020),
    ]
    labels = [
        StanceLabel(claim_id=claim.claim_id, candidate_ext_id="R", stance=Stance.REFUTES, confidence=0.9),
        StanceLabel(claim_id=claim.claim_id, candidate_ext_id="M", stance=Stance.NEUTRAL, confidence=0.5),
    ]
    cv = score_claim(claim, cands, labels, paper_year=2005)
    assert cv.verdict is Verdict.REFUTED


def test_paper_judged_by_most_damning_claim():
    good = score_claim(
        _claim(), [_cand("S", ["Meta-Analysis"])],
        [StanceLabel(claim_id="1#c0", candidate_ext_id="S", stance=Stance.SUPPORTS, confidence=0.9)],
    )
    bad = score_claim(
        _claim(), [_cand("R", ["Randomized Controlled Trial"])],
        [StanceLabel(claim_id="1#c0", candidate_ext_id="R", stance=Stance.REFUTES, confidence=0.9)],
    )
    pv = score_paper(PaperRecord(pmid="1"), [good, bad])
    assert pv.verdict is Verdict.REFUTED
    assert pv.n_refuted_claims == 1
