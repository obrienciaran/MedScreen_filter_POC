"""Summarise a filter run over a set of ordinary papers and list the ones it did not keep.

The representative set (``data/representative/``, built by ``fetch_representative_xml.py``) is
ordinary recent papers with no retractions, so the filter should keep almost all of them. Any
paper it down-weights, drops, or sends to review is therefore a candidate false positive worth a
human look. This script reads the flat CSV that ``medscreen-filter`` writes and reports how the
papers were split across the four actions, how many were not kept, and a table of just those
not-kept papers with the columns needed to check each one.

It runs offline on an existing CSV, so it needs no network and no LLM. Produce the CSV first:

    medscreen-filter --input data/representative --out-csv reports/representative.csv
    python scripts/flag_audit.py --csv reports/representative.csv

Keeping an ordinary paper is the expected outcome. A paper that was not kept is either a real
issue the filter caught or a mistake to investigate. The report exists to make that set small and
easy to review.
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
        "# Papers the filter did not keep",
        "",
        f"- Source CSV: `{source}`",
        f"- Papers: {total}",
        f"- **Not kept: {len(flagged)} of {total} ({flag_rate * 100:.0f}%)**",
        "",
        "On an ordinary, non-retracted set the expected action is `keep`. Each paper below was not",
        "kept, so it is a candidate false positive: either a real issue the filter caught or a",
        "mistake to investigate. Read `refuting_pmids` and `notes` to see what drove the decision.",
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

    lines += ["", "## Papers not kept", ""]
    if not flagged:
        lines.append("_Every paper was kept._")
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
    ap = argparse.ArgumentParser(description="Report which ordinary papers the filter did not keep.")
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
    print(f"Not kept: {flagged} of {total} ({rate:.0f}%)")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
