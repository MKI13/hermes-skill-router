"""Deterministic technical quality evaluation for finalized routing audits."""

from __future__ import annotations

from typing import Any

QUALITY_VERSION = 1
GRADE_THRESHOLDS = (
    ("excellent", 0.90),
    ("good", 0.75),
    ("acceptable", 0.55),
    ("poor", 0.30),
    ("failed", 0.00),
)
PENALTY_WEIGHTS = {
    "policy-adjusted": 0.05,
    "policy-degraded": 0.20,
    "audit-partial": 0.20,
    "audit-missed": 0.60,
    "primary-not-loaded": 0.40,
    "required-dependency-missing": 0.20,
    "optional-supporting-missing": 0.10,
    "skill-load-error": 0.15,
    "guard-warned": 0.10,
    "guard-blocked": 0.05,
    "guard-exhausted": 0.30,
    "guard-unavailable": 0.15,
    "guard-error": 0.20,
    "primary-after-task-tool": 0.20,
    "dependency-order-violated": 0.20,
}
_PENALTY_CAPS = {
    "required-dependency-missing": 0.40,
    "optional-supporting-missing": 0.30,
    "skill-load-error": 0.45,
}
_CONFIDENCE = {"high", "medium", "low", "unknown"}


def evaluate_quality(entry: dict[str, Any]) -> dict[str, Any]:
    """Evaluate one finalized, sanitized audit entry without semantic inference."""
    if not isinstance(entry, dict) or not entry.get("finalized"):
        return unknown_quality()
    policy_status = str(entry.get("policy_status") or "unknown")
    result = str(entry.get("result") or "unknown")
    if policy_status == "blocked":
        signals = _base_signals(entry)
        signals.update({
            "routing_valid": True,
            "policy_clean": True,
            "safely_blocked": True,
            "primary_loaded": None,
            "all_required_loaded": None,
            "loaded_before_task_tools": None,
            "guard_exhausted": False,
            "skill_load_errors": 0,
            "dependency_order_respected": None,
        })
        return {
            "quality_version": QUALITY_VERSION,
            "routing_method": _routing_method(entry.get("method")),
            "score": 1.0,
            "confidence": _blocked_confidence(entry),
            "grade": "excellent",
            "signals": signals,
            "penalties": [],
            "bonuses": [],
            "assessable": True,
        }
    if (
        policy_status not in {"valid", "adjusted", "degraded"}
        or result in {"not_applicable", "unknown"}
        or not entry.get("execution_observable")
        or not isinstance(entry.get("recommended"), list)
        or not entry.get("recommended")
    ):
        return unknown_quality(_routing_method(entry.get("method")))

    recommended = [item for item in entry["recommended"] if isinstance(item, dict)]
    executions = [item for item in entry.get("executions", []) if isinstance(item, dict)]
    successful = {
        str(item.get("name") or "")
        for item in executions
        if item.get("success") is True
    }
    primary = next(
        (str(item.get("name") or "") for item in recommended if item.get("role") == "primary"),
        "",
    )
    dependency_requirements = [
        (
            str(item.get("name") or ""),
            [
                str(parent or "")
                for parent in item.get("required_for", [])
                if str(parent or "")
            ]
            if isinstance(item.get("required_for"), list)
            else [],
        )
        for item in recommended
        if item.get("required_by_dependency") is True
    ]
    required_dependencies = [name for name, _parents in dependency_requirements if name]
    required_names = [name for name in [*required_dependencies, primary] if name]
    optional_supporting = [
        str(item.get("name") or "")
        for item in recommended
        if item.get("role") != "primary" and item.get("required_by_dependency") is not True
    ]
    missing_dependencies = [name for name in required_dependencies if name not in successful]
    missing_optional = [name for name in optional_supporting if name not in successful]
    load_errors = sum(
        _execution_error_count(item)
        for item in executions
    )
    dependency_order = _dependency_order(dependency_requirements, executions)
    before_tools = entry.get("primary_loaded_before_task_tools")
    if not isinstance(before_tools, bool):
        before_tools = None
    guard_status = str(entry.get("enforcement_status") or "not_required")
    block_count = _bounded_int(entry.get("block_count"), maximum=5)

    signals = _base_signals(entry)
    signals.update({
        "routing_valid": True,
        "policy_clean": policy_status == "valid",
        "safely_blocked": False,
        "primary_loaded": entry.get("primary_loaded")
        if isinstance(entry.get("primary_loaded"), bool)
        else None,
        "all_required_loaded": all(name in successful for name in required_names),
        "loaded_before_task_tools": before_tools,
        "guard_exhausted": guard_status == "exhausted",
        "skill_load_errors": load_errors,
        "dependency_order_respected": dependency_order,
    })

    penalties: list[dict[str, Any]] = []
    if policy_status == "adjusted":
        _add_penalty(penalties, "policy-adjusted")
    elif policy_status == "degraded":
        _add_penalty(penalties, "policy-degraded")
    if result == "partial":
        _add_penalty(penalties, "audit-partial")
    elif result == "missed":
        _add_penalty(penalties, "audit-missed")
    if entry.get("primary_loaded") is False:
        _add_penalty(penalties, "primary-not-loaded")
    _add_counted_penalty(
        penalties, "required-dependency-missing", len(missing_dependencies)
    )
    _add_counted_penalty(
        penalties, "optional-supporting-missing", len(missing_optional)
    )
    _add_counted_penalty(penalties, "skill-load-error", load_errors)
    if guard_status == "warned" or (
        entry.get("enforcement_mode") == "warn" and before_tools is False
    ):
        _add_penalty(penalties, "guard-warned")
    if block_count:
        _add_penalty(penalties, "guard-blocked")
    if guard_status == "exhausted":
        _add_penalty(penalties, "guard-exhausted")
    elif guard_status == "unavailable":
        _add_penalty(penalties, "guard-unavailable")
    elif guard_status == "error":
        _add_penalty(penalties, "guard-error")
    if before_tools is False:
        _add_penalty(penalties, "primary-after-task-tool")
    if dependency_order is False:
        _add_penalty(penalties, "dependency-order-violated")

    score = round(max(0.0, 1.0 - sum(float(item["value"]) for item in penalties)), 4)
    return {
        "quality_version": QUALITY_VERSION,
        "routing_method": _routing_method(entry.get("method")),
        "score": score,
        "confidence": _confidence(entry, before_tools, dependency_order),
        "grade": grade_for_score(score),
        "signals": signals,
        "penalties": penalties,
        "bonuses": [],
        "assessable": True,
    }


def safe_evaluate_quality(entry: dict[str, Any]) -> dict[str, Any]:
    """Return an unassessable record if deterministic evaluation fails."""
    try:
        return evaluate_quality(entry)
    except Exception:
        method = _routing_method(entry.get("method")) if isinstance(entry, dict) else "unknown"
        return unknown_quality(method)


def unknown_quality(routing_method: str = "unknown") -> dict[str, Any]:
    """Build the versioned record used when technical quality is not assessable."""
    return {
        "quality_version": QUALITY_VERSION,
        "routing_method": _routing_method(routing_method),
        "score": None,
        "confidence": "unknown",
        "grade": "unknown",
        "signals": {},
        "penalties": [],
        "bonuses": [],
        "assessable": False,
    }


def normalize_quality(value: Any) -> dict[str, Any] | None:
    """Normalize a persisted current-version quality record without reevaluation."""
    if not isinstance(value, dict) or value.get("quality_version") != QUALITY_VERSION:
        return None
    assessable = value.get("assessable") is True
    score = value.get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        score = None
        assessable = False
    elif not 0.0 <= float(score) <= 1.0:
        score = None
        assessable = False
    else:
        score = round(float(score), 4)
    confidence = str(value.get("confidence") or "unknown")
    if confidence not in _CONFIDENCE:
        confidence = "unknown"
    grade = grade_for_score(float(score)) if assessable and score is not None else "unknown"
    signals = value.get("signals") if isinstance(value.get("signals"), dict) else {}
    penalties = _normalize_adjustments(value.get("penalties"))
    bonuses = _normalize_adjustments(value.get("bonuses"))
    return {
        "quality_version": QUALITY_VERSION,
        "routing_method": _routing_method(value.get("routing_method")),
        "score": score if assessable else None,
        "confidence": confidence if assessable else "unknown",
        "grade": grade if assessable else "unknown",
        "signals": _normalize_signals(signals),
        "penalties": penalties if assessable else [],
        "bonuses": bonuses if assessable else [],
        "assessable": assessable,
    }


def grade_for_score(score: float) -> str:
    """Map a clamped score to the central deterministic grade thresholds."""
    selected = max(0.0, min(float(score), 1.0))
    for grade, threshold in GRADE_THRESHOLDS:
        if selected >= threshold:
            return grade
    return "failed"


def quality_summary(entries: list[dict[str, Any]], limit: int) -> str:
    """Render bounded aggregate statistics from persisted quality records."""
    safe_limit = max(1, min(int(limit), 1000))
    selected = entries[-safe_limit:]
    records = [normalize_quality(entry.get("quality")) for entry in selected if isinstance(entry, dict)]
    current = [record for record in records if record is not None]
    assessable = [record for record in current if record.get("assessable") is True]
    scores = [float(record["score"]) for record in assessable]
    grades = {name: 0 for name, _threshold in GRADE_THRESHOLDS}
    confidence = {name: 0 for name in ("high", "medium", "low")}
    for record in assessable:
        grade = str(record.get("grade") or "unknown")
        if grade in grades:
            grades[grade] += 1
        selected_confidence = str(record.get("confidence") or "unknown")
        if selected_confidence in confidence:
            confidence[selected_confidence] += 1
    unknown = len(selected) - len(assessable)
    average = f"{sum(scores) / len(scores):.2f}" if scores else "none"
    return "\n".join([
        "Skill Router Quality",
        "",
        f"Last {len(selected)} routed tasks:",
        f"Assessable: {len(assessable)}",
        f"Average score: {average}",
        "",
        f"Excellent: {grades['excellent']}",
        f"Good: {grades['good']}",
        f"Acceptable: {grades['acceptable']}",
        f"Poor: {grades['poor']}",
        f"Failed: {grades['failed']}",
        f"Unknown/not assessable: {unknown}",
        "",
        f"High confidence: {confidence['high']}",
        f"Medium confidence: {confidence['medium']}",
        f"Low confidence: {confidence['low']}",
    ])


def quality_last(entry: dict[str, Any] | None) -> str:
    """Render technical details for the latest persisted quality record."""
    if not isinstance(entry, dict):
        return "Routing Quality\n\nNo quality records."
    quality = normalize_quality(entry.get("quality"))
    if quality is None or not quality.get("assessable"):
        return (
            "Routing Quality\n\nScore: unknown\nGrade: unknown\nConfidence: unknown\n\n"
            "This routed turn is not technically assessable."
        )
    signals = quality["signals"]
    score = float(quality["score"])
    lines = [
        "Routing Quality",
        "",
        f"Score: {score:.2f}",
        f"Grade: {quality['grade']}",
        f"Confidence: {quality['confidence']}",
        f"Routing method: {quality['routing_method']}",
        "",
        "Signals:",
        f"Policy: {entry.get('policy_status', 'unknown')}",
        f"Audit: {entry.get('result', 'unknown')}",
        f"Primary loaded: {_display_signal(signals.get('primary_loaded'))}",
        "Primary before task tools: "
        + _display_signal(signals.get("loaded_before_task_tools")),
        "Required skills loaded: "
        + _display_signal(signals.get("all_required_loaded")),
        "Dependency order respected: "
        + _display_signal(signals.get("dependency_order_respected")),
        f"Guard: {entry.get('enforcement_status', 'not_required')}",
        f"Skill load errors: {signals.get('skill_load_errors', 0)}",
        "",
        "Penalties:",
    ]
    penalties = quality.get("penalties", [])
    if penalties:
        for item in penalties:
            lines.append(
                f"- {_penalty_label(str(item.get('code') or 'unknown'))}: "
                f"-{float(item.get('value') or 0):.2f}"
            )
    else:
        lines.append("none")
    return "\n".join(lines)


def _base_signals(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "audit_finalized": bool(entry.get("finalized")),
        "observer_available": bool(entry.get("execution_observable")),
    }


def _execution_error_count(item: dict[str, Any]) -> int:
    value = item.get("error_count")
    if isinstance(value, int) and not isinstance(value, bool):
        return max(0, min(value, 20))
    return 1 if item.get("success") is False else 0


def _dependency_order(
    dependencies: list[tuple[str, list[str]]],
    executions: list[dict[str, Any]],
) -> bool | None:
    if not dependencies:
        return True
    if any(not name or not parents for name, parents in dependencies):
        return None
    execution_by_name = {
        str(item.get("name") or ""): item
        for item in executions
        if str(item.get("name") or "")
    }
    required_names = {
        name
        for dependency, parents in dependencies
        for name in [dependency, *parents]
    }
    if any(
        name not in execution_by_name
        or execution_by_name[name].get("order_ambiguous") is True
        or execution_by_name[name].get("pending") is True
        for name in required_names
    ):
        return None
    successful_sequence = {
        name: item.get("sequence")
        for name, item in execution_by_name.items()
        if item.get("success") is True
        and isinstance(item.get("sequence"), int)
        and not isinstance(item.get("sequence"), bool)
    }
    if any(name not in successful_sequence for name in required_names):
        return None
    return all(
        int(successful_sequence[dependency]) < int(successful_sequence[parent])
        for dependency, parents in dependencies
        for parent in parents
    )


def _confidence(
    entry: dict[str, Any],
    before_tools: bool | None,
    dependency_order: bool | None,
) -> str:
    identities = all(str(entry.get(name) or "") for name in ("task_id", "turn_id", "session_id"))
    primary_known = isinstance(entry.get("primary_loaded"), bool)
    if identities and primary_known and before_tools is not None and dependency_order is not None:
        return "high"
    if primary_known and (identities or before_tools is not None):
        return "medium"
    return "low"


def _blocked_confidence(entry: dict[str, Any]) -> str:
    identities = all(str(entry.get(name) or "") for name in ("task_id", "turn_id", "session_id"))
    return "high" if identities else "medium"


def _add_penalty(penalties: list[dict[str, Any]], code: str) -> None:
    penalties.append({"code": code, "value": PENALTY_WEIGHTS[code], "count": 1})


def _add_counted_penalty(
    penalties: list[dict[str, Any]],
    code: str,
    count: int,
) -> None:
    if count <= 0:
        return
    value = min(PENALTY_WEIGHTS[code] * count, _PENALTY_CAPS[code])
    penalties.append({"code": code, "value": round(value, 4), "count": count})


def _normalize_adjustments(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    output: list[dict[str, Any]] = []
    for item in value[:20]:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "")[:80]
        amount = item.get("value")
        count = item.get("count")
        if (
            not code
            or isinstance(amount, bool)
            or not isinstance(amount, (int, float))
            or not 0.0 <= float(amount) <= 1.0
        ):
            continue
        output.append({
            "code": code,
            "value": round(float(amount), 4),
            "count": _bounded_int(count, maximum=20) or 1,
        })
    return output


def _normalize_signals(value: dict[str, Any]) -> dict[str, Any]:
    allowed = (
        "audit_finalized",
        "observer_available",
        "routing_valid",
        "policy_clean",
        "safely_blocked",
        "primary_loaded",
        "all_required_loaded",
        "loaded_before_task_tools",
        "guard_exhausted",
        "skill_load_errors",
        "dependency_order_respected",
    )
    output: dict[str, Any] = {}
    for key in allowed:
        selected = value.get(key)
        if isinstance(selected, bool) or selected is None:
            output[key] = selected
        elif key == "skill_load_errors":
            output[key] = _bounded_int(selected, maximum=20)
    return output


def _routing_method(value: Any) -> str:
    selected = str(value or "unknown")
    return selected if selected in {"model", "deterministic"} else "unknown"


def _bounded_int(value: Any, *, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(0, min(value, maximum))


def _display_signal(value: Any) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return "unknown"


def _penalty_label(code: str) -> str:
    return code.replace("-", " ")
