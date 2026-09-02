from __future__ import annotations

from skill_router_plugin.enforcement import SkillExecutionGuard


IDS = {"task_id": "task-1", "turn_id": "turn-1", "session_id": "session-1"}


def selection(name, role, status="ready"):
    return {
        "name": name,
        "role": role,
        "order": 1,
        "readiness_status": status,
    }


def start(guard, selections, *, mode="primary", policy_status="valid", available=True, blocks=2, **ids):
    return guard.start_turn(
        **{**IDS, **ids},
        policy_status=policy_status,
        selections=selections,
        mode=mode,
        max_blocks=blocks,
        available=available,
    )


def before(guard, tool_name="terminal", args=None, **ids):
    selected_ids = {**IDS, **ids}
    tool_call_id = selected_ids.pop("tool_call_id", "call-1")
    api_request_id = selected_ids.pop("api_request_id", f"request-{tool_call_id}")
    return guard.before_tool_call(
        **selected_ids,
        tool_name=tool_name,
        args=args or {},
        tool_call_id=tool_call_id,
        api_request_id=api_request_id,
    )


def load(guard, name, *, status="ok", call_id="load-1", **ids):
    selected_ids = {**IDS, **ids}
    assert guard.before_tool_call(
        **selected_ids,
        tool_name="skill_view",
        args={"name": name},
        tool_call_id=call_id,
    ) is None
    return guard.after_tool_call(
        **selected_ids,
        tool_name="skill_view",
        args={"name": name},
        tool_call_id=call_id,
        status=status,
    )


def state(guard, **ids):
    return guard.snapshot(**{**IDS, **ids})


def test_off_never_blocks_and_keeps_plan_diagnostic():
    guard = SkillExecutionGuard()
    initial = start(guard, [selection("github", "primary")], mode="off")

    directive = before(guard)

    assert directive is None
    assert initial["status"] == "not_required"
    assert initial["required_skills"] == ["github"]


def test_warn_allows_task_tool_and_marks_warning():
    guard = SkillExecutionGuard()
    start(guard, [selection("github", "primary")], mode="warn")

    directive = before(guard)

    current = state(guard)
    assert directive is None
    assert current["status"] == "warned"
    assert current["primary_loaded_before_task_tools"] is False


def test_warn_becomes_satisfied_after_primary_load():
    guard = SkillExecutionGuard()
    start(guard, [selection("github", "primary")], mode="warn")
    before(guard)

    load(guard, "github")
    directive = before(guard, tool_name="web_search")

    assert directive is None
    assert state(guard)["status"] == "satisfied"
    assert state(guard)["primary_loaded_before_task_tools"] is False


def test_warn_records_primary_loaded_before_first_task_tool():
    guard = SkillExecutionGuard()
    start(guard, [selection("github", "primary")], mode="warn")

    load(guard, "github")
    assert before(guard) is None

    assert state(guard)["status"] == "satisfied"
    assert state(guard)["primary_loaded_before_task_tools"] is True


def test_primary_blocks_until_successful_skill_view():
    guard = SkillExecutionGuard()
    start(guard, [selection("github", "primary")], mode="primary")

    blocked = before(guard)
    allowed_load = before(guard, tool_name="skill_view", args={"name": "github"})
    load(guard, "github", call_id="load-success")
    allowed_task = before(guard, tool_name="read_file")

    assert blocked["action"] == "block"
    assert "skill_view github" in blocked["message"]
    assert allowed_load is None
    assert allowed_task is None
    assert state(guard)["status"] == "satisfied"
    assert state(guard)["primary_loaded_before_task_tools"] is True


def test_linked_skill_file_does_not_satisfy_primary_load():
    guard = SkillExecutionGuard()
    start(guard, [selection("github", "primary")], mode="primary")
    args = {"name": "github", "loads_primary_document": False}

    assert guard.before_tool_call(
        **IDS, tool_name="skill_view", args=args, tool_call_id="linked-file"
    ) is None
    guard.after_tool_call(
        **IDS,
        tool_name="skill_view",
        args=args,
        tool_call_id="linked-file",
        status="ok",
    )

    assert state(guard)["loaded_skills"] == []
    assert before(guard)["action"] == "block"


def test_failed_skill_view_keeps_primary_pending():
    guard = SkillExecutionGuard()
    start(guard, [selection("github", "primary")], mode="primary")

    load(guard, "github", status="error")
    blocked = before(guard)

    assert blocked["action"] == "block"
    assert state(guard)["loaded_skills"] == []
    assert state(guard)["failed_skills"] == ["github"]


def test_primary_mode_requires_dependency_order_before_primary():
    guard = SkillExecutionGuard()
    start(
        guard,
        [selection("github", "supporting"), selection("pr-review", "primary")],
        mode="primary",
    )

    first_block = before(guard)
    out_of_order = load(guard, "pr-review", call_id="wrong-primary")
    load(guard, "github", call_id="dependency")
    second_block = before(guard, tool_call_id="task-2")
    load(guard, "pr-review", call_id="right-primary")
    allowed = before(guard, tool_name="write_file", tool_call_id="task-3")

    assert first_block["action"] == "block"
    assert "1. github\n2. pr-review" in first_block["message"]
    assert out_of_order["loaded_skills"] == []
    assert second_block["action"] == "block"
    assert allowed is None
    assert state(guard)["loaded_skills"] == ["github", "pr-review"]
    assert state(guard)["status"] == "satisfied"


def test_all_blocks_when_supporting_skill_after_primary_is_missing():
    guard = SkillExecutionGuard()
    start(
        guard,
        [selection("primary", "primary"), selection("security", "supporting")],
        mode="all",
    )

    load(guard, "primary")
    blocked = before(guard)

    assert blocked["action"] == "block"
    assert "skill_view security" in blocked["message"]


def test_all_allows_after_every_required_skill_loaded_in_order():
    guard = SkillExecutionGuard()
    start(
        guard,
        [selection("github", "supporting"), selection("primary", "primary"), selection("security", "supporting")],
        mode="all",
    )

    load(guard, "github", call_id="one")
    load(guard, "primary", call_id="two")
    load(guard, "security", call_id="three")

    assert before(guard) is None
    assert state(guard)["status"] == "satisfied"


def test_block_limit_exhausts_then_fails_open():
    guard = SkillExecutionGuard()
    start(guard, [selection("github", "primary")], mode="primary", blocks=2)

    first = before(guard, tool_call_id="task-1")
    second = before(guard, tool_call_id="task-2")
    third = before(guard, tool_call_id="task-3")
    fourth = before(guard, tool_call_id="task-4")

    assert first["action"] == "block"
    assert second["action"] == "block"
    assert third is None
    assert fourth is None
    assert state(guard)["block_count"] == 2
    assert state(guard)["status"] == "exhausted"
    assert state(guard)["primary_loaded_before_task_tools"] is False


def test_parallel_calls_from_one_model_response_do_not_bypass_block_limit():
    guard = SkillExecutionGuard()
    start(guard, [selection("github", "primary")], mode="primary", blocks=2)

    same_response = [
        guard.before_tool_call(
            **IDS,
            tool_name="terminal",
            args={},
            tool_call_id=f"parallel-{index}",
            api_request_id="request-1",
        )
        for index in range(3)
    ]
    second_response = guard.before_tool_call(
        **IDS,
        tool_name="terminal",
        args={},
        tool_call_id="second",
        api_request_id="request-2",
    )
    third_response = guard.before_tool_call(
        **IDS,
        tool_name="terminal",
        args={},
        tool_call_id="third",
        api_request_id="request-3",
    )

    assert all(item["action"] == "block" for item in same_response)
    assert second_response["action"] == "block"
    assert third_response is None
    assert state(guard)["block_count"] == 2
    assert state(guard)["status"] == "exhausted"


def test_policy_blocked_plan_is_not_enforced():
    guard = SkillExecutionGuard()
    initial = start(
        guard,
        [selection("broken", "primary", "broken")],
        mode="all",
        policy_status="blocked",
    )

    assert before(guard) is None
    assert initial["status"] == "policy_blocked"
    assert initial["required_skills"] == []


def test_degraded_plan_enforces_only_executable_final_skills():
    guard = SkillExecutionGuard()
    initial = start(
        guard,
        [
            selection("broken", "supporting", "broken"),
            selection("missing", "supporting", "dependency_missing"),
            selection("setup", "supporting", "setup_required"),
            selection("primary", "primary", "ready"),
            selection("disabled", "supporting", "disabled"),
        ],
        mode="all",
        policy_status="degraded",
    )

    assert initial["required_skills"] == ["setup", "primary"]


def test_skill_view_and_skills_list_are_always_allowed():
    guard = SkillExecutionGuard()
    start(guard, [selection("github", "primary")], mode="all")

    assert before(guard, tool_name="skill_view", args={"name": "another-skill"}) is None
    assert before(guard, tool_name="skills_list") is None
    assert state(guard)["block_count"] == 0


def test_new_turn_does_not_reuse_previous_turn_loads():
    guard = SkillExecutionGuard()
    start(guard, [selection("github", "primary")], mode="primary")
    load(guard, "github")
    assert before(guard) is None

    start(
        guard,
        [selection("github", "primary")],
        mode="primary",
        task_id="task-2",
        turn_id="turn-2",
    )
    blocked = before(guard, task_id="task-2", turn_id="turn-2")

    assert blocked["action"] == "block"
    assert state(guard, task_id="task-2", turn_id="turn-2")["loaded_skills"] == []


def test_foreign_session_or_subagent_identity_fails_open():
    guard = SkillExecutionGuard()
    start(guard, [selection("github", "primary")], mode="primary")

    directive = before(
        guard,
        task_id="foreign-task",
        turn_id="foreign-turn",
        session_id="foreign-session",
    )

    assert directive is None
    assert state(guard)["block_count"] == 0


def test_missing_identity_or_hook_capability_is_unavailable_and_open():
    guard = SkillExecutionGuard()
    no_identity = start(
        guard,
        [selection("github", "primary")],
        mode="primary",
        task_id="",
        turn_id="",
        session_id="",
    )
    unavailable = start(
        guard,
        [selection("github", "primary")],
        mode="primary",
        available=False,
        task_id="task-2",
        turn_id="turn-2",
    )

    assert no_identity["status"] == "unavailable"
    assert unavailable["status"] == "unavailable"
    assert before(guard, task_id="task-2", turn_id="turn-2") is None


def test_hard_mode_without_api_request_identity_fails_open():
    guard = SkillExecutionGuard()
    start(guard, [selection("github", "primary")], mode="primary")

    directive = before(guard, api_request_id="")

    assert directive is None
    assert state(guard)["status"] == "unavailable"
    assert state(guard)["block_count"] == 0


def test_guard_exception_marks_error_and_fails_open():
    guard = SkillExecutionGuard()
    start(guard, [selection("github", "primary")], mode="primary")
    internal = guard._turns[("session-1", "turn-1")]
    internal["required_skills"] = None

    directive = before(guard)

    assert directive is None
    assert state(guard)["status"] == "error"


def test_pruning_never_evicts_an_active_hard_enforcement_turn():
    guard = SkillExecutionGuard()
    for index in range(101):
        start(
            guard,
            [selection("github", "primary")],
            mode="primary",
            task_id=f"task-{index}",
            turn_id=f"turn-{index}",
        )

    directive = before(guard, task_id="task-0", turn_id="turn-0")

    assert directive["action"] == "block"


def test_guard_instances_keep_profiles_isolated():
    first = SkillExecutionGuard()
    second = SkillExecutionGuard()
    start(first, [selection("github", "primary")], mode="primary")
    start(second, [selection("github", "primary")], mode="primary")
    load(first, "github")

    assert before(first) is None
    assert before(second)["action"] == "block"
