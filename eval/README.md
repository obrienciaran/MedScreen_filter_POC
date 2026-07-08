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
semantic rank (k of 1, 5, 10, and 20). It measures ranking, not just presence: recall@20 = 78%
means the disproving study ranked in the top 20 for 78% of reversed claims. That top-20 cut is the
one the live filter uses to bound how many candidates reach the paid stance judge, so a study
ranked past 20 is retrieved but never judged.

Stance recall is the fraction of retrieved disproving studies that the stance judge labelled as
refuting. It is reported both over just the retrieved ones and over all reversed claims.

Caveat: stance recall is measured with the known disproving study always handed to the judge, even
when it ranked past the top 20 (the harness injects the answer-key document into the stance set on
purpose, to isolate the judge's accuracy from ranking quality). That is why stance recall (91%) is
higher than recall@20 (78%): 4 reversed claims had the disproving study retrieved but ranked past
20, which a live filter would not have sent to the judge. Read them together: 91% is the judge's
accuracy given the study reaches it, and 78% is the end-to-end catch rate through the ranking cap.
The bottleneck here is ranking, not the judge.

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

### Results

Measured on the 64-claim gold set, which splits into **32 wrong claims** (28 famous reversals + 4
known fabrications) and **32 still-true controls**. Each measure below is a fraction of whichever
half it applies to, so the denominators are 32, not 64. The model, where one is used, is **Gemini
2.5 Flash Lite**.

| Measure | Result | Uses a model? |
|---|---|---|
| Disproving study found by the search | 94% (30 of 32 wrong) | No |
| That study ranked in the top 20 | 78% (25 of 32 wrong) | No |
| Judge reads the study as refuting, once shown | 91% (29 of 32 wrong) | Yes |
| True controls picking up a refuting label | 47% (15 of 32 true) | Yes |
| True controls wrongly dropped | 0 of 32 true | Yes |
| Wrong claims caught (dropped or down-weighted) | 32 of 32 wrong | Yes |
| Claims correctly extracted | 83% | Yes |

How to read the rows:

- **Found by the search** is the headline: if the disproving study is never retrieved, nothing
  downstream can use it. It uses no model, so it is exact and free.
- **Ranked in the top 20** matters because only the 20 most relevant studies per claim are sent to
  the judge; a study ranked lower is found but never judged. This, not the judge, is the real limit:
  when the disproving study does reach the judge, it is read as refuting 91% of the time.
- **Refuting label on a control** is high (47%) because ordinary true claims pull in near-miss
  studies about a different population or dose, which the judge, reading only the abstract, over-reads
  as a contradiction. It never turns into a drop: dropping a paper takes two independent strong
  studies that agree, so every over-flagged control is down-weighted (reversible), not deleted. Of
  the 32 wrong claims, 13 are dropped and 19 down-weighted.

Two wrong claims are missed, and both are accepted limits. In one, the claim and its refutation
share only the topic (peptic ulcers, overturned by *H. pylori*). In the other, the overturning
trial is buried among many near-identical ones (vertebroplasty). A keyword search cannot reach
either without already naming the answer.

Claim extraction found 83% of the expected claims and kept their conditions (population, comparator,
direction) 93 to 100% of the time. Its precision is lower (43%) because it splits claims more
finely than the reference. See `eval/extraction/README.md`.

### Filter behaviour on ordinary papers

The harness above measures known reversals. To see how the filter behaves on ordinary papers, run
it on `data/representative/` (30 recent, non-retracted papers across common clinical areas) and
audit how many were flagged:

```bash
MEDSCREEN_LLM_PROVIDER=<provider> MEDSCREEN_EXTRACT_BACKEND=llm MEDSCREEN_STANCE_BACKEND=llm \
  MEDSCREEN_RETRIEVER=live medscreen-filter --input data/representative \
  --out-csv reports/representative.csv
python scripts/flag_audit.py --csv reports/representative.csv
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
