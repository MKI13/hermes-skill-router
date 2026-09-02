from __future__ import annotations

from copy import deepcopy

from skill_router_plugin import audit as audit_module
from skill_router_plugin.audit import SkillExecutionAudit


class State:
    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return deepcopy(self.values.get(key, default))

    def set(self, key, value):
        self.values[key] = deepcopy(value)


class Ctx:
    def __init__(self, profile="default", settings=None):
        self.profile_name = profile
        self.settings = settings or {}
        self.state = State()

    def get_config(self, key, default=None):
        return self.settings.get(key, default)


def recommendation(name, role="primary"):
    return {"name": name, "role": role, "order": 99, "reason": "not persisted"}


def decision(audit, recommended, *, observable=True, task_id="task-1", turn_id="turn-1"):
    audit.record_decision(
        task="Review the pull request",
        task_id=task_id,
        turn_id=turn_id,
        session_id="session-1",
        method="model",
        recommended=recommended,
        execution_observable=observable,
    )


def load_entry(ctx, index=-1):
    return ctx.state.get("router.audit")["entries"][index]


def observe(audit, name, *, status="ok", task_id="task-1", turn_id="turn-1", **kwargs):
    args = {"name": name, **kwargs.pop("args_extra", {})}
    audit.observe_tool_attempt(
        tool_name="skill_view",
        args=args,
        task_id=task_id,
        turn_id=turn_id,
        session_id="session-1",
    )
    audit.observe_tool_call(
        tool_name="skill_view",
        args=args,
        task_id=task_id,
        turn_id=turn_id,
        session_id="session-1",
        status=status,
        **kwargs,
    )


def finalize(audit, *, task_id="task-1", turn_id="turn-1"):
    audit.finalize_turn(
        task_id=task_id,
        turn_id=turn_id,
        session_id="session-1",
    )


def test_no_recommendation_is_not_applicable():
    ctx = Ctx()
    audit = SkillExecutionAudit(ctx)

    decision(audit, [])

    entry = load_entry(ctx)
    assert entry["result"] == "not_applicable"
    assert entry["primary_loaded"] is None
    assert entry["finalized"] is True


def test_primary_recommended_and_loaded_is_complete():
    ctx = Ctx()
    audit = SkillExecutionAudit(ctx)
    decision(audit, [recommendation("github")])

    observe(audit, "github")
    finalize(audit)

    entry = load_entry(ctx)
    assert entry["result"] == "complete"
    assert entry["primary_loaded"] is True


def test_primary_and_supporting_loaded_is_complete():
    ctx = Ctx()
    audit = SkillExecutionAudit(ctx)
    decision(audit, [recommendation("github"), recommendation("code-review", "supporting")])

    observe(audit, "github")
    observe(audit, "code-review")
    finalize(audit)

    assert load_entry(ctx)["result"] == "complete"


def test_primary_loaded_without_supporting_is_partial():
    ctx = Ctx()
    audit = SkillExecutionAudit(ctx)
    decision(audit, [recommendation("github"), recommendation("code-review", "supporting")])

    observe(audit, "github")
    finalize(audit)

    entry = load_entry(ctx)
    assert entry["result"] == "partial"
    assert entry["primary_loaded"] is True


def test_no_recommended_skill_loaded_is_missed():
    ctx = Ctx()
    audit = SkillExecutionAudit(ctx)
    decision(audit, [recommendation("github")])

    finalize(audit)

    entry = load_entry(ctx)
    assert entry["result"] == "missed"
    assert entry["primary_loaded"] is False


def test_foreign_skill_does_not_satisfy_recommendation():
    ctx = Ctx()
    audit = SkillExecutionAudit(ctx)
    decision(audit, [recommendation("github")])

    observe(audit, "unrelated")
    finalize(audit)

    assert load_entry(ctx)["result"] == "missed"


def test_supporting_only_is_partial_and_primary_is_false():
    ctx = Ctx()
    audit = SkillExecutionAudit(ctx)
    decision(audit, [recommendation("github"), recommendation("code-review", "supporting")])

    observe(audit, "code-review")
    finalize(audit)

    entry = load_entry(ctx)
    assert entry["result"] == "partial"
    assert entry["primary_loaded"] is False


def test_unavailable_execution_hooks_leave_result_unknown():
    ctx = Ctx()
    audit = SkillExecutionAudit(ctx)

    decision(audit, [recommendation("github")], observable=False)

    entry = load_entry(ctx)
    assert entry["result"] == "unknown"
    assert entry["primary_loaded"] is None
    assert entry["finalized"] is True


def test_unexpected_skill_view_arguments_are_ignored():
    ctx = Ctx()
    audit = SkillExecutionAudit(ctx)
    decision(audit, [recommendation("github")])

    audit.observe_tool_call(
        tool_name="skill_view",
        args=["github"],
        task_id="task-1",
        turn_id="turn-1",
        session_id="session-1",
        status="ok",
    )
    finalize(audit)

    assert load_entry(ctx)["result"] == "missed"


def test_interrupted_turn_becomes_unknown_when_next_turn_starts():
    ctx = Ctx()
    audit = SkillExecutionAudit(ctx)
    decision(audit, [recommendation("github")])

    decision(audit, [], task_id="task-2", turn_id="turn-2")

    first = load_entry(ctx, 0)
    assert first["result"] == "unknown"
    assert first["finalized"] is True
    assert first["primary_loaded"] is None


def test_linked_file_and_unrecommended_skill_loads_are_not_persisted():
    secret = "-".join(("SECRET", "UNRECOMMENDED", "SKILL"))
    ctx = Ctx()
    audit = SkillExecutionAudit(ctx)
    decision(audit, [recommendation("github")])

    audit.observe_tool_call(
        tool_name="skill_view",
        args={"name": "github", "loads_primary_document": False},
        task_id="task-1",
        turn_id="turn-1",
        session_id="session-1",
        status="ok",
    )
    observe(audit, secret)
    finalize(audit)

    entry = load_entry(ctx)
    assert entry["executions"] == []
    assert entry["result"] == "missed"
    assert secret not in repr(entry)


def test_failed_skill_view_is_not_counted_as_loaded():
    ctx = Ctx()
    audit = SkillExecutionAudit(ctx)
    decision(audit, [recommendation("github")])

    observe(audit, "github", status="error")
    finalize(audit)

    entry = load_entry(ctx)
    assert entry["result"] == "missed"
    assert entry["executions"] == [{
        "name": "github",
        "timestamp": entry["executions"][0]["timestamp"],
        "success": False,
        "sequence": 1,
        "error_count": 1,
        "pending": False,
        "order_ambiguous": False,
    }]


def test_duplicate_skill_view_calls_are_deduplicated():
    ctx = Ctx()
    audit = SkillExecutionAudit(ctx)
    decision(audit, [recommendation("github")])

    observe(audit, "github")
    observe(audit, "github")
    finalize(audit)

    entry = load_entry(ctx)
    assert entry["result"] == "complete"
    assert len(entry["executions"]) == 1


def test_history_is_bounded_to_configured_limit():
    ctx = Ctx(settings={"max_audit_entries": 10})
    audit = SkillExecutionAudit(ctx)

    for index in range(12):
        decision(
            audit,
            [],
            task_id=f"task-{index}",
            turn_id=f"turn-{index}",
        )

    entries = ctx.state.get("router.audit")["entries"]
    assert len(entries) == 10
    assert entries[0]["task_id"] == "task-2"
    assert entries[-1]["task_id"] == "task-11"
    assert audit.quality_status_fields() == (10, "unknown")


def test_profiles_keep_separate_audit_state():
    first_ctx = Ctx(profile="default")
    second_ctx = Ctx(profile="coding")
    first = SkillExecutionAudit(first_ctx)
    second = SkillExecutionAudit(second_ctx)

    decision(first, [recommendation("github")])
    decision(second, [recommendation("pytest")])

    assert load_entry(first_ctx)["profile"] == "default"
    assert load_entry(first_ctx)["recommended"][0]["name"] == "github"
    assert load_entry(second_ctx)["profile"] == "coding"
    assert load_entry(second_ctx)["recommended"][0]["name"] == "pytest"


def test_corrupt_or_old_state_is_ignored_without_touching_router_state():
    ctx = Ctx()
    ctx.state.set("router.snapshot", {"catalog_hash": "keep-me"})
    ctx.state.set("router.audit", {"version": 999, "entries": "corrupt"})
    audit = SkillExecutionAudit(ctx)

    decision(audit, [])

    assert ctx.state.get("router.snapshot") == {"catalog_hash": "keep-me"}
    assert len(ctx.state.get("router.audit")["entries"]) == 1


def test_prompt_secrets_tool_results_and_extra_arguments_are_not_persisted():
    secret = "-".join(("TOP", "SECRET", "API", "TOKEN"))
    ctx = Ctx()
    audit = SkillExecutionAudit(ctx)
    audit.record_decision(
        task=f"Use {secret} to review the request",
        task_id="task-1",
        turn_id="turn-1",
        session_id="session-1",
        method="model",
        recommended=[recommendation("github")],
        execution_observable=True,
    )

    observe(
        audit,
        "github",
        args_extra={"credential": secret},
        result=f"tool output {secret}",
        error_message=secret,
    )

    persisted = repr(ctx.state.get("router.audit"))
    assert secret not in persisted
    assert "tool output" not in persisted
    assert "reason" not in persisted


def test_finalized_audit_persists_versioned_quality_with_dependency_order():
    ctx = Ctx()
    audit = SkillExecutionAudit(ctx)
    audit.record_decision(
        task="Review",
        task_id="task-1",
        turn_id="turn-1",
        session_id="session-1",
        method="model",
        policy_status="valid",
        recommended=[
            {
                "name": "github",
                "role": "supporting",
                "required_by_dependency": True,
                "required_for": ["pr-review"],
            },
            {"name": "pr-review", "role": "primary"},
        ],
        enforcement_mode="primary",
        enforcement_status="pending",
        execution_observable=True,
    )
    observe(audit, "github")
    observe(audit, "pr-review")
    audit.update_enforcement(
        task_id="task-1",
        turn_id="turn-1",
        session_id="session-1",
        enforcement={
            "mode": "primary",
            "status": "satisfied",
            "block_count": 0,
            "primary_loaded_before_task_tools": True,
        },
    )

    finalize(audit)

    entry = load_entry(ctx)
    assert entry["quality"]["quality_version"] == 1
    assert entry["quality"]["score"] == 1.0
    assert entry["quality"]["grade"] == "excellent"
    assert entry["quality"]["confidence"] == "high"
    assert entry["quality"]["signals"]["dependency_order_respected"] is True


def test_dependency_quality_uses_invocation_order_not_completion_order():
    ctx = Ctx()
    audit = SkillExecutionAudit(ctx)
    recommended = [
        {
            "name": "dependency",
            "role": "supporting",
            "required_by_dependency": True,
            "required_for": ["primary"],
        },
        {"name": "primary", "role": "primary"},
    ]
    audit.record_decision(
        task="Review",
        task_id="task-1",
        turn_id="turn-1",
        session_id="session-1",
        method="model",
        policy_status="valid",
        recommended=recommended,
        enforcement_mode="all",
        enforcement_status="pending",
        execution_observable=True,
    )
    for name in ("dependency", "primary"):
        audit.observe_tool_attempt(
            tool_name="skill_view",
            args={"name": name},
            task_id="task-1",
            turn_id="turn-1",
            session_id="session-1",
        )
    for name in ("primary", "dependency"):
        audit.observe_tool_call(
            tool_name="skill_view",
            args={"name": name},
            task_id="task-1",
            turn_id="turn-1",
            session_id="session-1",
            status="ok",
        )
    audit.observe_tool_attempt(
        tool_name="skill_view",
        args={"name": "dependency"},
        task_id="task-1",
        turn_id="turn-1",
        session_id="session-1",
    )
    audit.observe_tool_call(
        tool_name="skill_view",
        args={"name": "dependency"},
        task_id="task-1",
        turn_id="turn-1",
        session_id="session-1",
        status="ok",
    )
    audit.update_enforcement(
        task_id="task-1",
        turn_id="turn-1",
        session_id="session-1",
        enforcement={
            "mode": "all",
            "status": "satisfied",
            "block_count": 0,
            "primary_loaded_before_task_tools": True,
        },
    )

    finalize(audit)

    entry = load_entry(ctx)
    assert entry["executions"][0]["sequence"] == 1
    assert entry["executions"][1]["sequence"] == 2
    assert entry["quality"]["signals"]["dependency_order_respected"] is True


def test_skill_load_error_before_success_remains_a_quality_signal():
    ctx = Ctx()
    audit = SkillExecutionAudit(ctx)
    audit.record_decision(
        task="Review",
        task_id="task-1",
        turn_id="turn-1",
        session_id="session-1",
        method="deterministic",
        policy_status="valid",
        recommended=[recommendation("github")],
        enforcement_mode="primary",
        enforcement_status="pending",
        execution_observable=True,
    )

    observe(audit, "github", status="error")
    observe(audit, "github", status="ok")
    audit.update_enforcement(
        task_id="task-1",
        turn_id="turn-1",
        session_id="session-1",
        enforcement={
            "mode": "primary",
            "status": "satisfied",
            "block_count": 0,
            "primary_loaded_before_task_tools": True,
        },
    )
    finalize(audit)

    entry = load_entry(ctx)
    assert entry["result"] == "complete"
    assert entry["executions"][0]["error_count"] == 1
    assert entry["quality"]["signals"]["skill_load_errors"] == 1
    assert entry["quality"]["score"] == 0.85


def test_quality_failure_does_not_prevent_audit_finalization(monkeypatch):
    ctx = Ctx()
    audit = SkillExecutionAudit(ctx)
    audit.record_decision(
        task="Review",
        task_id="task-1",
        turn_id="turn-1",
        session_id="session-1",
        method="model",
        policy_status="valid",
        recommended=[recommendation("github")],
        execution_observable=True,
    )
    monkeypatch.setattr(
        audit_module,
        "safe_evaluate_quality",
        lambda entry: (_ for _ in ()).throw(RuntimeError("quality failed")),
    )

    observe(audit, "github")
    finalize(audit)

    entry = load_entry(ctx)
    assert entry["finalized"] is True
    assert entry["result"] == "complete"
    assert entry["quality"]["assessable"] is False
    assert entry["quality"]["grade"] == "unknown"


def test_audit_persists_only_compact_shadow_comparison():
    ctx = Ctx()
    audit = SkillExecutionAudit(ctx)
    audit.record_decision(
        task="secret prompt",
        task_id="task-1",
        turn_id="turn-1",
        session_id="session-1",
        method="model",
        recommended=[recommendation("github")],
        policy_status="valid",
        execution_observable=True,
        learning_mode="shadow",
        actual_primary="github",
        shadow_primary="code-review",
        shadow_changed=True,
    )

    entry = audit.history()[-1]

    assert entry["learning_mode"] == "shadow"
    assert entry["actual_primary"] == "github"
    assert entry["shadow_primary"] == "code-review"
    assert entry["shadow_changed"] is True
    assert "secret prompt" not in repr(entry)
    assert "shadow_candidates" not in entry


def test_old_audit_entry_without_quality_remains_readable():
    ctx = Ctx()
    audit = SkillExecutionAudit(ctx)
    decision(audit, [])
    state = ctx.state.get("router.audit")
    state["entries"][0].pop("quality", None)
    ctx.state.set("router.audit", state)

    assert "Score: unknown" in audit.quality_last_text()
    assert audit.quality_status_fields() == (0, "none")


def test_enforcement_summary_updates_without_persisting_guard_payloads():
    secret = "-".join(("SECRET", "GUARD", "PAYLOAD"))
    ctx = Ctx()
    audit = SkillExecutionAudit(ctx)
    audit.record_decision(
        task="Review",
        task_id="task-1",
        turn_id="turn-1",
        session_id="session-1",
        method="model",
        recommended=[recommendation("github")],
        enforcement_mode="primary",
        enforcement_status="pending",
        execution_observable=True,
    )

    audit.update_enforcement(
        task_id="task-1",
        turn_id="turn-1",
        session_id="session-1",
        enforcement={
            "mode": "primary",
            "status": "satisfied",
            "block_count": 1,
            "primary_loaded_before_task_tools": True,
            "tool_output": secret,
            "required_skills": [secret],
        },
    )

    entry = load_entry(ctx)
    assert entry["enforcement_mode"] == "primary"
    assert entry["enforcement_status"] == "satisfied"
    assert entry["block_count"] == 1
    assert entry["primary_loaded_before_task_tools"] is True
    assert secret not in repr(entry)


def test_last_output_reports_partial_primary_result():
    ctx = Ctx()
    audit = SkillExecutionAudit(ctx)
    decision(audit, [recommendation("github"), recommendation("code-review", "supporting")])
    observe(audit, "github")
    finalize(audit)

    output = audit.last_text()

    assert "Policy: unknown" in output
    assert "Enforcement: off" in output
    assert "Guard: not_required" in output
    assert "1. github [PRIMARY]" in output
    assert "2. code-review [SUPPORTING]" in output
    assert "github: yes" in output
    assert "code-review: no" in output
    assert "Result: partial" in output
    assert "Primary loaded: yes" in output
