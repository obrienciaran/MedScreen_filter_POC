# CLAUDE.md

## Project Context

### What this project is

The goal is to create a data filter for medical AI training data.
Given a corpus of medical papers, the filter produces a flat table whose key columns are the paper identifier and whether
the paper's claims are truthful given the evidence, plus supporting metadata. Downstream
training keeps, drops, or down-weights papers from that table. The filter must generalise
across medical papers, not just a fixed list of known cases.

Truth is discovered by checking each paper's XML file, then checking its claims against trusted evidence, not inferred
from surface features (fluency, formatting, citations) or hand-written rules.  Confident medical misinformation imitates those surface features well, so a classifier or rule-based filter rewards the wrong thing while this evidence-grounded approach does not. 

Retrieval must be able to find the evidence that contradicts a wrong claim. If it cannot, we risk providing untruthful or
false data to the training pipeline, which will increase the degree of hallucinations in medical AI models. This repository is a harness that measures this single dependency on a slice where we already know the answers, so we learn whether the filter can work.
This is the proof of concept for a truth based data filter.

We use an LLM to extract the claim (unless we are in development mode and using generated data).

The core question is for medical claims the field already knows were reversed, can
retrieval surface the contradicting or superseding evidence? Output is a recall number plus
an error taxonomy showing where retrieval fails.


### Scope

- The filter (`medfact-filter`) is the product: ingest PubMed XML, extract claims, retrieve
  evidence, judge stance, aggregate to a per-paper verdict, and write a flat CSV plus an
  HTML graph. It runs fully on offline stubs and swaps in real backends via env.
- The harness (`medfact-run`) is the validation arm: it measures retrieval recall on the
  consensus-reversal gold slice, the dependency the filter's accuracy rests on.
- PubMed XML only (narrow focus). XML over .txt because it carries the
  CommentsCorrectionsList retraction/comment links, publication types, and MeSH.
- Claim-level scoring (more accurate than whole-paper). Verdict is supported / contested /
  refuted / unverified; action is keep / downweight / drop.
- On the roadmap, not built yet: GRADE aggregation, training-weight integration, UMLS
  grounding, ANN indexing, a non-LLM (NLI) stance backend.
- Sources: PubMed E-utilities and Europe PMC REST (both free). No Retraction Watch, UMLS,
  or licensed corpus.
- Slice: consensus-reversal cases (HRT and WHI, CAST, H. pylori, hospitalized COVID and
  hydroxychloroquine).
- DuckDB is the single store, exact brute-force cosine, no ANN index yet.
- Python 3.12, packaged with uv.

### Metrics

- Retrieval recall: was a known disproving study (the study recorded as overturning the
  claim) in the pool. Ground-truth anchored and independent of the stance judge, so the most
  trustworthy number.
- Stance recall: of retrieved known disproving studies, fraction recognised as refuting.
- Recall@k, and false-contradiction rate on still-true controls.
- Error taxonomy per miss: not_indexed, retrieved_not_recognized, entity_miss,
  condition_mismatch, tier_inversion.

### Architecture (`src/medfact_poc/`)

Shared core (top level):
- `schema.py`: Pydantic models for both the harness and filter flows.
- `http.py`: shared httpx client, rate limiting, TLS handling (`MEDFACT_INSECURE_TLS`,
  `MEDFACT_CA_BUNDLE`, `NCBI_EMAIL`, `NCBI_API_KEY`).
- `medline.py`: pure leaf extractors for MEDLINE/PubMed efetch XML, shared by
  `sources/pubmed.py` and `filtering/ingest.py` so the two parsers cannot drift.
- `llm.py`: provider-agnostic `LLMClient` (stub, Anthropic, OpenAI, Gemini), lazily
  imported. The single place a generative provider is chosen; used by stance and extract.
- `stance.py`: stance classification behind the `StanceBackend` Protocol, `classify_batch`
  runs calls concurrently. Stub (lexical) and `LLMStance` (any `llm` provider) backends.
- `graph.py`: `build_graph_data` (harness) and `build_paper_graph_data` (filter) are pure
  and tested. `render_html` writes a self-contained vis-network HTML file (CDN, no pyvis)
  with a data-driven legend and summary, edge filters, and hover/click focus.
- `store.py`: DuckDB cache for the harness (candidates, embeddings, claim_retrieval, stance).
- `sources/`: evidence providers behind the `Source` Protocol (`base.py`). Each owns its
  query building, fetch, and parse. Pure parse functions stay module level for testing.
- `retrieval/`: `query.py` builds queries, `semantic.py` re-ranks behind the `Embedder`
  Protocol, `links.py` expands the pool via PubMed retraction links.

`filtering/` (the product): `ingest.py` parses PubMed XML into `PaperRecord` (pure, tested);
`extract.py` lifts claims behind the `ClaimExtractor` Protocol (stub + LLM); `evidence.py`
retrieves refuting/debating works behind the `Retriever` Protocol (stub uses the paper's own
comment/retraction links, live reuses `Source`); `scoring.py` weighs stance into per-claim
and per-paper verdicts (pure, tested); `pipeline.py` orchestrates papers concurrently;
`flat_report.py` writes the flat CSV.

Harness (the validation arm, top level): `harness.py` orchestration and failure-bucket
assignment; `metrics.py`, `report.py` aggregation and markdown plus CSV output.

`cli/`: `medfact-build-cache`, `medfact-run`, `medfact-graph`, and `medfact-filter`.

Swappable plug points share the same Protocol shape: `Source`, `Embedder`, `StanceBackend`,
`ClaimExtractor`, `Retriever`, and `LLMClient`. Each has a dependency-free *stub* (an
offline placeholder that fakes the step with no LLM and no network) so the filter and
harness run offline, plus a real backend. Real runs need
`MEDFACT_LLM_PROVIDER` in {anthropic, openai, gemini}, `MEDFACT_EXTRACT_BACKEND=llm`,
`MEDFACT_STANCE_BACKEND=llm`, and `MEDFACT_RETRIEVER=live` (and `MEDFACT_EMBED_BACKEND=sbert`
for the harness). Stub output is a placeholder, not a real result.

### Data

`data/gold/consensus_reversals.yaml` is the gold dataset. Reversed claims carry the PMIDs of
the studies that overturned them (the known disproving studies). Controls carry none. All
those PMIDs were verified against PubMed esummary. It is a high-precision seed (ten reversals, eight controls).
It is the most accuracy-critical artifact, so change it with care.

### Invariants

- Factuality and writing quality are separate axes. The filter judges factuality. Do not
  merge them into one score, and never let writing quality stand in for truth.
- Keep claim conditions attached (population, comparator, dose, setting). Condition-stripped
  claims manufacture false verdicts.
- Retrieval recall stays ground-truth anchored and independent of the stance judge. A paper's truthfulness
  verdict can only be as reliable as the evidence retrieval surfaced for it.
- The truthfulness verdict is anchored in retrieved trusted evidence and its tier, not the
  LLM's freestanding opinion.
- Negative-evidence recall is a risk. Absence of contradicting evidence is not proof
  of truth. Do not assume retrieval found everything.

### The Principle of Least Abstraction

Your goal is clarity over cleverness. Start with the simplest possible solution. Follow the "Keep it simple stupid" principle.

### Duplication vs. Abstraction

Avoid hasty abstractions. Duplication is often better than the wrong abstraction.

### Codebase Architecture 

First consider clarity and simplicity. If architecture changes must be made to the codebase, follow DRY and SOLID principles as an general guideline. You may be pragmatic if needed and do not need to be strictly bound to these principles if it does not make sense.

## Important Rules

- *Never* run git commands without asking for user permission, even if 'auto-accept' is selected during a Claude Command session.
- *Never* run files which use an LLM API without asking for user permission,  even if 'auto-accept' is selected during a Claude Command session.
- *Never* attempt to re-engineer the code or alter data without asking for user permission.
- There is no need to check UI changes in HTML files. I will manually examine.
- *Never* make assumptions. Ask for more information and wait for the user response.
- Do *not* use numerical prefixes when writing comments.
- Do *not* use newline characters in print statements.
- Use double quotation marks instead of single quotation marks when possible.
- Use type hinting.
- Favor modular, resuable code.
- Favor vectorised code.
- Favor lazy loading.
- Use abstract base classes or Protocols to ensure code stability.
- Use Pydantic where appropriate.
- Testing should be implemented with Pytest where appropriate (i.e. critical code).
- Use concurrency when processing data with an LLM API.
- Read existing files before writing any output.
- Do not re-read files unless they have been changed.
- Avoid AI style language like the overuse of emdashes or semi-colons, or overuse of patterns like "not x, but y", or typical AI phrases like "honest review", "here's the catch", or "pragmatic approach".
