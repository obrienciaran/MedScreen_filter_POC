# 🏥 MedScreen: an evidence-based quality filter for medical papers

## What this is

EXPERIMENTAL

A proof of concept for an evidence-based data quality filter for medical training data. Point it
at a corpus of PubMed papers (XML) and it produces a flat table, one row per paper, judging
whether each paper's claims hold up against trusted medical evidence. Downstream training can then
keep, down-weight, or drop papers based on that table.

The goal is to keep only high-quality data. It checks each paper's claims, keeps the ones that
hold up against the evidence, and drops or down-weights the rest. Because it checks claims against
current evidence and publication dates, it favours newer findings that overturn older ones, so a
paper repeating a claim that has since been reversed gets caught.

Rule-based filters and LLM raters judge a paper by how it reads, which is what confident
misinformation imitates best. This filter checks each claim against retrieved evidence instead.

Early testing with a lightweight LLM (Gemini 2.5 Flash Lite, POC only) shows evidence retrieval can underperform direct LLM judgment. 

**Strengths**
- Every verdict shows the studies it was based on, so a decision can be checked.
- It uses publication dates, so it catches claims that later work has overturned, and papers that were later retracted.
- The full chain of reasoning can be audited.

**Weaknesses**
- The search can be too broad and pull in studies that are not really about the claim.
- The model is less sure when judging real papers than the synthetic test cases, so its stance calls are weaker in practice.
- Formal retractions are not always found or scored correctly.

This is experimental code. The search precision and the model's stance judgment both need work
before it is used in production.

## ➡️ What it produces

Running the filter writes `reports/filter.csv`, one row per paper. The filter can also draw an
optional evidence graph over the same data (`reports/filter.html`), but the table is the final output for use downstream.

<img width="1466" height="274" alt="Screenshot 2026-07-08 at 22 48 36" src="https://github.com/user-attachments/assets/cb3a72f9-27bf-472d-a005-9804c1c2d7ec" />

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
| `n_claims` | How many claims were extracted from the paper. |
| `n_refuted_claims` | How many claims were decisively refuted (verdict `refuted`). |
| `top_refuting_tier` | Evidence tier (`0.00`–`1.00`) of the strongest study that refutes any claim; `0.00` if none. |
| `refuting_confidence` | The stance judge's confidence (`0.00`–`1.00`) behind the strongest refutation; `0.00` if none. |
| `claim_scores` | Per-claim continuous scores as `claim_id=score` pairs, separated by `;`. |
| `refuting_pmids` | PMIDs of every study that refutes any claim, separated by `;`; empty if none. |
| `evidence_text_source` | Whether the stance judge read `full_text` or `abstract` for the majority of this paper's evidence. Full text is used when the study is in the Europe PMC open-access subset and full-text stance is enabled (`MEDSCREEN_STANCE_FULLTEXT=1`), otherwise the abstract. Empty when no evidence was judged (a formally retracted paper, or one with no evidence found). |
| `notes` | A short free-text note (for example a retraction marker or an error), if any. |

The `verdict` is a truthfulness category; the `action` is what it recommends doing with the
paper in training. The mapping is fixed:

| Verdict | Action | Meaning |
|---|---|---|
| `refuted` | `drop` | High-tier evidence contradicts the claim. |
| `contested` | `downweight` | Evidence points both ways, or the refutation is weak. |
| `supported` | `keep` | Evidence backs the claim, with no credible refutation. |
| `neutral` | `keep` | Only neutral evidence was found, so the result is inconclusive. A missing refutation does not prove a claim false. |
| `ungrounded` | `review` | No evidence was found at all, so the claim is not grounded in the literature and is flagged for a human. |

A paper takes the verdict and action of its single most damning claim.

## 🛠️ How it works

For each paper:

1. Ingest: read the PubMed XML into a structured record (claim text, publication type, MeSH
   terms, retraction/comment links).
2. Extract claims: an LLM lifts the paper's specific claims out of its text.
3. Retrieve evidence: for each claim, fetch candidate studies that bear on it. The pool is
   capped at 20 candidates per claim, which also bounds the stance step to at most 20 LLM calls
   per claim. When more than 20 are found, the paper's own dispute links come first (retraction
   notices, then comment/erratum links), then the boolean query hits fill the rest.

   The boolean query is a deterministic keyword search, not an LLM step. From the claim's
   normalized fields (intervention, outcome, population) the filter builds a small ladder of
   PubMed and Europe PMC queries: a loose `intervention AND outcome` core, a high-tier rung that
   ANDs the core with strong publication types (`Meta-Analysis`, `Systematic Review`,
   `Randomized Controlled Trial`, `Guideline`), a contradiction-seeking rung that adds harm
   language (`risk OR harm OR mortality OR increased OR "no benefit" OR retracted`), a
   retraction-targeted rung (intervention AND `Retracted Publication`), and a condition-focused
   rung (intervention AND population under the high-tier filter). Terms are sanitized and passed
   unquoted so each database's automatic term mapping can match differently-worded studies, and
   the results of every rung are unioned so no single over-narrow query can drop the disproving
   study. This runs entirely on the search APIs with no model call. See `query.py`.

   By default the pooled query hits keep their retrieval order; with the optional sbert backend
   (`MEDSCREEN_EMBED_BACKEND=sbert`) they are re-ranked by semantic relevance so the most
   relevant 20 are judged, with vectors cached in DuckDB and the model running on GPU when available.
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
what is kept. The pipeline also runs offline on stub backends so you can check that it runs
without a key or a network call. Stub output is a placeholder, not a real result.

See the [design notes](DESIGN.md) for how evidence is found, how scoring works, and how retrieval
is validated.

## 📊 Results

Tested on 64 medical claims with a known answer: **32 wrong** (famous reversals and known
fabrications) and **32 true** (still accepted). The test is to catch a wrong claim without attacking
a true one. MedScreen uses **Gemini 2.5 Flash Lite** for its two model steps. As a baseline, we gave
the **same model** each claim to judge from memory, with no evidence lookup.

| Outcome | LLM alone (from memory) | MedScreen (with evidence) |
|---|---|---|
| Wrong claims caught (of 32 wrong) | 30 | **32** |
| True claims wrongly dropped (of 32 true) | 0 | **0** |

MedScreen on its own terms:

| What we measured | Result |
|---|---|
| Disproving study found by the search | 94% (30 of 32 wrong) |
| Wrong claims caught (dropped or down-weighted) | 32 of 32 wrong |
| True claims wrongly dropped | 0 of 32 true |
| True claims down-weighted, not dropped | 8 of 32 true |
| Claims correctly extracted | 83% |

Same model on both sides, so it is a fair comparison. Working from memory, the model misses a
fabrication and a retraction it was never taught. MedScreen catches both by reading the retraction
notice and the overturning trial from the evidence. The cost is lower precision. MedScreen
down-weights 8 true claims where the model keeps all 32, but it never deletes a true claim, because
dropping a paper needs two independent strong studies to agree.

Full numbers are in [`eval/README.md`](eval/README.md); the [design notes](DESIGN.md) define each
measure in plain English.

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
# Offline stub backends (no key needed):
medscreen-filter --input path/to/pubmed_xml_dir

# Real backends (LLM extraction + stance, live retrieval):
MEDSCREEN_LLM_PROVIDER=gemini MEDSCREEN_EXTRACT_BACKEND=llm \
MEDSCREEN_STANCE_BACKEND=llm MEDSCREEN_RETRIEVER=live \
  medscreen-filter --input path/to/pubmed_xml_dir

# Add MEDSCREEN_EMBED_BACKEND=sbert to re-rank query hits by semantic relevance before the
# 20-cap (needs the `embed` extra; runs on GPU when available). MEDSCREEN_STANCE_FULLTEXT=1
# makes the stance judge read open-access full text instead of just the abstract.
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

`medscreen-run` works offline with stub backends, so retrieval recall needs no API key (only stance
and precision need a paid model). It writes a report to `reports/recall-<timestamp>.{md,csv}`. See
[Results](#-results) above for the headline numbers and [`eval/README.md`](eval/README.md) for what
each one means. The no-retrieval LLM-only comparison is in
[`reports/llm_only_baseline.md`](reports/llm_only_baseline.md).

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
- A human-labelled set of ordinary papers, each with an expected keep / down-weight / drop
  label, to give an end-to-end accuracy and false-positive number on the kind of papers the
  filter will actually see (the current gold set targets known reversals, the easy tail).
