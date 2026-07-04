# Evaluation

Where the filter's accuracy is measured. The filter's correctness rests on retrieval — if the
disproving study is never retrieved, no downstream step can use it — so most evaluation targets
that dependency. `DESIGN.md` covers the *why*; this folder is the *how* and the results.

Evaluation has three parts:

1. **Validation harness** — quantitative metrics on the labeled gold slice
   (`data/gold/consensus_reversals.yaml`), via `medscreen-run`.
2. **Case studies** — single-paper demonstrations of each verdict type.
3. **Claim-extraction eval** (`eval/extraction/`) — measures the one LLM step the harness
   bypasses.

## 1. Validation harness

```bash
medscreen-build-cache          # fetch + cache candidate evidence (network, NO LLM)
medscreen-run --use-cache      # score against the cache; writes reports/recall-<timestamp>.{md,csv}
```

Metrics:

- **Retrieval recall** — of the known disproving studies, the fraction retrieval surfaced.
  Model-independent, the headline number.
- **Recall@k** — retrieval recall within the top *k* by semantic rank (k = 1, 5, 10, 20).
- **Stance recall** (conditional / overall) — of retrieved disproving studies, the fraction the
  stance judge labeled `refutes`.
- **False-contradiction rate** — fraction of still-true controls with any candidate labeled
  `refutes`. The precision guard (a harness that flags everything is worthless).
- **Failure taxonomy** — per miss: `not_indexed`, `entity_miss`, `retrieved_not_recognized`,
  `condition_mismatch`, `tier_inversion`.

Which metrics need a real LLM:

| Metric | Needs a real LLM? |
|---|---|
| Retrieval recall, recall@k | No — queries are deterministic; the stub stance is fine |
| Stance recall | Yes — a real stance backend |
| False-contradiction / precision | Yes — a real stance backend |

So **retrieval can be iterated for free**; only stance and precision need a paid backend. For a
real measurement:

```bash
MEDSCREEN_EMBED_BACKEND=sbert MEDSCREEN_STANCE_BACKEND=<provider> MEDSCREEN_LLM_PROVIDER=<provider> \
  medscreen-run --use-cache
```

### Latest results (gold slice: 16 reversals + 4 fabrications + 12 controls)

- **Retrieval recall: 90% (18/20)** — model-free, exact.
- **Stance recall (overall): 85%** — Gemini 2.5 Flash Lite, single run 2026-07-04.
- **False-contradiction: 25% (3/12 controls)** — but **0/12 false drops**: the flagged controls
  have more supporting than refuting evidence, so the filter scores them `contested` (downweight),
  not `refuted`. The precision-first drop floors hold.
- **Caveat:** that real run used stub ranking (`sentence-transformers` not installed), so the
  stance/precision figures are a rough proxy; retrieval recall is exact.
- Two retrieval misses, **accepted as a limitation**: a conceptual etiology reversal (claim and
  refutation share only the topic) and a landmark buried among similar high-tier trials.
  Deterministic search cannot reach them without over-fitting to the answer, and an LLM here
  would be over-engineering. Precision-first: some false negatives are acceptable.

## 2. Case studies

Single papers that exercise one verdict. The deterministic ones run offline (stub backends) and
are still real results; evidence-based verdicts would need a real run.

| Case | Input | Output | Verdict | Needs LLM? |
|---|---|---|---|---|
| Fabricated entity (a disease that does not exist) | `data/bixonimania_live/` | `reports/bixonimania_case_study.*` | `ungrounded → review` (nothing to retrieve) | No |
| Formally retracted paper | `data/retracted_drop_live/` | `reports/retracted_drop_case_study.*` | `refuted → drop` (retraction fast-path) | No |

Regenerate a case study:

```bash
medscreen-filter --input <folder> --out-csv reports/<name>.csv --out-html reports/<name>.html
```

## 3. Claim-extraction evaluation (`eval/extraction/`)

The harness feeds hand-authored claims and never runs the LLM extractor, so extraction quality
is unmeasured — the largest untested variable in the pipeline. This set closes that gap.

- `eval/extraction/reference_claims.yaml` — 10 papers (from the representative sample) with their
  parsed title and abstract, and an `expected_claims` reference set (24 claims, conditions
  attached).
- `eval/extraction/papers/` — the pinned paper XML.
- **Scoring** (deferred — the one step here that needs a real LLM): run the extractor on each
  paper, then compare its output to `expected_claims` on claim precision/recall (found the real
  claims without inventing any) and condition retention (kept population/comparator/direction).
- **Limitation — reference not human-verified:** the `expected_claims` were extracted by a strong
  model (Claude), not human-authored or verified. So the eval measures agreement between a strong
  reference model and the weaker extractor under test (Gemini 2.5 Flash Lite), not agreement with
  human ground truth; any reference error propagates. A human review pass would make it a true
  gold set — deferred for the POC.
- **Status:** reference claims authored (strong model); the extractor run and scoring are
  deferred (the extractor run is the one step needing a real LLM).

## Output locations

- Harness metrics: `reports/recall-<timestamp>.{md,csv}` (gitignored; regenerable).
- Case studies: `reports/<name>_case_study.{csv,html}` (kept).
