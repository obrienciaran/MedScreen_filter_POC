"""Full-text stance judgment: JATS extraction, text-source selection, and how the choice
propagates through scoring into the flat report."""

from pathlib import Path

from medscreen_poc.reporting.flat_report import write_flat_csv
from medscreen_poc.schema import (
    Action,
    Candidate,
    ExtractedClaim,
    GoldEntry,
    NormalizedClaim,
    PaperVerdict,
    Stance,
    StanceLabel,
    Verdict,
)
from medscreen_poc.scraping import europepmc
from medscreen_poc.transformation.scoring import score_claim
from medscreen_poc.transformation.stance import LLMStance, StubStance

_JATS = """<article>
  <front><article-meta><abstract><p>Abstract only.</p></abstract></article-meta></front>
  <body>
    <sec><title>Results</title><p>The drug did <italic>not</italic> reduce mortality.</p></sec>
    <sec><title>Discussion</title><p>No benefit was observed.</p>
      <table-wrap><table><tr><td>tabular noise</td></tr></table></table-wrap>
    </sec>
  </body>
  <back><ref-list><ref><title>a reference</title></ref></ref-list></back>
</article>"""

_JATS_NS = """<article xmlns="http://jats.nlm.nih.gov">
  <body><sec><title>Findings</title><p>Clear body signal.</p></sec></body>
</article>"""


def test_extract_jats_body_keeps_narrative_drops_noise():
    body = europepmc.extract_jats_body(_JATS)
    assert "Results" in body
    assert "did not reduce mortality" in body  # inline markup flattened
    assert "No benefit was observed." in body
    assert "tabular noise" not in body  # table skipped
    assert "a reference" not in body  # back/ref-list outside body


def test_extract_jats_body_handles_namespace():
    assert "Clear body signal." in europepmc.extract_jats_body(_JATS_NS)


def test_extract_jats_body_returns_empty_on_junk():
    assert europepmc.extract_jats_body("not xml at all") == ""
    assert europepmc.extract_jats_body("<article><front/></article>") == ""


def test_parse_search_json_captures_open_access(tmp_path):
    payload = {
        "resultList": {"result": [
            {"pmid": "1", "source": "MED", "title": "t", "abstractText": "a",
             "pmcid": "PMC1", "isOpenAccess": "Y"},
            {"pmid": "2", "source": "MED", "title": "t", "abstractText": "a",
             "isOpenAccess": "N"},
        ]}
    }
    a, b = europepmc.parse_search_json(payload)
    assert a.pmcid == "PMC1" and a.is_open_access is True
    assert b.pmcid is None and b.is_open_access is False


class _FakeClient:
    """Records the prompt it is given and returns a fixed refuting verdict."""

    name = "fake"

    def __init__(self):
        self.prompt = ""

    def complete(self, prompt: str, *, max_tokens: int = 512) -> str:
        self.prompt = prompt
        return '{"stance": "refutes", "confidence": 0.9, "condition_match": true, "rationale": "x"}'


def _candidate(**kw) -> Candidate:
    base = dict(source="europepmc", ext_id="9", title="Study", abstract="short abstract")
    base.update(kw)
    return Candidate(**base)


_GOLD = GoldEntry(
    id="c1", claim_text="Drug reduces mortality.",
    normalized=NormalizedClaim(intervention="drug", outcome="mortality"),
    status="reversed",
)


def test_llm_stance_uses_full_text_when_present():
    client = _FakeClient()
    label = LLMStance(client).classify(_GOLD, _candidate(full_text="the full body text here"))
    assert label.text_source == "full_text"
    assert "the full body text here" in client.prompt
    assert "short abstract" not in client.prompt


def test_llm_stance_falls_back_to_abstract():
    client = _FakeClient()
    label = LLMStance(client).classify(_GOLD, _candidate())
    assert label.text_source == "abstract"
    assert "short abstract" in client.prompt


def test_stub_stance_records_text_source():
    assert StubStance().classify(_GOLD, _candidate()).text_source == "abstract"
    ft = StubStance().classify(_GOLD, _candidate(full_text="no benefit was found"))
    assert ft.text_source == "full_text"
    assert ft.stance is Stance.REFUTES  # cue matched in the full text


def test_score_claim_counts_text_sources():
    claim = ExtractedClaim(
        paper_pmid="p", index=0, claim_text="c",
        normalized=NormalizedClaim(intervention="i", outcome="o"),
    )
    candidates = [_candidate(ext_id="a"), _candidate(ext_id="b"), _candidate(ext_id="d")]
    labels = [
        StanceLabel(claim_id="c1", candidate_ext_id="a", stance=Stance.NEUTRAL, text_source="full_text"),
        StanceLabel(claim_id="c1", candidate_ext_id="b", stance=Stance.NEUTRAL, text_source="full_text"),
        StanceLabel(claim_id="c1", candidate_ext_id="d", stance=Stance.NEUTRAL, text_source="abstract"),
    ]
    cv = score_claim(claim, candidates, labels)
    assert cv.n_fulltext_evidence == 2
    assert cv.n_abstract_evidence == 1


def _verdict(**kw) -> PaperVerdict:
    base = dict(
        pmid="p", title="t", verdict=Verdict.SUPPORTED, score=0.7, action=Action.KEEP,
        n_claims=1, n_refuted_claims=0, top_refuting_tier=0.0,
    )
    base.update(kw)
    return PaperVerdict(**base)


def test_flat_csv_evidence_text_source_is_categorical(tmp_path):
    rows = write_flat_csv(
        [
            _verdict(pmid="ft", n_fulltext_evidence=6, n_abstract_evidence=2),
            _verdict(pmid="ab", n_fulltext_evidence=1, n_abstract_evidence=9),
            _verdict(pmid="none", n_fulltext_evidence=0, n_abstract_evidence=0),
        ],
        tmp_path / "f.csv",
    ).read_text().splitlines()
    header = rows[0].split(",")
    assert "evidence_text_source" in header
    col = header.index("evidence_text_source")
    by_pmid = {r.split(",")[0]: r.split(",")[col] for r in rows[1:]}
    assert by_pmid["ft"] == "full_text"  # majority full text
    assert by_pmid["ab"] == "abstract"  # majority abstract
    assert by_pmid["none"] == ""  # no evidence judged
