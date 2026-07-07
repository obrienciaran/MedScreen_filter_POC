# Future work

Concrete tasks to make the filter beat native LLM knowledge where it should, and to
measure that honestly. Ordered roughly by priority.

## 1. Full-text stance judgment — DONE

- [x] Read each retrieved study's full text in the stance step, not just the abstract
      (opt-in via `MEDSCREEN_STANCE_FULLTEXT=1`).
- [x] Source full text from the Europe PMC open-access subset; fall back to abstract
      when full text is unavailable, and record which was used
      (`evidence_text_source` column in `filter.csv`).
- [ ] Re-measure stance recall and the false-contradiction rate on the gold slice;
      expect the false-positive (down-weight) rate on ordinary papers to drop.

Note: this lifts the *stance* ceiling only. It cannot recover a study retrieval never
returned, so it does not fix the two retrieval misses.

## 2. Expand the gold set — DONE (doubled to 64)

Doubled the gold set from 32 to 64 claims (28 reversals + 4 fabrications + 32 controls),
adding twelve less-famous reversals and twenty generic still-true controls.

- [x] Add more reversals beyond the most famous cases (ACCORD, ASPREE, ORBITA, POISE,
      ILLUMINATE, ProCESS, CHEST, FIDELITY, HPS2-THRIVE, VITAL, PALLAS, WHI CaD).
- [x] Add generic controls across common clinical areas.
- [x] Verify every new `answer_key` PMID against PubMed efetch (title + year).
- [x] Keep conditions attached in `normalized` (population, comparator, dose, direction).
- [ ] Re-measure retrieval recall (free, model-free) and stance/precision (flash-lite)
      on the full 64 — this is step 4.

## 3. Human-labelled ordinary-paper set

- [ ] Assemble a small sample of ordinary, non-reversal papers with an expected
      keep / down-weight / drop label per paper (human-reviewed).
- [ ] Report the end-to-end keep/drop accuracy and false-positive rate. This is the
      currently-missing operating-point number.

## 4. LLM-only baseline comparison — DONE

- [x] Ran an LLM-only fact-checker (gemini-2.5-flash-lite, no retrieval) on the 64-claim
      set: 96.9% accuracy (62/64), 0 false positives, 2 false negatives.
- [x] The two misses illustrate where retrieval/XML wins: a fabrication the model does not
      know was retracted (`macchiarini-trachea`, caught by the filter's retraction fast
      path) and a contested reversal (`orbita-pci-angina-symptoms`). See
      `reports/llm_only_baseline.md`.
- [ ] Still to add for a sharper contrast: post-cutoff and long-tail cases where native
      knowledge is stale (item 2 seeds this).

## 5. Retrieval — DONE

- [x] Added an intervention-only high-tier query rung (PubMed + Europe PMC): surfaces
      strong studies on the intervention when a differently-worded outcome would bury the
      landmark trial (e.g. HPS2-THRIVE, whose title has no outcome term).
- [x] Canonicalised the intervention/outcome terms of five newly-added reversals whose
      verbose prose over-narrowed retrieval (conditions kept in comparator/population).
- Result: model-free retrieval recall on the expanded reversed set rose from 78.1%
  (25/32) to 93.8% (30/32). The only remaining misses are the two known-hard cases
  (H. pylori conceptual reversal, vertebroplasty buried trial), accepted under a
  precision-over-recall policy.

## 6. Semantic re-ranking for scale — DONE

- [x] The production filter (`LiveRetriever`) now re-ranks a claim's query hits by sbert
      similarity before the 20-cap when `MEDSCREEN_EMBED_BACKEND=sbert`, so the studies
      sent to the stance LLM are the most relevant rather than the first found. Dispute
      links still lead and are never cut.
- [x] Embeddings are cached in DuckDB (`store.embeddings`), shared by the filter and the
      harness, so a study is embedded once across claims, papers, and runs. Runs on GPU
      (CUDA/MPS) when available.
- [ ] Roadmap: an approximate-nearest-neighbour index to replace brute-force cosine when
      the embedding store grows large.
