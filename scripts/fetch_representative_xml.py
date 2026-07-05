"""Fetch 10 representative recent PubMed papers as standalone XML for a filter trial.

Unlike scripts/fetch_trial_xml.py (a curated, retraction-heavy stress test), this samples
ordinary recent journal articles across a spread of common clinical areas, excluding
retractions. The papers are whatever PubMed returns for each area, not chosen by verdict,
so the run reflects how the filter behaves on typical input (mostly kept).

Uses NCBI E-utilities. No LLM and no API key needed. Set NCBI_EMAIL for politeness, and
MEDSCREEN_INSECURE_TLS=1 / MEDSCREEN_CA_BUNDLE behind a TLS-terminating proxy.

    python scripts/fetch_representative_xml.py                     # canonical 10-paper sample
    python scripts/fetch_representative_xml.py --target 80 --per-topic 2 \
        --out-dir data/representative_large                        # larger sample

Scaling the set up lets you measure, on more than ten papers, how often the filter fails to keep
an ordinary paper it should keep (down-weighting or dropping it). Pair it with
scripts/flag_audit.py to summarise the run and list the papers it did not keep.
"""

from __future__ import annotations

import argparse
import os
import ssl
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
DEFAULT_OUT_DIR = Path("data/representative")

# Ordinary recent papers across common clinical areas, a representative sample the filter should
# mostly keep. The default run takes one paper per topic and stops at the first ``--target``. A
# larger set is reached by raising ``--per-topic`` and ``--target``, which is why the pool is
# long. The first ten topics reproduce the original canonical sample, so the default run is
# unchanged.
_NOT_RETRACTED = 'NOT "Retracted Publication"[pt] NOT "Retraction of Publication"[pt]'
TOPICS = [
    "type 2 diabetes",
    "hypertension",
    "breast cancer",
    "asthma",
    "major depressive disorder",
    "ischemic stroke",
    "rheumatoid arthritis",
    "chronic kidney disease",
    "chronic obstructive pulmonary disease",
    "Alzheimer disease",
    "heart failure",
    "atrial fibrillation",
    "coronary artery disease",
    "obesity",
    "osteoarthritis",
    "osteoporosis",
    "migraine",
    "epilepsy",
    "Parkinson disease",
    "multiple sclerosis",
    "inflammatory bowel disease",
    "chronic hepatitis",
    "HIV infection",
    "tuberculosis",
    "sepsis",
    "community-acquired pneumonia",
    "colorectal cancer",
    "prostate cancer",
    "lung cancer",
    "melanoma",
    "generalized anxiety disorder",
    "schizophrenia",
    "psoriasis",
    "atopic dermatitis",
    "gout",
    "iron deficiency anemia",
    "hypothyroidism",
    "glaucoma",
    "benign prostatic hyperplasia",
    "venous thromboembolism",
]


def _ssl_context() -> ssl.SSLContext | None:
    bundle = os.environ.get("MEDSCREEN_CA_BUNDLE")
    if bundle:
        return ssl.create_default_context(cafile=bundle)
    if os.environ.get("MEDSCREEN_INSECURE_TLS") == "1":
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    return None


def _params(extra: dict[str, str]) -> dict[str, str]:
    params = {**extra, "tool": "medscreen_poc_trial"}
    email = os.environ.get("NCBI_EMAIL")
    if email:
        params["email"] = email
    api_key = os.environ.get("NCBI_API_KEY")
    if api_key:
        params["api_key"] = api_key
    return params


def _get(url: str, extra: dict[str, str]) -> str:
    full = f"{url}?{urllib.parse.urlencode(_params(extra))}"
    with urllib.request.urlopen(full, timeout=30, context=_ssl_context()) as resp:
        return resp.read().decode("utf-8")


def esearch(term: str, retmax: int) -> list[str]:
    raw = _get(
        f"{EUTILS}/esearch.fcgi",
        {"db": "pubmed", "term": term, "retmax": str(retmax), "retmode": "xml", "sort": "relevance"},
    )
    root = ET.fromstring(raw)
    return [el.text for el in root.findall(".//IdList/Id") if el.text]


def efetch(pmids: list[str]) -> str:
    return _get(f"{EUTILS}/efetch.fcgi", {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"})


def collect_pmids(
    topics: list[str], *, per_topic: int, target: int, start_year: int, end_year: int, retmax: int
) -> list[str]:
    """Gather up to ``target`` unique ordinary-paper PMIDs, at most ``per_topic`` per topic."""
    pmids: list[str] = []
    seen: set[str] = set()
    for topic in topics:
        if len(pmids) >= target:
            break
        term = (f'"{topic}" AND {start_year}:{end_year}[dp] AND hasabstract '
                f'AND "Journal Article"[pt] {_NOT_RETRACTED}')
        try:
            hits = esearch(term, retmax)
        except Exception as exc:  # noqa: BLE001 - trial script, report and continue
            print(f"WARN esearch failed for [{topic}]: {exc}")
            continue
        taken = 0
        for pmid in hits:
            if len(pmids) >= target or taken >= per_topic:
                break
            if pmid not in seen:
                seen.add(pmid)
                pmids.append(pmid)
                taken += 1
                print(f"topic [{topic}] -> {pmid}")
        time.sleep(0.5)
    return pmids[:target]


def write_papers(pmids: list[str], out_dir: Path) -> int:
    """Fetch and write one PubmedArticleSet XML file per PMID. Returns the count written.

    efetch is batched because a few hundred ids share one request URL and overflow it.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for start in range(0, len(pmids), 100):
        batch = pmids[start:start + 100]
        root = ET.fromstring(efetch(batch))
        for art in root.findall(".//PubmedArticle"):
            pmid_el = art.find(".//MedlineCitation/PMID")
            if pmid_el is None or not pmid_el.text:
                continue
            pmid = pmid_el.text
            title_el = art.find(".//Article/ArticleTitle")
            title = (title_el.text or "").strip() if title_el is not None else ""
            pub_types = [el.text for el in art.findall(".//PublicationType") if el.text]
            wrapper = ET.Element("PubmedArticleSet")
            wrapper.append(art)
            (out_dir / f"{pmid}.xml").write_bytes(
                ET.tostring(wrapper, encoding="utf-8", xml_declaration=True)
            )
            written += 1
            print(f"  {pmid}: {title[:70]!r} | types={pub_types}")
        time.sleep(0.5)
    return written


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch ordinary recent PubMed papers as XML.")
    ap.add_argument("--target", type=int, default=10, help="total papers to fetch")
    ap.add_argument("--per-topic", type=int, default=1, help="max papers taken per topic")
    ap.add_argument("--start-year", type=int, default=2024)
    ap.add_argument("--end-year", type=int, default=2025)
    ap.add_argument("--retmax", type=int, default=5, help="candidates considered per topic")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    pmids = collect_pmids(
        TOPICS, per_topic=args.per_topic, target=args.target,
        start_year=args.start_year, end_year=args.end_year, retmax=args.retmax,
    )
    print(f"Fetching {len(pmids)} papers: {pmids}")
    written = write_papers(pmids, out_dir)
    print(f"Wrote {written} XML files to {out_dir}/")


if __name__ == "__main__":
    main()
