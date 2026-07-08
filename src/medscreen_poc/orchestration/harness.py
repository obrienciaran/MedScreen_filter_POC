"""Orchestration: gold claim, retrieve pool, stance, per-claim ClaimReport.

Key measurement decisions:
  * Retrieval recall is ground-truth anchored and stance-independent. Did the pool contain
    a gold answer-key PMID? This is the most trustworthy number because it does not depend
    on the LLM stance judge being correct.
  * Stance recall is conditional. Given an answer-key doc was retrieved, did the stance step
    recognize it as refuting? Separating these localizes failures.
  * Failure buckets explain why a reversed claim's contradiction was missed.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import yaml

from ..base.source import Source
from ..base.stance import StanceBackend
from ..schema import (
    Candidate,
    ClaimReport,
    ClaimStatus,
    FailureBucket,
    GoldEntry,
    GoldSet,
    Stance,
    StanceLabel,
)
from ..scraping import links
from ..scraping.http import make_client
from ..scraping.sources import get_sources
from ..store import Store
from ..transformation import semantic
from ..transformation.stance import classify_batch, get_stance_backend

GOLD_PATH = Path("data/gold/consensus_reversals.yaml")

# These can be tuned as needed.
RETMAX_PER_QUERY = 30
STANCE_TOP_K = 20  # cap stance calls per claim. Answer-key docs are always included.
SMALL_POOL = 3  # a pool at or below this size means entity_miss rather than not_indexed
RCT_TIER = 0.8  # tier below which a refutation counts as tier-inversion


def load_gold(path: str | Path = GOLD_PATH) -> GoldSet:
    data = yaml.safe_load(Path(path).read_text())
    return GoldSet.model_validate(data)


def retrieve_pool(
    gold: GoldEntry,
    *,
    store: Store,
    client: httpx.Client,
    use_cache: bool,
    sources: list[Source] | None = None,
) -> list[Candidate]:
    """Build the candidate pool for a claim from every source plus link expansion.

    When ``use_cache`` is set and a cached pool exists, read it from the store (offline).
    Otherwise query the live APIs and persist the result.
    """
    if use_cache:
        cached_ids = store.get_retrieval(gold.id, "pool")
        if cached_ids:
            by_id = store.get_candidates(cached_ids)
            return [by_id[i] for i in cached_ids if i in by_id]

    sources = sources if sources is not None else get_sources()
    by_id: dict[str, Candidate] = {}
    for source in sources:
        try:
            candidates = source.search_claim(gold.normalized, limit=RETMAX_PER_QUERY, client=client)
        except Exception as exc:  # noqa: BLE001 - isolate one source's failure from the claim's pool
            print(f"WARN: {source.name} failed for {gold.id}, skipping. {type(exc).__name__}: {exc}")
            continue
        for c in candidates:
            _merge(by_id, c, "keyword")

    # Secondary signal: pull retraction-linked PMIDs into the pool.
    try:
        linked = links.expand_via_links(list(by_id.values()), client=client)
    except Exception as exc:  # noqa: BLE001 - isolate link expansion's failure from the claim's pool
        print(f"WARN: link expansion failed for {gold.id}, skipping. {type(exc).__name__}: {exc}")
        linked = []
    for c in linked:
        _merge(by_id, c, "links")

    pool = list(by_id.values())
    store.upsert_candidates(pool)
    # The pool channel records membership only. Scores are meaningful per ranking channel.
    store.record_retrieval(gold.id, "pool", [(c.ext_id, 0.0) for c in pool])
    return pool


def _merge(by_id: dict[str, Candidate], c: Candidate, channel: str) -> None:
    existing = by_id.get(c.ext_id)
    if existing is None:
        c.retrieved_by = sorted(set(c.retrieved_by) | {channel})
        by_id[c.ext_id] = c
        return
    existing.retrieved_by = sorted(set(existing.retrieved_by) | {channel})
    # Enrich from the second source rather than discarding it. The two providers report the
    # same study with different completeness, so union the publication types (they drive
    # evidence_tier and the tier-inversion bucket) and fill any field the first source left
    # empty. Without this the first provider to insert an ext_id would lock in a poorer record.
    existing.pub_types = _union_preserving(existing.pub_types, c.pub_types)
    existing.retracted_by = _union_preserving(existing.retracted_by, c.retracted_by)
    existing.is_retraction_of = _union_preserving(existing.is_retraction_of, c.is_retraction_of)
    if not existing.abstract and c.abstract:
        existing.abstract = c.abstract
    if not existing.title and c.title:
        existing.title = c.title
    if existing.year is None and c.year is not None:
        existing.year = c.year
    if not existing.doi and c.doi:
        existing.doi = c.doi


def _union_preserving(first: list[str], second: list[str]) -> list[str]:
    """Union two string lists, keeping ``first``'s order and appending new, case-insensitive."""
    seen = {s.lower() for s in first}
    return first + [s for s in second if s.lower() not in seen]


def embed_pool(
    gold: GoldEntry, pool: list[Candidate], *, store: Store, embedder: semantic.Embedder
) -> list[tuple[str, float]]:
    """Embed the claim and pool, then return the pool ranked by cosine to the claim."""
    claim_vec = embedder.embed([_claim_text(gold)])[0]
    # Read each cached vector once, then keep the freshly computed ones in memory, so a pool of
    # N candidates costs N reads rather than 2N (one pass to decide what to embed, another to
    # gather the vectors for ranking).
    vec_by_id: dict[str, list[float]] = {}
    to_embed: list[Candidate] = []
    for c in pool:
        cached = store.get_embedding(c.ext_id, embedder.name)
        if cached is None:
            to_embed.append(c)
        else:
            vec_by_id[c.ext_id] = cached
    if to_embed:
        vecs = embedder.embed([f"{c.title} {c.abstract}" for c in to_embed])
        for c, v in zip(to_embed, vecs):
            store.upsert_embedding(c.ext_id, embedder.name, v)
            vec_by_id[c.ext_id] = v
    ranked_pool = [(c.ext_id, vec_by_id[c.ext_id]) for c in pool if c.ext_id in vec_by_id]
    ranked = semantic.rank_by_similarity(claim_vec, ranked_pool)
    store.record_retrieval(gold.id, f"semantic:{embedder.name}", ranked)
    return ranked


def _claim_text(gold: GoldEntry) -> str:
    n = gold.normalized
    return f"{gold.claim_text} {n.intervention} {n.outcome} {n.population or ''}".strip()


def run_claim(
    gold: GoldEntry,
    *,
    store: Store,
    client: httpx.Client,
    embedder: semantic.Embedder,
    stance_backend: StanceBackend,
    use_cache: bool,
    sources: list[Source] | None = None,
) -> tuple[ClaimReport, list[StanceLabel]]:
    pool = retrieve_pool(gold, store=store, client=client, use_cache=use_cache, sources=sources)
    by_id = {c.ext_id: c for c in pool}
    ranked = embed_pool(gold, pool, store=store, embedder=embedder)
    rank_of = {ext_id: i + 1 for i, (ext_id, _) in enumerate(ranked)}

    answer_set = set(gold.answer_key)
    retrieved_keys = [k for k in answer_set if k in by_id]
    answer_key_retrieved = bool(retrieved_keys)
    key_ranks = [rank_of[k] for k in retrieved_keys if k in rank_of]
    answer_key_rank = min(key_ranks, default=None)

    # Stance only on the top-K by semantic rank, but always include answer-key docs.
    top_ids = [ext_id for ext_id, _ in ranked[:STANCE_TOP_K]]
    stance_ids = list(dict.fromkeys(top_ids + retrieved_keys))
    to_classify = [by_id[i] for i in stance_ids if i in by_id]
    labels = classify_batch(stance_backend, gold, to_classify)
    store.upsert_stance(labels)

    refuting = [l for l in labels if l.stance is Stance.REFUTES]
    refuting_found = bool(refuting)
    # On-scope refuters only: the scorer discards refutations the judge marked off-scope
    # (condition_match is False), so the scope-aware control metric must do the same.
    refuting_onscope_found = any(l.condition_match is not False for l in refuting)
    answer_key_recognized = any(l.candidate_ext_id in answer_set for l in refuting)
    top_refuting_tier = max(
        (by_id[l.candidate_ext_id].evidence_tier for l in refuting), default=0.0
    )

    report = ClaimReport(
        claim_id=gold.id, status=gold.status, n_candidates=len(pool),
        answer_key_retrieved=answer_key_retrieved, answer_key_rank=answer_key_rank,
        refuting_found=refuting_found, answer_key_recognized=answer_key_recognized,
        top_refuting_tier=top_refuting_tier,
        failure_bucket=_classify_failure(
            gold, pool, labels, answer_key_retrieved,
            answer_key_recognized, refuting_found, top_refuting_tier, answer_set,
        ),
        false_contradiction=(gold.status is ClaimStatus.STILL_TRUE and refuting_found),
        false_contradiction_scoped=(
            gold.status is ClaimStatus.STILL_TRUE and refuting_onscope_found
        ),
    )
    return report, labels


def _classify_failure(
    gold: GoldEntry,
    pool: list[Candidate],
    labels: list[StanceLabel],
    answer_key_retrieved: bool,
    answer_key_recognized: bool,
    refuting_found: bool,
    top_refuting_tier: float,
    answer_set: set[str],
) -> FailureBucket:
    if gold.status is ClaimStatus.STILL_TRUE:
        return FailureBucket.NONE
    if answer_key_recognized:
        return FailureBucket.NONE  # full success (strict)
    if not answer_key_retrieved:
        return FailureBucket.ENTITY_MISS if len(pool) <= SMALL_POOL else FailureBucket.NOT_INDEXED
    # Answer key retrieved but not recognized as refuting.
    ak_labels = [l for l in labels if l.candidate_ext_id in answer_set]
    if any(l.condition_match is False for l in ak_labels):
        return FailureBucket.CONDITION_MISMATCH
    if refuting_found and top_refuting_tier < RCT_TIER:
        return FailureBucket.TIER_INVERSION
    return FailureBucket.RETRIEVED_NOT_RECOGNIZED


def run(
    gold_set: GoldSet,
    *,
    db_path: str | Path,
    use_cache: bool = False,
) -> tuple[list[ClaimReport], dict[str, list[StanceLabel]]]:
    embedder = semantic.get_embedder()
    stance_backend = get_stance_backend()
    sources = get_sources()
    reports: list[ClaimReport] = []
    all_labels: dict[str, list[StanceLabel]] = {}
    with Store(db_path) as store, make_client() as client:
        for gold in gold_set.entries:
            report, labels = run_claim(
                gold, store=store, client=client, embedder=embedder,
                stance_backend=stance_backend, use_cache=use_cache, sources=sources,
            )
            reports.append(report)
            all_labels[gold.id] = labels
    return reports, all_labels
