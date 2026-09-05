from __future__ import annotations

from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from skill_router_plugin import policy as policy_module
from skill_router_plugin import runtime as runtime_module
from skill_router_plugin.audit import SkillExecutionAudit
from skill_router_plugin.policy import apply_routing_policy
from skill_router_plugin.production import ProductionRoutingEnhancements
from skill_router_plugin.profile_identity import ProfileIdentity
from skill_router_plugin.quality import safe_evaluate_quality
from skill_router_plugin.runtime import SkillRouterRuntime
from skill_router_plugin.telemetry import routing_telemetry, summarize_routing_telemetry


class State:
    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return deepcopy(self.values.get(key, default))

    def set(self, key, value):
        self.values[key] = deepcopy(value)


class Context:
    def __init__(self, profile="telemetry-test", **settings):
        self.profile_name = profile
        self.state = State()
        self.settings = {"openviking_enabled": False, "learning_mode": "shadow", **settings}

    def get_config(self, key, default=None):
        return self.settings.get(key, default)


class Compatibility:
    capabilities = SimpleNamespace(skill_execution_audit=True, skill_execution_guard=True)

    def status_lines(self):
        return []


def catalog():
    common = {
        "description": "", "use_when": [], "avoid_when": [],
        "works_with": [], "alternatives": [], "setup_needed": False,
        "requirements": {"commands": [], "python_modules": [], "skills": [], "config": []},
    }
    words = "alpha bravo charlie delta echo foxtrot".split()
    return [
        {**deepcopy(common), "name": "unverified", "readiness_status": "unknown", "keywords": words},
        {**deepcopy(common), "name": "verified", "readiness_status": "ready", "keywords": words[:-1]},
    ]


def selection():
    return [
        {"name": "unverified", "role": "primary", "reason": "test fixture", "order": 1},
        {"name": "verified", "role": "supporting", "reason": "test fixture", "order": 2},
    ]


def policy(*, entries=None, selected=None, explicit=None, limit=5):
    return apply_routing_policy(
        task="alpha bravo charlie delta echo foxtrot",
        selected_skills=selection() if selected is None else selected,
        catalog_entries=catalog() if entries is None else entries,
        max_skills=limit, explicit_skill_names=explicit or [],
    )


def record(audit, result, *, session="session-a", turn="turn-a", telemetry=True):
    audit.record_decision(
        task="private request text not to be retained",
        task_id="task-" + turn, turn_id=turn, session_id=session,
        method="model", recommended=result["selections"],
        policy_status=result["policy_status"], execution_observable=True,
        telemetry=result["telemetry"] if telemetry else None,
    )


def runtime(monkeypatch, profile="telemetry-test"):
    instance = SkillRouterRuntime(Context(profile, routing_mode="model"), Compatibility())
    instance._save_snapshot({"catalog_hash": "test-catalog", "entries": catalog()})
    monkeypatch.setattr(instance, "ensure_catalog", lambda **kwargs: False)
    monkeypatch.setattr(runtime_module, "select_skills", lambda *args, **kwargs: (selection(), "model"))
    return instance


def test_policy_attaches_actual_confidence_and_primary_fallback():
    result = policy()
    data = result["telemetry"]
    assert data["original_primary"] == "unverified"
    assert data["final_primary"] == "verified"
    assert data["confidence"] in {"medium", "high"}
    assert data["fallback_applied"] is True
    assert data["fallback_reason"] == "ready_within_margin"
    assert not any("telemetry" in item for item in result["selections"])


def test_explicit_override_is_not_counted_as_automatic_fallback():
    result = policy(explicit=["verified"])
    assert result["telemetry"]["original_primary"] == "unverified"
    assert result["telemetry"]["final_primary"] == "verified"
    assert result["telemetry"]["fallback_applied"] is False
    assert result["telemetry"]["confidence"] == "not_assessed"


def test_unknown_with_clear_relevance_lead_is_retained():
    entries = catalog()
    entries[1]["keywords"] = []
    result = policy(entries=entries)
    assert result["telemetry"]["final_primary"] == "unverified"
    assert result["telemetry"]["fallback_applied"] is False


def test_block_after_intermediate_decision_does_not_claim_final_fallback():
    entries = catalog()
    entries[1]["requirements"]["skills"] = ["helper"]
    helper = {**deepcopy(entries[1]), "name": "helper", "requirements": {"skills": []}}
    result = policy(entries=entries + [helper], limit=1)
    assert result["policy_status"] == "blocked"
    assert result["telemetry"]["final_primary"] == ""
    assert result["telemetry"]["confidence"] == "none"
    assert result["telemetry"]["fallback_applied"] is False


@pytest.mark.parametrize("status", ["broken", "disabled", "dependency_missing"])
def test_blocked_skill_has_no_executable_final_primary(status):
    entry = catalog()[0]
    entry["readiness_status"] = status
    result = policy(entries=[entry], selected=selection()[:1])
    assert result["selections"] == []
    assert result["telemetry"]["original_primary"] == "unverified"
    assert result["telemetry"]["confidence"] == "none"
    assert result["telemetry"]["final_primary"] == ""


def test_no_match_and_invented_name_do_not_create_primary_metadata():
    no_match = policy(selected=[])
    assert no_match["telemetry"] == routing_telemetry(confidence="none")
    invented = policy(selected=[{"name": "invented", "role": "primary"}])
    assert invented["telemetry"] == routing_telemetry(confidence="none")


def test_telemetry_failure_does_not_change_routing(monkeypatch):
    expected = policy()
    monkeypatch.setattr(policy_module, "policy_telemetry", lambda *args: (_ for _ in ()).throw(ValueError()))
    result = policy()
    assert result["selections"] == expected["selections"]
    assert result["policy_status"] == expected["policy_status"]
    assert result["telemetry"] == routing_telemetry()


def test_runtime_passes_policy_metadata_directly_to_persisted_audit(monkeypatch):
    instance = runtime(monkeypatch)
    text = instance.pre_llm_call(
        user_message="alpha bravo charlie delta echo foxtrot", task_id="task-a",
        turn_id="turn-a", session_id="session-a",
    )
    assert "PRIMARY: verified" in text
    history = instance.audit.history()
    assert len(history) == 1
    assert history[0]["routing_telemetry"] == policy()["telemetry"]
    assert history[0]["primary_loaded"] is None
    assert history[0]["result"] == "unknown"


def test_registered_production_wrapper_preserves_telemetry_pipeline(monkeypatch):
    instance = runtime(monkeypatch)
    enhancements = ProductionRoutingEnhancements(instance, instance.compatibility)
    enhancements.install()
    instance.pre_llm_call(
        user_message="alpha bravo charlie delta echo foxtrot", task_id="task-a",
        turn_id="turn-a", session_id="session-a",
    )
    assert instance.audit.history()[-1]["routing_telemetry"] == policy()["telemetry"]


def test_recommend_diagnostics_do_not_create_audit_decisions(monkeypatch):
    instance = runtime(monkeypatch)
    before = instance.audit.history()
    text = instance.command("recommend alpha bravo charlie delta echo foxtrot")
    assert "Original primary: unverified" in text
    assert "Final primary: verified" in text
    assert "Fallback reason: ready_within_margin" in text
    assert instance.audit.history() == before


def test_audit_roundtrip_and_turn_finalization_preserve_metadata():
    context = Context()
    audit = SkillExecutionAudit(context)
    result = policy()
    record(audit, result)
    context.state.values = json.loads(json.dumps(context.state.values))
    restored = SkillExecutionAudit(context)
    restored.finalize_turn(task_id="task-turn-a", turn_id="turn-a", session_id="session-a")
    entry = restored.history()[-1]
    assert entry["routing_telemetry"] == result["telemetry"]
    assert entry["result"] == "missed"
    assert entry["primary_loaded"] is False
    assert "private request text not to be retained" not in json.dumps(context.state.values)
    without = {key: value for key, value in entry.items() if key != "routing_telemetry"}
    assert safe_evaluate_quality(entry) == safe_evaluate_quality(without)


def test_session_decisions_are_not_mixed():
    audit = SkillExecutionAudit(Context())
    first = policy()
    second = policy(explicit=["unverified"])
    record(audit, first, session="session-a", turn="turn-a")
    record(audit, second, session="session-b", turn="turn-b")
    audit.finalize_turn(task_id="task-turn-a", turn_id="turn-a", session_id="session-a")
    entries = audit.history()
    assert entries[0]["routing_telemetry"] == first["telemetry"]
    assert entries[1]["routing_telemetry"] == second["telemetry"]
    assert entries[1]["finalized"] is False


def test_foreign_profile_cannot_read_the_telemetry():
    context = Context()
    owner = SkillExecutionAudit(context, ProfileIdentity(name="a", scope_token="scope-a"))
    record(owner, policy())
    foreign = SkillExecutionAudit(context, ProfileIdentity(name="b", scope_token="scope-b"))
    assert foreign.history() == []
    assert "Observed: 0" in foreign.telemetry_summary_text()


def test_legacy_audit_remains_unassessed_after_another_save():
    context = Context()
    audit = SkillExecutionAudit(context)
    record(audit, policy(), telemetry=False)
    stored = context.state.values["router.audit"]["entries"][0]
    stored.pop("routing_telemetry", None)
    record(audit, policy(), turn="turn-b")
    legacy = SkillExecutionAudit(context).history()[0]
    assert legacy["routing_telemetry"] == routing_telemetry()
    report = summarize_routing_telemetry(audit.history())
    assert report["observed"] == 1
    assert report["unobserved"] == 1


def test_audit_history_limit_also_bounds_telemetry():
    context = Context(max_audit_entries=10)
    audit = SkillExecutionAudit(context)
    for index in range(14):
        record(audit, policy(), turn=f"turn-{index}")
    assert len(audit.history()) == 10
    assert summarize_routing_telemetry(audit.history())["observed"] == 10


def test_audit_and_quality_telemetry_rendering_are_read_only():
    context = Context()
    audit = SkillExecutionAudit(context)
    record(audit, policy())
    before = deepcopy(context.state.values)
    assert "Fallback applied: yes" in audit.last_text()
    assert "Routing decision telemetry" in audit.summary_text()
    assert "Routing decision telemetry" in audit.quality_summary_text()
    assert "Confidence:" in audit.quality_last_text()
    assert context.state.values == before


def test_shadow_diagnostics_expose_observations_without_changing_weights(monkeypatch):
    instance = runtime(monkeypatch)
    instance.pre_llm_call(
        user_message="alpha bravo charlie delta echo foxtrot", task_id="task-a",
        turn_id="turn-a", session_id="session-a",
    )
    before = deepcopy(instance.ctx.state.values)
    text = instance.command("learning")
    assert "Routing decision telemetry" in text
    assert "Observational only" in text
    assert instance.ctx.state.values == before
