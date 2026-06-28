from pathlib import Path

from medscreen_poc.orchestration.pipeline import run_filter
from medscreen_poc.reporting.graph import build_paper_graph_data, render_html
from medscreen_poc.transformation.ingest import parse_pubmed_xml
from medscreen_poc.schema import Action, Verdict

FIXTURE = Path(__file__).parent / "fixtures" / "efetch_sample.xml"


def test_filter_end_to_end_stub():
    papers = parse_pubmed_xml(FIXTURE.read_text())
    verdicts = {v.pmid: v for v in run_filter(papers)}

    # The retracted RCT is refuted via its RetractionIn link and should be dropped.
    rct = verdicts["11111111"]
    assert rct.verdict is Verdict.REFUTED
    assert rct.action is Action.DROP
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
