from __future__ import annotations

import pytest

from skill_router_plugin.quality import (
    QUALITY_VERSION,
    evaluate_quality,
    grade_for_score,
    normalize_quality,
    quality_last,
    quality_summary,
    safe_evaluate_quality,
)


def recommendation(name, role="supporting", *, required=False):
    item = {"name": name, "role": role, "order": 1}
    if required:
        item["required_by_dependency"] = True
        item["required_for"] = ["primary"]
    return item


def execution(name, sequence, success=True):
    return {"name": name, "sequence": sequence, "success": success, "timestamp": "now"}


def audit_entry(**overrides):
    value = {
        "task_id": "task",
        "turn_id": "turn",
        "session_id": "session",
        "method": "model",
        "policy_status": "valid",
        "enforcement_mode": "primary",
        "enforcement_status": "satisfied",
        "block_count": 0,
        "primary_loaded_before_task_tools": True,
        "recommended": [recommendation("github", "primary")],
        "executions": [execution("github", 1)],
        "result": "complete",
        "primary_loaded": True,
        "execution_observable": True,
        "finalized": True,
    }
    value.update(overrides)
    return value


def penalty_codes(quality):
    return [item["code"] for item in quality["penalties"]]


def test_ideal_turn_is_excellent_with_high_confidence():
    quality = evaluate_quality(audit_entry(
        recommended=[
            recommendation("dependency", required=True),
            recommendation("primary", "primary"),
        ],
        executions=[execution("dependency", 1), execution("primary", 2)],
    ))

    assert quality["quality_version"] == QUALITY_VERSION
    assert quality["score"] == 1.0
    assert quality["grade"] == "excellent"
    assert quality["confidence"] == "high"
    assert quality["routing_method"] == "model"
    assert quality["signals"]["all_required_loaded"] is True
    assert quality["signals"]["dependency_order_respected"] is True
    assert quality["penalties"] == []
    assert quality["bonuses"] == []
    assert quality["assessable"] is True


def test_partial_optional_supporting_load_reduces_score():
    quality = evaluate_quality(audit_entry(
        recommended=[
            recommendation("primary", "primary"),
            recommendation("optional"),
        ],
        executions=[execution("primary", 1)],
        result="partial",
    ))

    assert quality["score"] == pytest.approx(0.70)
    assert quality["grade"] == "acceptable"
    assert penalty_codes(quality) == ["audit-partial", "optional-supporting-missing"]


def test_missed_primary_is_strongly_penalized():
    quality = evaluate_quality(audit_entry(
        executions=[],
        result="missed",
        primary_loaded=False,
        primary_loaded_before_task_tools=False,
        enforcement_mode="warn",
        enforcement_status="warned",
    ))

    assert quality["score"] == 0.0
    assert quality["grade"] == "failed"
    assert "audit-missed" in penalty_codes(quality)
    assert "primary-not-loaded" in penalty_codes(quality)


def test_warn_and_primary_after_task_tool_reduce_quality():
    quality = evaluate_quality(audit_entry(
        enforcement_mode="warn",
        enforcement_status="satisfied",
        primary_loaded_before_task_tools=False,
    ))

    assert quality["score"] == pytest.approx(0.70)
    assert penalty_codes(quality) == ["guard-warned", "primary-after-task-tool"]


def test_single_guard_block_has_only_small_penalty_after_recovery():
    quality = evaluate_quality(audit_entry(block_count=1))

    assert quality["score"] == pytest.approx(0.95)
    assert quality["grade"] == "excellent"
    assert penalty_codes(quality) == ["guard-blocked"]


def test_guard_exhaustion_is_strong_negative_signal():
    quality = evaluate_quality(audit_entry(
        enforcement_status="exhausted",
        block_count=2,
        primary_loaded_before_task_tools=False,
    ))

    assert quality["signals"]["guard_exhausted"] is True
    assert quality["score"] == pytest.approx(0.45)
    assert "guard-exhausted" in penalty_codes(quality)


def test_skill_load_errors_are_counted_and_capped():
    quality = evaluate_quality(audit_entry(
        recommended=[recommendation("primary", "primary")],
        executions=[
            execution("one", 1, False),
            execution("two", 2, False),
            execution("three", 3, False),
            execution("four", 4, False),
            execution("primary", 5),
        ],
    ))

    assert quality["signals"]["skill_load_errors"] == 4
    error_penalty = next(item for item in quality["penalties"] if item["code"] == "skill-load-error")
    assert error_penalty == {"code": "skill-load-error", "value": 0.45, "count": 4}


def test_dependency_order_violation_is_detected():
    quality = evaluate_quality(audit_entry(
        recommended=[
            recommendation("dependency", required=True),
            recommendation("primary", "primary"),
        ],
        executions=[execution("primary", 1), execution("dependency", 2)],
    ))

    assert quality["signals"]["dependency_order_respected"] is False
    assert quality["score"] == pytest.approx(0.80)
    assert "dependency-order-violated" in penalty_codes(quality)


def test_dependency_of_optional_supporting_skill_can_follow_primary():
    quality = evaluate_quality(audit_entry(
        recommended=[
            recommendation("primary", "primary"),
            {
                "name": "support-dependency",
                "role": "supporting",
                "required_by_dependency": True,
                "required_for": ["optional-support"],
            },
            recommendation("optional-support"),
        ],
        executions=[
            execution("primary", 1),
            execution("support-dependency", 2),
            execution("optional-support", 3),
        ],
    ))

    assert quality["signals"]["dependency_order_respected"] is True
    assert quality["score"] == 1.0


def test_missing_dependency_has_unknown_order_and_stronger_penalty():
    quality = evaluate_quality(audit_entry(
        recommended=[
            recommendation("dependency", required=True),
            recommendation("primary", "primary"),
        ],
        executions=[execution("primary", 1)],
        result="partial",
    ))

    assert quality["signals"]["all_required_loaded"] is False
    assert quality["signals"]["dependency_order_respected"] is None
    assert quality["score"] == pytest.approx(0.60)
    assert "required-dependency-missing" in penalty_codes(quality)


def test_adjusted_and_degraded_policy_have_deterministic_penalties():
    adjusted = evaluate_quality(audit_entry(policy_status="adjusted"))
    degraded = evaluate_quality(audit_entry(policy_status="degraded"))

    assert adjusted["score"] == pytest.approx(0.95)
    assert adjusted["grade"] == "excellent"
    assert degraded["score"] == pytest.approx(0.80)
    assert degraded["grade"] == "good"


def test_safely_blocked_policy_is_high_quality_not_failed():
    quality = evaluate_quality(audit_entry(
        policy_status="blocked",
        enforcement_status="policy_blocked",
        recommended=[],
        executions=[],
        result="not_applicable",
        primary_loaded=None,
        primary_loaded_before_task_tools=None,
    ))

    assert quality["assessable"] is True
    assert quality["signals"]["safely_blocked"] is True
    assert quality["score"] == 1.0
    assert quality["grade"] == "excellent"
    assert quality["confidence"] == "high"


@pytest.mark.parametrize(
    "overrides",
    [
        {"recommended": [], "executions": [], "result": "not_applicable", "primary_loaded": None},
        {"finalized": False},
        {"execution_observable": False, "result": "unknown", "primary_loaded": None},
    ],
)
def test_unassessable_turns_have_unknown_grade_and_confidence(overrides):
    quality = evaluate_quality(audit_entry(**overrides))

    assert quality["assessable"] is False
    assert quality["score"] is None
    assert quality["grade"] == "unknown"
    assert quality["confidence"] == "unknown"


def test_confidence_medium_and_low_follow_missing_technical_evidence():
    medium = evaluate_quality(audit_entry(primary_loaded_before_task_tools=None))
    low = evaluate_quality(audit_entry(
        task_id="",
        turn_id="",
        session_id="",
        primary_loaded_before_task_tools=None,
    ))

    assert medium["confidence"] == "medium"
    assert low["confidence"] == "low"


def test_model_and_deterministic_routing_score_equally():
    model = evaluate_quality(audit_entry(method="model"))
    deterministic = evaluate_quality(audit_entry(method="deterministic"))

    assert model["score"] == deterministic["score"] == 1.0
    assert model["routing_method"] == "model"
    assert deterministic["routing_method"] == "deterministic"


@pytest.mark.parametrize(
    ("score", "grade"),
    [
        (1.0, "excellent"),
        (0.90, "excellent"),
        (0.89, "good"),
        (0.75, "good"),
        (0.74, "acceptable"),
        (0.55, "acceptable"),
        (0.54, "poor"),
        (0.30, "poor"),
        (0.29, "failed"),
        (0.0, "failed"),
    ],
)
def test_grade_thresholds(score, grade):
    assert grade_for_score(score) == grade


def test_quality_failure_is_safe_and_unassessable():
    quality = safe_evaluate_quality({"finalized": True, "policy_status": "valid", "recommended": object()})

    assert quality["assessable"] is False
    assert quality["grade"] == "unknown"
    assert quality["confidence"] == "unknown"


def test_normalization_rejects_old_or_damaged_quality_records():
    assert normalize_quality({"quality_version": 0, "score": 1.0}) is None
    damaged = normalize_quality({
        "quality_version": QUALITY_VERSION,
        "score": 7.0,
        "grade": "excellent",
        "confidence": "high",
        "assessable": True,
    })
    assert damaged["assessable"] is False
    assert damaged["grade"] == "unknown"
    reconstructed = normalize_quality({
        "quality_version": QUALITY_VERSION,
        "score": 1.0,
        "grade": "failed",
        "confidence": "high",
        "signals": {"routing_valid": True},
        "penalties": [],
        "bonuses": [],
        "assessable": True,
    })
    assert reconstructed["grade"] == "excellent"


def test_quality_summary_counts_assessable_and_unknown_records():
    excellent = evaluate_quality(audit_entry())
    failed = evaluate_quality(audit_entry(
        executions=[], result="missed", primary_loaded=False, primary_loaded_before_task_tools=False
    ))
    entries = [
        {"quality": excellent},
        {"quality": failed},
        {"quality": None},
    ]

    output = quality_summary(entries, 20)

    assert "Last 3 routed tasks:" in output
    assert "Assessable: 2" in output
    assert "Average score: 0.50" in output
    assert "Excellent: 1" in output
    assert "Failed: 1" in output
    assert "Unknown/not assessable: 1" in output
    assert "High confidence: 2" in output


def test_quality_last_contains_only_technical_metadata():
    secret = "SECRET USER PROMPT"
    entry = audit_entry(user_message=secret, tool_result=secret)
    entry["quality"] = evaluate_quality(entry)

    output = quality_last(entry)

    assert "Score: 1.00" in output
    assert "Grade: excellent" in output
    assert "Policy: valid" in output
    assert "Audit: complete" in output
    assert "Required skills loaded: yes" in output
    assert "Penalties:\nnone" in output
    assert secret not in output
