"""Leaf extractors for MEDLINE/PubMed efetch XML.

Both the harness source (``scraping/pubmed.py``, which builds Candidates from a live
efetch call) and the filter ingester (``transformation/ingest.py``, which builds
PaperRecords from corpus files) parse the same ``PubmedArticle`` schema. These pure
element helpers are the shared leaves, kept in one place so the two parsers cannot drift.
Each parser still owns how it assembles its own model and which relationships it keeps.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET


def text(node: ET.Element, path: str) -> str | None:
    el = node.find(path)
    return el.text.strip() if el is not None and el.text else None


def abstract(art: ET.Element) -> str:
    """Join the abstract's text into one string.

    A structured abstract splits into several ``AbstractText`` sections each carrying a
    ``Label`` (BACKGROUND, METHODS, RESULTS, CONCLUSIONS). Those labels are dropped on purpose:
    the downstream stance and extract steps read the prose, not the section headers.
    """
    return " ".join(
        (el.text or "").strip() for el in art.findall(".//Abstract/AbstractText")
    ).strip()


def pub_types(art: ET.Element) -> list[str]:
    return [
        (el.text or "").strip()
        for el in art.findall(".//PublicationTypeList/PublicationType")
        if el.text
    ]


def year(art: ET.Element) -> int | None:
    y = text(art, ".//JournalIssue/PubDate/Year")
    if y and y.isdigit():
        return int(y)
    medline_date = text(art, ".//JournalIssue/PubDate/MedlineDate")
    if medline_date and medline_date[:4].isdigit():
        return int(medline_date[:4])
    return None


def doi(art: ET.Element) -> str | None:
    for el in art.findall(".//ArticleIdList/ArticleId"):
        if el.get("IdType") == "doi" and el.text:
            return el.text.strip()
    for el in art.findall(".//ELocationID"):
        if el.get("EIdType") == "doi" and el.text:
            return el.text.strip()
    return None


def comments_corrections(art: ET.Element) -> dict[str, list[str]]:
    """Group CommentsCorrectionsList referenced PMIDs by RefType.

    The shared leaf for both parsers: the ingester keeps the full grouping (every RefType),
    while the efetch parser picks out the retraction relationships. Kept here so the two
    cannot drift in how they read the same element.
    """
    grouped: dict[str, list[str]] = {}
    for cc in art.findall(".//CommentsCorrectionsList/CommentsCorrections"):
        ref_type = cc.get("RefType", "")
        ref_pmid = text(cc, "PMID")
        if ref_type and ref_pmid:
            grouped.setdefault(ref_type, []).append(ref_pmid)
    return grouped
