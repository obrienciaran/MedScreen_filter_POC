"""Production re-ranking: LiveRetriever orders query hits by semantic similarity when sbert is
selected, and caches each candidate's vector in the shared DuckDB store."""

from medscreen_poc.schema import Candidate, ExtractedClaim, NormalizedClaim
from medscreen_poc.scraping.evidence import LiveRetriever
from medscreen_poc.store import Store


class _FakeEmbedder:
    """Deterministic 2-D embedder: texts containing 'match' point one way, others the opposite,
    so cosine ranks the matching candidates first."""

    name = "fake"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] if "match" in t.lower() else [0.0, 1.0] for t in texts]


def _cand(ext_id: str, abstract: str) -> Candidate:
    return Candidate(source="pubmed", ext_id=ext_id, title=ext_id, abstract=abstract)


def _claim() -> ExtractedClaim:
    return ExtractedClaim(
        paper_pmid="p", index=0, claim_text="match claim",
        normalized=NormalizedClaim(intervention="match", outcome="outcome"),
    )


def test_rank_query_hits_orders_by_similarity_and_caches(tmp_path):
    r = LiveRetriever()
    r._rerank = True
    r._embedder = _FakeEmbedder()
    r._store = Store(tmp_path / "emb.duckdb")

    cands = [_cand("A", "unrelated"), _cand("B", "a match is here"), _cand("C", "unrelated")]
    ranked = r._rank_query_hits(_claim(), cands)

    assert ranked[0].ext_id == "B"  # the matching candidate ranks first
    # vector was written to the shared cache, so a later call reuses it
    assert r._store.get_embedding("B", "fake") is not None


def test_rank_query_hits_reuses_cached_vectors(tmp_path):
    r = LiveRetriever()
    r._rerank = True
    r._store = Store(tmp_path / "emb.duckdb")
    r._store.upsert_embedding("X", "fake", [1.0, 0.0])
    r._store.upsert_embedding("Y", "fake", [0.0, 1.0])

    calls = {"n": 0}

    class _CountingEmbedder(_FakeEmbedder):
        def embed(self, texts):
            calls["n"] += len(texts)
            return super().embed(texts)

    r._embedder = _CountingEmbedder()
    ranked = r._rank_query_hits(_claim(), [_cand("X", "unrelated"), _cand("Y", "unrelated")])
    assert ranked[0].ext_id == "X"  # cached vector [1,0] matches the claim
    assert calls["n"] == 1  # only the claim was embedded; both candidates came from cache


def test_no_rerank_by_default():
    # Default (stub embedder, sbert not selected): re-ranking is off, so no model is loaded.
    assert LiveRetriever()._rerank is False
