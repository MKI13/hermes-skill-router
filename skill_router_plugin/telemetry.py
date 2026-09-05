"""Secret-safe routing decision telemetry helpers."""

from __future__ import annotations

from typing import Any

_CONFIDENCE = {"high", "medium", "none", "not_assessed"}


def routing_telemetry(
    *,
    confidence: str = "not_assessed",
    original_primary: str = "",
    final_primary: str = "",
    fallback_applied: bool = False,
    fallback_reason: str = "",
) -> dict[str, Any]:
    """Return bounded, content-free telemetry for one routing decision."""
    return {
        "confidence": confidence if confidence in _CONFIDENCE else "not_assessed",
        "original_primary": _safe_name(original_primary),
        "final_primary": _safe_name(final_primary),
        "fallback_applied": bool(fallback_applied),
        "fallback_reason": _safe_reason(fallback_reason) if fallback_applied else "",
    }


def telemetry_from_policy(policy: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize telemetry attached to a policy result without trusting arbitrary values."""
    if not isinstance(policy, dict):
        return routing_telemetry()
    raw = policy.get("telemetry")
    if not isinstance(raw, dict):
        return routing_telemetry()
    return routing_telemetry(
        confidence=str(raw.get("confidence") or "not_assessed"),
        original_primary=str(raw.get("original_primary") or ""),
        final_primary=str(raw.get("final_primary") or ""),
        fallback_applied=bool(raw.get("fallback_applied")),
        fallback_reason=str(raw.get("fallback_reason") or ""),
    )


def _safe_name(value: str) -> str:
    text = " ".join(str(value or "").split())
    return text.replace("[", "(").replace("]", ")")[:120]


def _safe_reason(value: str) -> str:
    text = " ".join(str(value or "").split())
    return text.replace("[", "(").replace("]", ")")[:240]
