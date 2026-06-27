# `reports/` — generated output

This folder holds the artifacts the tools write. Nothing here is hand-edited.

Most files here are **regenerable output and are not committed** (they are listed in
`.gitignore`); rerun the tool to recreate them. Only `README.md` and `graph_demo.html` are
checked into the repo.

### Files from the filter (`medscreen-filter`, the data quality filter)

- `filter.csv` — the per-paper truthfulness table, one row per paper. Columns are documented
  below. This is a real run and the filter's real output (i.e. not the validation run on our gold standard curated dataset),
  regenerated on every run.
- `filter.html` — the same run drawn as an interactive evidence graph. One node per paper,
  coloured by its truthfulness verdict. A visual aid over the same data in `filter.csv`.

### Files from the validation tool (`medscreen-run`, the recall check, on the gold standard curated dataset)

- `recall-<timestamp>.md` / `recall-<timestamp>.csv` — how often the search found the known
  disproving study on the gold slice. These are retrieval-recall metrics, not per-paper
  verdicts; see the main `README.md`. One pair is written per run, timestamped.
- `graph.html` — the evidence graph for the validation run (`medscreen-graph`). Claims as boxes,
  retrieved studies as dots, line colour for stance. Written only after a validation run.

### Checked-in file

- `graph_demo.html` — a static, seeded example of the validation graph shipped with the repo so
  the visualization can be viewed without running anything. It is a demo, not a live result.

## `filter.csv` columns

One row per paper. The first two columns identify the paper, `verdict` and `action` are what
a downstream training pipeline acts on, and the rest are the evidence behind the verdict so a
curator can audit or override it.

| column | meaning |
|---|---|
| `pmid` | PubMed identifier of the paper. |
| `title` | Article title. |
| `verdict` | Evidence-grounded truthfulness verdict (see below). |
| `score` | Truthfulness score from `0.000` to `1.000`: `1` = well supported, `0` = refuted. |
| `action` | Recommended training-data action: `keep`, `downweight`, or `drop`. |
| `n_claims` | How many checkable claims were extracted from the paper. |
| `n_refuted_claims` | How many of those claims were judged `refuted`. |
| `top_refuting_tier` | Evidence strength (`0.00`–`1.00`) of the strongest study refuting any claim; `0.00` if nothing refuted it (see the tier table). |
| `refuting_pmids` | PMIDs of the works that refuted the paper's claims, separated by `;`; empty if none. |
| `notes` | Free-text notes, e.g. `no claims extracted`. |

### `verdict`

The verdict is grounded in the retrieved evidence and its strength, not in the model's
free-standing opinion. A paper is judged as harshly as its **most damning claim**, so one
confidently wrong central claim is enough to refute the paper.

| verdict | meaning |
|---|---|
| `supported` | Evidence backs the claims and nothing credible refutes them. |
| `contested` | Evidence both supports and refutes, or refutation exists but is not strong enough to be decisive. |
| `refuted` | Higher-tier evidence contradicts a claim. |
| `unverified` | No usable evidence was found. Absence of refutation is **not** evidence of falsity. |

### `action`

`action` is the default policy derived from `verdict`. The continuous `score` is also written
so you can set your own threshold instead of relying on these defaults.

| verdict | default action |
|---|---|
| `refuted` | `drop` |
| `contested` | `downweight` |
| `supported` | `keep` |
| `unverified` | `keep` (a missing refutation is not falsity) |

### `score`

`score` is continuous truthfulness, not a probability. Per claim it is
`0.5 + 0.4 × support_strength − 0.8 × refute_strength`, clamped to `0 - 1`, where each strength
is the stance confidence weighted by the evidence tier of the study making that point. The
paper's score is the **minimum** across its claims (its weakest, most-refuted claim).

### `top_refuting_tier` and the evidence tiers

The tier is a coarse, GRADE-type weight read from a study's publication type. It exists
so a high-tier refutation outweighs low-tier support; it is not a precise scoring instrument.

| tier | publication type |
|---|---|
| `1.00` | Guideline / practice guideline |
| `0.95` | Retraction of publication |
| `0.90` | Systematic review |
| `0.85` | Meta-analysis |
| `0.80` | Randomized / controlled clinical trial |
| `0.50` | Observational / cohort / comparative study |
| `0.40` | Unknown or generic journal article |
| `0.20` | Case report |
