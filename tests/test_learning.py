from __future__ import annotations

from copy import deepcopy
import threading

import pytest

from skill_router_plugin import learning as learning_module
from skill_router_plugin.learning import (
    LEARNING_VERSION,
    MAX_SHADOW_BIAS,
    ShadowLearning,
    compare_shadow_ranking,
    empty_learning_state,
    learning_last,
    learning_skill,
    learning_summary,
    normalize_learning_state,
    rebuild_learning_state,
)
from skill_router_plugin.quality import QUALITY_VERSION, evaluate_quality


class State:
    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return deepcopy(self.values.get(key, default))

    def set(self, key, value):
        self.values[key] = deepcopy(value)


class Ctx:
    profile_name = "profile"

    def __init__(self):
        self.state = State()


def recommendation(name, role="primary", *, dependency_for=None):
    value = {"name": name, "role": role, "order": 1}
    if dependency_for:
        value.update({"required_by_dependency": True, "required_for": [dependency_for]})
    return value


def execution(name, sequence=1, *, success=True, errors=0):
    return {
        "name": name,
        "sequence": sequence,
        "success": success,
        "error_count": errors,
        "pending": False,
        "order_ambiguous": False,
    }


def audit_entry(
    recommendations=None,
    executions=None,
    *,
    result="complete",
    confidence="high",
    primary_before=True,
    quality_version=QUALITY_VERSION,
    assessable=True,
    extra=None,
):
    recommendations = recommendations or [recommendation("github")]
    executions = executions if executions is not None else [execution("github")]
    entry = {
        "task_id": "task",
        "turn_id": "turn",
        "session_id": "session",
        "method": "model",
        "policy_status": "valid",
        "enforcement_mode": "primary",
        "enforcement_status": "satisfied",
        "block_count": 0,
        "primary_loaded_before_task_tools": primary_before,
        "recommended": recommendations,
        "executions": executions,
        "result": result,
        "primary_loaded": any(
            item.get("success") is True
            and any(rec.get("name") == item.get("name") and rec.get("role") == "primary" for rec in recommendations)
            for item in executions
        ),
        "execution_observable": True,
        "finalized": True,
        "learning_mode": "shadow",
        "actual_primary": next((item["name"] for item in recommendations if item.get("role") == "primary"), ""),
        "shadow_primary": next((item["name"] for item in recommendations if item.get("role") == "primary"), ""),
        "shadow_changed": False,
    }
    quality = evaluate_quality(entry)
    quality["confidence"] = confidence
    quality["quality_version"] = quality_version
    quality["assessable"] = assessable
    if not assessable:
        quality.update({"score": None, "grade": "unknown", "confidence": "unknown"})
    entry["quality"] = quality
    if extra:
        entry.update(extra)
    return entry


def repeat(entry, count):
    return [deepcopy(entry) for _ in range(count)]


def test_high_confidence_records_are_used():
    state = rebuild_learning_state(repeat(audit_entry(), 5), min_samples=5)

    assert state["learning_version"] == LEARNING_VERSION
    assert state["quality_version"] == QUALITY_VERSION
    assert state["usable_quality_records"] == 5
    assert state["skills"]["github"]["samples"] == 5
    assert state["skills"]["github"]["status"] == "sufficient_data"
    assert 0 < state["skills"]["github"]["shadow_bias"] < 0.04


def test_medium_is_downweighted_and_low_is_ignored():
    history = repeat(audit_entry(confidence="medium"), 5) + repeat(audit_entry(confidence="low"), 5)
    state = rebuild_learning_state(history, min_samples=5)

    skill = state["skills"]["github"]
    assert state["usable_quality_records"] == 5
    assert skill["samples"] == 5
    assert skill["weighted_samples"] < 2
    assert skill["status"] == "insufficient_data"
    assert skill["shadow_bias"] == 0.0


def test_records_captured_while_learning_is_off_are_ignored():
    entry = audit_entry()
    entry["learning_mode"] = "off"

    state = rebuild_learning_state(repeat(entry, 10), min_samples=5)

    assert state["usable_quality_records"] == 0
    assert state["skills"] == {}


def test_unassessable_and_wrong_quality_version_are_ignored():
    history = [
        audit_entry(assessable=False),
        audit_entry(quality_version=999),
    ]

    state = rebuild_learning_state(history, min_samples=5)

    assert state["usable_quality_records"] == 0
    assert state["skills"] == {}


def test_fewer_than_minimum_samples_never_produce_bias():
    state = rebuild_learning_state(repeat(audit_entry(executions=[]), 2), min_samples=3)
    skill = state["skills"]["github"]

    assert skill["status"] == "insufficient_data"
    assert skill["shadow_bias"] == 0.0


def test_maximum_minimum_sample_setting_is_reachable():
    skill = rebuild_learning_state(repeat(audit_entry(), 100), min_samples=100)["skills"]["github"]

    assert skill["status"] == "sufficient_data"
    assert skill["shadow_bias"] > 0


def test_five_samples_are_more_conservative_than_fifty():
    five = rebuild_learning_state(repeat(audit_entry(), 5), min_samples=5)
    fifty = rebuild_learning_state(repeat(audit_entry(), 50), min_samples=5)

    bias_five = five["skills"]["github"]["shadow_bias"]
    bias_fifty = fifty["skills"]["github"]["shadow_bias"]
    assert 0 < bias_five < bias_fifty < MAX_SHADOW_BIAS


def test_one_bad_observation_only_slightly_changes_stable_bias():
    good = repeat(audit_entry(), 50)
    mixed = repeat(audit_entry(), 49) + [audit_entry(executions=[], result="missed", primary_before=False)]

    good_bias = rebuild_learning_state(good, min_samples=5)["skills"]["github"]["shadow_bias"]
    mixed_bias = rebuild_learning_state(mixed, min_samples=5)["skills"]["github"]["shadow_bias"]

    assert 0 < good_bias - mixed_bias < 0.02


def test_repeated_bad_skill_specific_evidence_is_conservative_and_clamped():
    bad = audit_entry(executions=[], result="missed", primary_before=False)
    five = rebuild_learning_state(repeat(bad, 5), min_samples=5)["skills"]["github"]
    many = rebuild_learning_state(repeat(bad, 500), min_samples=5)["skills"]["github"]

    assert -0.06 < five["shadow_bias"] < 0
    assert -MAX_SHADOW_BIAS <= many["shadow_bias"] < five["shadow_bias"]


def test_roles_are_aggregated_separately():
    recommendations = [
        recommendation("primary", "primary"),
        recommendation("support", "supporting"),
        recommendation("dependency", "supporting", dependency_for="primary"),
    ]
    executions = [
        execution("dependency", 1),
        execution("primary", 2),
        execution("support", 3),
    ]

    state = rebuild_learning_state(
        repeat(audit_entry(recommendations, executions), 5),
        min_samples=5,
    )

    assert state["skills"]["primary"]["primary_samples"] == 5
    assert state["skills"]["support"]["supporting_samples"] == 5
    assert state["skills"]["dependency"]["dependency_samples"] == 5
    assert state["skills"]["dependency"]["roles"]["dependency"]["technical_score"] == 1.0
    assert state["skills"]["support"]["shadow_bias"] == 0.0


def test_load_error_only_reduces_affected_skill_signal():
    recommendations = [recommendation("a"), recommendation("b", "supporting")]
    entry = audit_entry(
        recommendations,
        [execution("a", 1), execution("b", 2, errors=1)],
    )

    state = rebuild_learning_state(repeat(entry, 5), min_samples=5)

    assert state["skills"]["a"]["load_error_rate"] == 0.0
    assert state["skills"]["b"]["load_error_rate"] == 1.0
    assert state["skills"]["a"]["roles"]["primary"]["technical_score"] == 1.0
    assert state["skills"]["b"]["roles"]["supporting"]["technical_score"] == 0.75


def test_repeated_primary_load_errors_eventually_create_small_negative_bias():
    entry = audit_entry(executions=[execution("github", errors=1)])

    five = rebuild_learning_state(repeat(entry, 5), min_samples=5)["skills"]["github"]
    fifty = rebuild_learning_state(repeat(entry, 50), min_samples=5)["skills"]["github"]

    assert five["shadow_bias"] == 0.0
    assert -0.02 < fifty["shadow_bias"] < 0


def test_global_low_quality_is_not_copied_into_skill_aggregate():
    entry = audit_entry()
    entry["quality"]["score"] = 0.30
    entry["quality"]["grade"] = "poor"

    skill = rebuild_learning_state(repeat(entry, 5), min_samples=5)["skills"]["github"]

    assert skill["average_quality"] == 1.0
    assert skill["roles"]["primary"]["technical_score"] == 1.0
    assert skill["shadow_bias"] > 0


def test_old_samples_with_negligible_effective_weight_are_insufficient():
    old_github = repeat(audit_entry(), 5)
    recent_other = repeat(
        audit_entry([recommendation("other")], [execution("other")]),
        995,
    )

    skill = rebuild_learning_state(old_github + recent_other, min_samples=5)["skills"]["github"]

    assert skill["primary_samples"] == 5
    assert skill["status"] == "insufficient_data"
    assert skill["confidence"] == "low"
    assert skill["shadow_bias"] == 0.0


def test_recent_observations_have_slightly_more_weight():
    old_bad_then_good = repeat(audit_entry(executions=[], result="missed", primary_before=False), 25) + repeat(audit_entry(), 25)
    old_good_then_bad = repeat(audit_entry(), 25) + repeat(audit_entry(executions=[], result="missed", primary_before=False), 25)

    recent_good = rebuild_learning_state(old_bad_then_good, min_samples=5)["skills"]["github"]["shadow_bias"]
    recent_bad = rebuild_learning_state(old_good_then_bad, min_samples=5)["skills"]["github"]["shadow_bias"]

    assert recent_good > recent_bad


def test_shadow_can_change_while_actual_list_remains_identical():
    history = repeat(audit_entry([recommendation("b")], [execution("b")]), 50)
    state = rebuild_learning_state(history, min_samples=5)
    actual = [
        {"name": "a", "role": "primary", "readiness_status": "ready"},
        {"name": "b", "role": "supporting", "readiness_status": "ready"},
    ]
    original = deepcopy(actual)

    comparison = compare_shadow_ranking(actual, state, mode="shadow")

    assert comparison == {
        "learning_mode": "shadow",
        "actual_primary": "a",
        "shadow_primary": "b",
        "shadow_changed": True,
    }
    assert actual == original


def test_explicit_skill_prevents_shadow_primary_change():
    state = rebuild_learning_state(
        repeat(audit_entry([recommendation("b")], [execution("b")]), 50),
        min_samples=5,
    )
    actual = [
        {"name": "a", "role": "primary", "readiness_status": "ready"},
        {"name": "b", "role": "supporting", "readiness_status": "ready"},
    ]

    comparison = compare_shadow_ranking(actual, state, explicit_skill_names=["a"], mode="shadow")

    assert comparison["shadow_primary"] == "a"
    assert comparison["shadow_changed"] is False


def test_unready_or_dependency_candidate_cannot_be_promoted():
    state = rebuild_learning_state(
        repeat(audit_entry([recommendation("b")], [execution("b")]), 50),
        min_samples=5,
    )
    actual = [
        {"name": "a", "role": "primary", "readiness_status": "ready"},
        {"name": "b", "role": "supporting", "readiness_status": "broken"},
        {
            "name": "c",
            "role": "supporting",
            "readiness_status": "ready",
            "required_by_dependency": True,
        },
    ]

    comparison = compare_shadow_ranking(actual, state, mode="shadow")

    assert comparison["shadow_primary"] == "a"
    assert comparison["shadow_changed"] is False


def test_learning_off_never_changes_shadow():
    state = rebuild_learning_state(
        repeat(audit_entry([recommendation("b")], [execution("b")]), 50),
        min_samples=5,
    )
    actual = [
        {"name": "a", "role": "primary", "readiness_status": "ready"},
        {"name": "b", "role": "supporting", "readiness_status": "ready"},
    ]

    comparison = compare_shadow_ranking(actual, state, mode="off")

    assert comparison["learning_mode"] == "off"
    assert comparison["shadow_primary"] == "a"


def test_rebuild_is_deterministic_and_profile_state_is_separate():
    history = repeat(audit_entry(), 5)
    first_ctx = Ctx()
    second_ctx = Ctx()
    first = ShadowLearning(first_ctx)
    second = ShadowLearning(second_ctx)

    state_one = first.rebuild(history, 5)
    state_two = first.rebuild(history, 5)

    assert state_one == state_two
    assert second.state(5) == empty_learning_state(5)


def test_reset_only_clears_derived_state_and_rebuild_restores_it():
    ctx = Ctx()
    learning = ShadowLearning(ctx)
    history = repeat(audit_entry(), 5)
    learning.rebuild(history, 5)

    reset = learning.reset(5)

    assert reset["skills"] == {}
    assert learning.state(5)["skills"] == {}
    assert learning.rebuild(history, 5)["skills"]["github"]["samples"] == 5


def test_reset_invalidates_an_inflight_older_rebuild(monkeypatch):
    ctx = Ctx()
    learning = ShadowLearning(ctx)
    started = threading.Event()
    release = threading.Event()
    original = learning_module.rebuild_learning_state

    def delayed(history, *, min_samples):
        started.set()
        assert release.wait(timeout=2)
        return original(history, min_samples=min_samples)

    monkeypatch.setattr(learning_module, "rebuild_learning_state", delayed)
    worker = threading.Thread(target=lambda: learning.rebuild(repeat(audit_entry(), 5), 5))
    worker.start()
    assert started.wait(timeout=2)

    learning.reset(5)
    release.set()
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert learning.state(5) == empty_learning_state(5)


def test_newer_rebuild_wins_over_stale_history_supplier():
    ctx = Ctx()
    learning = ShadowLearning(ctx)
    started = threading.Event()
    release = threading.Event()
    old_history = repeat(audit_entry([recommendation("old")], [execution("old")]), 5)
    new_history = repeat(audit_entry([recommendation("new")], [execution("new")]), 5)

    def delayed_old_history():
        started.set()
        assert release.wait(timeout=2)
        return old_history

    worker = threading.Thread(target=lambda: learning.rebuild(delayed_old_history, 5))
    worker.start()
    assert started.wait(timeout=2)

    learning.rebuild(lambda: new_history, 5)
    release.set()
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert set(learning.state(5)["skills"]) == {"new"}


def test_corrupt_or_wrong_version_state_fails_safe():
    assert normalize_learning_state({"learning_version": 999}, min_samples=5) == empty_learning_state(5)
    assert normalize_learning_state("corrupt", min_samples=5) == empty_learning_state(5)
    state = empty_learning_state(5)
    state["skills"]["github"] = {
        "samples": 50,
        "primary_samples": 50,
        "shadow_bias": float("nan"),
        "roles": {
            "primary": {
                "samples": 50,
                "weighted_samples": 40.0,
                "technical_score": float("nan"),
                "load_success_rate": 1.0,
            }
        },
    }
    assert normalize_learning_state(state, min_samples=5)["skills"] == {}


def test_persisted_shadow_bias_is_recomputed_within_clamp():
    state = empty_learning_state(5)
    state["skills"]["github"] = {
        "samples": 50,
        "primary_samples": 50,
        "shadow_bias": 9.0,
        "roles": {
            "primary": {
                "samples": 50,
                "weighted_samples": 40.0,
                "technical_score": 1.0,
                "load_success_rate": 1.0,
            }
        },
    }

    normalized = normalize_learning_state(state, min_samples=5)

    assert 0 < normalized["skills"]["github"]["shadow_bias"] < MAX_SHADOW_BIAS


def test_min_samples_is_clamped():
    assert empty_learning_state(1)["min_samples"] == 3
    assert empty_learning_state(999)["min_samples"] == 100


def test_learning_state_does_not_copy_private_audit_data():
    secret = "SECRET PROMPT RESPONSE TOOL RESULT ERROR"
    entry = audit_entry(extra={
        "prompt": secret,
        "response": secret,
        "tool_result": secret,
        "error": secret,
        "task_hash": secret,
    })

    state = rebuild_learning_state(repeat(entry, 5), min_samples=5)

    assert secret not in repr(state)
    assert "task_hash" not in repr(state)


def test_learning_renderers_are_compact_and_explicitly_shadow_only():
    entries = repeat(audit_entry(), 5)
    entries[-1].update({"actual_primary": "github", "shadow_primary": "review", "shadow_changed": True})
    state = rebuild_learning_state(entries, min_samples=5)

    summary = learning_summary(state, "shadow")
    detail = learning_skill(state, "github")
    last = learning_last(state)

    assert "Mode: shadow" in summary
    assert "Skills with sufficient evidence: 1" in summary
    assert "No routing behavior was changed." in summary
    assert "Primary: 5" in detail
    assert "Shadow bias: +" in detail
    assert "Actual primary: github" in last
    assert "Shadow primary: review" in last
    assert "Shadow changed selection: yes" in last
