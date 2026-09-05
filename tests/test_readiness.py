from __future__ import annotations

from skill_router_plugin.readiness import (
    BROKEN,
    DEPENDENCY_MISSING,
    READY,
    READINESS_VERSION,
    SETUP_REQUIRED,
    UNKNOWN,
    evaluate_readiness,
)


def skill_content(frontmatter: str) -> str:
    return f"---\nname: demo\ndescription: Demo skill\n{frontmatter}\n---\n# Demo\n"


def evaluate(content: str, **kwargs):
    return evaluate_readiness(
        content=content,
        visible_skill_names=kwargs.pop("visible_skill_names", {"demo"}),
        metadata_hints=kwargs.pop("metadata_hints", {}),
        get_config=kwargs.pop("get_config", lambda key, default=None: default),
        content_expected=kwargs.pop("content_expected", True),
        environment=kwargs.pop("environment", {}),
        **kwargs,
    )


def check(kind: str, name: str, available):
    state = "available" if available is True else "missing" if available is False else "unknown"
    return {"type": kind, "name": name, "available": available, "state": state}


def test_skill_without_declared_requirements_is_unknown():
    result = evaluate(skill_content(""))
    assert result["readiness_version"] == READINESS_VERSION == 2
    assert result["readiness_status"] == UNKNOWN
    assert result["setup_needed"] is False
    assert result["dependency_checks"] == []
    assert result["readiness_reasons"] == ["No readiness requirements were declared."]


def test_all_command_dependencies_available_is_ready():
    result = evaluate(
        skill_content("requirements:\n  commands: [git, gh]"),
        command_finder=lambda command: f"/usr/bin/{command}",
    )
    assert result["readiness_status"] == READY
    assert result["dependency_checks"] == [
        check("command", "git", True),
        check("command", "gh", True),
    ]
    assert result["readiness_summary"] == {
        "declared": 2, "checked": 2, "available": 2, "missing": 0, "unknown": 0, "setup": 0,
    }


def test_missing_command_is_dependency_missing_with_actionable_detail():
    result = evaluate(
        skill_content("requirements:\n  commands:\n    - git\n    - gh"),
        command_finder=lambda command: "/usr/bin/git" if command == "git" else None,
    )
    assert result["readiness_status"] == DEPENDENCY_MISSING
    assert result["setup_needed"] is False
    assert result["dependency_checks"][1] == check("command", "gh", False)
    assert result["missing_dependencies"] == [{"type": "command", "name": "gh"}]
    assert result["readiness_reasons"] == ["Missing command: gh."]


def test_python_module_dependency_is_checked_without_importing_it():
    result = evaluate(
        skill_content("requirements:\n  python_modules: [example.module]"),
        module_finder=lambda module: object() if module == "example.module" else None,
    )
    assert result["readiness_status"] == READY
    assert result["dependency_checks"] == [check("python_module", "example.module", True)]


def test_required_skill_present_is_ready():
    result = evaluate(
        skill_content("requirements:\n  skills: [github]"),
        visible_skill_names={"demo", "github"},
    )
    assert result["readiness_status"] == READY
    assert result["dependency_checks"][0]["available"] is True


def test_required_skill_missing_is_dependency_missing():
    result = evaluate(
        skill_content("requirements:\n  skills: [github]"),
        visible_skill_names={"demo"},
    )
    assert result["readiness_status"] == DEPENDENCY_MISSING
    assert result["dependency_checks"][0] == check("skill", "github", False)
    assert result["missing_dependencies"] == [{"type": "skill", "name": "github"}]


def test_mcp_requirement_is_ready_only_when_profile_server_is_enabled():
    content = skill_content("requirements:\n  mcps: [codebase-memory]")
    ready = evaluate(content, mcp_readiness={"codebase-memory": True})
    missing = evaluate(content, mcp_readiness={})
    disabled = evaluate(content, mcp_readiness={"codebase-memory": False})
    assert ready["readiness_status"] == READY
    assert ready["dependency_checks"] == [check("mcp", "codebase-memory", True)]
    assert missing["readiness_status"] == DEPENDENCY_MISSING
    assert disabled["readiness_status"] == DEPENDENCY_MISSING
    assert disabled["readiness_reasons"] == ["Missing MCP: codebase-memory."]


def test_mcp_requirement_is_unknown_when_passive_discovery_is_unavailable():
    result = evaluate(
        skill_content("requirements:\n  mcps:\n    - codebase-memory"),
        mcp_readiness=None,
    )
    assert result["readiness_status"] == UNKNOWN
    assert result["dependency_checks"] == [check("mcp", "codebase-memory", None)]
    assert result["unknown_dependencies"] == [{"type": "mcp", "name": "codebase-memory"}]
    assert result["readiness_reasons"] == ["Could not passively verify MCP: codebase-memory."]


def test_missing_declared_config_requires_setup_without_exposing_value():
    secret = "super-secret-token"
    result = evaluate(
        skill_content("requirements:\n  config: [GITHUB_TOKEN]"),
        get_config=lambda key, default=None: secret if key == "GITHUB_TOKEN" else default,
    )
    assert result["readiness_status"] == READY
    assert secret not in repr(result)
    missing = evaluate(skill_content("requirements:\n  config: [GITHUB_TOKEN]"))
    assert missing["readiness_status"] == SETUP_REQUIRED
    assert missing["setup_needed"] is True
    assert missing["setup_requirements"] == ["GITHUB_TOKEN"]
    assert missing["missing_dependencies"] == []
    assert missing["readiness_reasons"] == ["Required config is not set: GITHUB_TOKEN."]
    assert secret not in repr(missing)


def test_explicit_setup_requirement_is_setup_required():
    result = evaluate(skill_content("setup_required: true"))
    assert result["readiness_status"] == SETUP_REQUIRED
    assert result["setup_needed"] is True


def test_legacy_hermes_prerequisites_are_supported():
    result = evaluate(
        skill_content("prerequisites:\n  commands: [git]\n  env_vars: [API_TOKEN]"),
        command_finder=lambda command: "/usr/bin/git",
        environment={"API_TOKEN": "configured-secret"},
    )
    assert result["readiness_status"] == READY
    assert {item["type"] for item in result["dependency_checks"]} == {"command", "config"}
    assert "configured-secret" not in repr(result)


def test_invalid_requirement_structure_is_broken():
    result = evaluate(skill_content("requirements:\n  commands:\n    nested: invalid"))
    assert result["readiness_status"] == BROKEN
    assert result["readiness_reasons"] == ["Invalid requirements declaration."]


def test_readiness_probe_exception_fails_safe_to_unknown():
    def failing_finder(command):
        raise RuntimeError("probe failed")
    result = evaluate(
        skill_content("requirements:\n  commands: [git]"),
        command_finder=failing_finder,
    )
    assert result["readiness_status"] == UNKNOWN
    assert result["readiness_reasons"] == ["Readiness check unavailable."]


def test_passive_host_status_can_mark_ready_or_disabled():
    ready = evaluate(skill_content(""), metadata_hints={"status": "ready"})
    disabled = evaluate(skill_content(""), metadata_hints={"disabled": True})
    assert ready["readiness_status"] == READY
    assert disabled["readiness_status"] == "disabled"


def test_missing_raw_file_is_broken_only_when_content_was_expected():
    broken = evaluate("", content_expected=True)
    degraded = evaluate("", content_expected=False)
    assert broken["readiness_status"] == BROKEN
    assert degraded["readiness_status"] == UNKNOWN


def test_mixed_readiness_is_deterministic_and_bounded():
    result = evaluate(
        skill_content(
            "requirements:\n"
            "  commands: [git, missing-cli]\n"
            "  skills: [github]\n"
            "  mcps: [codebase-memory]\n"
            "  config: [TOKEN]"
        ),
        command_finder=lambda command: "/usr/bin/git" if command == "git" else None,
        visible_skill_names={"demo"},
        mcp_readiness={"codebase-memory": False},
    )
    assert result["readiness_status"] == DEPENDENCY_MISSING
    assert result["missing_dependencies"] == [
        {"type": "command", "name": "missing-cli"},
        {"type": "skill", "name": "github"},
        {"type": "mcp", "name": "codebase-memory"},
    ]
    assert result["setup_requirements"] == ["TOKEN"]
    assert result["readiness_summary"]["missing"] == 3
    assert result["readiness_summary"]["setup"] == 1
