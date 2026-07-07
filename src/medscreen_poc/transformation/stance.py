"""Stance classification: does a candidate support, refute, or stay neutral on the claim
as asserted (conditions included)?

This is measurement instrumentation, not the production annotator. Using an LLM as the
stance judge here is acceptable precisely because the stance step is one of the variables
the harness measures. Its correctness shows up as the gap between retrieval recall and
stance recall. It must never be promoted into an "is this claim true" judge in a real
pipeline.

Backends are pluggable (see ``base.stance``):
  * ``stub`` is a deterministic lexical heuristic, dependency-free, for plumbing.
  * ``llm`` is any provider behind ``LLMClient`` (Claude, ChatGPT, Gemini) with a
    condition-aware prompt returning structured JSON. ``anthropic``, ``openai``, and
    ``gemini`` are accepted as aliases that also pin the provider.
"""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor

from ..base.llm import LLMClient
from ..base.stance import StanceBackend
from ..llm import get_llm_for_backend
from ..schema import Candidate, GoldEntry, Stance, StanceLabel

def _as_float(value: object, default: float) -> float:
    """Coerce a model-supplied value to float, falling back when it is missing or not numeric."""
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


_ABSTRACT_CHARS = 4000


def _evidence_text(candidate: Candidate) -> tuple[str, str]:
    """The text the stance judge should read for a candidate, and which kind it is.

    Prefers the study's full text when it was fetched (open-access subset, full-text stance
    enabled), truncated to ``MEDSCREEN_STANCE_FULLTEXT_CHARS``; otherwise the abstract. Returns
    ``(text, "full_text" | "abstract")`` so the choice is recorded on the label.
    """
    if candidate.full_text:
        budget = int(os.environ.get("MEDSCREEN_STANCE_FULLTEXT_CHARS", "24000"))
        return candidate.full_text[:budget], "full_text"
    return (candidate.abstract or "")[:_ABSTRACT_CHARS] or "(no abstract)", "abstract"


# Lexical cues used only by the stub backend.
_REFUTE_CUES = (
    "no benefit", "no significant", "increased risk", "increased mortality", "harm",
    "did not reduce", "no effect", "ineffective", "not associated with",
    "associated with increased", "retracted", "withdrawn", "no reduction",
)


class StubStance:
    """Lexical heuristic. This is not a real stance signal. It only lets the harness run
    offline. Treat any stub-derived stance recall as a lower-bound placeholder."""

    name = "stub"

    def classify(self, gold: GoldEntry, candidate: Candidate) -> StanceLabel:
        body, text_source = _evidence_text(candidate)
        text = f"{candidate.title} {body}".lower()
        hits = [c for c in _REFUTE_CUES if c in text]
        if hits:
            stance = Stance.REFUTES
            conf = min(0.3 + 0.1 * len(hits), 0.7)
            rationale = f"stub: refute cues {hits[:3]}"
        else:
            stance = Stance.NEUTRAL
            conf = 0.2
            rationale = "stub: no refute cues"
        return StanceLabel(
            claim_id=gold.id, candidate_ext_id=candidate.ext_id,
            stance=stance, confidence=conf, rationale=rationale, condition_match=None,
            text_source=text_source,
        )


_PROMPT = """You are assessing how a piece of medical evidence relates to a specific claim.

CLAIM (as asserted): {claim_text}
Structured: intervention={intervention}, outcome={outcome}, population={population}, \
comparator={comparator}, asserted direction={direction}

EVIDENCE:
Title: {title}
Publication types: {pub_types}
Year: {year}
Evidence text ({text_source}): {evidence_text}

Decide the stance of the EVIDENCE toward the CLAIM. Critically, only judge "refutes" \
if the evidence concerns the SAME population, intervention and outcome the claim asserts \
AND contradicts its asserted direction. If the evidence tests a DIFFERENT condition \
(different population, comparator, dose, or setting), set condition_match=false and prefer \
"neutral" unless it still directly contradicts.

Respond with a JSON object as shown below and nothing else:
{{"stance": "supports|refutes|neutral", "confidence": 0.0-1.0, \
"condition_match": true|false, "rationale": "one sentence"}}"""


class LLMStance:
    """Condition-aware stance classifier backed by any ``LLMClient`` provider."""

    def __init__(self, client: LLMClient) -> None:
        self.name = f"stance:{client.name}"
        self._client = client

    def classify(self, gold: GoldEntry, candidate: Candidate) -> StanceLabel:
        n = gold.normalized
        evidence_text, text_source = _evidence_text(candidate)
        prompt = _PROMPT.format(
            claim_text=gold.claim_text,
            intervention=n.intervention, outcome=n.outcome,
            population=n.population or "unspecified",
            comparator=n.comparator or "unspecified",
            direction=n.direction or "unspecified",
            title=candidate.title, pub_types=", ".join(candidate.pub_types) or "unknown",
            year=candidate.year or "unknown",
            text_source=text_source.replace("_", " "), evidence_text=evidence_text,
        )
        text = self._client.complete(prompt, max_tokens=300)
        return self._parse(gold.id, candidate.ext_id, text, text_source)

    @staticmethod
    def _parse(claim_id: str, ext_id: str, text: str, text_source: str = "abstract") -> StanceLabel:
        data: dict = {}
        stance = Stance.NEUTRAL
        try:
            start, end = text.index("{"), text.rindex("}") + 1
            parsed = json.loads(text[start:end])
            # A well-formed response is a JSON object. Anything else (an array, a bare value)
            # is treated as unparseable and falls back to neutral rather than crashing here.
            if isinstance(parsed, dict):
                data = parsed
                stance = Stance(data.get("stance", "neutral"))
        except (ValueError, KeyError):
            data, stance = {}, Stance.NEUTRAL
        # A stray non-bool condition_match is dropped to None so it never fails model validation.
        condition_match = data.get("condition_match")
        return StanceLabel(
            claim_id=claim_id, candidate_ext_id=ext_id, stance=stance,
            confidence=_as_float(data.get("confidence"), 0.0),
            rationale=str(data.get("rationale", "")),
            condition_match=condition_match if isinstance(condition_match, bool) else None,
            text_source=text_source if text_source in ("full_text", "abstract") else "abstract",
        )


def get_stance_backend() -> StanceBackend:
    backend = os.environ.get("MEDSCREEN_STANCE_BACKEND", "stub").lower()
    if backend == "stub":
        return StubStance()
    return LLMStance(get_llm_for_backend(backend))


def classify_batch(
    backend: StanceBackend,
    gold: GoldEntry,
    candidates: list[Candidate],
    max_workers: int | None = None,
    *,
    executor: ThreadPoolExecutor | None = None,
) -> list[StanceLabel]:
    """Classify candidates concurrently, preserving input order.

    Stance calls against an LLM backend are independent network-bound requests, so they fan
    out across a thread pool. Pass ``executor`` to reuse one shared pool across many claims
    (the filter does this so total LLM concurrency is a single bound, not the product of the
    paper and stance worker counts). With no ``executor`` a private pool is created, sized by
    ``MEDSCREEN_STANCE_CONCURRENCY`` (default 8). The stub backend runs the same path
    harmlessly.
    """
    if not candidates:
        return []

    def _classify(c: Candidate) -> StanceLabel:
        try:
            return backend.classify(gold, c)
        except Exception as exc:  # noqa: BLE001 - isolate one candidate's failure from the batch
            print(f"WARN: stance classify failed for {gold.id}/{c.ext_id}, treating as neutral. "
                f"{type(exc).__name__}: {exc}")
            return StanceLabel(
                claim_id=gold.id, candidate_ext_id=c.ext_id, stance=Stance.NEUTRAL,
                confidence=0.0, rationale=f"error: {type(exc).__name__}: {exc}", condition_match=None,
            )

    if executor is not None:
        return list(executor.map(_classify, candidates))
    workers = max_workers or int(os.environ.get("MEDSCREEN_STANCE_CONCURRENCY", "8"))
    workers = max(1, min(workers, len(candidates)))
    with ThreadPoolExecutor(max_workers=workers) as own:
        return list(own.map(_classify, candidates))
