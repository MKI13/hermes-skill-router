"""Repository regressions; these do not constitute a live Hermes-profile test."""
from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from skill_router_plugin.production import ProductionRoutingEnhancements
from skill_router_plugin.runtime import SkillRouterRuntime


class State:
    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return deepcopy(self.values.get(key, default))

    def set(self, key, value):
        self.values[key] = deepcopy(value)


class Runtime:
    def __init__(self, settings=None):
        settings = settings or {}
        self.ctx = SimpleNamespace(state=State(), get_config=lambda key, default=None: settings.get(key, default))
        self.profile = SimpleNamespace(name="isolated-fixture", scope_token="fixture-scope")
        self.embedding = SimpleNamespace(rank=lambda *args, **kwargs: {})
        self.entries = [{
            "name": "skill-router:codebase-memory",
            "readiness_status": "ready",
            "setup_needed": False,
            "requirements": {"mcps": ["codebase-memory"]},
        }]
        self._snapshot = lambda: {"catalog_hash": "fixture", "entries": self.entries}
        # Use the real normalization; a typo otherwise silently looks deterministic.
        self._routing_mode = lambda: SkillRouterRuntime._routing_mode(self)
        self.ensure_catalog = lambda *, force: False
        self.pre_llm_call = lambda **kwargs: None
        self.command = lambda args: "base"
        self._policy_result = lambda task, selected, entries, limit: {"policy_status": "valid", "selections": selected}


class Compatibility:
    capabilities = SimpleNamespace(raw_skill_reader=True, skill_lifecycle=True,
        skill_execution_guard=True, skill_execution_audit=True,
        profile_discovery=True, mcp_discovery=True)

    def active_mcp_readiness(self):
        return {"codebase-memory": True}


def enhancement(settings=None):
    return ProductionRoutingEnhancements(Runtime(settings), Compatibility())


@pytest.mark.parametrize("status", ["unknown", "setup_required", "dependency_missing", "broken", "disabled", "invalid", None])
def test_canary_never_claims_nonready_skill_is_ready(status):
    ext = enhancement()
    ext.runtime.entries[0]["readiness_status"] = status
    output = ext.canary_text()
    assert "Overall: PASS" not in output
    assert "Codebase Memory skill and MCP are ready" not in output
    assert "SKIP" in output


@pytest.mark.parametrize("status", ["unknown", "setup_required", "dependency_missing", "broken", "disabled"])
def test_rollout_never_approves_nonready_codebase_skill(status):
    ext = enhancement()
    ext.runtime.entries[0]["readiness_status"] = status
    assert "Decision: REVIEW" in ext.rollout_text()


@pytest.mark.parametrize("field", ["routing_mode", "enforcement_mode", "learning_mode"])
@pytest.mark.parametrize("value", ["unsupported-private-value", [], 123, ""])
def test_preflight_rejects_invalid_config_without_echoing_values(field, value):
    output = enhancement({field: value}).rollout_text()
    assert "Decision: BLOCKED" in output
    assert "unsupported-private-value" not in output


@pytest.mark.parametrize("field", ["openviking_enabled", "followup_context_enabled"])
@pytest.mark.parametrize("value", ["false", "true", 0, None])
def test_preflight_rejects_string_and_nonboolean_flags(field, value):
    assert "Decision: BLOCKED" in enhancement({field: value}).rollout_text()


@pytest.mark.parametrize("action", ["doctor_text", "canary_text"])
def test_diagnostics_do_not_hide_invalid_routing_mode(action):
    output = getattr(enhancement({"routing_mode": "unsupported-private-value"}), action)()
    assert "Overall: BLOCKED" in output
    assert "unsupported-private-value" not in output


@pytest.mark.parametrize("snapshot", [{}, {"entries": []}, {"catalog_hash": "fixture", "entries": "invalid"}])
def test_canary_blocks_missing_or_malformed_catalog(snapshot):
    ext = enhancement()
    ext.runtime._snapshot = lambda: snapshot
    assert "Overall: BLOCKED" in ext.canary_text()


@pytest.mark.parametrize("requirements", ["codebase-memory", ["codebase-memory"], {"mcps": "codebase-memory"}])
def test_malformed_requirements_neither_crash_nor_imply_readiness(requirements):
    ext = enhancement()
    ext.runtime.entries[0]["requirements"] = requirements
    assert "Overall: PASS" not in ext.canary_text()
    assert "Decision: READY" not in ext.rollout_text()


def test_canary_checks_final_policy_not_only_followup_selection():
    ext = enhancement()
    ext.runtime._policy_result = lambda *args: {"policy_status": "blocked", "selections": []}
    output = ext.canary_text()
    assert "Overall: BLOCKED" in output


def test_canary_can_find_ready_skill_after_unusable_candidate():
    ext = enhancement()
    broken = deepcopy(ext.runtime.entries[0])
    broken.update(name="unusable-codebase", readiness_status="broken")
    ext.runtime.entries.insert(0, broken)
    assert "Overall: PASS" in ext.canary_text()


@pytest.mark.parametrize("overrides", [{"setup_needed": True}, {"policy_metadata_complete": False}])
def test_inconsistent_ready_metadata_does_not_receive_pass(overrides):
    ext = enhancement()
    ext.runtime.entries[0].update(overrides)
    assert "Overall: PASS" not in ext.canary_text()
    assert "Decision: READY" not in ext.rollout_text()


def test_configuration_discovery_is_explicitly_not_a_live_model_or_mcp_test():
    output = enhancement().canary_text()
    assert "configuration-only" in output
    assert "not a live MCP or local-model test" in output
