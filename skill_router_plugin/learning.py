"""Deterministic profile-scoped shadow learning from bounded routing audits."""

from __future__ import annotations

import math
import threading
from typing import Any

from .quality import QUALITY_VERSION, normalize_quality

LEARNING_VERSION = 1
LEARNING_STATE_KEY = "router.learning"
SUPPORTED_QUALITY_VERSIONS = {QUALITY_VERSION}
CONFIDENCE_WEIGHTS = {"high": 1.0, "medium": 0.35}
RECENCY_DECAY = 0.985
SHRINKAGE_SAMPLES = 20.0
POSITIVE_BIAS_SCALE = 0.60
NEGATIVE_BIAS_SCALE = 0.25
NEUTRAL_TECHNICAL_SCORE = 0.80
MAX_SHADOW_BIAS = 0.20
MIN_EFFECTIVE_SAMPLE_RATIO = 0.50
SHADOW_ORDER_STEP = 0.05
MAX_LEARNING_SKILLS = 500
MAX_SHADOW_HISTORY = 20
_READINESS_PRIORITY = {"ready": 0, "unknown": 1, "setup_required": 2}
_ROLES = ("primary", "supporting", "dependency")


class ShadowLearning:
    """Rebuild and expose technical learning aggregates for one profile state."""

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self._lock = threading.RLock()
        self._generation = 0
        self._last_write_succeeded = True

    def rebuild(self, audit_history: Any, min_samples: int) -> dict[str, Any]:
        """Recompute and persist learning state from a history value or supplier."""
        with self._lock:
            self._generation += 1
            generation = self._generation
        try:
            history = audit_history() if callable(audit_history) else audit_history
            state = rebuild_learning_state(history, min_samples=min_samples)
        except Exception:
            with self._lock:
                self._last_write_succeeded = False
            return empty_learning_state(min_samples)
        try:
            with self._lock:
                if generation != self._generation:
                    value = self.ctx.state.get(LEARNING_STATE_KEY, None)
                    return normalize_learning_state(value, min_samples=min_samples)
                self.ctx.state.set(LEARNING_STATE_KEY, state)
                self._last_write_succeeded = True
        except Exception:
            with self._lock:
                self._last_write_succeeded = False
            return empty_learning_state(min_samples)
        return state

    def state(self, min_samples: int) -> dict[str, Any]:
        """Read current-version learning state or return a fail-safe empty state."""
        try:
            with self._lock:
                value = self.ctx.state.get(LEARNING_STATE_KEY, None)
        except Exception:
            return empty_learning_state(min_samples)
        return normalize_learning_state(value, min_samples=min_samples)

    def reset(self, min_samples: int) -> dict[str, Any]:
        """Clear only derived learning aggregates; audits remain untouched."""
        state = empty_learning_state(min_samples)
        try:
            with self._lock:
                self._generation += 1
                self.ctx.state.set(LEARNING_STATE_KEY, state)
                self._last_write_succeeded = True
        except Exception:
            with self._lock:
                self._last_write_succeeded = False
        return state

    def write_succeeded(self) -> bool:
        """Report whether the latest attempted state write completed."""
        with self._lock:
            return self._last_write_succeeded


def rebuild_learning_state(
    audit_history: list[dict[str, Any]],
    *,
    min_samples: int,
) -> dict[str, Any]:
    """Build deterministic bounded aggregates from current-version quality history."""
    minimum = _min_samples(min_samples)
    history = [entry for entry in audit_history if isinstance(entry, dict)][-1000:]
    usable = [
        entry
        for entry in history
        if entry.get("learning_mode") == "shadow" and _usable_quality(entry) is not None
    ]
    accumulators: dict[str, dict[str, Any]] = {}
    total = len(usable)
    for index, entry in enumerate(usable):
        quality = _usable_quality(entry)
        if quality is None:
            continue
        age = total - index - 1
        weight = CONFIDENCE_WEIGHTS[str(quality["confidence"])] * (RECENCY_DECAY ** age)
        executions = {
            str(item.get("name") or ""): item
            for item in entry.get("executions", [])
            if isinstance(item, dict) and str(item.get("name") or "")
        }
        recommendations = entry.get("recommended")
        if not isinstance(recommendations, list):
            continue
        for recommendation in recommendations[:5]:
            if not isinstance(recommendation, dict):
                continue
            name = _safe_name(recommendation.get("name"))
            if not name:
                continue
            role = _observation_role(recommendation)
            execution = executions.get(name, {})
            loaded = execution.get("success") is True
            error_count = _bounded_count(execution.get("error_count"), maximum=20)
            role_score = _technical_score(
                role,
                loaded=loaded,
                error_count=error_count,
                primary_before=entry.get("primary_loaded_before_task_tools"),
                dependency_order=_dependency_order_for_skill(
                    name, recommendation, executions
                ),
            )
            accumulator = accumulators.setdefault(name, _empty_accumulator())
            accumulator["samples"] += 1
            accumulator["weighted_samples"] += weight
            accumulator["technical_sum"] += role_score * weight
            accumulator["load_sum"] += (1.0 if loaded else 0.0) * weight
            accumulator["error_sum"] += (1.0 if error_count > 0 else 0.0) * weight
            role_accumulator = accumulator["roles"][role]
            role_accumulator["samples"] += 1
            role_accumulator["weighted_samples"] += weight
            role_accumulator["score_sum"] += role_score * weight
            role_accumulator["load_sum"] += (1.0 if loaded else 0.0) * weight

    skills: dict[str, dict[str, Any]] = {}
    ordered = sorted(
        accumulators.items(),
        key=lambda item: (-int(item[1]["samples"]), item[0].casefold()),
    )[:MAX_LEARNING_SKILLS]
    for name, accumulator in ordered:
        skills[name] = _finalize_skill(accumulator, minimum)

    comparisons = _shadow_comparisons(history)
    return {
        "learning_version": LEARNING_VERSION,
        "quality_version": QUALITY_VERSION,
        "min_samples": minimum,
        "usable_quality_records": len(usable),
        "skills": skills,
        "shadow_comparisons": comparisons,
    }


def compare_shadow_ranking(
    actual_selections: list[dict[str, Any]],
    learning_state: dict[str, Any],
    *,
    explicit_skill_names: list[str] | set[str] | tuple[str, ...] = (),
    mode: str = "shadow",
) -> dict[str, Any]:
    """Compare actual and biased primary ordering without mutating recommendations."""
    actual_primary = next(
        (
            _safe_name(item.get("name"))
            for item in actual_selections
            if isinstance(item, dict) and item.get("role") == "primary"
        ),
        "",
    )
    actual_readiness = next(
        (
            str(item.get("readiness_status") or "unknown")
            for item in actual_selections
            if isinstance(item, dict) and item.get("role") == "primary"
        ),
        "unknown",
    )
    comparison = {
        "learning_mode": mode if mode in {"off", "shadow"} else "off",
        "actual_primary": actual_primary,
        "shadow_primary": actual_primary,
        "shadow_changed": False,
    }
    if comparison["learning_mode"] != "shadow" or not actual_primary:
        return comparison
    explicit = {_safe_name(name) for name in explicit_skill_names}
    explicit.discard("")
    if explicit:
        return comparison
    normalized_state = normalize_learning_state(
        learning_state,
        min_samples=_min_samples(learning_state.get("min_samples", 5))
        if isinstance(learning_state, dict)
        else 5,
    )
    skills = normalized_state["skills"]
    candidates: list[tuple[float, int, str]] = []
    candidate_index = 0
    for item in actual_selections:
        if not isinstance(item, dict) or item.get("required_by_dependency") is True:
            continue
        name = _safe_name(item.get("name"))
        readiness = str(item.get("readiness_status") or "unknown")
        if (
            not name
            or readiness not in _READINESS_PRIORITY
            or readiness != actual_readiness
        ):
            continue
        bias = float(skills.get(name, {}).get("shadow_bias") or 0.0)
        base_score = 1.0 - (candidate_index * SHADOW_ORDER_STEP)
        candidates.append((base_score + bias, candidate_index, name))
        candidate_index += 1
    if not candidates:
        return comparison
    candidates.sort(key=lambda item: (-item[0], item[1], item[2].casefold()))
    comparison["shadow_primary"] = candidates[0][2]
    comparison["shadow_changed"] = candidates[0][2] != actual_primary
    return comparison


def normalize_learning_state(value: Any, *, min_samples: int) -> dict[str, Any]:
    """Validate persisted aggregates without guessing across learning versions."""
    minimum = _min_samples(min_samples)
    if (
        not isinstance(value, dict)
        or value.get("learning_version") != LEARNING_VERSION
        or value.get("quality_version") not in SUPPORTED_QUALITY_VERSIONS
    ):
        return empty_learning_state(minimum)
    raw_skills = value.get("skills")
    skills: dict[str, dict[str, Any]] = {}
    if isinstance(raw_skills, dict):
        for raw_name, raw_skill in list(raw_skills.items())[:MAX_LEARNING_SKILLS]:
            name = _safe_name(raw_name)
            skill = _normalize_skill(raw_skill, minimum)
            if name and skill is not None:
                skills[name] = skill
    comparisons = _normalize_comparisons(value.get("shadow_comparisons"))
    return {
        "learning_version": LEARNING_VERSION,
        "quality_version": QUALITY_VERSION,
        "min_samples": minimum,
        "usable_quality_records": _bounded_count(value.get("usable_quality_records"), maximum=1000),
        "skills": skills,
        "shadow_comparisons": comparisons,
    }


def empty_learning_state(min_samples: int) -> dict[str, Any]:
    """Return an empty current-version learning state."""
    return {
        "learning_version": LEARNING_VERSION,
        "quality_version": QUALITY_VERSION,
        "min_samples": _min_samples(min_samples),
        "usable_quality_records": 0,
        "skills": {},
        "shadow_comparisons": [],
    }


def learning_summary(state: dict[str, Any], mode: str) -> str:
    """Render profile learning aggregates without source audit payloads."""
    skills = state.get("skills") if isinstance(state.get("skills"), dict) else {}
    sufficient = [skill for skill in skills.values() if skill.get("status") == "sufficient_data"]
    positive = sum(1 for skill in sufficient if float(skill.get("shadow_bias") or 0.0) > 0.005)
    negative = sum(1 for skill in sufficient if float(skill.get("shadow_bias") or 0.0) < -0.005)
    neutral = len(sufficient) - positive - negative
    comparisons = state.get("shadow_comparisons")
    if not isinstance(comparisons, list):
        comparisons = []
    changed = sum(1 for item in comparisons if isinstance(item, dict) and item.get("shadow_changed") is True)
    return "\n".join([
        "Skill Router Learning",
        "",
        f"Mode: {mode}",
        f"Version: {LEARNING_VERSION}",
        "",
        f"Usable quality records: {int(state.get('usable_quality_records') or 0)}",
        f"Skills with sufficient evidence: {len(sufficient)}",
        "",
        f"Positive bias: {positive}",
        f"Neutral bias: {neutral}",
        f"Negative bias: {negative}",
        "",
        f"Shadow changed primary: {changed} / {len(comparisons)} recent assessable turns",
        "",
        "No routing behavior was changed.",
    ])


def learning_skill(state: dict[str, Any], skill_name: str) -> str:
    """Render one skill's compact technical aggregate."""
    name = _safe_name(skill_name)
    skills = state.get("skills") if isinstance(state.get("skills"), dict) else {}
    skill = skills.get(name)
    if not isinstance(skill, dict):
        return f"Skill learning data not found: {name or 'unknown'}"
    bias = float(skill.get("shadow_bias") or 0.0)
    return "\n".join([
        f"Skill: {name}",
        "",
        "Samples:",
        f"Primary: {skill['primary_samples']}",
        f"Supporting: {skill['supporting_samples']}",
        f"Dependency: {skill['dependency_samples']}",
        "",
        f"Average technical quality: {float(skill['average_quality']):.2f}",
        f"Load success: {float(skill['load_success_rate']) * 100:.0f}%",
        f"Load error rate: {float(skill['load_error_rate']) * 100:.0f}%",
        f"Confidence: {skill['confidence']}",
        f"Shadow confidence: {skill['shadow_confidence']}",
        "",
        f"Shadow bias: {bias:+.2f}",
        "",
        f"Status: {skill['status']}",
        "",
        "Technical routing/execution evidence only.",
    ])


def learning_last(state: dict[str, Any]) -> str:
    """Render the latest bounded actual-versus-shadow comparison."""
    comparisons = state.get("shadow_comparisons")
    latest = comparisons[-1] if isinstance(comparisons, list) and comparisons else None
    if not isinstance(latest, dict):
        return "Skill Router Learning\n\nNo shadow comparison recorded.\n\nNo routing behavior was changed."
    return "\n".join([
        "Skill Router Learning",
        "",
        f"Actual primary: {latest.get('actual_primary') or 'none'}",
        f"Shadow primary: {latest.get('shadow_primary') or 'none'}",
        f"Shadow changed selection: {'yes' if latest.get('shadow_changed') else 'no'}",
        "",
        "No routing behavior was changed.",
    ])


def _usable_quality(entry: dict[str, Any]) -> dict[str, Any] | None:
    quality = normalize_quality(entry.get("quality"))
    if (
        quality is None
        or quality.get("quality_version") not in SUPPORTED_QUALITY_VERSIONS
        or quality.get("assessable") is not True
        or quality.get("confidence") not in CONFIDENCE_WEIGHTS
        or not isinstance(quality.get("score"), (int, float))
    ):
        return None
    return quality


def _observation_role(recommendation: dict[str, Any]) -> str:
    if recommendation.get("required_by_dependency") is True:
        return "dependency"
    return "primary" if recommendation.get("role") == "primary" else "supporting"


def _technical_score(
    role: str,
    *,
    loaded: bool,
    error_count: int,
    primary_before: Any,
    dependency_order: bool | None,
) -> float:
    load = 1.0 if loaded else 0.0
    error_free = 1.0 if loaded and error_count == 0 else 0.0
    if role == "primary":
        timely = 1.0 if loaded and primary_before is True else 0.0
        return (0.60 * load) + (0.25 * error_free) + (0.15 * timely)
    if role == "dependency":
        ordered = 1.0 if loaded and dependency_order is True else 0.0
        return (0.60 * load) + (0.25 * error_free) + (0.15 * ordered)
    return (0.75 * load) + (0.25 * error_free)


def _dependency_order_for_skill(
    name: str,
    recommendation: dict[str, Any],
    executions: dict[str, dict[str, Any]],
) -> bool | None:
    parents = recommendation.get("required_for")
    if not isinstance(parents, list) or not parents:
        return None
    dependency = executions.get(name)
    if not isinstance(dependency, dict) or dependency.get("success") is not True:
        return None
    sequence = dependency.get("sequence")
    if not isinstance(sequence, int) or isinstance(sequence, bool):
        return None
    for raw_parent in parents[:5]:
        parent = executions.get(_safe_name(raw_parent))
        if not isinstance(parent, dict) or parent.get("success") is not True:
            return None
        parent_sequence = parent.get("sequence")
        if not isinstance(parent_sequence, int) or isinstance(parent_sequence, bool):
            return None
        if sequence >= parent_sequence:
            return False
    return True


def _empty_accumulator() -> dict[str, Any]:
    return {
        "samples": 0,
        "weighted_samples": 0.0,
        "technical_sum": 0.0,
        "load_sum": 0.0,
        "error_sum": 0.0,
        "roles": {
            role: {
                "samples": 0,
                "weighted_samples": 0.0,
                "score_sum": 0.0,
                "load_sum": 0.0,
            }
            for role in _ROLES
        },
    }


def _finalize_skill(accumulator: dict[str, Any], minimum: int) -> dict[str, Any]:
    weighted = max(float(accumulator["weighted_samples"]), 0.000001)
    roles = {
        role: _finalize_role(accumulator["roles"][role])
        for role in _ROLES
    }
    primary = roles["primary"]
    sufficient = (
        int(primary["samples"]) >= minimum
        and float(primary["weighted_samples"]) >= minimum * MIN_EFFECTIVE_SAMPLE_RATIO
    )
    bias = _shadow_bias(float(primary["technical_score"]), float(primary["weighted_samples"])) if sufficient else 0.0
    confidence = _evidence_confidence(
        int(accumulator["samples"]),
        float(accumulator["weighted_samples"]),
        minimum,
    )
    shadow_confidence = _evidence_confidence(
        int(primary["samples"]),
        float(primary["weighted_samples"]),
        minimum,
    )
    return {
        "samples": int(accumulator["samples"]),
        "weighted_samples": round(float(accumulator["weighted_samples"]), 4),
        "primary_samples": int(roles["primary"]["samples"]),
        "supporting_samples": int(roles["supporting"]["samples"]),
        "dependency_samples": int(roles["dependency"]["samples"]),
        "average_quality": round(float(accumulator["technical_sum"]) / weighted, 4),
        "load_success_rate": round(float(accumulator["load_sum"]) / weighted, 4),
        "primary_success_rate": round(float(primary["load_success_rate"]), 4),
        "load_error_rate": round(float(accumulator["error_sum"]) / weighted, 4),
        "confidence": confidence,
        "shadow_confidence": shadow_confidence,
        "shadow_bias": bias,
        "status": "sufficient_data" if sufficient else "insufficient_data",
        "roles": roles,
    }


def _finalize_role(value: dict[str, Any]) -> dict[str, Any]:
    weighted = float(value["weighted_samples"])
    divisor = max(weighted, 0.000001)
    return {
        "samples": int(value["samples"]),
        "weighted_samples": round(weighted, 4),
        "technical_score": round(float(value["score_sum"]) / divisor, 4) if weighted else 0.0,
        "load_success_rate": round(float(value["load_sum"]) / divisor, 4) if weighted else 0.0,
    }


def _shadow_bias(technical_score: float, weighted_samples: float) -> float:
    delta = max(-1.0, min(1.0, technical_score - NEUTRAL_TECHNICAL_SCORE))
    shrinkage = weighted_samples / (weighted_samples + SHRINKAGE_SAMPLES)
    scale = POSITIVE_BIAS_SCALE if delta >= 0 else NEGATIVE_BIAS_SCALE
    bias = max(-MAX_SHADOW_BIAS, min(MAX_SHADOW_BIAS, delta * scale * shrinkage))
    return 0.0 if abs(bias) < 0.005 else round(bias, 4)


def _evidence_confidence(samples: int, weighted_samples: float, minimum: int) -> str:
    if samples < minimum or weighted_samples < minimum * MIN_EFFECTIVE_SAMPLE_RATIO:
        return "low"
    if weighted_samples >= minimum * 3:
        return "high"
    return "medium"


def _shadow_comparisons(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for entry in history:
        if _usable_quality(entry) is None or entry.get("learning_mode") != "shadow":
            continue
        actual = _safe_name(entry.get("actual_primary"))
        shadow = _safe_name(entry.get("shadow_primary"))
        if not actual:
            continue
        output.append({
            "actual_primary": actual,
            "shadow_primary": shadow or actual,
            "shadow_changed": bool(entry.get("shadow_changed")) and bool(shadow),
        })
    return output[-MAX_SHADOW_HISTORY:]


def _normalize_skill(value: Any, minimum: int) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    roles_value = value.get("roles") if isinstance(value.get("roles"), dict) else {}
    for raw_role in roles_value.values():
        if not isinstance(raw_role, dict):
            continue
        for field in ("weighted_samples", "technical_score", "load_success_rate"):
            number = raw_role.get(field)
            if isinstance(number, (int, float)) and not isinstance(number, bool):
                if not math.isfinite(float(number)):
                    return None
    roles = {
        role: _normalize_role(roles_value.get(role))
        for role in _ROLES
    }
    samples = min(1000, sum(int(roles[role]["samples"]) for role in _ROLES))
    weighted_samples = min(
        1000.0,
        sum(float(roles[role]["weighted_samples"]) for role in _ROLES),
    )
    primary = roles["primary"]
    primary_samples = int(primary["samples"])
    primary_weighted = float(primary["weighted_samples"])
    sufficient = primary_samples >= minimum and primary_weighted >= minimum * MIN_EFFECTIVE_SAMPLE_RATIO
    bias = _shadow_bias(float(primary["technical_score"]), primary_weighted) if sufficient else 0.0
    technical_sum = sum(
        float(roles[role]["technical_score"]) * float(roles[role]["weighted_samples"])
        for role in _ROLES
    )
    load_sum = sum(
        float(roles[role]["load_success_rate"]) * float(roles[role]["weighted_samples"])
        for role in _ROLES
    )
    divisor = max(weighted_samples, 0.000001)
    return {
        "samples": samples,
        "weighted_samples": round(weighted_samples, 4),
        "primary_samples": primary_samples,
        "supporting_samples": int(roles["supporting"]["samples"]),
        "dependency_samples": int(roles["dependency"]["samples"]),
        "average_quality": round(technical_sum / divisor, 4) if weighted_samples else 0.0,
        "load_success_rate": round(load_sum / divisor, 4) if weighted_samples else 0.0,
        "primary_success_rate": float(primary["load_success_rate"]),
        "load_error_rate": _bounded_float(value.get("load_error_rate"), 0.0, 1.0),
        "confidence": _evidence_confidence(samples, weighted_samples, minimum),
        "shadow_confidence": _evidence_confidence(primary_samples, primary_weighted, minimum),
        "shadow_bias": bias,
        "status": "sufficient_data" if sufficient else "insufficient_data",
        "roles": roles,
    }


def _normalize_role(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {}
    return {
        "samples": _bounded_count(value.get("samples"), maximum=1000),
        "weighted_samples": _bounded_float(value.get("weighted_samples"), 0.0, 1000.0),
        "technical_score": _bounded_float(value.get("technical_score"), 0.0, 1.0),
        "load_success_rate": _bounded_float(value.get("load_success_rate"), 0.0, 1.0),
    }


def _normalize_comparisons(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    output: list[dict[str, Any]] = []
    for item in value[-MAX_SHADOW_HISTORY:]:
        if not isinstance(item, dict):
            continue
        actual = _safe_name(item.get("actual_primary"))
        shadow = _safe_name(item.get("shadow_primary"))
        if actual:
            output.append({
                "actual_primary": actual,
                "shadow_primary": shadow or actual,
                "shadow_changed": bool(item.get("shadow_changed")) and bool(shadow),
            })
    return output


def _min_samples(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        value = 5
    return max(3, min(100, value))


def _bounded_count(value: Any, *, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(0, min(maximum, value))


def _bounded_float(value: Any, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return max(minimum, min(maximum, 0.0))
    number = float(value)
    if not math.isfinite(number):
        return max(minimum, min(maximum, 0.0))
    return round(max(minimum, min(maximum, number)), 4)


def _safe_name(value: Any) -> str:
    text = " ".join(str(value or "").split())
    return text.replace("[", "(").replace("]", ")")[:200]
