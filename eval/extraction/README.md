# Claim extraction check

Before any evidence is retrieved, the filter uses an LLM to pull each paper's claims out of
its text. If that step misses a claim, or drops the conditions attached to it (who was
studied, the comparison, the direction of effect), everything after it is judged on the
wrong thing. This folder measures how well the extractor does that job.

## What is here

- `reference_claims.yaml`: 10 papers from the representative sample, each with its title,
  abstract, and a set of expected claims (with conditions attached).
- `papers/`: the pinned PubMed XML for those papers.
- `score.py`: runs the extractor on each paper, matches its claims against the expected
  ones, and rewrites this file with the numbers below.

## How to run

Needs a real LLM. From the repo root:

```bash
MEDSCREEN_EXTRACT_BACKEND=llm MEDSCREEN_LLM_PROVIDER=gemini python eval/extraction/score.py
```

## Latest results

- Extractor: `extract:gemini:gemini-2.5-flash-lite`
- Run: 2026-07-05 01:05
- Papers: 10  |  expected claims: 24  |  extracted claims: 47

- **Recall** (expected claims found): **83%** (20/24)
- **Precision** (extracted claims that match an expected one): **43%** (20/47). Lower because the extractor pulls more, finer-grained claims.
- **F1**: 56%

Conditions kept, over matched claims where the expected claim specifies the field:

- Population kept: 93% (14/15)
- Comparator kept: 100% (1/1)
- Direction agreement: 100% (8/8)

| pmid | expected | extracted | matched |
|---|---|---|---|
| 38177157 | 3 | 5 | 3 |
| 38469546 | 3 | 5 | 3 |
| 38733347 | 3 | 5 | 1 |
| 38777539 | 2 | 5 | 2 |
| 38928291 | 3 | 5 | 3 |
| 39051318 | 2 | 5 | 2 |
| 39084811 | 1 | 2 | 1 |
| 39185405 | 3 | 5 | 2 |
| 39496213 | 2 | 5 | 2 |
| 39501335 | 2 | 5 | 1 |

Caveat: the expected claims were written by a strong model (Claude), not a person, so this
measures agreement with that model, not human ground truth (see `eval/README.md`).
