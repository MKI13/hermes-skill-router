"""Repository reproductions of live failures; not a live-model acceptance test."""
from __future__ import annotations

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

from skill_router_plugin import planner, production, runtime as runtime_module
from skill_router_plugin.catalog import is_negated_name
from skill_router_plugin.policy import apply_routing_policy, detect_explicit_skill_names
from skill_router_plugin.production import ProductionRoutingEnhancements, install_production_enhancements
from skill_router_plugin.runtime import SkillRouterRuntime
from test_routing_telemetry_pipeline import Context, Compatibility


def entry(name="pdf", status="unknown", **extra):
    return {
        "name": name, "description": "", "category": "documents",
        "keywords": [], "use_when": [], "avoid_when": [], "alternatives": [],
        "readiness_status": status, "setup_needed": status == "setup_required",
        "requirements": {"skills": []}, "policy_metadata_complete": True,
        **extra,
    }


def selected(name, role="primary"):
    return {"name": name, "role": role, "order": 1, "reason": "fixture"}


def policy(task, entries, selections, explicit=()):
    return apply_routing_policy(task=task, catalog_entries=entries,
        selected_skills=selections, explicit_skill_names=list(explicit), max_skills=5)


def make_runtime(monkeypatch, *, context=None, entries=None):
    ctx = context or Context("live-regression", routing_mode="deterministic")
    compat = Compatibility()
    instance = SkillRouterRuntime(ctx, compat)
    instance._save_snapshot({"catalog_hash": "fixture-catalog", "entries": entries or [entry()]})
    monkeypatch.setattr(instance, "ensure_catalog", lambda **kwargs: False)
    monkeypatch.setattr(instance, "request_deep_refresh", lambda *args: False)
    monkeypatch.setattr(runtime_module, "select_skills", planner.select_skills)
    monkeypatch.setattr(production, "_ORIGINAL_SELECT", None)
    ext = install_production_enhancements(instance, compat)
    return instance, ext


def turn(instance, message, session="session-a", number=1):
    return instance.pre_llm_call(user_message=message, session_id=session,
        task_id=f"{session}-task-{number}", turn_id=f"{session}-turn-{number}")


def test_real_runtime_unknown_skill_followup_uses_exact_name(monkeypatch):
    instance, ext = make_runtime(monkeypatch)
    first = turn(instance, "Nutze pdf.")
    assert "readiness-unknown" in first
    key = ext._session_key("session-a")
    state = instance.ctx.state.get("router.followup_context.v1")
    assert state["sessions"][key]["previous_primary_skill"] == "pdf"
    second = turn(instance, "Mach weiter.", number=2)
    assert "method=session-followup" in second
    assert instance.audit.history()[-1]["recommended"][0]["name"] == "pdf"


def test_followup_survives_runtime_reload_and_is_session_scoped(monkeypatch):
    instance, _ = make_runtime(monkeypatch)
    turn(instance, "Nutze pdf.")
    reloaded, _ = make_runtime(monkeypatch, context=instance.ctx)
    other = turn(reloaded, "Mach weiter.", session="session-b")
    assert "method=session-followup" not in other
    own = turn(reloaded, "Mach weiter.", number=2)
    assert "method=session-followup" in own


def test_persisted_context_comes_from_policy_not_formatted_text(monkeypatch):
    instance, ext = make_runtime(monkeypatch)
    def fake_pre(**kwargs):
        instance._policy_result("pdf", [selected("pdf")], [entry()], 5)
        return "[Skill Router policy=valid]\n1. PRIMARY: fabricated-skill [ready]\n[/Skill Router]"
    ext._pre = fake_pre
    turn(instance, "A private request.")
    raw = instance.ctx.state.get("router.followup_context.v1")
    assert raw["sessions"][ext._session_key("session-a")]["previous_primary_skill"] == "pdf"
    assert "fabricated-skill" not in repr(raw)
    assert "A private request" not in repr(raw)


def test_fabricated_display_without_policy_cannot_seed_context(monkeypatch):
    instance, ext = make_runtime(monkeypatch)
    ext._pre = lambda **kwargs: "[Skill Router policy=valid]\n1. PRIMARY: pdf\n[/Skill Router]"
    turn(instance, "private fixture")
    assert ext._context(ext._session_key("session-a")) is None


def test_blocked_turn_clears_previous_context(monkeypatch):
    instance, ext = make_runtime(monkeypatch)
    turn(instance, "Nutze pdf.")
    instance._save_snapshot({"catalog_hash": "changed", "entries": [entry(status="disabled")]})
    turn(instance, "Nutze pdf.", number=2)
    assert ext._context(ext._session_key("session-a")) is None


def test_legacy_suffix_corruption_is_not_interpreted_as_a_skill(monkeypatch):
    instance, ext = make_runtime(monkeypatch)
    instance.ctx.state.set("router.followup_context.v1", {
        "version": 1, "profile_scope": instance.profile.scope_token,
        "sessions": {ext._session_key("session-a"): {
            "previous_primary_skill": "pdf readiness-unknown", "previous_policy_status": "valid"}},
    })
    assert ext._context(ext._session_key("session-a")) is None
    assert "method=session-followup" not in turn(instance, "Mach weiter.")


@pytest.mark.parametrize("task", [
    "Verwende den Skill arxiv dafür nicht.", "Benutze arxiv dafür nicht.",
    "Nutze arxiv nicht.", "Verwende arxiv nicht.",
    "Bitte arxiv nicht verwenden.", "Use pdf, not arxiv.",
    "Nutze arxiv auf keinen Fall.", "Verwende skill-router:codebase-memory nicht.",
])
def test_exclusion_wins_over_an_explicit_name(task):
    name = "skill-router:codebase-memory" if "codebase-memory" in task else "arxiv"
    assert is_negated_name(task, name)
    assert name not in detect_explicit_skill_names(task, [entry(name)])


@pytest.mark.parametrize("task", [
    "Nutze pdf, nicht arxiv.", "Nutze pdf und verwende arxiv nicht.",
    "Nutze arxiv nicht, sondern pdf.", "Nutze arxiv nicht und stattdessen pdf.",
    "Nutze pdf. arxiv bitte nicht.", "Nutze pdf; arxiv nicht.",
    "Nutze pdf nicht nur zum Lesen.", "Nutze nicht nur pdf, sondern auch arxiv.",
    "Use pdf not arxiv.",
])
def test_negation_does_not_spill_into_the_positive_pdf_clause(task):
    assert not is_negated_name(task, "pdf")
    assert "pdf" in detect_explicit_skill_names(task, [entry("pdf"), entry("arxiv")])


@pytest.mark.parametrize("explicit", [(), ("arxiv",)])
def test_policy_removes_negated_model_or_embedding_selection(explicit):
    result = policy("Verwende arxiv nicht.", [entry("arxiv", "ready")], [selected("arxiv")], explicit)
    assert result["selections"] == []
    assert result["telemetry"]["final_primary"] == ""
    assert result["telemetry"]["fallback_applied"] is False


def test_negated_dependency_cannot_be_reintroduced_by_expansion():
    entries = [entry("paper-review", "ready", requirements={"skills": ["arxiv"]}), entry("arxiv", "ready")]
    result = policy("Nutze paper-review, aber arxiv nicht.", entries, [selected("paper-review")], ("paper-review",))
    assert result["selections"] == []
    assert result["policy_status"] == "blocked"


@pytest.mark.parametrize("status", ["dependency_missing", "setup_required"])
@pytest.mark.parametrize("explicit", [False, True])
def test_unavailable_root_is_not_an_executable_primary(status, explicit):
    result = policy("Nutze box.", [entry("box", status)], [selected("box")], ("box",) if explicit else ())
    assert result["selections"] == []
    assert result["policy_status"] == "blocked"
    assert result["telemetry"]["final_primary"] == ""
    assert result["telemetry"]["fallback_applied"] is False


def test_explicit_missing_skill_is_not_silently_replaced():
    entries = [entry("box", "dependency_missing"), entry("ready-alternative", "ready")]
    result = policy("Nutze box.", entries, [selected("box"), selected("ready-alternative", "supporting")], ("box",))
    assert result["selections"] == []
    assert result["policy_status"] == "blocked"


def test_automatic_unavailable_candidate_does_not_block_usable_candidate():
    entries = [entry("box", "dependency_missing"), entry("ready-alternative", "ready")]
    result = policy("Handle the task.", entries, [selected("box"), selected("ready-alternative", "supporting")])
    assert [item["name"] for item in result["selections"]] == ["ready-alternative"]


@pytest.mark.parametrize("as_dependency", [False, True])
def test_setup_flag_cannot_be_bypassed_by_ready_label(as_dependency):
    blocked = entry("needs-setup", "ready", setup_needed=True)
    root = entry("root", "ready", requirements={"skills": ["needs-setup"]})
    name = "root" if as_dependency else "needs-setup"
    result = policy(f"Nutze {name}.", [root, blocked], [selected(name)], (name,))
    assert result["selections"] == []


def test_structured_context_is_isolated_between_concurrent_turns(monkeypatch):
    instance, ext = make_runtime(monkeypatch, entries=[entry("pdf"), entry("arxiv")])
    barrier = threading.Barrier(2)
    def fake_pre(user_message, **kwargs):
        name = user_message
        instance._policy_result(name, [selected(name)], [entry("pdf"), entry("arxiv")], 5)
        barrier.wait(timeout=5)
        return "presentation deliberately contains no skill names"
    ext._pre = fake_pre
    # Storage writes are serialized in the fake state, to isolate decision capture.
    original_save = ext._save_context
    lock = threading.Lock()
    def save(*args, **kwargs):
        with lock:
            return original_save(*args, **kwargs)
    monkeypatch.setattr(ext, "_save_context", save)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(turn, instance, name, session=name) for name in ("pdf", "arxiv")]
        for future in futures:
            future.result(timeout=10)
    assert ext._context(ext._session_key("pdf"))["previous_primary_skill"] == "pdf"
    assert ext._context(ext._session_key("arxiv"))["previous_primary_skill"] == "arxiv"
