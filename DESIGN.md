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

- Several searches per claim, unioned: a broad one (intervention + outcome), one limited to
  strong study types (meta-analyses, reviews, RCTs, guidelines), one looking for contradiction
  (`risk`, `harm`, `no benefit`), a retraction-targeted one (intervention + retracted-publication
  filter, so link expansion can reach a retraction notice), and a condition-focused one
  (intervention + population + strong study types, since a descriptive outcome over-narrows while
  the disease name pins a landmark trial). Boolean words in a term are treated as operators and
  each term is parenthesised so `A OR B` groups correctly.
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

0. Retraction fast path. If the paper's own XML shows it is formally retracted, either via a
   `RetractionIn` link or the `Retracted Publication` publication type, drop it immediately with
   `verdict_basis = retraction`, skipping extraction, retrieval, and the stance model. This is
   the cheapest and strongest signal, so it runs first (the pub type covers the case where the
   link has not yet propagated). Every other paper is scored on retrieved evidence
   (`verdict_basis = evidence`). A present retraction signal is reliable; its absence is not
   proof a paper was not retracted (indexing lag), so the evidence path still runs otherwise.
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

### Why `n_refuted_claims` can be `0` while `top_refuting_tier` and `refuting_pmids` have values

Expected, not a bug. Each claim is checked against several retrieved studies; some may refute it,
others support it. A claim is `refuted` only when studies refute it, none support it, and the
strongest refutation is unambiguous (tier × confidence ≥ 0.6, refuting tier ≥ 0.8, confidence
≥ 0.7). A claim with studies on both sides, or with only a weak lone refutation, is `contested`.

`refuting_pmids` and `top_refuting_tier` collect every study that refuted any claim, regardless of
how that claim was finally scored, so a `contested` claim still contributes its refuting studies
to those columns. `n_refuted_claims` counts only claims whose final verdict is `refuted`. So a
paper whose claims are all `supported` or `contested` shows `n_refuted_claims = 0` while
`refuting_pmids` is non-empty.

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
(found via the retraction link) — a distinct path reached by a retraction-targeted query rung.

> Status: retrieval recall is 90% (18 of 20 reversed) on the gold slice (16 reversals +
> 4 fabrications + 12 controls), measured model-free via `medscreen-build-cache` +
> `medscreen-run --use-cache`. Two misses remain. The peptic-ulcer etiology reversal shares only
> the disease with its refutation ("stress and acid" vs "H. pylori"), so no keyword or MeSH query
> finds it without already naming the answer (bacteria) — a known limit of keyword retrieval for
> conceptual reversals. The vertebroplasty reversal's landmark trial is buried among many similar
> high-tier trials that the condition does not disambiguate. Both are accepted false negatives
> rather than over-broadening the search and risking control precision; bridging them needs a
> semantic query-expansion step, deferred on purpose.
>
> The condition-focused query rung (intervention + population) added arthroscopy and PCI, whose
> descriptive outcomes previously over-narrowed the core query. It does not raise LLM cost:
> stance is capped at the top 20 candidates per claim and every pool already exceeds 20, so the
> call count is unchanged; the rung only widens retrieval, which is network-bound.
>
> Stance and precision, measured on the gold slice with sbert ranking and a real stance model
> (Gemini 2.5 Flash Lite): 85% overall stance recall (17 of 20 answer keys recognised as
> refuting; the misses are the two retrieval misses plus one condition-mismatch). The
> false-contradiction rate (a control with any candidate labelled refuting) is 25% (3 of 12).
> Crucially, none of those three would be dropped: each has more supporting than refuting
> evidence, so the filter scores them `contested` (downweight), not `refuted`. The false DROP
> rate on controls is 0 of 12 — the precision-first floors hold. The residual softness is a
> stance-judge limitation, not a retrieval one. An earlier stub-ranked run gave the same 85% /
> 25% / 0-drops, so ranking quality did not move the headline numbers.
>
> Claim extraction (Gemini 2.5 Flash Lite) was measured against a strong-model reference: 83%
> claim recall and strong condition retention (93-100% for population/comparator/direction), so
> the extractor keeps conditions rather than stripping them; precision is lower because it
> extracts more, finer-grained claims than the reference (`eval/README.md`).

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
