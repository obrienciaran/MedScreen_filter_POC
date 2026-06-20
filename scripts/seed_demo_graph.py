"""Seed a demo store with synthetic stance and render the evidence graph.

This is a demonstration only. It invents candidates and stance verdicts so the graph is
fully populated without any network or LLM call. It writes to a separate demo database so
the real cache is untouched. The synthetic data is shaped to show every visual case:

  * success: known disproving study retrieved and recognised as refuting (red edge to a
    gold-ringed blue node)
  * retrieved_not_recognized: known disproving study present but judged neutral (grey edge)
  * not_indexed: known disproving study never retrieved (dashed "not retrieved" edge)
  * supporting and neutral distractors (green and grey edges)
  * a retraction link between two papers (dashed purple edge)
  * control claims that stay supported and are never flagged

Run with the project venv:  python scripts/seed_demo_graph.py
"""

from __future__ import annotations

from pathlib import Path

from medfact_poc.graph import build_graph_data, render_html
from medfact_poc.harness import load_gold
from medfact_poc.schema import Candidate, ClaimStatus, GoldEntry, Stance, StanceLabel
from medfact_poc.store import Store

DEMO_DB = Path("data/cache/demo.duckdb")
DEMO_HTML = Path("reports/graph_demo.html")

# Claims used to demonstrate specific outcomes.
NOT_INDEXED = {"rofecoxib-cv-safe"}  # answer key never added, shows a "not retrieved" edge
NOT_RECOGNISED = {"vitamin-e-cv"}  # answer key present but judged neutral
RETRACTION_DEMO = "tight-glycemic-icu"  # gets a retracted paper plus its retraction notice


def _candidate(ext_id: str, title: str, year: int | None, pub_types: list[str], **kw) -> Candidate:
    return Candidate(source="pubmed", ext_id=ext_id, title=title, year=year,
                     pub_types=pub_types, abstract=title, **kw)


def seed_reversed(entry: GoldEntry) -> tuple[list[Candidate], list[StanceLabel]]:
    cands: list[Candidate] = []
    labels: list[StanceLabel] = []

    if entry.id not in NOT_INDEXED:
        for ak in entry.answer_key:
            cands.append(_candidate(ak, f"Landmark study overturning '{entry.normalized.intervention}'",
                                    entry.reversal_year, ["Randomized Controlled Trial"]))
            if entry.id in NOT_RECOGNISED:
                labels.append(StanceLabel(claim_id=entry.id, candidate_ext_id=ak,
                                          stance=Stance.NEUTRAL, confidence=0.4,
                                          rationale="synthetic: judged neutral despite refuting"))
            else:
                labels.append(StanceLabel(claim_id=entry.id, candidate_ext_id=ak,
                                          stance=Stance.REFUTES, confidence=0.92,
                                          rationale="synthetic: high-tier trial contradicts the claim"))

    supp = f"{entry.id}-supp"
    cands.append(_candidate(supp, "Early observational study supporting the original belief",
                            (entry.reversal_year or 2000) - 5, ["Observational Study"]))
    labels.append(StanceLabel(claim_id=entry.id, candidate_ext_id=supp,
                              stance=Stance.SUPPORTS, confidence=0.55,
                              rationale="synthetic: low-tier support"))

    neu = f"{entry.id}-neu"
    cands.append(_candidate(neu, "Narrative review with background context", entry.reversal_year,
                            ["Review"]))
    labels.append(StanceLabel(claim_id=entry.id, candidate_ext_id=neu,
                              stance=Stance.NEUTRAL, confidence=0.3, rationale="synthetic: neutral"))

    if entry.id == RETRACTION_DEMO:
        fraud = f"{entry.id}-fraud"
        retr = f"{entry.id}-retraction"
        cands.append(_candidate(fraud, "Since-retracted paper claiming benefit", entry.reversal_year,
                                ["Journal Article"], retracted_by=[retr]))
        cands.append(_candidate(retr, "Retraction notice", (entry.reversal_year or 2009) + 1,
                                ["Retraction of Publication"], is_retraction_of=[fraud]))
        labels.append(StanceLabel(claim_id=entry.id, candidate_ext_id=fraud,
                                  stance=Stance.SUPPORTS, confidence=0.4, rationale="synthetic"))
        labels.append(StanceLabel(claim_id=entry.id, candidate_ext_id=retr,
                                  stance=Stance.REFUTES, confidence=0.7, rationale="synthetic"))

    return cands, labels


def seed_control(entry: GoldEntry) -> tuple[list[Candidate], list[StanceLabel]]:
    supp = f"{entry.id}-supp"
    neu = f"{entry.id}-neu"
    cands = [
        _candidate(supp, "Meta-analysis confirming current consensus", 2018, ["Meta-Analysis"]),
        _candidate(neu, "Background review", 2015, ["Review"]),
    ]
    labels = [
        StanceLabel(claim_id=entry.id, candidate_ext_id=supp, stance=Stance.SUPPORTS,
                    confidence=0.85, rationale="synthetic: strong support"),
        StanceLabel(claim_id=entry.id, candidate_ext_id=neu, stance=Stance.NEUTRAL,
                    confidence=0.3, rationale="synthetic: neutral"),
    ]
    return cands, labels


def main() -> None:
    gold = load_gold()
    if DEMO_DB.exists():
        DEMO_DB.unlink()
    with Store(DEMO_DB) as store:
        for entry in gold.entries:
            if entry.status is ClaimStatus.REVERSED:
                cands, labels = seed_reversed(entry)
            else:
                cands, labels = seed_control(entry)
            store.upsert_candidates(cands)
            store.upsert_stance(labels)
        data = build_graph_data(gold, store)
    out = render_html(data, DEMO_HTML)
    print(f"Demo graph: {len(data.nodes)} nodes, {len(data.edges)} edges")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
