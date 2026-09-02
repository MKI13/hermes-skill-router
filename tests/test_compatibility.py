from __future__ import annotations

from types import SimpleNamespace

from skill_router_plugin.compat import HermesCompatibility


class FullCtx:
    def __init__(self):
        self.hooks = {}

    def register_hook(self, name, callback):
        self.hooks[name] = callback

    def register_auxiliary_task(self, **kwargs):
        pass


class RejectGuardCtx(FullCtx):
    def register_hook(self, name, callback):
        if name == "pre_tool_call":
            raise ValueError("unsupported hook")
        super().register_hook(name, callback)


class RejectAuditCtx(FullCtx):
    def register_hook(self, name, callback):
        if name == "post_tool_call":
            raise ValueError("unsupported hook")
        super().register_hook(name, callback)


class EmptyCtx:
    pass


class Manager:
    def __init__(self, plugin_path=None):
        self.plugin_path = plugin_path

    def find_plugin_skill(self, name):
        return self.plugin_path


def module_loader(*, skill_utils=None, plugins=None, skills_tool=None):
    modules = {
        "agent.skill_utils": skill_utils,
        "hermes_cli.plugins": plugins,
        "tools.skills_tool": skills_tool or SimpleNamespace(),
    }

    def load(name):
        value = modules.get(name)
        if value is None:
            raise ImportError(name)
        return value

    return load


def expected_skill_utils(**overrides):
    values = {
        "get_project_skills_dirs": lambda: [],
        "get_scan_ordered_skills_dirs": lambda: [],
        "iter_project_skill_files": lambda root: [],
        "iter_skill_index_files": lambda root, filename: [],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def available_plugins(manager=None, valid_hooks=None):
    selected = manager or Manager()
    hooks = valid_hooks if valid_hooks is not None else {
        "on_session_start",
        "on_skill_lifecycle",
        "pre_llm_call",
        "pre_tool_call",
        "post_tool_call",
        "post_llm_call",
    }
    return SimpleNamespace(get_plugin_manager=lambda: selected, VALID_HOOKS=hooks)


def test_all_expected_hermes_apis_report_full_status():
    compatibility = HermesCompatibility(
        FullCtx(),
        module_loader=module_loader(
            skill_utils=expected_skill_utils(),
            plugins=available_plugins(),
        ),
    )

    capabilities = compatibility.capabilities

    assert capabilities.status == "full"
    assert capabilities.raw_skill_reader is True
    assert capabilities.plugin_skill_lookup is True
    assert capabilities.skill_lifecycle is True
    assert capabilities.auxiliary_tasks is True
    assert capabilities.skill_execution_audit is True
    assert capabilities.skill_execution_guard is True
    assert compatibility.status_lines() == [
        "Hermes compatibility: full",
        "Raw skill reader: available",
        "Plugin skill lookup: available",
        "Lifecycle support: available",
        "Auxiliary tasks: available",
        "Skill execution audit: available",
        "Skill execution guard: available",
    ]


def test_readiness_hints_normalize_passive_hermes_metadata():
    compatibility = HermesCompatibility(
        FullCtx(),
        module_loader=module_loader(
            skill_utils=expected_skill_utils(),
            plugins=available_plugins(),
        ),
    )

    hints = compatibility.readiness_hints({
        "readiness_status": "setup_needed",
        "setup_needed": True,
        "requirements": {"commands": ["git"]},
    })

    assert hints == {
        "status": "setup_required",
        "setup_needed": True,
        "requirements": {"commands": ["git"]},
    }


def test_agent_skill_utils_completely_unavailable_is_degraded():
    compatibility = HermesCompatibility(
        FullCtx(),
        module_loader=module_loader(plugins=available_plugins()),
    )

    assert compatibility.capabilities.status == "degraded"
    assert compatibility.capabilities.raw_skill_reader is False
    assert compatibility.read_visible_skill_files({"github"}, max_chars=20_000) == (
        {},
        "metadata-only",
    )


def test_get_plugin_manager_unavailable_is_degraded():
    compatibility = HermesCompatibility(
        FullCtx(),
        module_loader=module_loader(
            skill_utils=expected_skill_utils(),
            plugins=SimpleNamespace(),
        ),
    )

    assert compatibility.capabilities.status == "degraded"
    assert compatibility.capabilities.raw_skill_reader is True
    assert compatibility.capabilities.plugin_skill_lookup is False
    assert "Plugin skill lookup: unavailable" in compatibility.status_lines()


def test_single_expected_skill_utility_missing_disables_raw_reader():
    skill_utils = expected_skill_utils()
    del skill_utils.iter_project_skill_files
    compatibility = HermesCompatibility(
        FullCtx(),
        module_loader=module_loader(
            skill_utils=skill_utils,
            plugins=available_plugins(),
        ),
    )

    assert compatibility.capabilities.status == "degraded"
    assert compatibility.capabilities.raw_skill_reader is False
    assert any("iter_project_skill_files" in issue for issue in compatibility.capabilities.issues)


def test_incompatible_skill_utility_call_degrades_to_metadata_only(tmp_path):
    skill_utils = expected_skill_utils(
        get_project_skills_dirs=lambda: [tmp_path],
        get_scan_ordered_skills_dirs=lambda: [tmp_path],
        iter_project_skill_files=lambda: [],
    )
    compatibility = HermesCompatibility(
        FullCtx(),
        module_loader=module_loader(
            skill_utils=skill_utils,
            plugins=available_plugins(),
        ),
    )

    content, mode = compatibility.read_visible_skill_files({"demo"}, max_chars=20_000)

    assert content == {}
    assert mode == "metadata-only"
    assert compatibility.capabilities.raw_skill_reader is False
    assert compatibility.capabilities.status == "degraded"


def test_execution_guard_hook_forwards_sanitized_metadata_and_directive():
    ctx = FullCtx()
    compatibility = HermesCompatibility(
        ctx,
        module_loader=module_loader(
            skill_utils=expected_skill_utils(),
            plugins=available_plugins(),
        ),
    )
    calls = []

    def callback(**kwargs):
        calls.append(kwargs)
        return {"action": "block", "message": "Load a skill first."}

    registered = compatibility.register_skill_execution_guard(callback)
    directive = ctx.hooks["pre_tool_call"](
        tool_name="skill_view",
        args={"name": "github", "token": "SECRET"},
        task_id="task",
        turn_id="turn",
        session_id="session",
        tool_call_id="call",
        api_request_id="request",
    )

    assert registered is True
    assert directive == {"action": "block", "message": "Load a skill first."}
    assert calls == [{
        "tool_name": "skill_view",
        "args": {"name": "github", "loads_primary_document": True},
        "task_id": "task",
        "turn_id": "turn",
        "session_id": "session",
        "tool_call_id": "call",
        "api_request_id": "request",
    }]
    assert "SECRET" not in repr(calls)


def test_execution_guard_is_unavailable_when_hook_catalog_lacks_pre_tool_call():
    ctx = FullCtx()
    compatibility = HermesCompatibility(
        ctx,
        module_loader=module_loader(
            skill_utils=expected_skill_utils(),
            plugins=available_plugins(valid_hooks={"post_tool_call", "post_llm_call"}),
        ),
    )

    registered = compatibility.register_skill_execution_guard(lambda **kwargs: None)

    assert registered is False
    assert "pre_tool_call" not in ctx.hooks
    assert compatibility.capabilities.skill_execution_guard is False
    assert "Skill execution guard: unavailable" in compatibility.status_lines()


def test_execution_guard_registration_failure_is_feature_detected():
    ctx = RejectGuardCtx()
    compatibility = HermesCompatibility(
        ctx,
        module_loader=module_loader(
            skill_utils=expected_skill_utils(),
            plugins=available_plugins(),
        ),
    )

    registered = compatibility.register_skill_execution_guard(lambda **kwargs: None)

    assert registered is False
    assert compatibility.capabilities.skill_execution_guard is False
    assert compatibility.capabilities.status == "degraded"
    assert "Skill execution guard: unavailable" in compatibility.status_lines()
    assert any(
        "skill execution guard registration" in issue
        for issue in compatibility.capabilities.issues
    )


def test_execution_audit_hooks_forward_only_required_metadata():
    ctx = FullCtx()
    compatibility = HermesCompatibility(
        ctx,
        module_loader=module_loader(
            skill_utils=expected_skill_utils(),
            plugins=available_plugins(),
        ),
    )
    tool_calls = []
    turns = []

    registered = compatibility.register_skill_execution_audit(
        lambda **kwargs: tool_calls.append(kwargs),
        lambda **kwargs: turns.append(kwargs),
    )
    ctx.hooks["post_tool_call"](
        tool_name="skill_view",
        args={"name": "github"},
        task_id="task",
        turn_id="turn",
        session_id="session",
        status="ok",
        result="SECRET TOOL OUTPUT",
        error_message="SECRET ERROR",
    )
    ctx.hooks["post_llm_call"](
        task_id="task",
        turn_id="turn",
        session_id="session",
        user_message="SECRET PROMPT",
        assistant_response="SECRET RESPONSE",
    )

    assert registered is True
    assert tool_calls == [{
        "tool_name": "skill_view",
        "args": {"name": "github", "loads_primary_document": True},
        "task_id": "task",
        "turn_id": "turn",
        "session_id": "session",
        "tool_call_id": "",
        "status": "ok",
    }]
    assert turns == [{
        "task_id": "task",
        "turn_id": "turn",
        "session_id": "session",
    }]


def test_execution_audit_registration_failure_is_feature_detected():
    ctx = RejectAuditCtx()
    compatibility = HermesCompatibility(
        ctx,
        module_loader=module_loader(
            skill_utils=expected_skill_utils(),
            plugins=available_plugins(),
        ),
    )

    registered = compatibility.register_skill_execution_audit(lambda **kwargs: None, lambda **kwargs: None)

    assert registered is False
    assert compatibility.capabilities.skill_execution_audit is False
    assert compatibility.capabilities.status == "degraded"
    assert "Skill execution audit: unavailable" in compatibility.status_lines()
    assert any(
        "skill execution audit registration" in issue
        for issue in compatibility.capabilities.issues
    )


def test_missing_host_features_report_degraded_status():
    compatibility = HermesCompatibility(
        EmptyCtx(),
        module_loader=module_loader(
            skill_utils=expected_skill_utils(),
            plugins=available_plugins(),
        ),
    )

    capabilities = compatibility.capabilities

    assert capabilities.status == "degraded"
    assert capabilities.skill_lifecycle is False
    assert capabilities.auxiliary_tasks is False
    assert capabilities.skill_execution_audit is False
    assert capabilities.skill_execution_guard is False
    assert "Lifecycle support: unavailable" in compatibility.status_lines()
    assert "Auxiliary tasks: unavailable" in compatibility.status_lines()
    assert "Skill execution guard: unavailable" in compatibility.status_lines()


def test_full_reader_resolves_local_and_plugin_skills(tmp_path):
    root = tmp_path / "skills"
    local_file = root / "demo" / "SKILL.md"
    local_file.parent.mkdir(parents=True)
    local_file.write_text("---\nname: demo\n---\n# Demo", encoding="utf-8")
    plugin_file = tmp_path / "plugin-skill.md"
    plugin_file.write_text("# Plugin skill", encoding="utf-8")
    skill_utils = expected_skill_utils(
        get_project_skills_dirs=lambda: [root],
        get_scan_ordered_skills_dirs=lambda: [root],
        iter_project_skill_files=lambda selected_root: [local_file],
    )
    compatibility = HermesCompatibility(
        FullCtx(),
        module_loader=module_loader(
            skill_utils=skill_utils,
            plugins=available_plugins(Manager(plugin_file)),
        ),
    )

    content, mode = compatibility.read_visible_skill_files(
        {"demo", "plugin:workflow"},
        max_chars=20_000,
    )

    assert mode == "raw-path-current-hermes"
    assert content["demo"].endswith("# Demo")
    assert content["plugin:workflow"] == "# Plugin skill"
