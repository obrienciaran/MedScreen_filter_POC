# Session Handoff / Next Steps

Handoff for a fresh Claude session. Read `CLAUDE.md` (scope + rules) and `DESIGN.md`
(design + validation status) first — they are the source of truth. This file captures the
open engineering work and the context that is not obvious from the code.

This is a data-quality filter: a retrieval + claim-verification pipeline over a corpus of
research papers (PubMed XML), plus a validation harness that measures one dependency —
retrieval recall — on a labeled evaluation set. An LLM is used only for two bounded steps
(claim extraction and stance labeling); it does not run retrieval or decide the verdict.

## Where things stand (as of commit `79b7893`)

- **Retrieval recall: 90% (18/20 positive cases)**, measured model-free (no LLM) via
  `medscreen-build-cache` + `medscreen-run --use-cache`.
- **Precision measured once** (real Gemini 2.5 Flash Lite, stub ranking): 85% stance recall,
  25% soft false-contradiction, **0/12 false drops** — flagged controls score `contested`
  (downweight), not `refuted`. See `eval/README.md`.
- **`eval/` folder** now documents all evaluation (harness metrics, case studies, extraction).
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

### 1. Claim-extraction evaluation (IN PROGRESS — the largest unmeasured variable)
The harness feeds hand-authored claims and never runs the extractor, so extraction quality is
untested. Scaffolded in `eval/extraction/`:
- `reference_claims.yaml` — 10 gathered papers with parsed title/abstract and an empty
  `expected_claims` list.
- **Remaining:** AUTHOR the expected claims by hand (the claims each paper actually asserts,
  conditions attached), then run the extractor once and score claim precision/recall plus
  condition retention. The extractor run is the one step here that needs a real LLM — deferred
  (user does not want real LLM calls yet).

### 2. Faithful precision re-measure (can happen soon)
Precision was measured once but with stub ranking. A faithful re-run wants
`sentence-transformers` installed (`embed` extra) plus a real stance backend.

## Done since the last handoff
- **Condition-rung precision VALIDATED** (single real Gemini 2.5 Flash Lite run): 85% stance
  recall, 25% soft false-contradiction, **0/12 false drops**. No precision penalty; rung kept.
- **Drop case study added** (`data/retracted_drop_live/` -> `reports/retracted_drop_case_study.*`),
  alongside the existing `ungrounded` case study (`data/bixonimania_live/`).
- **`eval/` folder created**, documenting harness metrics, case studies, and the extraction eval.

## Not doing (decided)
- Growing the gold set — it is a POC; current size (32) is fine.
- Chasing the two retrieval misses (conceptual reversal + buried landmark) — accepted as a
  limitation. Deterministic search can't reach them without over-fitting to the answer, and an
  LLM would be over-engineering. Precision-first: some false negatives are fine.
- `contested` / `supported` case studies — they need a real run; deferred.

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
