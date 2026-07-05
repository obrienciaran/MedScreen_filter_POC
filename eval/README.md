# Evaluation

This folder is where the filter's accuracy is measured. The filter can only be as good as its
retrieval: if the disproving study is never retrieved, no later step can use it. So most of the
evaluation targets retrieval. `DESIGN.md` explains why the filter is built this way. This folder
covers how it is measured and what the results are.

There are three parts:

1. The validation harness gives numbers on the labelled gold set
   (`data/gold/consensus_reversals.yaml`), run with `medscreen-run`.
2. The case studies are single papers that show one verdict each.
3. The claim-extraction check measures the one LLM step the harness skips (`eval/extraction/`).

## 1. Validation harness

```bash
medscreen-build-cache          # fetch and cache candidate evidence (network, no LLM)
medscreen-run --use-cache      # score against the cache; writes reports/recall-<timestamp>.{md,csv}
```

The metrics it reports:

Retrieval recall is the fraction of the known disproving studies that retrieval brought back. It
does not depend on the model, so it is the main number.

Recall@k is retrieval recall counting only cases where the disproving study ranked in the top k by
semantic rank (k of 1, 5, 10, and 20).

Stance recall is the fraction of retrieved disproving studies that the stance judge labelled as
refuting. It is reported both over just the retrieved ones and over all reversed claims.

False-contradiction rate is the fraction of still-true control papers where any candidate was
labelled refuting. It guards precision, because a harness that flags everything has perfect recall
and no value.

Failure taxonomy records, for each miss, why it missed: `not_indexed`, `entity_miss`,
`retrieved_not_recognized`, `condition_mismatch`, or `tier_inversion`.

Only some metrics need a real LLM:

| Metric | Needs a real LLM? |
|---|---|
| Retrieval recall, recall@k | No. The queries are deterministic, so the stub stance is fine. |
| Stance recall | Yes, a real stance backend. |
| False-contradiction and precision | Yes, a real stance backend. |

So retrieval can be measured for free, and only stance and precision need a paid backend. For a
real measurement:

```bash
MEDSCREEN_EMBED_BACKEND=sbert MEDSCREEN_STANCE_BACKEND=<provider> MEDSCREEN_LLM_PROVIDER=<provider> \
  medscreen-run --use-cache
```

### Results (gold slice: 16 reversals, 4 fabrications, 12 controls)

Retrieval recall is 90% (18 of 20), model-free and exact.

Stance recall overall is 85%, using sbert ranking and Gemini 2.5 Flash Lite for stance.

The false-contradiction rate is 25% (3 of 12 controls), but no control was dropped (0 of 12). The
three flagged controls had more supporting than refuting evidence, so the filter scored them
`contested` (down-weight). A mislabelled control becomes a down-weight rather than a drop.

Extraction, comparing Gemini 2.5 Flash Lite against a stronger reference model, found 83% of the
expected claims. Its precision is lower (43%) because it extracts more, finer-grained claims. It
kept the conditions (population, comparator, direction) 93 to 100% of the time. See
`eval/extraction/results.md`.

Two retrieval misses remain, and they are accepted as a limitation. One is a conceptual reversal
where the claim and its refutation share only the topic. The other is a landmark trial buried among
many similar high-tier trials. A keyword search cannot reach either without already naming the
answer, and adding an LLM step here would not be worth it for the POC. The filter is precision
first, so some misses are acceptable.

### Filter behaviour on ordinary papers

The harness above measures known reversals. To see how the filter behaves on ordinary papers, run
it on `data/representative_large/` (30 recent, non-retracted papers across common clinical areas)
and audit how many were flagged:

```bash
MEDSCREEN_LLM_PROVIDER=<provider> MEDSCREEN_EXTRACT_BACKEND=llm MEDSCREEN_STANCE_BACKEND=llm \
  MEDSCREEN_RETRIEVER=live medscreen-filter --input data/representative_large \
  --out-csv reports/representative_large.csv
python scripts/flag_audit.py --csv reports/representative_large.csv
```

`flag_audit.py` reports how many of these papers the filter did not keep, that is, how many it
down-weighted or dropped. Because the papers are ordinary and non-retracted, the filter should keep
almost all of them, so any it did not keep is a candidate false positive to inspect.

Result on the 30-paper set with Gemini 2.5 Flash Lite: 15 kept, 14 down-weighted, 1 dropped, so
half the papers were not kept. The down-weights are mostly review and guideline papers where one of
several extracted claims drew a weak or mixed refutation. The single drop was a corroborated
refutation of one claim (two or more studies), which is what the drop action is reserved for.

Half is high, partly because the set is dominated by broad review articles, which make many claims
and so are more exposed to a single flagged claim than a primary research paper would be.
Three things would lower it. Reading each paper's full text instead of only its abstract would give
the stance judge the context to rule out false refutations that the abstract alone leaves
ambiguous. Using a more capable model for extraction and stance would cut spurious claims and
misjudged evidence. And reducing how much one flagged claim can move a paper that makes many claims
would stop a single weak refutation from down-weighting an otherwise sound paper. All three are
future work.

## 2. Case studies

Single papers that show one verdict each. The offline ones use stub backends and are still real
results. Evidence-based verdicts need a real run.

| Case | Input | Verdict | Needs LLM? |
|---|---|---|---|
| Fabricated entity (a disease that does not exist) | `data/bixonimania_live/` | `ungrounded`, so `review` (nothing to retrieve) | No |
| Formally retracted paper | `data/retracted_drop_live/` | `refuted`, so `drop` (retraction fast path) | No |

Regenerate a case study:

```bash
medscreen-filter --input <folder> --out-csv reports/<name>.csv --out-html reports/<name>.html
```

## 3. Claim-extraction check (`eval/extraction/`)

The harness feeds hand-written claims and never runs the LLM extractor, so extraction quality is
untested there, and it is the largest untested variable in the pipeline. This set closes that gap.

`eval/extraction/reference_claims.yaml` holds 10 papers from the representative sample, each with
its parsed title and abstract and a reference set of expected claims (24 claims, with conditions
attached). `eval/extraction/papers/` holds the pinned paper XML.

Scoring runs the extractor on each paper and compares its output to the expected claims on two
things: claim precision and recall (did it find the real claims without inventing extras), and
condition retention (did it keep the population, comparator, and direction). This is the one step
here that needs a real LLM, so it is deferred.

One limitation: the expected claims were written by a strong model (Claude), not by a person. So
the check measures agreement between a strong reference model and the weaker extractor under test
(Gemini 2.5 Flash Lite), not agreement with human ground truth, and any error in the reference
carries through. A human review pass would turn it into a true gold set, and that is deferred for
the POC.

Status: the reference claims are written; running the extractor and scoring it are deferred,
because running the extractor needs a real LLM.

## Output locations

Harness metrics go to `reports/recall-<timestamp>.{md,csv}` (regenerable, not committed). Case
study output goes to `reports/<name>.{csv,html}` (regenerable).
