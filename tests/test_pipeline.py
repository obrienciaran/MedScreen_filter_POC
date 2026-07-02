from pathlib import Path

from medscreen_poc.orchestration.pipeline import run_filter, run_paper
from medscreen_poc.reporting.graph import build_paper_graph_data, render_html
from medscreen_poc.scraping.evidence import StubRetriever
from medscreen_poc.transformation.extract import StubExtractor
from medscreen_poc.transformation.ingest import parse_pubmed_xml
from medscreen_poc.transformation.stance import StubStance
from medscreen_poc.schema import Action, PaperRecord, Verdict

FIXTURE = Path(__file__).parent / "fixtures" / "efetch_sample.xml"


def test_retracted_pubtype_short_circuits_without_link():
    # A paper marked "Retracted Publication" but with no RetractionIn link is still dropped by
    # the cheap fast path, before any extraction, retrieval, or stance call.
    paper = PaperRecord(pmid="7", title="x", pub_types=["Journal Article", "Retracted Publication"])
    v = run_paper(paper, extractor=StubExtractor(), retriever=StubRetriever(),
                  stance_backend=StubStance())
    assert v.verdict is Verdict.REFUTED
    assert v.action is Action.DROP
    assert v.verdict_basis == "retraction"
    assert v.refuting_pmids == []
    assert "Retracted Publication" in v.notes


def test_filter_end_to_end_stub():
    papers = parse_pubmed_xml(FIXTURE.read_text())
    verdicts = {v.pmid: v for v in run_filter(papers)}

    # The retracted RCT is refuted via its RetractionIn link and should be dropped. The
    # short-circuit catches it before any extraction/retrieval, so the basis is "retraction".
    rct = verdicts["11111111"]
    assert rct.verdict is Verdict.REFUTED
    assert rct.action is Action.DROP
    assert rct.verdict_basis == "retraction"
    assert "99999999" in rct.refuting_pmids

    # The retraction notice itself has no evidence pool of its own, so it is ungrounded:
    # not refuted, but not silently kept either, it is flagged for review.
    notice = verdicts["22222222"]
    assert notice.verdict is Verdict.UNGROUNDED
    assert notice.action is Action.REVIEW
    assert notice.grounded is False


def test_paper_graph_renders(tmp_path):
    papers = parse_pubmed_xml(FIXTURE.read_text())
    verdicts = run_filter(papers)
    out = render_html(build_paper_graph_data(verdicts), tmp_path / "g.html")
    html = out.read_text()
    assert "paper:11111111" in html
    assert "ev:99999999" in html  # the refuting work is a node
