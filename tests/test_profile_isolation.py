from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

from skill_router_plugin.audit import SkillExecutionAudit
from skill_router_plugin.learning import ShadowLearning
from skill_router_plugin.profile_identity import ProfileIdentity
from skill_router_plugin.runtime import SkillRouterRuntime
from skill_router_plugin import runtime as runtime_module


class State:
    quota_bytes = 10 * 1024 * 1024

    def __init__(self, values=None):
        self.values = deepcopy(values or {})

    def get(self, key, default=None):
        return deepcopy(self.values.get(key, default))

    def set(self, key, value):
        self.values[key] = deepcopy(value)


class Ctx:
    def __init__(self, name, state=None):
        self.profile_name = name
        self.state = state or State()

    def get_config(self, key, default=None):
        return default


class Compatibility:
    def __init__(self, scope):
        self.scope = scope

    def profile_scope_id(self):
        return self.scope

    @property
    def capabilities(self):
        return SimpleNamespace(skill_execution_audit=True, skill_execution_guard=True)

    def status_lines(self):
        return []


def _catalog(name):
    return {
        "catalog_hash": f"catalog-{name}",
        "reader_mode": "test",
        "skills": [{
            "name": name,
            "description": name,
            "category": "test",
            "content_hash": f"hash-{name}",
            "readiness_hash": f"ready-{name}",
            "readiness_status": "ready",
            "setup_needed": False,
            "requirements": {"skills": []},
            "dependency_checks": [],
            "readiness_reasons": [],
        }],
    }


def _audit_entry(profile):
    return {
        "task_id": "task",
        "turn_id": "turn",
        "session_id": "session",
        "timestamp": "2026-01-01T00:00:00+00:00",
        "profile": profile,
        "method": "deterministic",
        "policy_status": "valid",
        "recommended": [],
        "executions": [],
        "result": "not_applicable",
        "execution_observable": True,
        "finalized": True,
    }


def test_copied_scoped_state_is_rejected_before_openviking_reconciliation(monkeypatch):
    source_ctx = Ctx("alpha")
    source = SkillRouterRuntime(source_ctx, Compatibility("home-v1:alpha"))
    source._save_snapshot({
        "entries": [],
        "catalog_hash": "source",
        "openviking_owned_names": ["source-owned"],
    })
    source.audit.record_decision(
        task="hello",
        task_id="task",
        turn_id="turn",
        session_id="session",
        method="deterministic",
        recommended=[],
        execution_observable=True,
    )
    source.learning.rebuild(source.audit.history, 5)

    target_ctx = Ctx("beta", State(source_ctx.state.values))
    target = SkillRouterRuntime(target_ctx, Compatibility("home-v1:beta"))

    assert target._snapshot() == {}
    assert target.audit.history() == []
    assert target.learning.state(5)["usable_quality_records"] == 0

    monkeypatch.setattr(runtime_module, "scan_catalog", lambda ctx, compat: _catalog("beta-only"))
    observed = []
    monkeypatch.setattr(
        target.openviking,
        "sync_skills",
        lambda records, entries, previous_owned, should_stop: observed.append(previous_owned)
        or {"enabled": False, "synced": 0, "deleted": 0, "failed": [], "owned_names": []},
    )
    monkeypatch.setattr(target.openviking, "write_plan", lambda plan: False)

    target.deep_refresh("scope-test")

    assert observed == [set()]
    assert [entry["name"] for entry in target._snapshot()["entries"]] == ["beta-only"]


def test_legacy_named_audits_require_every_entry_to_match_explicitly():
    ctx = Ctx("beta", State({
        "router.audit": {
            "version": 1,
            "entries": [_audit_entry("alpha"), _audit_entry("beta"), {**_audit_entry("beta"), "profile": None}],
        }
    }))
    audit = SkillExecutionAudit(ctx, ProfileIdentity("beta", "home-v1:beta"))

    history = audit.history()

    assert history == []


def test_legacy_learning_is_rebuilt_only_from_attributable_audits():
    ctx = Ctx("beta", State({
        "router.audit": {"version": 1, "entries": [_audit_entry("beta")]},
        "router.learning": {"learning_version": 1, "usable_quality_records": 999},
    }))
    profile = ProfileIdentity("beta", "home-v1:beta")
    audit = SkillExecutionAudit(ctx, profile)
    learning = ShadowLearning(ctx, profile)

    assert learning.state(5)["usable_quality_records"] == 0
    rebuilt = learning.rebuild(audit.history, 5)

    assert rebuilt["usable_quality_records"] == 0
    assert ctx.state.values["router.learning"]["profile_scope"] == "home-v1:beta"


def test_legacy_custom_profile_state_fails_closed():
    ctx = Ctx("custom", State({
        "router.snapshot": {"profile": "custom", "entries": [{"name": "foreign"}]},
        "router.audit": {"version": 1, "entries": [_audit_entry("custom")]},
        "router.learning": {"learning_version": 1, "usable_quality_records": 9},
    }))
    runtime = SkillRouterRuntime(ctx, Compatibility("home-v1:custom-b"))

    assert runtime._snapshot() == {}
    assert runtime.audit.history() == []
    assert runtime.learning.state(5)["usable_quality_records"] == 0


def test_same_profile_name_with_different_home_scope_rejects_v04_state():
    ctx = Ctx("alpha")
    source = SkillRouterRuntime(ctx, Compatibility("home-v1:first"))
    source._save_snapshot({"entries": [{"name": "alpha-only"}]})
    copied = Ctx("alpha", State(ctx.state.values))
    target = SkillRouterRuntime(copied, Compatibility("home-v1:second"))

    assert target._snapshot() == {}
