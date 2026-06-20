"""PubMed source via NCBI E-utilities.

Three operations:
  * ``esearch`` — a query string -> list of PMIDs
  * ``efetch``  -> full records (abstract, publication types, year, DOI)
  * retraction/update links are parsed straight from the efetch XML
    (``CommentsCorrectionsList``), which is simpler and more complete than ELink.

Network calls go through ``medfact_poc.http`` for rate limiting + TLS handling.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import httpx

from .. import medline
from ..http import make_client, ncbi_params, ncbi_throttle
from ..retrieval import query
from ..schema import Candidate, NormalizedClaim

_EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


class PubMedSource:
    """Evidence provider backed by NCBI E-utilities (two-step esearch then efetch)."""

    name = "pubmed"

    def search_claim(
        self, claim: NormalizedClaim, *, limit: int, client: httpx.Client
    ) -> list[Candidate]:
        pmids: list[str] = []
        seen: set[str] = set()
        for q in query.pubmed_queries(claim):
            for pmid in esearch(q, retmax=limit, client=client):
                if pmid not in seen:
                    seen.add(pmid)
                    pmids.append(pmid)
        return efetch(pmids, client=client)


def esearch(query: str, *, retmax: int = 50, client: httpx.Client | None = None) -> list[str]:
    """Return PMIDs matching ``query`` (most relevant first)."""
    own = client is None
    client = client or make_client()
    try:
        ncbi_throttle()
        params = ncbi_params(
            {"db": "pubmed", "term": query, "retmax": str(retmax), "retmode": "json", "sort": "relevance"}
        )
        r = client.get(f"{_EUTILS}/esearch.fcgi", params=params)
        r.raise_for_status()
        return r.json().get("esearchresult", {}).get("idlist", [])
    finally:
        if own:
            client.close()


def efetch(pmids: list[str], *, client: httpx.Client | None = None) -> list[Candidate]:
    """Fetch full records for ``pmids`` and parse them into Candidates."""
    if not pmids:
        return []
    own = client is None
    client = client or make_client()
    try:
        ncbi_throttle()
        params = ncbi_params({"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"})
        r = client.get(f"{_EUTILS}/efetch.fcgi", params=params)
        r.raise_for_status()
        return parse_efetch_xml(r.text)
    finally:
        if own:
            client.close()


def parse_efetch_xml(xml_text: str) -> list[Candidate]:
    """Parse an efetch PubmedArticleSet into Candidates. Pure; unit-testable."""
    root = ET.fromstring(xml_text)
    out: list[Candidate] = []
    for art in root.findall(".//PubmedArticle"):
        pmid = medline.text(art, ".//MedlineCitation/PMID")
        if not pmid:
            continue
        retracted_by, is_retraction_of = _parse_corrections(art)
        out.append(
            Candidate(
                source="pubmed",
                ext_id=pmid,
                doi=medline.doi(art),
                title=medline.text(art, ".//Article/ArticleTitle") or "",
                abstract=medline.abstract(art),
                pub_types=medline.pub_types(art),
                year=medline.year(art),
                retracted_by=retracted_by,
                is_retraction_of=is_retraction_of,
                retrieved_by=[],
            )
        )
    return out


def _parse_corrections(art: ET.Element) -> tuple[list[str], list[str]]:
    """Extract retraction relationships from CommentsCorrectionsList.

    RefType semantics (from the PMID's perspective):
      * RetractionIn  -> this article is retracted BY the referenced PMID
      * RetractionOf  -> this article IS a retraction OF the referenced PMID
    """
    retracted_by: list[str] = []
    is_retraction_of: list[str] = []
    for cc in art.findall(".//CommentsCorrectionsList/CommentsCorrections"):
        ref_type = cc.get("RefType", "")
        ref_pmid = medline.text(cc, "PMID")
        if not ref_pmid:
            continue
        if ref_type == "RetractionIn":
            retracted_by.append(ref_pmid)
        elif ref_type == "RetractionOf":
            is_retraction_of.append(ref_pmid)
    return retracted_by, is_retraction_of
