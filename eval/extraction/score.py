"""Score the LLM claim extractor against the reference set.

Runs the configured claim extractor on each paper in ``reference_claims.yaml`` and compares its
output to the reference claims on two axes:

  * claim precision / recall / F1 — did the extractor find the reference claims (recall) without
    inventing extras (precision)? Claims are matched greedily 1:1 by token overlap.
  * condition retention — for matched claims where the reference specifies a population,
    comparator, or direction, did the extractor keep it (and, for direction, agree)?

Offline (stub) by default, which only checks the plumbing. For a real measurement set the LLM
extractor:

    python eval/extraction/score.py                                    # stub extractor
    MEDSCREEN_EXTRACT_BACKEND=llm MEDSCREEN_LLM_PROVIDER=gemini \\
      python eval/extraction/score.py                                  # real extractor

It writes the results into ``eval/extraction/README.md``. The matching (``similarity`` /
``match_claims``) is pure and unit-tested. See ``eval/README.md`` for the not-human-verified
reference caveat.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
REFS = HERE / "reference_claims.yaml"
RESULTS = HERE / "README.md"

# Token overlap (Jaccard) at/above which a reference and an extracted claim are the same claim.
MATCH_THRESHOLD = 0.18
_STOP = {
    "the", "a", "an", "of", "in", "to", "and", "or", "for", "with", "is", "are", "by", "on",
    "its", "their", "that", "this", "from", "as", "at", "be", "can", "not",
}
_CONDITIONS = ("population", "comparator", "direction")


def _tokens(*texts: str | None) -> set[str]:
    out: set[str] = set()
    for t in texts:
        if not t:
            continue
        for w in re.findall(r"[a-z0-9]+", str(t).lower()):
            if len(w) > 2 and w not in _STOP:
                out.add(w)
    return out


def similarity(a: dict, b: dict) -> float:
    """Jaccard token overlap over each claim's text, intervention, and outcome."""
    ta = _tokens(a.get("claim_text"), a.get("intervention"), a.get("outcome"))
    tb = _tokens(b.get("claim_text"), b.get("intervention"), b.get("outcome"))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def match_claims(reference: list[dict], extracted: list[dict]) -> list[tuple[int, int, float]]:
    """Greedy 1:1 matching of reference to extracted claims, best similarity first."""
    pairs = sorted(
        (
            (similarity(r, e), i, j)
            for i, r in enumerate(reference)
            for j, e in enumerate(extracted)
        ),
        reverse=True,
    )
    ref_used: set[int] = set()
    ext_used: set[int] = set()
    matches: list[tuple[int, int, float]] = []
    for s, i, j in pairs:
        if s < MATCH_THRESHOLD or i in ref_used or j in ext_used:
            continue
        ref_used.add(i)
        ext_used.add(j)
        matches.append((i, j, s))
    return matches


def _prf(n_matched: int, n_ref: int, n_ext: int) -> tuple[float, float, float]:
    recall = n_matched / n_ref if n_ref else 0.0
    precision = n_matched / n_ext if n_ext else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return precision, recall, f1


def condition_retention(
    reference: list[dict], extracted: list[dict], matches: list[tuple[int, int, float]]
) -> dict[str, tuple[int, int]]:
    """Per condition field: (kept, specified) over matched pairs where the reference specifies it.

    For ``direction`` the extractor must not only keep it but agree on the value.
    """
    stats = {f: [0, 0] for f in _CONDITIONS}
    for i, j, _ in matches:
        r, e = reference[i], extracted[j]
        for f in _CONDITIONS:
            if r.get(f):
                stats[f][1] += 1
                if f == "direction":
                    stats[f][0] += int(e.get("direction") == r.get("direction"))
                elif e.get(f):
                    stats[f][0] += 1
    return {f: (kept, spec) for f, (kept, spec) in stats.items()}


def _claim_dict(claim) -> dict:
    n = claim.normalized
    return {
        "claim_text": claim.claim_text, "intervention": n.intervention, "outcome": n.outcome,
        "population": n.population, "comparator": n.comparator, "direction": n.direction,
    }


def run(refs_path: Path = REFS) -> str:
    """Run the configured extractor over the reference papers and return a markdown report."""
    from medscreen_poc.transformation.extract import get_extractor
    from medscreen_poc.transformation.ingest import parse_pubmed_xml

    extractor = get_extractor()
    papers = yaml.safe_load(refs_path.read_text())["papers"]

    tot_ref = tot_ext = tot_match = 0
    cond_totals = {f: [0, 0] for f in _CONDITIONS}
    rows: list[str] = []
    for p in papers:
        record = parse_pubmed_xml((refs_path.parent / p["xml"]).read_text())[0]
        extracted = [_claim_dict(c) for c in extractor.extract(record)]
        reference = p["expected_claims"]
        matches = match_claims(reference, extracted)
        tot_ref += len(reference)
        tot_ext += len(extracted)
        tot_match += len(matches)
        for f, (kept, spec) in condition_retention(reference, extracted, matches).items():
            cond_totals[f][0] += kept
            cond_totals[f][1] += spec
        rows.append(f"| {p['pmid']} | {len(reference)} | {len(extracted)} | {len(matches)} |")

    precision, recall, f1 = _prf(tot_match, tot_ref, tot_ext)
    pct = lambda x: f"{x * 100:.0f}%"
    ratio = lambda kept, spec: f"{pct(kept / spec)} ({kept}/{spec})" if spec else "n/a"
    lines = [
        "# Claim extraction check",
        "",
        "Before any evidence is retrieved, the filter uses an LLM to pull each paper's claims out of",
        "its text. If that step misses a claim, or drops the conditions attached to it (who was",
        "studied, the comparison, the direction of effect), everything after it is judged on the",
        "wrong thing. This folder measures how well the extractor does that job.",
        "",
        "## What is here",
        "",
        "- `reference_claims.yaml`: 10 papers from the representative sample, each with its title,",
        "  abstract, and a set of expected claims (with conditions attached).",
        "- `papers/`: the pinned PubMed XML for those papers.",
        "- `score.py`: runs the extractor on each paper, matches its claims against the expected",
        "  ones, and rewrites this file with the numbers below.",
        "",
        "## How to run",
        "",
        "Needs a real LLM. From the repo root:",
        "",
        "```bash",
        "MEDSCREEN_EXTRACT_BACKEND=llm MEDSCREEN_LLM_PROVIDER=gemini python eval/extraction/score.py",
        "```",
        "",
        "## Latest results",
        "",
        f"- Extractor: `{extractor.name}`",
        f"- Run: {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"- Papers: {len(papers)}  |  expected claims: {tot_ref}  |  extracted claims: {tot_ext}",
        "",
        f"- **Recall** (expected claims found): **{pct(recall)}** ({tot_match}/{tot_ref})",
        f"- **Precision** (extracted claims that match an expected one): **{pct(precision)}**"
        f" ({tot_match}/{tot_ext}). Lower because the extractor pulls more, finer-grained claims.",
        f"- **F1**: {pct(f1)}",
        "",
        "Conditions kept, over matched claims where the expected claim specifies the field:",
        "",
        f"- Population kept: {ratio(*cond_totals['population'])}",
        f"- Comparator kept: {ratio(*cond_totals['comparator'])}",
        f"- Direction agreement: {ratio(*cond_totals['direction'])}",
        "",
        "| pmid | expected | extracted | matched |",
        "|---|---|---|---|",
        *rows,
        "",
        "Caveat: the expected claims were written by a strong model (Claude), not a person, so this",
        "measures agreement with that model, not human ground truth (see `eval/README.md`).",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Score the claim extractor against the reference set.")
    ap.add_argument("--refs", default=str(REFS))
    ap.add_argument("--out", default=str(RESULTS))
    args = ap.parse_args()
    report = run(Path(args.refs))
    Path(args.out).write_text(report)
    print(report)
    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
