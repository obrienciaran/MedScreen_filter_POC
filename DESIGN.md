# 🏥 MedScreen: design notes

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
  (`risk`, `harm`, `no benefit`), an intervention-only high-tier one (drops the outcome, since a
  landmark trial reliably names the intervention but often phrases the outcome differently), a
  retraction-targeted one (intervention + retracted-publication filter, so link expansion can
  reach a retraction notice), and a condition-focused one (intervention + population + strong
  study types, since a descriptive outcome over-narrows while the disease name pins a landmark
  trial). Boolean words in a term are treated as operators and each term is parenthesised so
  `A OR B` groups correctly.
- Two sources queried independently.
- Optional cache: set `MEDSCREEN_QUERY_CACHE` to a file path (DuckDB) to fetch repeated searches
  once across a corpus. Unset to always search live.

Per-claim cap and ordering. The filter keeps at most 20 candidate studies per claim
(`scraping/evidence.py`), which also caps the stance model at 20 calls per claim so a claim
matching hundreds of papers never triggers hundreds of model calls. The paper's own dispute links
(retraction notices, then comment/erratum links) fill the first slots, since those are the
strongest evidence a filter has; query hits fill the rest. By default query hits keep the order the
search APIs returned (free, no model). With the optional sbert backend
(`MEDSCREEN_EMBED_BACKEND=sbert`) they are re-ranked by meaning before the cap, so the 20 judged are
the most relevant rather than the first found. Embeddings only re-order an already-fetched pool;
they cannot recover a study the queries never returned, which is why retrieval, not ranking, is the
central failure the validation measures. Vectors are cached in DuckDB, shared with the harness, and
run on GPU when present.

The stance judge reads only each candidate's title and abstract, not full text. Abstracts are cheap
to fetch and short to send, but a refutation or condition caveat stated only in a paper's Results or
Methods is then invisible, which limits both stance recall and precision. Accepted for the POC.

## 📄 How a paper is scored

Scoring combines the stance model's per-study labels, weighted by evidence tier, with fixed
thresholds in `transformation/scoring.py`. The arithmetic and the keep/drop decision are fixed and
never call the model. But its inputs, each study's stance label and the model's confidence in it,
do come from the model, so the stance model still shapes which way an evidence-based verdict goes,
even though it never makes the verdict itself. The scoring layer guarantees that no single study's
label decides a paper on its own: each label is weighted by the study's evidence tier, combined
across all the retrieved evidence, and held to strict drop thresholds.

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
2. Score the claim. First drop any refutation the judge marked off-scope (`condition_match`
   false, meaning the study tested a different population, dose, comparator, or setting than the
   claim): it refutes a different claim and is not evidence against this one. Starting at 0.5,
   supporting evidence raises the score and refuting evidence
   lowers it (refutation weighs about twice as much). Both sides are combined across all the
   studies found, not read off the single strongest one. The strongest study sets the base, and
   each further study that agrees adds a smaller amount on top. So a consistent body of evidence
   counts for more than one study, and many weak studies cannot outweigh one strong study, because
   each study's weight already reflects its evidence tier (a case report adds very little).
   The verdict is `refuted`, `contested`, `supported`, `neutral` (only neutral evidence was
   found), or `ungrounded` (no evidence was found). A claim is `refuted`, which drops the paper,
   only when the refutation is strong and backed up: at least two separate studies refute it, the
   combined refuting strength is at least 0.6, and the strongest of those studies is tier 0.8 or
   higher (an RCT or above) with a stance confidence of at least 0.7. Requiring two studies means
   a single study refuting one claim of a paper that makes several claims down-weights the paper
   instead of dropping it, which was the main cause of wrongful drops. Anything weaker, or any
   claim with evidence on both sides, is `contested` instead. This keeps the drop action for
   high-confidence, corroborated cases (thresholds in `scoring.py`).

   A paper that was correct when written and later superseded by newer work, but never actually
   contradicted, is kept on purpose. Science is incremental, and a once-true paper is not false.
   Only a genuine refutation (subsequent evidence that contradicts the claim) moves it off `keep`.
3. Roll up to the paper by its most damning claim: lowest score, worst verdict. `refuted` drops
   the paper, `contested` down-weights it, `supported` and `neutral` keep it, `ungrounded` flags
   it for review. Neutral is kept on purpose, since a missing refutation is not proof a claim is
   false.

Each row also carries two provenance flags. `verdict_basis` (`retraction` / `evidence` /
`none`) records whether the verdict came from the retraction fast path or from retrieved
evidence. `refutation_timing` (`prior` / `subsequent` / `unknown`) records whether the refuting
evidence predates the paper (it ignored already-published evidence) or postdates it (the
reversal pattern). Timing is a time ordering only; it does not assert the paper was ever
accepted consensus. Both are written to the flat CSV alongside the continuous per-claim scores.

### Why `n_refuted_claims` can be `0` while `top_refuting_tier` and `refuting_pmids` have values

Expected, not a bug. Each claim is checked against several retrieved studies; some may refute it,
others support it. A claim is `refuted` only when studies refute it, none support it, and the
refutation is strong and backed up (at least two studies refute it, combined refuting strength at
least 0.6, and the strongest study tier 0.8 or higher with confidence at least 0.7). A claim with
studies on both sides, or with only a single or weak refutation, is `contested`.

`refuting_pmids` and `top_refuting_tier` collect every study that refuted any claim, regardless of
how that claim was finally scored, so a `contested` claim still contributes its refuting studies
to those columns. `n_refuted_claims` counts only claims whose final verdict is `refuted`. So a
paper whose claims are all `supported` or `contested` shows `n_refuted_claims = 0` while
`refuting_pmids` is non-empty.

## ❓ Validation study: can the search find the evidence?

The filter is only as good as its search: if the disproving study is never retrieved, nothing
downstream can use it. So a separate test (`medscreen-run`) measures exactly that, on the 64-claim
gold set (32 reversed + 32 still-true controls) where each reversed claim's disproving study is
recorded in advance. Reversed claims come in two kinds: a `reversal` is good-faith science later
superseded (found by keyword/high-tier search), a `fabrication` is retracted misconduct whose
disproving evidence is the retraction notice (reached by a retraction-targeted query).

Four measures, each in plain English, with the result on the full set:

- **Retrieval recall** — did the search pull the known disproving study into the pool at all? This
  is model-free, so it is the headline number. **94%** (30 of 32).
- **Recall@k** — did that study rank near the top? After retrieval the pool is sorted by how close
  each study is in meaning to the claim; recall@k is the share of reversed claims whose disproving
  study lands in the top k. It matters because only the top 20 reach the (paid) stance judge, so a
  study ranked lower is found but never judged. **9 / 34 / 62 / 78%** at k = 1 / 5 / 10 / 20.
- **Stance recall** — when the judge sees the disproving study, does it call it refuting? **91%**
  (29 of 32). This hands the study to the judge regardless of rank, to test the judge alone; the
  end-to-end figure that respects the top-20 cap is **78%** (equal to recall@20). So the limit here
  is ranking, not the judge.
- **False-contradiction rate** — how often a still-true control keeps a refuting label the scorer
  actually counts. The scope-aware rate is **25%** (8 of 32): the scorer discards refutations the
  judge flagged as off-scope (`condition_match` false), so a control refuted only by an off-scope
  study is no longer counted. The raw rate, keeping every refuting label including the off-scope
  ones, is **47%** (15 of 32) and is reported alongside for honesty. Either way none is dropped: the
  strict thresholds turn each flag into a reversible down-weight, so the false-drop rate on controls
  is **0 of 32** (of the 32 reversals, 13 drop and 19 down-weight).

Two reversals are missed and accepted as limitations: peptic ulcers (the refutation shares only the
disease, "stress and acid" vs "H. pylori") and vertebroplasty (the landmark trial is buried among
similar ones). Bridging either needs semantic query-expansion, deferred on purpose to protect
control precision. Each miss is tagged with a root cause (`not_indexed`, `entity_miss`,
`retrieved_not_recognized`, `condition_mismatch`, `tier_inversion`) in
`reports/recall-<timestamp>.{md,csv}`.

Claim extraction (measured against a strong-model reference) found 83% of the expected claims and
kept their conditions 93–100% of the time; precision is lower only because it splits claims more
finely (`eval/README.md`). All numbers use Gemini 2.5 Flash Lite; retrieval recall and recall@k are
model-free.

## 🤔 Doesn't this exist already?

Why not trust well-cited sources, like a h-index? Reputation judges who is speaking, not whether they are right.
The belief that hormone replacement therapy prevents coronary heart disease was highly cited the
entire time it was wrong, until the 2002 Women's Health Initiative trial found the opposite.

Why not just count refuted claims? That assumes the hard part, finding and confirming the
refuting study, is already done. This POC tests that step instead of taking it for granted.

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
