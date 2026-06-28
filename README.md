# 🏥 MedScreen — Evidence-Grounded Data Quality Filter for Medical Papers

## What this is

EXPERIMENTAL

A proof of concept for an evidence-based data quality filter for medical training data. Point it
at a corpus of PubMed papers (XML) and it produces a flat table, one row per paper, judging
whether each paper's claims hold up against trusted medical evidence. Downstream training can then
keep, down-weight, or drop papers based on that table.

The point is to filter on truth, not surface features. Rule-based filters, quality classifiers,
and LLM raters all judge a paper by how it reads (fluency, formatting, resemblance to a trusted
reference), which is exactly what confident misinformation imitates best. This filter instead
pulls out each claim and checks it against the evidence, so the verdict is discovered, not
guessed.

It is a POC, so it tests the one dependency the approach rests on; can retrieval find the evidence
that contradicts a wrong claim?

## ➡️ What it produces

Running the filter writes `reports/filter.csv`, one row per paper:

| paper | truthful | ... |
|---|---|---|
| paper identifier | do its claims hold up against the evidence | confidence, contradicting studies, evidence tier, other metadata |

Every column is documented in [`reports/README.md`](reports/README.md). The filter can also draw
an optional evidence graph over the same data (`reports/filter.html`), but the table is the
product.

<img width="1199" height="279" alt="Filter output table" src="https://github.com/user-attachments/assets/8ec9ed89-82d9-4dc7-a768-a57945c77b06" />

The columns in the screenshot:

| column | meaning |
|---|---|
| `pmid` | PubMed identifier of the paper. |
| `title` | Article title. |
| `verdict` | Truthfulness verdict: `supported`, `contested`, `refuted`, or `unverified`. |
| `score` | Truthfulness score, `0.000` (refuted) to `1.000` (well supported). |
| `action` | Recommended training action: `keep`, `downweight`, or `drop`. |
| `n_claims` | How many claims were extracted from the paper. |
| `n_refuted_claims` | How many claims were decisively refuted (verdict `refuted`). See the note below. |
| `top_refuting_tier` | Evidence tier (`0.00`–`1.00`) of the strongest study that refutes any claim; `0.00` if none. |
| `refuting_pmids` | PMIDs of every study that refutes any claim, separated by `;`; empty if none. |

### Why `n_refuted_claims` can be `0` while `top_refuting_tier` and `refuting_pmids` have values

This is expected, not a bug. The three columns measure two different things:

- `refuting_pmids` and `top_refuting_tier` report whether any refuting study was found, for any
  claim, no matter how that claim ends up scored.
- `n_refuted_claims` counts only claims whose final verdict is `refuted`.

A claim is marked `refuted` only when it has refuting evidence, has no supporting evidence, and that
refutation is strong enough. If a claim has refuting studies but also has supporting studies (or the
refutation is too weak to be decisive), the claim is `contested`, not `refuted`. A `contested` claim
still reports its refuting studies in `refuting_pmids` and `top_refuting_tier`, but it does not add
to `n_refuted_claims`. So every row in the screenshot is `supported` or `contested`, never `refuted`, which is why
`n_refuted_claims` is `0` on every row.

## 🛠️ How it works

The filter processes each paper on its own, judged only against external trusted evidence, so cost
grows linearly with the number of papers. For one paper:

1. Ingest: read the PubMed XML into a structured record (claim text, publication type, MeSH
   terms, retraction/comment links).
2. Extract claims: an LLM lifts the paper's specific claims out of its text.
3. Retrieve evidence: for each claim, fetch a small set of candidate studies that bear on it.
   This is the step the POC validates.
4. Judge stance: an LLM reads each candidate's title and abstract and labels it supporting,
   refuting, or neutral toward the claim.
5. Score: weigh those labels by evidence tier into a per-claim verdict, then take the paper's
   worst claim as its verdict (see below).

The whole pipeline also runs offline on stub backends (no network, no LLM) so you can check the
plumbing before spending anything. Stub output is a placeholder, not a real result.

The LLM's role is deliberately bounded to those two steps (extract and judge stance). It does not
run the search, score a paper, or decide which papers are kept.

For how evidence is found, how a paper is scored, how the search is validated, and why the
approach is built this way, see the [design notes](DESIGN.md).

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

Writes `reports/filter.csv` (per-paper table, documented in
[`reports/README.md`](reports/README.md)) and `reports/filter.html` (interactive graph). The other
HTML files in `reports/` are not a filter run — `graph_demo.html` is a shipped example and
`graph.html` is the validation visualization.

Input must be PubMed/MEDLINE XML, since it carries the `CommentsCorrectionsList` links, publication
types, and MeSH terms the filter relies on. The ingester reads any PubMed XML it can and skips
(with an error) any it cannot.

## 🏃 Run the validation

```bash
medscreen-build-cache      # fetch candidate evidence for the gold set into DuckDB
medscreen-run --use-cache  # score against the cache, write report to ./reports/
medscreen-graph            # render the evidence graph to reports/graph.html
pytest                   # unit tests (network tests are opt-in: pytest -m live)
```

`medscreen-run` defaults to stub backends (offline, no key). For a real measurement:

```bash
MEDSCREEN_EMBED_BACKEND=sbert MEDSCREEN_STANCE_BACKEND=llm MEDSCREEN_LLM_PROVIDER=gemini \
  medscreen-run --use-cache
```

`MEDSCREEN_EMBED_BACKEND=sbert` needs the `embed` extra; without it the numbers come from stubs and
are not a real measurement.

## 🌀 Visualization (optional)

A secondary aid, not the product. `medscreen-graph` renders a validation run to a self-contained
interactive page (`reports/graph.html`) — claims as boxes, retrieved studies as dots, line colour
for stance, with a legend, edge filters, a "recall gaps only" view, and hover/click focus. The
filter draws the same graph for its own results at `reports/filter.html`. Run `medscreen-run` (or
`medscreen-filter`) first so there is data to draw.

<img width="1499" height="768" alt="Evidence graph" src="https://github.com/user-attachments/assets/e0018172-eb28-4b29-b49c-bbc18d825967" />

## 🛣️ Roadmap

Not built yet:

- GRADE-based evidence weighting: today the filter weights evidence by a flat publication-type tier (an RCT is 0.8, a systematic review 0.9, and so on), which judges a study by its type label alone. GRADE keeps the same role of deciding how much each piece is allowed to move a claim's score, but rates it more accurately by adjusting for risk of bias, inconsistency, indirectness, and imprecision, so evidence quality rather than just the study type drives the verdict.
- Strengthening the retrieval process, so contradicting and superseding evidence is surfaced more reliably. This includes LLM-driven query and topic expansion to match on meaning rather than surface wording, and approximate-nearest-neighbour indexing to replace the current brute-force cosine search.
- Broader evaluation. Expanding the gold slice and error taxonomy to measure recall and false-contradiction rates across more medical domains.
- Testing with a local LLM to avoid API costs during development and evaluation.
