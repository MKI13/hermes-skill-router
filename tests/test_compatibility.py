from __future__ import annotations

from contextvars import ContextVar
import hashlib
from types import SimpleNamespace

from skill_router_plugin.compat import (
    HermesCompatibility,
    PluginInstallSpec,
    ProfileDiscoveryError,
)


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


def module_loader(*, skill_utils=None, plugins=None, skills_tool=None, profiles=None, constants=None, plugins_cmd=None, config=None):
    modules = {
        "agent.skill_utils": skill_utils,
        "hermes_cli.plugins": plugins,
        "tools.skills_tool": skills_tool or SimpleNamespace(),
        "hermes_cli.profiles": profiles,
        "hermes_constants": constants,
        "hermes_cli.plugins_cmd": plugins_cmd,
        "hermes_cli.config": config,
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


def available_profiles():
    return SimpleNamespace(
        list_profile_names=lambda: ["default"],
        profile_exists=lambda name: name == "default",
        get_profile_dir=lambda name: "/profiles/" + name,
        validate_profile_name=lambda name: None,
    )


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
            profiles=available_profiles(),
            config=SimpleNamespace(load_config_readonly=lambda: {}),
        ),
        hermes_executable="hermes-test",
    )

    capabilities = compatibility.capabilities

    assert capabilities.status == "full"
    assert capabilities.raw_skill_reader is True
    assert capabilities.plugin_skill_lookup is True
    assert capabilities.skill_lifecycle is True
    assert capabilities.auxiliary_tasks is True
    assert capabilities.skill_execution_audit is True
    assert capabilities.skill_execution_guard is True
    assert capabilities.mcp_discovery is True
    assert compatibility.status_lines() == [
        "Hermes compatibility: full",
        "Raw skill reader: available",
        "Plugin skill lookup: available",
        "Lifecycle support: available",
        "Auxiliary tasks: available",
        "Skill execution audit: available",
        "Skill execution guard: available",
        "Profile discovery: available",
        "Profile configuration: available",
        "Native MCP config discovery: available",
    ]


def test_mcp_readiness_uses_exact_profile_config_identities_without_credentials():
    secret = "must-not-escape"
    compatibility = HermesCompatibility(
        FullCtx(),
        module_loader=module_loader(
            skill_utils=expected_skill_utils(),
            plugins=available_plugins(),
            config=SimpleNamespace(load_config_readonly=lambda: {
                "mcp_servers": {
                    "codebase-memory": {"command": "memory", "env": {"TOKEN": secret}},
                    "disabled-server": {"url": "https://example.invalid", "enabled": "off"},
                    "integer-disabled": {"command": "disabled", "enabled": 0},
                    "invalid-server": {"enabled": True},
                    "preset-only": {"preset": "github", "enabled": True},
                },
            }),
        ),
    )

    readiness = compatibility.active_mcp_readiness()

    assert readiness == {
        "codebase-memory": True,
        "disabled-server": False,
        "integer-disabled": False,
        "invalid-server": None,
        "preset-only": None,
    }
    assert secret not in repr(readiness)


def test_mcp_readiness_fails_unknown_when_config_api_or_config_is_unavailable():
    unavailable = HermesCompatibility(
        FullCtx(),
        module_loader=module_loader(
            skill_utils=expected_skill_utils(),
            plugins=available_plugins(),
        ),
    )
    failing = HermesCompatibility(
        FullCtx(),
        module_loader=module_loader(
            skill_utils=expected_skill_utils(),
            plugins=available_plugins(),
            config=SimpleNamespace(load_config_readonly=lambda: (_ for _ in ()).throw(OSError())),
        ),
    )

    assert unavailable.active_mcp_readiness() is None
    assert unavailable.capabilities.mcp_discovery is False
    assert failing.active_mcp_readiness() is None
    assert failing.capabilities.mcp_discovery is True


def test_mcp_readiness_is_reloaded_from_each_active_profile_context():
    active_profile = ContextVar("active_mcp_profile", default="profile-a")
    configs = {
        "profile-a": {"mcp_servers": {"codebase-memory": {"command": "memory"}}},
        "profile-b": {"mcp_servers": {}},
    }
    compatibility = HermesCompatibility(
        FullCtx(),
        module_loader=module_loader(
            skill_utils=expected_skill_utils(),
            plugins=available_plugins(),
            config=SimpleNamespace(
                load_config_readonly=lambda: configs[active_profile.get()]
            ),
        ),
    )

    assert compatibility.active_mcp_readiness() == {"codebase-memory": True}
    token = active_profile.set("profile-b")
    try:
        assert compatibility.active_mcp_readiness() == {}
    finally:
        active_profile.reset(token)
    assert compatibility.active_mcp_readiness() == {"codebase-memory": True}


def test_mcp_readiness_recovers_after_transient_config_read_failure():
    calls = {"count": 0}

    def read_config():
        calls["count"] += 1
        if calls["count"] == 1:
            raise OSError()
        return {"mcp_servers": {"memory": {"command": "memory"}}}

    compatibility = HermesCompatibility(
        FullCtx(),
        module_loader=module_loader(
            skill_utils=expected_skill_utils(),
            plugins=available_plugins(),
            config=SimpleNamespace(load_config_readonly=read_config),
        ),
    )

    assert compatibility.active_mcp_readiness() is None
    assert compatibility.active_mcp_readiness() == {"memory": True}


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


def test_custom_home_scope_hashes_the_active_home_not_a_synthetic_profile(tmp_path):
    custom_home = tmp_path / "deployment"
    ctx = FullCtx()
    ctx.profile_name = "custom"
    profiles = available_profiles()
    profiles.get_profile_dir = lambda name: (_ for _ in ()).throw(AssertionError(name))
    compatibility = HermesCompatibility(
        ctx,
        module_loader=module_loader(
            skill_utils=expected_skill_utils(),
            plugins=available_plugins(),
            profiles=profiles,
            constants=SimpleNamespace(get_hermes_home=lambda: custom_home),
        ),
        hermes_executable="hermes-test",
    )

    expected = hashlib.sha256(str(custom_home.resolve()).encode()).hexdigest()

    assert compatibility.profile_scope_id() == f"home-v1:{expected}"


def test_profile_discovery_fails_closed_when_one_profile_cannot_be_resolved(tmp_path):
    def profile_dir(name):
        if name == "broken":
            raise OSError("unreadable")
        return tmp_path / name

    profiles = SimpleNamespace(
        list_profile_names=lambda: ["beta", "alpha", "broken", "alpha"],
        profile_exists=lambda name: True,
        get_profile_dir=profile_dir,
        validate_profile_name=lambda name: None,
    )
    compatibility = HermesCompatibility(
        FullCtx(),
        module_loader=module_loader(
            skill_utils=expected_skill_utils(),
            plugins=available_plugins(),
            profiles=profiles,
        ),
        hermes_executable="hermes-test",
    )

    try:
        compatibility.discover_profiles()
    except ProfileDiscoveryError:
        pass
    else:
        raise AssertionError("profile discovery should fail closed")

    assert compatibility.capabilities.profile_discovery is False
    assert compatibility.capabilities.profile_configuration is False
    assert any("profile broken" in issue for issue in compatibility.capabilities.issues)


def test_profile_discovery_returns_sorted_name_only_records(tmp_path):
    profiles = SimpleNamespace(
        list_profile_names=lambda: ["beta", "alpha", "alpha"],
        profile_exists=lambda name: True,
        get_profile_dir=lambda name: tmp_path / name,
        validate_profile_name=lambda name: None,
    )
    compatibility = HermesCompatibility(
        FullCtx(),
        module_loader=module_loader(
            skill_utils=expected_skill_utils(),
            plugins=available_plugins(),
            profiles=profiles,
        ),
        hermes_executable="hermes-test",
    )

    discovered = compatibility.discover_profiles()

    assert [profile.name for profile in discovered] == ["alpha", "beta"]
    assert all(not hasattr(profile, "path") for profile in discovered)


def test_missing_profile_api_reports_clean_degraded_capabilities():
    compatibility = HermesCompatibility(
        FullCtx(),
        module_loader=module_loader(
            skill_utils=expected_skill_utils(),
            plugins=available_plugins(),
        ),
    )

    assert compatibility.capabilities.profile_discovery is False
    assert compatibility.capabilities.profile_configuration is False
    assert "Profile discovery: degraded" in compatibility.status_lines()
    assert "Profile configuration: degraded" in compatibility.status_lines()
    assert compatibility.discover_profiles() == []


def test_profile_inspection_uses_only_public_hermes_cli_metadata():
    calls = []

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        tail = argv[3:]
        if tail[:2] == ["plugins", "list"]:
            stdout = '[{"name":"skill-router","status":"enabled","version":"0.4.0","source":"git"}]'
        elif tail[:2] == ["config", "get"]:
            stdout = "deterministic\n" if tail[-1].endswith("routing_mode") else ""
            if not stdout:
                return SimpleNamespace(returncode=1, stdout="", stderr="SECRET")
        elif tail == ["skill-router", "status"]:
            stdout = (
                "Indexed skills: 7\nRouting mode: deterministic\n"
                "Enforcement mode: warn\nLearning: shadow\n"
                "OpenViking enabled/synced: False / 0\n"
            )
        else:
            raise AssertionError(tail)
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="SECRET")

    compatibility = HermesCompatibility(
        FullCtx(),
        module_loader=module_loader(
            skill_utils=expected_skill_utils(),
            plugins=available_plugins(),
            profiles=available_profiles(),
        ),
        command_runner=runner,
        hermes_executable="hermes-test",
    )

    inspection = compatibility.inspect_profile("default")

    assert inspection.installed is True
    assert inspection.enabled is True
    assert inspection.version == "0.4.0"
    assert inspection.skill_count == 7
    assert inspection.routing_mode == "deterministic"
    assert inspection.enforcement_mode == "warn"
    assert inspection.learning_mode == "shadow"
    assert inspection.openviking_enabled is False
    assert inspection.setting("routing_mode") == "deterministic"
    assert inspection.setting("learning_mode") is None
    assert all(call[0][:3] == ["hermes-test", "--profile", "default"] for call in calls)
    assert "SECRET" not in repr(inspection)


def test_install_spec_accepts_local_source_and_rejects_credentialed_url(tmp_path):
    revision = "0123456789abcdef0123456789abcdef01234567"
    metadata = {"skill-router": {"source": tmp_path.as_uri(), "revision": revision}}
    compatibility = HermesCompatibility(
        FullCtx(),
        module_loader=module_loader(
            skill_utils=expected_skill_utils(),
            plugins=available_plugins(),
            profiles=available_profiles(),
            plugins_cmd=SimpleNamespace(_read_install_metadata=lambda: metadata),
        ),
        hermes_executable="hermes-test",
    )

    assert compatibility.current_plugin_install_spec() == PluginInstallSpec(tmp_path.as_uri(), revision)

    metadata["skill-router"]["source"] = "https://user:SECRET@github.com/MKI13/hermes-skill-router.git"
    spec = compatibility.current_plugin_install_spec()

    assert spec.source == ""
    assert "SECRET" not in repr(spec)


def test_not_enabled_plugin_is_installed_and_intentionally_inactive():
    def runner(argv, **kwargs):
        tail = argv[3:]
        if tail[:2] == ["plugins", "list"]:
            return SimpleNamespace(
                returncode=0,
                stdout='[{"name":"skill-router","status":"not enabled","version":"0.4.0"}]',
            )
        if tail[:2] == ["config", "get"]:
            return SimpleNamespace(returncode=1, stdout="")
        raise AssertionError(tail)

    compatibility = HermesCompatibility(
        FullCtx(),
        module_loader=module_loader(
            skill_utils=expected_skill_utils(),
            plugins=available_plugins(),
            profiles=available_profiles(),
        ),
        command_runner=runner,
        hermes_executable="hermes-test",
    )

    inspection = compatibility.inspect_profile("default")

    assert inspection.installed is True
    assert inspection.enabled is False
    assert inspection.version == "0.4.0"


def test_legacy_plugin_config_counts_as_explicit_when_canonical_key_is_absent():
    calls = []

    def runner(argv, **kwargs):
        tail = argv[3:]
        calls.append(tail)
        if tail[:2] == ["plugins", "list"]:
            return SimpleNamespace(
                returncode=0,
                stdout='[{"name":"skill-router","status":"not enabled","version":"0.3.0"}]',
            )
        if tail[:2] == ["config", "get"]:
            key = tail[-1]
            if key.endswith("config.routing_mode"):
                return SimpleNamespace(returncode=0, stdout="model\n")
            return SimpleNamespace(returncode=1, stdout="")
        raise AssertionError(tail)

    compatibility = HermesCompatibility(
        FullCtx(),
        module_loader=module_loader(
            skill_utils=expected_skill_utils(),
            plugins=available_plugins(),
            profiles=available_profiles(),
        ),
        command_runner=runner,
        hermes_executable="hermes-test",
    )

    inspection = compatibility.inspect_profile("default")

    assert inspection.setting("routing_mode") == "model"
    canonical = "plugins.entries.skill-router.settings.routing_mode"
    legacy = "plugins.entries.skill-router.config.routing_mode"
    assert ["config", "get", canonical] in calls
    assert ["config", "get", legacy] in calls
