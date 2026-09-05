from __future__ import annotations

from types import SimpleNamespace

from skill_router_plugin.runtime import SkillRouterRuntime


class FakeCtx:
    profile_name = "test"

    def __init__(self, snapshot):
        self._state = {"router.snapshot": snapshot}

    def get_state(self, key, default=None):
        return self._state.get(key, default)

    def set_state(self, key, value):
        self._state[key] = value

    def get_config(self, key, default=None):
        return default


class FakeCompatibility:
    def __init__(self):
        self.capabilities = SimpleNamespace(
            skill_execution_audit=True,
            skill_execution_guard=True,
        )

    def status_lines(self):
        return []


def runtime_for(entry):
    ctx = FakeCtx({"entries": [entry], "catalog_hash": "abc"})
    runtime = SkillRouterRuntime.__new__(SkillRouterRuntime)
    runtime.ctx = ctx
    runtime.compatibility = FakeCompatibility()
    runtime._lock = __import__("threading").RLock()
    return runtime


def test_inspect_readiness2_renders_grouped_diagnostics_and_router_action():
    runtime = runtime_for({
        "name": "github-development",
        "readiness_status": "dependency_missing",
        "readiness_summary": "Missing 2 dependencies; setup required for 1 config item.",
        "missing_dependencies": [
            {"type": "command", "name": "gh"},
            {"type": "mcp", "name": "codebase-memory"},
        ],
        "unknown_dependencies": [],
        "setup_requirements": [
            {"type": "config", "name": "GITHUB_TOKEN"},
        ],
        "dependency_checks": [],
        "readiness_reasons": ["One or more declared dependencies are missing."],
    })

    text = runtime.inspect_text("github-development")

    assert "Skill: github-development" in text
    assert "Readiness: dependency_missing" in text
    assert "Summary: Missing 2 dependencies; setup required for 1 config item." in text
    assert "Missing:" in text
    assert "- command: gh" in text
    assert "- mcp: codebase-memory" in text
    assert "Setup required:" in text
    assert "- config: GITHUB_TOKEN" in text
    assert "Router action:" in text
    assert "Do not select as Primary until requirements are satisfied." in text


def test_inspect_readiness2_unknown_is_explained_without_blocking_claim():
    runtime = runtime_for({
        "name": "remote-skill",
        "readiness_status": "unknown",
        "readiness_summary": "1 dependency could not be checked passively.",
        "missing_dependencies": [],
        "unknown_dependencies": [
            {"type": "mcp", "name": "remote-mcp"},
        ],
        "setup_requirements": [],
        "dependency_checks": [],
        "readiness_reasons": [],
    })

    text = runtime.inspect_text("remote-skill")

    assert "Unknown / not passively verifiable:" in text
    assert "- mcp: remote-mcp" in text
    assert "Treat as unverified; do not promote over a ready alternative." in text


def test_inspect_ready_skill_has_positive_action():
    runtime = runtime_for({
        "name": "ready-skill",
        "readiness_status": "ready",
        "readiness_summary": "All declared requirements are available.",
        "missing_dependencies": [],
        "unknown_dependencies": [],
        "setup_requirements": [],
        "dependency_checks": [],
        "readiness_reasons": [],
    })

    text = runtime.inspect_text("ready-skill")

    assert "Router action:" in text
    assert "Eligible for normal routing." in text
