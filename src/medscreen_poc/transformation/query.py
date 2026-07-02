"""Query construction from a normalized claim.

Generates several formulations per claim because retrieval recall is set here. A single
rigid query is the easiest way to manufacture a ``not_indexed`` false negative. The
formulations run as a ladder from loose (bare concept terms) to contradiction-targeted
(high-tier publication types, harm/risk language), and the caller unions their results, so
no single over-narrow query can drop the disproving study.

Terms are passed UNQUOTED so the database's automatic term mapping can match them. Quoting a
long multi-word phrase forces an exact-string match that descriptive claim text almost never
satisfies (a quoted ``"estrogen plus progestin hormone replacement therapy"`` will not match
the landmark trial that phrases it differently). Terms are also sanitized first to strip the
parenthetical annotations and punctuation carried in from the claim's prose.
"""

from __future__ import annotations

import re

from ..schema import NormalizedClaim

# Publication types that carry contradiction weight. Used as PubMed filters and as
# Europe PMC query fragments.
HIGH_TIER_PUBMED = (
    '("Meta-Analysis"[ptyp] OR "Systematic Review"[ptyp] OR '
    '"Randomized Controlled Trial"[ptyp] OR "Guideline"[ptyp] OR "Practice Guideline"[ptyp])'
)

# Contradiction-seeking fragment. "no benefit" stays quoted as a genuine short phrase.
_CONTRADICTION_PUBMED = '(risk OR harm OR mortality OR increased OR "no benefit" OR retracted)'

# Retracted-publication filter. Paired with the intervention alone, it surfaces retracted work
# on the topic; link expansion then follows that paper's RetractionIn to the retraction notice,
# which is the disproving evidence for a fabrication (a paper echoing a retracted claim).
_RETRACTED_PUBMED = '"Retracted Publication"[pt]'

# Words that must act as boolean operators, not search terms. A claim like "encainide or
# flecainide" carries a lowercase "or"; left as-is, PubMed and Europe PMC treat it as the
# literal term "or" and quietly narrow the search, so it is uppercased to the operator.
_BOOLEAN_OPERATORS = {"and", "or", "not"}


def _sanitize(term: str | None) -> str:
    """Reduce a prose claim term to a plain keyword string.

    Drops parenthetical annotations (``"stress and gastric acid (etiologic claim)"`` carries
    the note ``(etiologic claim)``) and punctuation, while keeping hyphens so tokens like
    ``beta-carotene`` survive. Standalone and/or/not are uppercased to boolean operators.
    Returns an empty string for empty input.
    """
    if not term:
        return ""
    without_parens = re.sub(r"\([^)]*\)", " ", term)
    without_punct = re.sub(r"[^\w\s-]", " ", without_parens)
    cleaned = re.sub(r"\s+", " ", without_punct).strip()
    return " ".join(
        tok.upper() if tok.lower() in _BOOLEAN_OPERATORS else tok for tok in cleaned.split()
    )


def _core_terms(claim: NormalizedClaim) -> str:
    """The intervention-and-outcome core both providers build their queries from.

    Each term is wrapped in parentheses so an embedded operator (``encainide OR flecainide``)
    groups correctly when ANDed with the other term, instead of leaking into ``A OR B AND C``.
    Returns an empty string when neither term survives sanitization, which the callers treat as
    "nothing searchable" and return no queries.
    """
    terms = [t for t in (_sanitize(claim.intervention), _sanitize(claim.outcome)) if t]
    return " AND ".join(f"({t})" for t in terms)


def _dedup(queries: list[str]) -> list[str]:
    """Drop empty and duplicate queries while preserving order."""
    seen: set[str] = set()
    out: list[str] = []
    for q in queries:
        if q and q not in seen:
            seen.add(q)
            out.append(q)
    return out


def pubmed_queries(claim: NormalizedClaim) -> list[str]:
    """Ordered PubMed queries; the caller unions the results.

    Four rungs: ``core`` for broad relevance, ``high-tier`` to surface the trials and reviews
    that overturn consensus, a contradiction-seeking rung, and a retraction-targeted rung. The
    last pairs the intervention alone with the retracted-publication filter to reach retracted
    work whose retraction notice is then followed by link expansion (the fabrication path,
    validated on the gold slice: it recovers Macchiarini and Obokata). It drops the outcome
    because a descriptive outcome over-narrows, and the pt filter keeps the rung tiny. A
    core-plus-population rung was dropped earlier as it added no answer key the others missed.
    """
    intervention = _sanitize(claim.intervention)
    core = _core_terms(claim)
    if not core:
        return []
    queries = [
        core,                                    # loose: let automatic term mapping work
        f"{core} AND {HIGH_TIER_PUBMED}",        # high-tier: surfaces landmark trials / reviews
        f"{core} AND {_CONTRADICTION_PUBMED}",   # contradiction-seeking
    ]
    if intervention:
        queries.append(f"({intervention}) AND {_RETRACTED_PUBMED}")  # retraction-targeted
    return _dedup(queries)


def europepmc_queries(claim: NormalizedClaim) -> list[str]:
    """Ordered Europe PMC queries, mirroring the PubMed core and high-tier rungs."""
    core = _core_terms(claim)
    if not core:
        return []
    high_tier = (
        f"({core}) AND (PUB_TYPE:\"Meta-Analysis\" OR PUB_TYPE:\"Systematic Review\" "
        f'OR PUB_TYPE:"Randomized Controlled Trial")'
    )
    return _dedup([core, high_tier])
