# Session Handoff / Next Steps

Handoff for a fresh Claude session. Read `CLAUDE.md` (scope + rules) and `DESIGN.md`
(design + validation status) first — they are the source of truth. This file captures the
open engineering work and the context that is not obvious from the code.

This is a data-quality filter: a retrieval + claim-verification pipeline over a corpus of
source documents (XML), plus a validation harness that measures one dependency — retrieval
recall — on a labeled evaluation set. An LLM is used only for two bounded steps (claim
extraction and stance labeling); it does not run retrieval or decide the verdict.

## Where things stand (as of commit `ab4b919`)

- **Retrieval recall: 90% (18/20 positive cases)**, measured model-free (no LLM) via
  `medscreen-build-cache` + `medscreen-run --use-cache`.
- **Precision measured once** (real Gemini 2.5 Flash Lite, stub ranking): 85% stance recall,
  25% soft false-contradiction, **0/12 false drops** — flagged controls score `contested`
  (downweight), not `refuted`. See `eval/README.md`.
- **`eval/` folder** now documents all evaluation (harness metrics, case studies, extraction).
- **Labeled set: 32 cases** = 20 positives (16 "reversal", 4 "fabrication") + 12 controls, in
  `data/gold/consensus_reversals.yaml`, spread across varied topic domains.
- **44 tests pass** (`.venv/bin/python -m pytest -q`; 1 live network test deselected by default).
- Two remaining retrieval misses, both **accepted** (see philosophy below):
  - A case where the claim and its disproving source share only the broad topic and use
    different vocabulary, so lexical/keyword search cannot bridge them without already encoding
    the answer. Needs semantic query expansion.
  - A case where the disproving source is buried among many similar high-tier sources that the
    query cannot disambiguate.

## Next steps (priority order)

### 1. Run the claim-extraction eval live (the one remaining LLM step) — START HERE
Everything is built and offline-validated: `eval/extraction/reference_claims.yaml` holds 24
reference claims (authored by a strong model — see the not-human-verified caveat there and in
`eval/README.md`), and `eval/extraction/score.py` runs the extractor and scores it (claim
precision/recall/F1 + condition retention), unit-tested. Remaining: run the extractor live and
commit the result.
- Run (uses the FREE-tier `GEMINI_API_KEY` — ~10 calls, fits its 20/day daily quota; do NOT use
  the paid key, which was a one-time run):
  ```bash
  MEDSCREEN_EXTRACT_BACKEND=llm MEDSCREEN_LLM_PROVIDER=gemini MEDSCREEN_LLM_MODEL=gemini-2.5-flash-lite \
    python eval/extraction/score.py --out eval/extraction/results.md
  ```
- Then commit `eval/extraction/results.md`. It measures strong-model-reference vs Gemini 2.5
  Flash Lite agreement, not human ground truth.

### 2. Faithful precision re-measure (can happen soon)
Precision was measured once but with stub ranking. A faithful re-run wants
`sentence-transformers` installed (`embed` extra) plus a real stance backend.

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
- `GEMINI_API_KEY` is free-tier (20 req/day) — fine for small runs (e.g. the ~10-call extraction
  eval), too little for a full harness run (~640 calls). A separate paid key `GEMINI_API_KEY_PAID`
  exists but was a deliberate one-time run — do not reuse it.
- `sentence-transformers` NOT installed -> sbert ranking unavailable (stub fallback = random
  ranking). Install the `embed` extra for real ranking.
- Bash outbound network is sometimes gated/denied; `WebFetch` worked for the source document API
  when direct calls were blocked (e.g. verifying source IDs).
- Retrieval measurement is LLM-free and safe to run: `medscreen-build-cache` (network) then
  `medscreen-run --use-cache` (offline, stub stance — retrieval recall is stance-independent).
- Throwaway measurement DBs (`data/cache/*.duckdb`) are gitignored; delete them after use.

## Hard rules (from CLAUDE.md + user preferences)
- NEVER run git commands without asking the user.
- NEVER run anything that uses a real LLM API without asking (the user explicitly does not want
  real LLM calls right now).
- NEVER alter the labeled data (`consensus_reversals.yaml`) without asking — it is the most
  accuracy-critical artifact; every source ID must be verified against the source API before adding.
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
