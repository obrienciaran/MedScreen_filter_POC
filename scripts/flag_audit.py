"""Summarise a filter run over a presumed-keep set and list the papers it flagged.

The representative set (``data/representative/``, built by ``fetch_representative_xml.py``) is
ordinary recent papers with no retractions, so the filter should keep almost all of them. Any
paper it down-weights, drops, or sends to review is therefore a candidate false positive worth a
human look. This script reads the flat CSV that ``medscreen-filter`` writes and reports the
action distribution, the over-flag rate, and a table of just the flagged papers with the columns
needed to audit each one.

It runs offline on an existing CSV, so it needs no network and no LLM. Produce the CSV first:

    medscreen-filter --input data/representative --out-csv reports/representative.csv
    python scripts/flag_audit.py --csv reports/representative.csv

An ordinary paper that keeps is expected; a flagged one is either a real issue the filter caught
or an over-flag to investigate. The point of the report is to make that set small and reviewable.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
from pathlib import Path

# Actions that mark a paper as "not simply kept", ordered most to least severe for the report.
_FLAG_ACTIONS = ("drop", "downweight", "review")

# Columns lifted into the flagged-paper table, in display order.
_AUDIT_COLUMNS = (
    "pmid", "title", "verdict", "action", "score", "n_claims", "n_refuted_claims",
    "top_refuting_tier", "refuting_confidence", "refuting_pmids", "notes",
)


def _severity(action: str) -> int:
    """Sort key: flagged actions first (most severe first), everything else last."""
    return _FLAG_ACTIONS.index(action) if action in _FLAG_ACTIONS else len(_FLAG_ACTIONS)


def _load_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build_report(rows: list[dict[str, str]], *, source: str) -> str:
    """Render the action distribution and the flagged-paper table as markdown."""
    total = len(rows)
    counts: dict[str, int] = {}
    for row in rows:
        action = row.get("action", "")
        counts[action] = counts.get(action, 0) + 1
    flagged = [r for r in rows if r.get("action", "") in _FLAG_ACTIONS]
    flag_rate = len(flagged) / total if total else 0.0

    lines = [
        "# Over-flag audit (presumed-keep set)",
        "",
        f"- Source CSV: `{source}`",
        f"- Papers: {total}",
        f"- **Over-flag rate: {flag_rate * 100:.0f}%** ({len(flagged)}/{total} not kept)",
        "",
        "On an ordinary, non-retracted set the expected action is `keep`. Each flagged paper below",
        "is a candidate false positive: either a real issue the filter caught or an over-flag to",
        "investigate. Read `refuting_pmids` and `notes` to see what drove the flag.",
        "",
        "## Action distribution",
        "",
        "| Action | Count |",
        "|---|---|",
    ]
    for action in ("keep", *_FLAG_ACTIONS):
        if action in counts:
            lines.append(f"| `{action}` | {counts[action]} |")
    for action, n in sorted(counts.items()):
        if action not in ("keep", *_FLAG_ACTIONS):
            lines.append(f"| `{action}` | {n} |")

    lines += ["", "## Flagged papers", ""]
    if not flagged:
        lines.append("_None flagged: every paper was kept._")
        return "\n".join(lines) + "\n"

    lines.append("| " + " | ".join(_AUDIT_COLUMNS) + " |")
    lines.append("|" + "|".join(["---"] * len(_AUDIT_COLUMNS)) + "|")
    ordered = sorted(flagged, key=lambda r: (_severity(r.get("action", "")), r.get("score", "")))
    for row in ordered:
        cells = []
        for col in _AUDIT_COLUMNS:
            value = (row.get(col, "") or "").replace("|", "\\|").replace("\n", " ")
            if col == "title" and len(value) > 60:
                value = value[:59] + "…"
            cells.append(value)
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Audit a filter CSV for over-flagged ordinary papers.")
    ap.add_argument("--csv", default="reports/filter.csv", help="filter output CSV to audit")
    ap.add_argument("--out", default=None, help="markdown output path (default reports/flag_audit-<stamp>.md)")
    args = ap.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        raise SystemExit(f"CSV not found: {csv_path}. Run medscreen-filter first.")
    rows = _load_rows(csv_path)

    out_path = Path(args.out) if args.out else Path("reports") / f"flag_audit-{dt.datetime.now():%Y%m%d-%H%M%S}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    report = build_report(rows, source=str(csv_path))
    out_path.write_text(report, encoding="utf-8")

    total = len(rows)
    flagged = sum(1 for r in rows if r.get("action", "") in _FLAG_ACTIONS)
    rate = flagged / total * 100 if total else 0.0
    print(f"Over-flag rate: {rate:.0f}% ({flagged}/{total} not kept)")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
