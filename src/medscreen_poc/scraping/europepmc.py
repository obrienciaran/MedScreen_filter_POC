"""Europe PMC source via its REST search API.

Used as a second, independent retrieval channel so that "not_indexed" failures reflect
genuine absence rather than one provider's quirks. Europe PMC returns structured JSON
including pubType and abstractText in a single call.

Europe PMC is an evidence retrieval source, not filter input. The filter ingests PubMed
XML only. This source is queried to find studies that contradict or debate a claim.
"""

from __future__ import annotations

import json
from xml.etree import ElementTree

import httpx

from ..schema import Candidate, NormalizedClaim
from ..transformation import query
from .http import generic_throttle, get_with_retry, make_client
from .querycache import get_query_cache

_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
_FULLTEXT = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"


class EuropePMCSource:
    """Evidence provider backed by the Europe PMC REST search API (single step)."""

    name = "europepmc"

    def search_claim(
        self, claim: NormalizedClaim, *, limit: int, client: httpx.Client
    ) -> list[Candidate]:
        by_id: dict[str, Candidate] = {}
        for q in query.europepmc_queries(claim):
            for c in search(q, page_size=limit, client=client):
                by_id.setdefault(c.ext_id, c)
        return list(by_id.values())


def search(query: str, *, page_size: int = 50, client: httpx.Client | None = None) -> list[Candidate]:
    """Search Europe PMC and return Candidates (abstracts included).

    Consults the query cache (when enabled) so a recurring query hits the network once.
    """
    cache = get_query_cache()
    if cache is not None and (hit := cache.get("europepmc", query, page_size)) is not None:
        return [Candidate.model_validate(d) for d in json.loads(hit)]
    own = client is None
    client = client or make_client()
    try:
        params = {
            "query": query,
            "format": "json",
            "pageSize": str(page_size),
            "resultType": "core",  # includes abstractText and pubTypeList
        }
        # Europe PMC occasionally answers a 429/5xx under load; the shared helper backs off
        # and retries rather than aborting the run on a transient gateway error.
        r = get_with_retry(client, _SEARCH, params, throttle=generic_throttle)
        candidates = parse_search_json(r.json())
        if cache is not None:
            cache.put("europepmc", query, page_size,
                json.dumps([c.model_dump() for c in candidates]))
        return candidates
    finally:
        if own:
            client.close()


def parse_search_json(payload: dict) -> list[Candidate]:
    """Parse a Europe PMC search response into Candidates. Pure and unit-testable."""
    out: list[Candidate] = []
    for rec in payload.get("resultList", {}).get("result", []):
        # Prefer PMID as ext_id when present so it aligns with the gold answer keys.
        pmid = rec.get("pmid")
        ext_id = pmid or f"{rec.get('source', 'EPMC')}:{rec.get('id', '')}"
        pub_types = rec.get("pubTypeList", {}).get("pubType", [])
        if isinstance(pub_types, str):
            pub_types = [pub_types]
        year = None
        if (yr := rec.get("pubYear")) and str(yr).isdigit():
            year = int(yr)
        out.append(
            Candidate(
                source="europepmc",
                ext_id=ext_id,
                doi=rec.get("doi"),
                title=rec.get("title", "") or "",
                abstract=rec.get("abstractText", "") or "",
                pub_types=[p for p in pub_types if p],
                year=year,
                pmcid=rec.get("pmcid"),
                is_open_access=rec.get("isOpenAccess") == "Y",
                retrieved_by=[],
            )
        )
    return out


# Body sections that add tokens without stance signal. References, tables, and figures are
# dropped so the full text the judge reads is the study's own argument, not its bibliography.
_JATS_SKIP = {"ref-list", "table-wrap", "fig", "table", "back"}
# JATS elements whose text carries the narrative: paragraphs and section headings.
_JATS_TEXT = {"p", "title"}


def _local_name(tag: str) -> str:
    """Strip any XML namespace so JATS elements match whether or not one is declared."""
    return tag.rsplit("}", 1)[-1]


def _collect_jats_text(element: ElementTree.Element, parts: list[str]) -> None:
    for child in element:
        name = _local_name(child.tag)
        if name in _JATS_SKIP:
            continue
        if name in _JATS_TEXT:
            text = " ".join("".join(child.itertext()).split())
            if text:
                parts.append(text)
        else:
            _collect_jats_text(child, parts)


def extract_jats_body(xml_text: str) -> str:
    """Extract readable body text from a JATS full-text XML document. Pure and unit-testable.

    Concatenates the article body's paragraphs and section headings, skipping references,
    tables, and figures. Returns an empty string if the document has no parseable body, so the
    caller falls back to the abstract.
    """
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return ""
    body = next((el for el in root.iter() if _local_name(el.tag) == "body"), None)
    if body is None:
        return ""
    parts: list[str] = []
    _collect_jats_text(body, parts)
    return "\n".join(parts)


def fetch_full_text(candidate: Candidate, *, client: httpx.Client) -> str:
    """Fetch a candidate's full text from the Europe PMC open-access subset.

    Returns the body text, or an empty string when the article is not open access, has no
    PMCID, or the request fails. A non-OA article has no fetchable full text, so the caller
    keeps the abstract rather than treating the miss as an error.
    """
    if not candidate.pmcid or not candidate.is_open_access:
        return ""
    url = _FULLTEXT.format(pmcid=candidate.pmcid)
    try:
        r = get_with_retry(client, url, {}, throttle=generic_throttle)
    except httpx.HTTPError:
        return ""
    return extract_jats_body(r.text)


def enrich_full_text(candidates: list[Candidate], *, client: httpx.Client) -> list[Candidate]:
    """Populate ``full_text`` in place on the open-access candidates. Returns the same list.

    Only open-access candidates with a PMCID are fetched; the rest keep an empty ``full_text``
    and are judged on their abstract. Fetches are network-bound, not LLM calls.
    """
    for c in candidates:
        if c.pmcid and c.is_open_access and not c.full_text:
            c.full_text = fetch_full_text(c, client=client)
    return candidates
