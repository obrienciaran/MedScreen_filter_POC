# 🏥 MedScreen — Design notes

Background detail behind the filter. The main [`README.md`](README.md) covers what it produces
and how to run it. This file explains how evidence is found, how a paper is scored, how the
search is validated, and why the approach is built this way.

## 🔎 How evidence is found

Evidence is not stored locally, and this is not a vector search over all of PubMed. For each claim
the filter builds a few keyword/boolean queries (`transformation/query.py`) and sends them to the
PubMed E-utilities and Europe PMC search endpoints, which return a capped, relevance-ranked list
of study IDs. It unions those with any dispute links from the paper's own XML, then fetches each
candidate's abstract and publication type.

Retrieval is tuned so a known refutation actually comes back:

- Several searches per claim: a broad one (intervention + outcome), one limited to strong study
  types (meta-analyses, reviews, RCTs, guidelines), and one looking for contradiction (`risk`,
  `harm`, `no benefit`).
- Two sources queried independently.
- Optional cache: set `MEDSCREEN_QUERY_CACHE` to a file path (DuckDB) to fetch repeated searches
  once across a corpus. Unset to always search live.

Embeddings (`transformation/semantic.py`) are used only to re-rank an already-fetched pool during
validation (`recall@k`); they cannot recover a study the queries never returned. Whether the
queries succeed is the central failure mode, and exactly what the validation measures.

> Status: proof of concept. Tested on 10 PubMed papers with Gemini 2.5 Flash Lite (6 kept, 4
> downweighted, 0 dropped; all 10 got a real verdict). Not yet run on a large or varied dataset;
> query construction, retrieval, and scoring all need refinement before production use.

## 📄 How a paper is scored

Scoring is mechanical, not a model opinion. Thresholds live in `transformation/scoring.py`.

0. Retraction fast path. If the paper's own XML carries a `RetractionIn` link, it is formally
   retracted: drop it immediately with `verdict_basis = retraction`, skipping extraction,
   retrieval, and the stance model. This is the cheapest and strongest signal, so it runs
   first. Every other paper is scored on retrieved evidence (`verdict_basis = evidence`). A
   present retraction link is reliable; its absence is not proof a paper was not retracted
   (indexing lag), so the evidence path still runs for everything else.
1. Weigh each study by its publication-type evidence tier (guideline 1.0, retraction 0.95,
   systematic review 0.9, meta-analysis 0.85, RCT 0.8, observational 0.5, case report 0.2, else
   0.4). Its pull on a claim is that tier × the model's stance confidence.
2. Score the claim. Starting at 0.5, the strongest supporting pull raises the score and the
   strongest refuting pull lowers it (refutation weighs about twice as much). Verdict is
   `refuted`, `contested`, `supported`, or `unverified` (no usable evidence). A claim is
   `refuted` only when the strongest refutation is unambiguous: strength (tier × confidence)
   ≥ 0.6, refuting study tier ≥ 0.8 (RCT or higher), and stance confidence ≥ 0.7. Anything
   weaker, or any case with evidence on both sides, is `contested` rather than `refuted`. This
   reserves the destructive action for high-precision cases (thresholds in `scoring.py`).
3. Roll up to the paper by its most damning claim: lowest score, worst verdict. `refuted` drops
   the paper, `contested` down-weights it, `supported` and `unverified` keep it. Unverified is
   kept on purpose, since a missing refutation is not proof a claim is false.

Each row also carries two provenance flags. `verdict_basis` (`retraction` / `evidence` /
`none`) records whether the verdict came from the retraction fast path or from retrieved
evidence. `refutation_timing` (`prior` / `subsequent` / `unknown`) records whether the refuting
evidence predates the paper (it ignored already-published evidence) or postdates it (the
reversal pattern). Timing is a time ordering only; it does not assert the paper was ever
accepted consensus. Both are written to the flat CSV alongside the continuous per-claim scores.

## ❓ Validation study: can the search find the evidence?

The filter is only as good as its search. A separate test (`medscreen-run`) checks that one step
using claims the field already knows were wrong, where the disproving study is recorded in
advance. It runs the filter's search and checks how often it finds the known study, scored in two
stages so a failure traces to the right one:

- Retrieval recall: of the disproving studies that exist, the fraction the search pulled back.
  Model-independent. The headline number.
- Stance recall: of those fetched, the fraction the model labelled refuting.
- Recall@k: retrieval recall within the top k results (k = 1, 5, 10, 20).
- False-contradiction rate: fraction of still-true controls wrongly flagged refuted (lower is
  better).

Each miss is tagged with a root cause (`not_indexed`, `entity_miss`, `retrieved_not_recognized`,
`condition_mismatch`, `tier_inversion`). Results print at the end of a run and save to
`reports/recall-<timestamp>.md` and `.csv`.

The gold set holds two kinds of `reversed` claim, tagged by `category`. A `reversal` is
good-faith science superseded by a newer study (found by keyword/high-tier search). A
`fabrication` is retracted misconduct whose disproving evidence is the retraction notice
(found via the retraction link) — a distinct retrieval path. Four fabrication cases (Wakefield,
Macchiarini, Boldt, Obokata) were added, so recall must be re-measured on the expanded slice;
the numbers below predate them.

> Status: real measurement, two known gaps. A real run (`pritamdeka/S-PubMedBert-MS-MARCO`
> embeddings, Gemini 2.5 Flash Lite stance) on the 10-reversal/8-control gold slice scored 80%
> retrieval recall and a 25% false-contradiction rate (`reports/recall-20260621-194531.md`).
> Stance recall is 100% conditional on retrieval, so retrieval is the sole bottleneck. Both misses
> are `not_indexed` (the 1984 Marshall & Warren ulcer paper and the NICE-SUGAR trial), needing
> MeSH-based queries or alias expansion. A stronger stance model than Flash Lite would improve the
> false-contradiction rate.

## 🤔 Doesn't this exist already?

Why not trust well-cited sources, like a h-index? Reputation judges who is speaking, not whether they are right.
The belief that hormone replacement therapy prevents coronary heart disease was highly cited the
entire time it was wrong, until the 2002 Women's Health Initiative trial found the opposite.

Why not just count refuted claims? That assumes the hard part — finding and confirming the
refuting study — is already done. This POC tests that step instead of taking it for granted.

### Related work

The closest methodological cousins decompose text into atomic claims and verify each against
retrieved evidence:

- FActScore (Min et al., 2023, "FActScore: Fine-grained Atomic Evaluation of Factual Precision
  in Long Form Text Generation") breaks a generation into atomic facts and scores each as
  supported/unsupported against a knowledge source.
- SAFE (Wei et al., DeepMind, 2024, "Long-form factuality in large language models") extends
  this with a search-augmented evaluator that issues queries and rates each atomic fact against
  retrieved results.

Both apply this pipeline to model *outputs*. MedScreen applies the same retrieve-then-verify
decomposition to training *inputs* (published papers), and adds an evidence-tier weighting plus a
retrieval-recall validation harness anchored on known consensus reversals.
