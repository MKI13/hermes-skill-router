"""Bounded routing metadata; never retain prompts or free-form explanations."""

from __future__ import annotations

import math
import re
from typing import Any

_CONFIDENCE = ("high", "medium", "none", "not_assessed")
_REASON_CODES = {"ready_within_margin", "policy_replacement", "unspecified"}
_NAME = re.compile(r"[\w][\w.:/-]{0,119}\Z", re.UNICODE)


def routing_telemetry(
    *,
    confidence: str = "not_assessed",
    original_primary: str = "",
    final_primary: str = "",
    fallback_applied: bool = False,
    fallback_reason: str = "",
) -> dict[str, Any]:
    """Normalize five metadata fields without coercing arbitrary objects to text."""
    original = _safe_name(original_primary)
    final = _safe_name(final_primary)
    changed = fallback_applied is True and bool(original and final and original != final)
    level = confidence if isinstance(confidence, str) and confidence in _CONFIDENCE else "not_assessed"
    reason = fallback_reason if isinstance(fallback_reason, str) and fallback_reason in _REASON_CODES else "unspecified"
    return {
        "confidence": level,
        "original_primary": original,
        "final_primary": final,
        "fallback_applied": changed,
        "fallback_reason": reason if changed else "",
    }


def normalize_routing_telemetry(raw: Any) -> dict[str, Any]:
    """Drop unknown fields, unsupported labels, and malformed values."""
    if not isinstance(raw, dict):
        return routing_telemetry()
    return routing_telemetry(
        confidence=raw.get("confidence"),
        original_primary=raw.get("original_primary"),
        final_primary=raw.get("final_primary"),
        fallback_applied=raw.get("fallback_applied"),
        fallback_reason=raw.get("fallback_reason"),
    )


def telemetry_from_policy(policy: dict[str, Any] | None) -> dict[str, Any]:
    """Read only the dedicated telemetry object from a policy result."""
    return normalize_routing_telemetry(policy.get("telemetry") if isinstance(policy, dict) else None)


def policy_telemetry(
    selected: Any,
    result: dict[str, Any],
    catalog_entries: Any,
    explicit_names: Any,
    decision: dict[str, Any],
) -> dict[str, Any]:
    """Describe the actual post-policy primary, not a proposed intermediate result.

    Names must originate in the current catalog. An explicit override is not an
    automatic fallback. No-match and blocked outcomes never claim a fallback.
    Confidence is only reported for the candidate assessed by the decision engine.
    """
    catalog = {
        item["name"] for item in catalog_entries
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    } if isinstance(catalog_entries, list) else set()
    original = _primary(selected, catalog)
    final = _primary(result.get("selections"), catalog)
    explicit = {
        name for name in explicit_names if isinstance(name, str)
    } if isinstance(explicit_names, list) else set()
    changed = bool(original and final and original != final and final not in explicit)
    confidence = "none" if not final else "not_assessed"
    if final and final == decision.get("primary") and final not in explicit:
        confidence = decision.get("confidence", "not_assessed")
    reason = "ready_within_margin" if decision.get("fallback_applied") is True and final == decision.get("primary") else "policy_replacement"
    return routing_telemetry(
        confidence=confidence,
        original_primary=original,
        final_primary=final,
        fallback_applied=changed,
        fallback_reason=reason,
    )


def telemetry_for_recommendations(raw: Any, recommended: Any) -> dict[str, Any]:
    """Reconcile persisted metadata with the actual recommended primary."""
    result = normalize_routing_telemetry(raw)
    if not isinstance(raw, dict) or result == routing_telemetry():
        return result  # Older callers and records have no measured metadata.
    final = _primary(recommended)
    if result["final_primary"] != final:
        return routing_telemetry(
            confidence="none" if not final else "not_assessed",
            original_primary=result["original_primary"],
            final_primary=final,
        )
    return result


def telemetry_lines(raw: Any) -> list[str]:
    """Render only normalized metadata, never cached arbitrary fields."""
    data = normalize_routing_telemetry(raw)
    return [
        f"Confidence: {data['confidence']}",
        f"Original primary: {data['original_primary'] or 'none'}",
        f"Final primary: {data['final_primary'] or 'none'}",
        f"Fallback applied: {'yes' if data['fallback_applied'] else 'no'}",
        f"Fallback reason: {data['fallback_reason'] or 'none'}",
    ]


def summarize_routing_telemetry(entries: Any) -> dict[str, Any]:
    """Summarize at most 1,000 audit entries without changing quality or learning."""
    counts = {label: 0 for label in _CONFIDENCE}
    observed = 0
    unobserved = 0
    fallbacks = 0
    cohorts = {
        label: {"decisions": 0, "assessed": 0, "score_sum": 0.0}
        for label in ("fallback", "no_fallback")
    }
    for entry in entries[-1000:] if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        data = normalize_routing_telemetry(entry.get("routing_telemetry"))
        counts[data["confidence"]] += 1
        if not any((data["original_primary"], data["final_primary"], data["confidence"] != "not_assessed")):
            unobserved += 1
            continue
        observed += 1
        if data["fallback_applied"]:
            fallbacks += 1
        group = cohorts["fallback" if data["fallback_applied"] else "no_fallback"]
        group["decisions"] += 1
        quality = entry.get("quality")
        if entry.get("finalized") is not True or not isinstance(quality, dict) or quality.get("assessable") is not True:
            continue
        score = quality.get("score")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            continue
        if not 0.0 <= score <= 1.0 or not math.isfinite(score):
            continue
        group["assessed"] += 1
        group["score_sum"] += score
    for group in cohorts.values():
        total = group.pop("score_sum")
        group["mean_quality"] = round(total / group["assessed"], 4) if group["assessed"] else None
    return {
        "observed": observed,
        "unobserved": unobserved,
        "fallbacks": fallbacks,
        "confidence_counts": counts,
        "cohorts": cohorts,
    }


def telemetry_summary_text(entries: Any) -> str:
    report = summarize_routing_telemetry(entries)
    counts = report["confidence_counts"]
    lines = [
        "Routing decision telemetry",
        f"Observed: {report['observed']} | Not recorded: {report['unobserved']}",
        " | ".join(f"{name}={counts[name]}" for name in _CONFIDENCE),
        f"Automatic primary fallbacks: {report['fallbacks']}",
    ]
    for name, group in report["cohorts"].items():
        mean = f"{group['mean_quality']:.4f}" if group["mean_quality"] is not None else "not_assessed"
        lines.append(f"{name}: decisions={group['decisions']}, assessed={group['assessed']}, mean quality={mean}")
    lines.append("Observational only: confidence is not execution success or proof of a quality improvement.")
    return "\n".join(lines)


def _primary(items: Any, catalog: set[str] | None = None) -> str:
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or item.get("role") != "primary":
            continue
        name = _safe_name(item.get("name"))
        if name and (catalog is None or name in catalog):
            return name
    return ""


def _safe_name(value: Any) -> str:
    if not isinstance(value, str) or not _NAME.fullmatch(value):
        return ""
    return value
