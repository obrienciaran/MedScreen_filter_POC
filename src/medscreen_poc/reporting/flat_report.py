"""Write the filter's verdicts to the flat table the end user consumes.

One row per paper. The first columns are the paper identifier and the truthfulness
verdict. The rest are the metadata a curator needs to act on or audit a row: the score, the
recommended training action, how many claims were refuted, the strongest refuting evidence
tier, and the PMIDs of the refuting works.
"""

from __future__ import annotations

import csv
from pathlib import Path

from ..schema import PaperVerdict

COLUMNS = [
    "pmid", "title", "verdict", "score", "action", "verdict_basis", "refutation_timing",
    "grounded", "n_claims", "n_refuted_claims", "top_refuting_tier", "refuting_confidence",
    "claim_scores", "refuting_pmids", "evidence_text_source", "notes",
]


def write_flat_csv(verdicts: list[PaperVerdict], path: str | Path) -> Path:
    """Write one row per paper to ``path``. Returns the path.

    ``score`` is the paper's verdict score (its most damning claim). ``refuting_confidence`` is
    the stance judge's confidence behind the strongest refutation, and ``claim_scores`` carries
    every per-claim continuous score as ``claim_id=score`` pairs, so a downstream consumer can
    threshold on the continuous signal instead of only the discrete action.
    ``evidence_text_source`` records whether the stance judge read ``full_text`` or ``abstract``
    for the majority of this paper's evidence, so a verdict is auditable back to the depth of
    evidence behind it. It is empty when no evidence was judged (a formally retracted paper, or
    one with no evidence found).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        for v in verdicts:
            refuting_confidence = max(
                (cv.refuting_confidence for cv in v.claim_verdicts), default=0.0
            )
            claim_scores = ";".join(f"{cv.claim_id}={cv.score:.3f}" for cv in v.claim_verdicts)
            # One category per paper: whether the stance judge read full text or only the abstract
            # for most of the evidence behind the verdict. Empty when no evidence was judged.
            if v.n_fulltext_evidence == 0 and v.n_abstract_evidence == 0:
                evidence_text_source = ""
            elif v.n_fulltext_evidence >= v.n_abstract_evidence:
                evidence_text_source = "full_text"
            else:
                evidence_text_source = "abstract"
            w.writerow([
                v.pmid, v.title, v.verdict.value, f"{v.score:.3f}", v.action.value,
                v.verdict_basis, v.refutation_timing, str(v.grounded).lower(), v.n_claims,
                v.n_refuted_claims, f"{v.top_refuting_tier:.2f}", f"{refuting_confidence:.2f}",
                claim_scores, ";".join(v.refuting_pmids), evidence_text_source, v.notes,
            ])
    return path
