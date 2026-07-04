import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval" / "extraction"))

import score  # noqa: E402


def _c(text, intervention="", outcome="", population=None, comparator=None, direction=None):
    return {"claim_text": text, "intervention": intervention, "outcome": outcome,
            "population": population, "comparator": comparator, "direction": direction}


def test_similarity_high_for_same_claim_low_for_unrelated():
    a = _c("statins reduce cardiovascular mortality", "statin therapy", "cardiovascular mortality")
    b = _c("statin therapy lowers cardiovascular mortality", "statins", "cardiovascular mortality")
    c = _c("vaccination prevents measles", "measles vaccine", "measles")
    assert score.similarity(a, b) > score.similarity(a, c)
    assert score.similarity(a, b) >= score.MATCH_THRESHOLD
    assert score.similarity(a, c) < score.MATCH_THRESHOLD


def test_match_claims_is_one_to_one_best_first():
    reference = [
        _c("statins reduce cardiovascular mortality", "statins", "cardiovascular mortality"),
        _c("aspirin prevents recurrent stroke", "aspirin", "recurrent stroke"),
    ]
    extracted = [
        _c("aspirin lowers recurrent stroke risk", "aspirin", "recurrent stroke"),
        _c("statin therapy cuts cardiovascular mortality", "statins", "cardiovascular mortality"),
        _c("an unrelated claim about kidneys", "dialysis", "kidney function"),
    ]
    matches = match = score.match_claims(reference, extracted)
    matched_refs = {i for i, _, _ in matches}
    matched_exts = {j for _, j, _ in matches}
    assert matched_refs == {0, 1}          # both reference claims found
    assert matched_exts == {0, 1}          # the unrelated extracted claim (index 2) is unmatched
    assert len(matched_exts) == len(matches)  # one-to-one


def test_condition_retention_counts_and_direction_agreement():
    reference = [_c("x reduces y in z", "x", "y", population="z", direction="decreases")]
    extracted = [_c("x reduces y in z", "x", "y", population="z", direction="increases")]
    matches = score.match_claims(reference, extracted)
    stats = score.condition_retention(reference, extracted, matches)
    assert stats["population"] == (1, 1)   # specified and kept
    assert stats["direction"] == (0, 1)    # specified but the value disagrees
