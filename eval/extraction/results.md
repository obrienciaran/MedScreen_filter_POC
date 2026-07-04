# Claim-extraction evaluation results

- Extractor: `extract:gemini:gemini-2.5-flash-lite`
- Run: 2026-07-05 01:05
- Papers: 10  |  reference claims: 24  |  extracted claims: 47

## Claim matching

- **Recall** (reference claims found): **83%** (20/24)
- **Precision** (extracted claims that match a reference): **43%** (20/47)
- **F1**: 56%

## Condition retention (over matched claims where the reference specifies the field)

- Population kept: 93% (14/15)
- Comparator kept: 100% (1/1)
- Direction agreement: 100% (8/8)

## Per paper

| pmid | reference | extracted | matched |
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

> Reference not human-verified: the reference claims were extracted by a strong model, so this measures agreement with that model, not human ground truth (see `eval/README.md`).
