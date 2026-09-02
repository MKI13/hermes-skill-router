from __future__ import annotations

from copy import deepcopy

from __init__ import register
from skill_router_plugin import runtime as runtime_module


class State:
    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return deepcopy(self.values.get(key, default))

    def set(self, key, value):
        self.values[key] = deepcopy(value)


class Ctx:
    profile_name = "default"

    def __init__(self):
        self.state = State()
        self.aux = []
        self.skills = []
        self.sections = []
        self.hooks = []
        self.commands = []
        self.cli_commands = []
        self.unloads = []

    def get_config(self, key, default=None):
        return default

    def register_auxiliary_task(self, **kwargs):
        self.aux.append(kwargs)

    def register_skill(self, *args):
        self.skills.append(args)

    def register_system_prompt_section(self, *args, **kwargs):
        self.sections.append((args, kwargs))

    def register_hook(self, name, callback):
        self.hooks.append((name, callback))

    def register_command(self, **kwargs):
        self.commands.append(kwargs)

    def register_cli_command(self, **kwargs):
        self.cli_commands.append(kwargs)

    def on_unload(self, callback):
        self.unloads.append(callback)


class DegradedCtx(Ctx):
    register_auxiliary_task = None

    def register_hook(self, name, callback):
        if name == "on_skill_lifecycle":
            raise ValueError("unsupported hook")
        self.hooks.append((name, callback))


def test_registers_always_on_router_surfaces():
    ctx = Ctx()

    register(ctx)

    assert ctx.aux[0]["key"] == "skill_router_planner"
    assert ctx.skills[0][0] == "skill-router"
    assert ctx.sections[0][0][0] == "skill-router.rules"
    assert {name for name, _ in ctx.hooks} == {
        "on_session_start",
        "on_skill_lifecycle",
        "pre_llm_call",
        "post_tool_call",
        "post_llm_call",
    }
    assert ctx.commands[0]["name"] == "skill-router"
    assert "inspect <skill>" in ctx.commands[0]["args_hint"]
    assert "audit [last|N]" in ctx.commands[0]["args_hint"]
    assert ctx.cli_commands[0]["name"] == "skill-router"
    assert len(ctx.unloads) == 1


def test_registration_degrades_when_auxiliary_and_lifecycle_features_fail():
    ctx = DegradedCtx()

    register(ctx)

    assert ctx.aux == []
    assert {name for name, _ in ctx.hooks} == {
        "on_session_start",
        "pre_llm_call",
        "post_tool_call",
        "post_llm_call",
    }
    assert ctx.commands[0]["name"] == "skill-router"


def test_registered_hook_pipeline_audits_a_loaded_primary(monkeypatch):
    ctx = Ctx()
    monkeypatch.setattr(runtime_module.OpenVikingBridge, "find_scores", lambda self, task, entries: {})
    monkeypatch.setattr(runtime_module, "scan_catalog", lambda context, compatibility: {
        "catalog_hash": "catalog",
        "reader_mode": "metadata-only",
        "skills": [{
            "name": "github",
            "description": "Manage pull requests",
            "category": "dev",
            "content_hash": "content",
            "readiness_hash": "readiness",
            "readiness_status": "unknown",
            "setup_needed": False,
            "requirements": {},
            "dependency_checks": [],
            "readiness_reasons": [],
        }],
    })
    monkeypatch.setattr(runtime_module, "select_skills", lambda *args, **kwargs: ([{
        "name": "github",
        "role": "primary",
        "order": 1,
        "reason": "GitHub task",
        "readiness_status": "unknown",
    }], "deterministic"))
    register(ctx)
    hooks = {name: callback for name, callback in ctx.hooks}

    hooks["pre_llm_call"](
        user_message="Review a pull request",
        task_id="task-1",
        turn_id="turn-1",
        session_id="session-1",
    )
    hooks["post_tool_call"](
        tool_name="skill_view",
        args={"name": "github"},
        task_id="task-1",
        turn_id="turn-1",
        session_id="session-1",
        status="ok",
        result="SECRET TOOL OUTPUT",
    )
    hooks["post_llm_call"](
        task_id="task-1",
        turn_id="turn-1",
        session_id="session-1",
        user_message="SECRET PROMPT",
        assistant_response="SECRET RESPONSE",
    )

    output = ctx.commands[0]["handler"]("audit last")
    persisted = repr(ctx.state.get("router.audit"))

    assert "Policy: valid" in output
    assert "Result: complete" in output
    assert "Primary loaded: yes" in output
    assert "SECRET" not in persisted
