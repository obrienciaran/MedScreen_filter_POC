# 🏥 MedScreen — Evidence-Grounded Data Quality Filter for Medical Papers

## What this is

EXPERIMENTAL

A proof of concept for an evidence-based data quality filter for medical training data. Point it
at a corpus of PubMed papers (XML) and it produces a flat table, one row per paper, judging
whether each paper's claims hold up against trusted medical evidence. Downstream training can then
keep, down-weight, or drop papers based on that table.

Rule-based filters and LLM raters judge a paper by how it reads, which is what confident
misinformation imitates best. This filter checks each claim against retrieved evidence instead.

## ➡️ What it produces

Running the filter writes `reports/filter.csv`, one row per paper. The filter can also draw an
optional evidence graph over the same data (`reports/filter.html`), but the table is the product.

<img width="958" height="188" alt="Screenshot 2026-07-04 at 13 32 18" src="https://github.com/user-attachments/assets/4a4dd1cd-fa0b-4826-91e1-5506942d7f44" />

The columns in the screenshot:

| column | meaning |
|---|---|
| `pmid` | PubMed identifier of the paper. |
| `title` | Article title. |
| `verdict` | Truthfulness verdict: `supported`, `contested`, `refuted`, `neutral`, or `ungrounded` (see the verdict-to-action table below). |
| `score` | Truthfulness score, `0.000` (refuted) to `1.000` (well supported). |
| `action` | Recommended training action: `keep`, `downweight`, `drop`, or `review`. |
| `verdict_basis` | What the verdict rests on: `retraction` (a formal retraction link in the paper's own record), `evidence` (retrieved literature), or `none`. |
| `refutation_timing` | Whether the refuting evidence came `prior` to the paper, `subsequent` to it (the reversal pattern), or `unknown`. |
| `grounded` | `true` if any supporting evidence was found for the paper's claims, else `false`. |
| `superseded` | `true` if newer higher-tier evidence has appeared that does not support a claim (outdated but not refuted); it down-weights the paper, never drops it. |
| `n_claims` | How many claims were extracted from the paper. |
| `n_refuted_claims` | How many claims were decisively refuted (verdict `refuted`). |
| `top_refuting_tier` | Evidence tier (`0.00`–`1.00`) of the strongest study that refutes any claim; `0.00` if none. |
| `refuting_confidence` | The stance judge's confidence (`0.00`–`1.00`) behind the strongest refutation; `0.00` if none. |
| `claim_scores` | Per-claim continuous scores as `claim_id=score` pairs, separated by `;`. |
| `refuting_pmids` | PMIDs of every study that refutes any claim, separated by `;`; empty if none. |
| `notes` | A short free-text note (for example a retraction marker or an error), if any. |

The `verdict` is a truthfulness category; the `action` is what it recommends doing with the
paper in training. The mapping is fixed:

| Verdict | Action | Meaning |
|---|---|---|
| `refuted` | `drop` | High-tier evidence contradicts the claim. |
| `contested` | `downweight` | Evidence points both ways, or the refutation is weak. |
| `supported` | `keep` | Evidence backs the claim, with no credible refutation. |
| `neutral` | `keep` | Only neutral evidence was found; inconclusive, and absence of refutation is not proof of falsity. |
| `ungrounded` | `review` | No evidence was found at all, so the claim is not grounded in the literature and is flagged for a human. |

A paper takes the verdict and action of its single most damning claim.

## 🛠️ How it works

For each paper:

1. Ingest: read the PubMed XML into a structured record (claim text, publication type, MeSH
   terms, retraction/comment links).
2. Extract claims: an LLM lifts the paper's specific claims out of its text.
3. Retrieve evidence: for each claim, fetch candidate studies that bear on it.
4. Judge stance: an LLM labels each candidate supporting, refuting, or neutral toward the claim.
5. Score: combine those labels with each study's evidence tier into a per-claim verdict. Every
   claim is scored, but the paper's verdict and score come from its single most damning claim.

   The verdict and the score are two separate outputs.

   The verdict (`refuted` > `contested` > `supported`) is a category set by severity alone. A
   paper with nine supported claims and one refuted claim is `refuted`.

   The score (0.0 to 1.0) measures how strongly the evidence backs that verdict. It comes from
   two inputs: the evidence tier of the refuting study (an RCT scores higher than a case report)
   and the stance judge's confidence (a 0.0 to 1.0 value the LLM reports with its label, saying
   how sure it is). A weakly refuted and a strongly refuted claim get the same `refuted` verdict
   but different scores.

The LLM handles only extraction and stance. It does not run the search, score papers, or decide
what is kept. The pipeline also runs offline on stub backends so you can check the plumbing
without a key or network call; stub output is a placeholder, not a real result.

See the [design notes](DESIGN.md) for how evidence is found, how scoring works, and how retrieval
is validated.

## ⚙️ Setup

```bash
uv venv --python 3.12
uv pip install -e ".[dev]"
# optional backends: real embeddings + one LLM provider for extraction + stance
uv pip install -e ".[dev,embed,gemini]"   # or anthropic / openai
```

Everything runs with no optional deps and no API key using stub backends. Set credentials via env
for real backends:

```bash
export NCBI_API_KEY=...        # optional, raises PubMed rate limit
export NCBI_EMAIL=you@org.com  # polite identification for E-utilities
export GEMINI_API_KEY=...      # or ANTHROPIC_API_KEY / OPENAI_API_KEY
```

## 🏃 Run the filter

```bash
# Offline stub backends — no key needed:
medscreen-filter --input path/to/pubmed_xml_dir

# Real backends (LLM extraction + stance, live retrieval):
MEDSCREEN_LLM_PROVIDER=gemini MEDSCREEN_EXTRACT_BACKEND=llm \
MEDSCREEN_STANCE_BACKEND=llm MEDSCREEN_RETRIEVER=live \
  medscreen-filter --input path/to/pubmed_xml_dir
```

Input must be PubMed/MEDLINE XML, since it carries the `CommentsCorrectionsList` links, publication
types, and MeSH terms the filter relies on. The ingester reads any PubMed XML it can and skips
(with an error) any it cannot.

## 🏃 Run the validation

```bash
medscreen-build-cache      # fetch candidate evidence for the gold set into DuckDB (no LLM)
medscreen-run --use-cache  # score against the cache, write report to ./reports/
medscreen-graph            # render the evidence graph to reports/graph.html
pytest                   # unit tests (network tests are opt-in: pytest -m live)
```

`medscreen-run` defaults to stub backends (offline, no key). On the gold set the pipeline
retrieves 90% of the known disproving studies and correctly recognises 85% of them as
contradicting the claim. None of the 12 known-good control papers were wrongly dropped; a few
were flagged for down-weighting instead, which is the safe and reversible action. Claim
extraction finds 83% of the expected claims and keeps their conditions intact. What each metric
means, which need a real LLM backend, and the full results are in [`eval/README.md`](eval/README.md).

## 🌀 Visualization (optional)

`medscreen-graph` renders a run to an interactive evidence graph (`reports/graph.html`). The
filter writes the same graph for its own results at `reports/filter.html`. Run `medscreen-run` or
`medscreen-filter` first so there is data to draw.

<img width="1499" height="768" alt="Evidence graph" src="https://github.com/user-attachments/assets/e0018172-eb28-4b29-b49c-bbc18d825967" />

## 🛣️ Roadmap

Not built yet:

- GRADE-based evidence weighting: today the filter weights evidence by a flat publication-type tier (an RCT is 0.8, a systematic review 0.9, and so on), which judges a study by its type label alone. GRADE keeps the same role of deciding how much each piece is allowed to move a claim's score, but rates it more accurately by adjusting for risk of bias, inconsistency, indirectness, and imprecision, so evidence quality rather than just the study type drives the verdict.
- Strengthening the retrieval process, so contradicting and superseding evidence is surfaced more reliably. This includes LLM-driven query and topic expansion to match on meaning rather than surface wording, and approximate-nearest-neighbour indexing to replace the current brute-force cosine search.
- Broader evaluation across more medical domains and clinical specialties.
- Testing with a local LLM to avoid API costs during development and evaluation.
