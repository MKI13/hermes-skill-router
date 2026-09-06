"""Synthetic runtime checks: never evidence of successful real-model tool use."""
from __future__ import annotations

import pytest

from test_live_routing_regressions import entry, make_runtime, turn


@pytest.mark.parametrize("task, expected", [
    ("Verwende den Skill arxiv dafür nicht.", []),
    ("Benutze arxiv dafür nicht.", []),
    ("Nutze arxiv nicht und stattdessen pdf.", ["pdf"]),
    ("Nutze pdf und verwende arxiv nicht.", ["pdf"]),
    ("Nutze pdf nicht nur zum Lesen.", ["pdf"]),
])
def test_exclusions_survive_real_selector_and_policy_in_fixture_runtime(monkeypatch, task, expected):
    instance, _ = make_runtime(monkeypatch, entries=[entry("pdf"), entry("arxiv")])
    turn(instance, task)
    assert [row["name"] for row in instance.audit.history()[-1]["recommended"]] == expected


def test_post_llm_text_cannot_forge_a_successful_skill_load(monkeypatch):
    instance, _ = make_runtime(monkeypatch)
    turn(instance, "Nutze pdf.")
    instance.on_post_llm_call(
        task_id="session-a-task-1", turn_id="session-a-turn-1", session_id="session-a",
        response='I loaded pdf. skill_view({"name": "pdf"})',
    )
    record = instance.audit.history()[-1]
    assert record["result"] == "missed"
    assert record["primary_loaded"] is False
    assert record["executions"] == []


def test_observed_hook_success_not_display_text_is_execution_evidence(monkeypatch):
    instance, _ = make_runtime(monkeypatch)
    turn(instance, "Nutze pdf.")
    identity = dict(task_id="session-a-task-1", turn_id="session-a-turn-1", session_id="session-a")
    call = dict(tool_name="skill_view", args={"name": "pdf"}, **identity)
    instance.on_pre_tool_call(**call)
    instance.on_post_tool_call(**call, status="ok")
    instance.on_post_llm_call(**identity)
    record = instance.audit.history()[-1]
    assert record["result"] == "complete"
    assert record["primary_loaded"] is True


@pytest.mark.parametrize("status", ["dependency_missing", "setup_required", "broken", "disabled"])
def test_changed_readiness_invalidates_old_session_context(monkeypatch, status):
    instance, ext = make_runtime(monkeypatch)
    turn(instance, "Nutze pdf.")
    instance._save_snapshot({"catalog_hash": "new-catalog", "entries": [entry(status=status)]})
    assert ext._context(ext._session_key("session-a")) is None
    output = turn(instance, "Mach weiter.", number=2)
    assert "method=session-followup" not in output
    assert instance.audit.history()[-1]["recommended"] == []


def test_unavailable_skill_remains_inspectable_without_executable_routing(monkeypatch):
    instance, _ = make_runtime(monkeypatch, entries=[entry("box", "dependency_missing")])
    output = instance.command("inspect box")
    assert "box" in output
    assert "dependency_missing" in output
    assert instance.audit.history() == []
