# MedFact_POC — Evidence-Grounded Truth Filter for Medical Papers

## Overview

Imagine you want to teach a medical AI using millions of articles. Some of those
articles are wrong. They confidently promote treatments that were later disproven.
The danger is that a *well-written* wrong article looks just as trustworthy as a
correct one. Good writing is not the same as being right.

The usual way to fix this is to check each claim against trusted medical evidence,
"Does the research actually back this up, or does it contradict it?" But that only
works if we can *find* the contradicting evidence in the first place. When a treatment
is debunked, the debunking is often buried, scattered, or poorly indexed compared to the
original (wrong) claim.

This project tests the one assumption that everything else depends on. That assumption is
simple. An automated search can find the evidence that contradicts a wrong claim.

Here is how we test it. We take medical claims that we already know turned out to be
wrong. One example is the old belief that hormone replacement therapy prevents heart
disease, which large trials later disproved. For each of these claims we already know
which study overturned it, so we have the right answer in advance. Then we run an
automated search and check a single thing. Does the search find that overturning study?

The result tells us whether this POC can work at all. If the search usually finds the overturning
evidence, the foundation is solid and the full system is worth building. If the search
usually misses it, the foundation is broken. A system built on top of a broken search
would look reliable on famous topics, where the evidence is easy to find, and would be
quietly wrong on rarer topics, where the evidence is hard to find. Being wrong on the
hard topics is the exact problem this project wants to solve.

It works like testing a new research assistant before you trust them with real work.
You give the assistant a set of medical claims that you already know are false, and you
keep to yourself the study that disproved each one. That hidden list is your answer key.
You then ask the assistant to go and find the disproving study for every claim. Because
you already hold the answers, you can check two things. First, did the assistant find
the right study. Second, when the assistant failed, what went wrong. Maybe (s)he never
found the study at all. Maybe (s)he found the study but did not realise the study disagreed
with the claim. Those two failures call for two different fixes, which is why the tool
records them separately.

## What it produces

The end goal is a data filter for training-data curation. Run it over a corpus of medical
papers and it returns a flat table, one row per paper:

| paper | truthful | ... |
|---|---|---|
| paper identifier | do its claims hold up against the evidence | confidence, contradicting studies, evidence tier, other metadata |

Downstream training keeps, drops, or down-weights papers from that table. The verdict is
*discovered* by checking each paper's claims against trusted evidence, not guessed from
writing quality or hand-written rules, and the method is meant to generalise across medical
papers rather than a fixed list of known cases. The evidence graph is an optional visual
aid over the same data, not the product.

This repository is the foundation of that filter. Before a truthfulness verdict can be
trusted, retrieval has to be able to find the evidence that contradicts a wrong claim. The
harness here measures exactly that, on claims where the answer is already known, so we know
the filter can work before building the rest of it.

## In one line

> For medical claims the world *already knows* were reversed, can retrieval actually
> surface the contradicting / superseding evidence?

If that recall is poor, a claim-scoring pipeline degrades to "confident about the
well-litigated, silently wrong about everything under-indexed".

## What it measures

The headline metric is deliberately **decomposed** so failures are localizable:

- **Retrieval recall** — was contradicting evidence retrieved at all (in top-k)?
- **Stance recall** — given it was retrieved, was it *recognized* as refuting?
- **Recall@k** — rank sensitivity.
- **False-contradiction rate** — on a control set of still-true claims, how often do we
  wrongly flag contradiction? (A harness that flags everything has perfect recall and
  zero value.)

And the real deliverable, an **error taxonomy** per missed claim:
`not_indexed`, `retrieved_not_recognized`, `entity_miss`, `condition_mismatch`,
`tier_inversion`.

## Scope

Two entry points share the same machinery:

- **The filter** (`medfact-filter`) is the product: point it at a folder of PubMed XML and
  it writes the per-paper truthfulness table plus an HTML graph.
- **The harness** (`medfact-run`) is the validation: it measures retrieval recall on the
  consensus-reversal gold slice, the dependency the filter's accuracy rests on.

On the roadmap, not built here yet: GRADE aggregation, training-weight integration, UMLS
grounding, ANN indexing, and a non-LLM (NLI) stance backend.

## Setup

```bash
uv venv --python 3.12
uv pip install -e ".[dev]"
# optional backends: real embeddings, and one LLM provider for claim extraction + stance
uv pip install -e ".[dev,embed,gemini]"   # or anthropic / openai
```

Everything runs end-to-end with **no optional deps and no API key** using built-in *stub*
backends. A stub is a placeholder that fakes a step's output deterministically with **no
LLM call and no network**, so you can validate the plumbing before spending anything. The
real run uses an LLM (see below); stub output is a placeholder, not a real result.

Set credentials/keys via env when using real backends:

```bash
export NCBI_API_KEY=...        # optional, raises PubMed rate limit
export NCBI_EMAIL=you@org.com  # polite identification for E-utilities
export GEMINI_API_KEY=...      # or ANTHROPIC_API_KEY / OPENAI_API_KEY
```

## Run the filter

```bash
# Offline, synthetic (stub) backends — no key needed:
medfact-filter --input path/to/pubmed_xml_dir

# Real backends (claim extraction + stance via an LLM, live evidence retrieval):
MEDFACT_LLM_PROVIDER=gemini MEDFACT_EXTRACT_BACKEND=llm \
MEDFACT_STANCE_BACKEND=llm MEDFACT_RETRIEVER=live \
  medfact-filter --input path/to/pubmed_xml_dir
```

It writes `reports/filter.csv` (one row per paper: pmid, verdict, score, action, metadata)
and `reports/filter.html` (the interactive graph). `verdict` is one of supported /
contested / refuted / unverified; `action` is keep / downweight / drop. The input is
PubMed/MEDLINE XML because that format carries the `CommentsCorrectionsList` retraction and
comment links, the publication types (evidence tier), and MeSH terms the filter relies on.

## Run the harness

```bash
medfact-build-cache      # fetch candidate evidence for the gold set into DuckDB
medfact-run              # run the measurement, write report to ./reports/
medfact-graph            # render the evidence graph to reports/graph.html
pytest                   # unit tests (network tests are opt-in: pytest -m live)
```

## Visualization

`medfact-graph` turns the stored run into an interactive network you open in a browser
(`reports/graph.html`). Claims and evidence papers are nodes. A claim links to each
evidence item the stance step judged, and the edge colour shows the verdict: red for
refutes, green for supports, grey for neutral. A study known to disprove a claim is drawn
as a blue dot ringed in gold when the search found it, and when the search missed it as an
orange triangle joined by an amber dashed "not retrieved" link, so recall gaps stand out.
Retraction links between papers are drawn as dashed purple edges.

A language model is used in only two narrow places: it reads each claim from the paper's
text, and it judges whether a retrieved study disproves or supports that claim. It does not
do the search, it does not decide which papers are kept or dropped, and it does not score a
paper on its own; those come from the retrieved evidence and its tier.

The page is self-contained (vis-network from CDN, no Python rendering dependency) and
adds a summary panel, a legend, edge-type filters, a "recall gaps only" view, a freeze or
resume layout toggle, hover-to-focus neighbourhood highlighting, and a click-for-details
panel. The layout is force-directed by default (`--no-physics` to start it frozen).

`medfact-filter` reuses the same renderer for `reports/filter.html`, where each node is a
scored paper coloured by its verdict (red refuted, amber contested, green supported, grey
unverified) and a blue dot ringed in gold marks a study that refuted it. The summary and
legend adapt to the data automatically.

Run `medfact-run` first so the store holds stance results.
