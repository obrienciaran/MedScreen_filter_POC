from medscreen_poc.transformation import query
from medscreen_poc.schema import NormalizedClaim


def _claim():
    return NormalizedClaim(
        intervention="hydroxychloroquine",
        outcome="mortality",
        population="hospitalized COVID-19 patients",
        comparator="usual care",
        direction="decreases",
    )


def test_pubmed_queries_include_core_and_contradiction():
    qs = query.pubmed_queries(_claim())
    assert any("hydroxychloroquine" in q and "mortality" in q for q in qs)
    # a high-tier / pub-type targeted formulation exists
    assert any("Meta-Analysis" in q for q in qs)
    # an explicit contradiction-seeking formulation exists
    assert any("harm" in q or "risk" in q or "no benefit" in q for q in qs)
    # no duplicates
    assert len(qs) == len(set(qs))


def test_embedded_or_becomes_boolean_operator_and_is_grouped():
    # "encainide or flecainide" must query (encainide OR flecainide), not require the word "or".
    c = NormalizedClaim(intervention="encainide or flecainide (class Ic antiarrhythmics)",
                        outcome="mortality")
    core = query.pubmed_queries(c)[0]
    assert "(encainide OR flecainide)" in core
    assert " or " not in core  # no lowercase operator left as a search term
    # the intervention group is ANDed with the outcome, precedence preserved by parentheses
    assert "(encainide OR flecainide) AND (mortality)" in core


def test_pubmed_queries_have_retraction_targeted_rung():
    # A rung pairing the intervention with the retracted-publication filter, outcome dropped, so
    # link expansion can reach a retraction notice (the fabrication path).
    qs = query.pubmed_queries(_claim())
    assert any(
        '"Retracted Publication"[pt]' in q and "hydroxychloroquine" in q and "mortality" not in q
        for q in qs
    )


def test_europepmc_queries_nonempty_and_unique():
    qs = query.europepmc_queries(_claim())
    assert qs and all(qs)
    assert len(qs) == len(set(qs))
    assert any("PUB_TYPE" in q for q in qs)


def test_as_query_terms_drops_missing_fields():
    c = NormalizedClaim(intervention="aspirin", outcome="stroke")
    assert c.as_query_terms() == ["aspirin", "stroke"]
