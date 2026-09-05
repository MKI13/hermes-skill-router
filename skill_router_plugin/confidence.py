"""Conservative confidence and fallback decisions for routed skill candidates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

READY = "ready"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class ConfidenceCandidate:
    name: str
    score: float
    readiness_status: str
    explicit: bool = False


@dataclass(frozen=True)
class ConfidenceDecision:
    primary: str | None
    confidence: str
    fallback_applied: bool
    reason: str


def choose_primary(
    candidates: Iterable[ConfidenceCandidate],
    *,
    minimum_score: float,
    ready_fallback_margin: float = 5.0,
    high_confidence_margin: float = 10.0,
) -> ConfidenceDecision:
    """Choose one conservative primary without overriding an explicit user request.

    Rules:
    - Explicit candidates always win if they meet the minimum score.
    - Otherwise the top relevant candidate wins by default.
    - If the top candidate is UNKNOWN and a READY candidate is almost as relevant,
      prefer READY within ``ready_fallback_margin``.
    - Never use readiness alone to make an irrelevant candidate executable.
    """
    minimum = float(minimum_score)
    fallback_margin = max(0.0, float(ready_fallback_margin))
    high_margin = max(0.0, float(high_confidence_margin))
    ranked = sorted(
        (candidate for candidate in candidates if float(candidate.score) >= minimum),
        key=lambda candidate: (-float(candidate.score), candidate.name.casefold()),
    )
    if not ranked:
        return ConfidenceDecision(None, "none", False, "No candidate met the minimum relevance score.")

    explicit = next((candidate for candidate in ranked if candidate.explicit), None)
    if explicit is not None:
        return ConfidenceDecision(
            explicit.name,
            _confidence_label(explicit.score, minimum, high_margin),
            False,
            "Explicit user-selected skill retained.",
        )

    top = ranked[0]
    if top.readiness_status == UNKNOWN:
        ready = next(
            (
                candidate
                for candidate in ranked[1:]
                if candidate.readiness_status == READY
                and float(top.score) - float(candidate.score) <= fallback_margin
            ),
            None,
        )
        if ready is not None:
            return ConfidenceDecision(
                ready.name,
                _confidence_label(ready.score, minimum, high_margin),
                True,
                f"Preferred ready skill within {fallback_margin:.1f} relevance points of unknown top candidate {top.name}.",
            )

    return ConfidenceDecision(
        top.name,
        _confidence_label(top.score, minimum, high_margin),
        False,
        "Highest-confidence relevant candidate retained.",
    )


def _confidence_label(score: float, minimum: float, high_margin: float) -> str:
    return "high" if float(score) >= minimum + high_margin else "medium"
