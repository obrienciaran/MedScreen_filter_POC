# Session Handoff / Next Steps

Handoff for a fresh Claude session. Read `CLAUDE.md` (scope + rules) and `DESIGN.md`
(design + validation status) first — they are the source of truth. This file captures the
open engineering work and the context that is not obvious from the code.

This is a data-quality filter: a retrieval + claim-verification pipeline over a corpus of
research papers (PubMed XML), plus a validation harness that measures one dependency —
retrieval recall — on a labeled evaluation set. An LLM is used only for two bounded steps
(claim extraction and stance labeling); it does not run retrieval or decide the verdict.

## Where things stand (as of commit `8fa04d5`)

- **Retrieval recall: 90% (18/20 positive cases)**, measured model-free (no LLM) via
  `medscreen-build-cache` + `medscreen-run --use-cache`.
- **Labeled set: 32 cases** = 20 positives (16 "reversal", 4 "fabrication") + 12 controls, in
  `data/gold/consensus_reversals.yaml`, spread across varied topic domains.
- **41 tests pass** (`.venv/bin/python -m pytest -q`; 1 live network test deselected by default).
- Two remaining retrieval misses, both **accepted** (see philosophy below):
  - A case where the claim and its disproving source share only the broad topic and use
    different vocabulary, so lexical/keyword search cannot bridge them without already encoding
    the answer. Needs semantic query expansion.
  - A case where the disproving source is buried among many similar high-tier sources that the
    query cannot disambiguate.

### Recent commits (newest first)
- `8fa04d5` Grow labeled set to 32 cases and add a condition-focused query rung
- `1693206` Retraction-targeted query rung recovers the retracted-source path
- `d706648` Treat and/or/not as boolean operators in query construction
- `3fd348f` Extend retraction fast path to the Retracted Publication publication type
- `0476899` Precision-first drop policy, provenance flags, and retracted-source cases

## Next steps (priority order)

### 1. Validate the condition-focused query rung's PRECISION (deferred, highest priority)
The condition rung (`intervention + population + high-tier filter`, in
`transformation/query.py`) recovered two cases and took recall 80% -> 90%. Its effect on
**precision** (false-positive rate on the 12 controls) is **UNVALIDATED**.

- **Blocker:** needs a real stance LLM. The `GEMINI_API_KEY` in the env is **free-tier
  (20 requests/day)**, already exhausted; a full run needs ~640-660 stance calls. No
  `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` set. `sentence-transformers` (the `embed` extra) is
  NOT installed, so ranking falls back to the stub (near-random top-20 to stance) — install it
  for a faithful precision number.
- **How to run once real capacity exists** (ASK THE USER FIRST — real LLM calls cost money and
  the user has said not to make real LLM calls yet):
  ```bash
  # retrieval cache (network, no LLM):
  MEDSCREEN_QUERY_CACHE=1 medscreen-build-cache --db data/cache/harness_measure.duckdb
  # precision run (real stance + real ranking):
  MEDSCREEN_LLM_PROVIDER=<provider> MEDSCREEN_STANCE_BACKEND=<provider> \
    MEDSCREEN_EMBED_BACKEND=sbert \
    medscreen-run --use-cache --db data/cache/harness_measure.duckdb --out /tmp/precision
  ```
  Then read the false-positive (false-contradiction) rate on the 12 controls. Prior baseline on
  an earlier, smaller control set was 25%.
- **Decision rule:** if precision holds, keep the rung. If it hurts precision, narrow or revert
  it — recall falls back to 80%, acceptable under the precision-first philosophy.
- **Cost note (already established):** the condition rung does NOT raise LLM cost. Stance is
  capped at the top 20 candidates per claim and every candidate pool already exceeds 20, so the
  call count is unchanged; the rung only widens retrieval (network-bound). KEEP the top-20 cap —
  it bounds eventual LLM spend at corpus scale.

### 2. Measure claim EXTRACTION (identified gap, not started)
Extraction (the LLM step that turns a paper into checkable claims) is unmeasured: the harness
feeds hand-authored normalized claims and bypasses the extractor. Build a small paper->claims
labeled set (~20-50 papers; a human writes the reference claims, optionally bootstrapped by a
model draft then curated), run the extractor once, cache, and score precision/recall plus
condition retention. This is the largest unmeasured variable in the pipeline.

### 3. Case-study inputs for verdict types not covered by the harness
The harness labeled set covers the positive and control cases. The filter's runtime verdicts
`contested`, `ungrounded`, and `supported` are shown via case-study XML inputs. One already
exists at `data/bixonimania_live/99000001.xml` (a fabricated-topic paper that lands in
`ungrounded -> review`; report in `reports/bixonimania_case_study.{csv,html}`). Could add a
retracted-source XML (`drop` via the fast path); `contested`/`supported` need a live run.

### 4. (Later) Semantic query expansion for the two hard misses
On the roadmap. LLM-driven query/topic expansion to match on meaning rather than surface
wording. Low priority given the precision-first stance.

### 5. (Optional) Grow the labeled set further for statistical stability.

## Established decisions & philosophy (respect these)
- **Evidence-based factuality filter, full stop.** It judges whether a paper's claims are
  factually correct against retrieved evidence, NOT paper quality (never use sample size,
  statistical rigour, venue prestige, citation count, author reputation). See CLAUDE.md
  "What this filter judges (and what it does not)".
- **Precision over recall.** Maximize true positives; label found cases correctly. False
  negatives are acceptable. `drop` is reserved for unambiguous, high-tier, high-confidence
  refutation (floors in `scoring.py`: strength >= 0.6, tier >= 0.8, confidence >= 0.7);
  anything weaker is `contested` -> downweight.
- **`ungrounded -> review`** (conservative), never silently kept.
- **Don't overengineer.** Duplication beats the wrong abstraction. MEASURE before adding query
  rungs — an earlier speculative rung was reverted for this reason; the condition rung was kept
  only because measurement justified it.
- **Provenance flags** already emitted per paper in the flat CSV: `verdict_basis`
  (retraction/evidence/none) and `refutation_timing` (prior/subsequent/unknown), plus continuous
  per-claim `claim_scores` and `refuting_confidence`.

## Environment gotchas
- `GEMINI_API_KEY` is FREE-TIER (20 req/day) — cannot do full LLM runs.
- `sentence-transformers` NOT installed -> sbert ranking unavailable (stub fallback = random
  ranking). Install the `embed` extra for real ranking.
- Bash outbound network is sometimes gated/denied; `WebFetch` worked for the PubMed E-utilities
  (esummary/efetch) during source-ID verification.
- Retrieval measurement is LLM-free and safe to run: `medscreen-build-cache` (network) then
  `medscreen-run --use-cache` (offline, stub stance — retrieval recall is stance-independent).
- Throwaway measurement DBs (`data/cache/*.duckdb`) are gitignored; delete them after use.

## Hard rules (from CLAUDE.md + user preferences)
- NEVER run git commands without asking the user.
- NEVER run anything that uses a real LLM API without asking (the user explicitly does not want
  real LLM calls right now).
- NEVER alter the labeled data (`consensus_reversals.yaml`) without asking — it is the most
  accuracy-critical artifact; every source ID must be verified against PubMed before adding.
- NO `Co-Authored-By` trailer in git commits (user preference; see memory
  `no-coauthor-trailer`).
- Keep the README high-level: query-rung internals, recall/precision numbers, and
  stance/false-positive detail belong in DESIGN.md, not the README.

## Key files
- `CLAUDE.md` — scope, invariants, rules.
- `DESIGN.md` — design, scoring, validation status (currently 90%, 18/20).
- `data/gold/consensus_reversals.yaml` — the 32-case labeled set (accuracy-critical).
- `src/medscreen_poc/transformation/query.py` — query rungs: core, high-tier, contradiction,
  retraction-targeted, condition-focused.
- `src/medscreen_poc/transformation/scoring.py` — verdict logic + drop floors.
- `src/medscreen_poc/orchestration/harness.py` — validation harness (retrieval recall).
- `src/medscreen_poc/orchestration/pipeline.py` — the filter (retraction fast-path, shared
  stance executor, top-20 cap).
