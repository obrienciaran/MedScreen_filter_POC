# The `reports/` folder

This folder holds the files the tools write. Nothing here is hand-edited.

Most files here are regenerable output and are not committed (they are listed in `.gitignore`).
Rerun the tool to recreate them. Only `README.md` and `graph_demo.html` are checked into the repo.

### Files from the filter (`medscreen-filter`)

`filter.csv` is the per-paper truthfulness table, one row per paper, with the columns described
below. This is a real filter run, not the validation run on the gold set. It is rewritten on every
run.

`filter.html` draws the same run as an interactive graph, one node per paper, coloured by its
verdict. It is a visual aid over the same data in `filter.csv`.

### Files from the validation tool (`medscreen-run`, run on the gold set)

`recall-<timestamp>.md` and `recall-<timestamp>.csv` record how often the search found the known
disproving study on the gold set. These are retrieval-recall metrics, not per-paper verdicts. See
the main `README.md`. One pair is written per run, with a timestamp.

`graph.html` is the evidence graph for a validation run, drawn by `medscreen-graph`: claims as
boxes, retrieved studies as dots, and line colour for stance. It is written only after a validation
run.

### Checked-in file

`graph_demo.html` is a static, seeded example of the validation graph, kept in the repo so the
visualization can be viewed without running anything. It is a demo, not a live result.

## `filter.csv` columns

One row per paper. The `pmid` and `title` identify the paper, `verdict` and `action` are what a
training pipeline acts on, and the rest are the evidence behind the verdict so a curator can audit
or override it. The full column list is:

`pmid`, `title`, `verdict`, `score`, `action`, `verdict_basis`, `refutation_timing`, `grounded`,
`n_claims`, `n_refuted_claims`, `top_refuting_tier`, `refuting_confidence`, `claim_scores`,
`refuting_pmids`, `evidence_text_source`, `notes`. The main `README.md` documents each one. The verdict, action, score, and
evidence tier are explained below.

### `verdict`

The verdict comes from the retrieved evidence and its strength, not from the model's own opinion. A
paper is judged as harshly as its most damning claim, so one confidently wrong central claim is
enough to refute the paper.

| verdict | meaning |
|---|---|
| `supported` | Evidence backs the claims and nothing credible refutes them. |
| `contested` | Evidence both supports and refutes, or a refutation exists but is not strong enough to be decisive. |
| `refuted` | Higher-tier evidence contradicts a claim, with corroboration. |
| `neutral` | Only neutral evidence was found. A missing refutation does not prove a claim false. |
| `ungrounded` | No evidence was found at all, so the claim is not grounded in the literature. |

### `action`

The action is the default policy that follows from the verdict. The continuous `score` is also
written, so you can set your own threshold instead of using these defaults.

| verdict | default action |
|---|---|
| `refuted` | `drop` |
| `contested` | `downweight` |
| `supported` | `keep` |
| `neutral` | `keep` (a missing refutation does not prove a claim false) |
| `ungrounded` | `review` (no evidence found, so flag it for a human) |

### `score`

The score is a continuous measure of truthfulness, not a probability. Per claim it is
`0.5 + 0.4 × support_strength − 0.8 × refute_strength`, clamped to the range 0 to 1. Each strength
combines the stance confidence and evidence tier across all the studies on that side, so a body of
agreeing studies counts for more than a single study. The paper's score is the lowest of its
claim scores, that is, its weakest claim.

### `top_refuting_tier` and the evidence tiers

The tier is a coarse, GRADE-style weight read from a study's publication type. It exists so that a
high-tier refutation outweighs low-tier support. It is not a precise scoring instrument.

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
