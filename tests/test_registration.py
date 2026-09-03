from __future__ import annotations

import argparse
from copy import deepcopy
import sys
from types import SimpleNamespace

from __init__ import register


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


class CliCompatibility:
    def __init__(self, ctx):
        self.ctx = ctx
        self.capabilities = SimpleNamespace(
            profile_discovery=True,
            profile_configuration=True,
            skill_execution_audit=True,
            skill_execution_guard=True,
        )

    def profile_scope_id(self):
        return "home-v1:test"

    def status_lines(self):
        return []

    def register_auxiliary_task(self, **kwargs):
        self.ctx.register_auxiliary_task(**kwargs)
        return True

    def register_skill_lifecycle(self, callback):
        self.ctx.register_hook("on_skill_lifecycle", callback)
        return True

    def register_skill_execution_guard(self, callback):
        self.ctx.register_hook("pre_tool_call", callback)
        return True

    def register_skill_execution_audit(self, post_tool, post_llm):
        self.ctx.register_hook("post_tool_call", post_tool)
        self.ctx.register_hook("post_llm_call", post_llm)
        return True


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
    registered_hooks = {name for name, _ in ctx.hooks}
    assert registered_hooks - {"pre_tool_call"} == {
        "on_session_start",
        "on_skill_lifecycle",
        "pre_llm_call",
        "post_tool_call",
        "post_llm_call",
    }
    assert ctx.commands[0]["name"] == "skill-router"
    assert "inspect <skill>" in ctx.commands[0]["args_hint"]
    assert "audit [last|N]" in ctx.commands[0]["args_hint"]
    assert "quality [last|N]" in ctx.commands[0]["args_hint"]
    assert "learning [last|reset|rebuild|<skill>]" in ctx.commands[0]["args_hint"]
    assert "enforcement" in ctx.commands[0]["args_hint"]
    assert ctx.cli_commands[0]["name"] == "skill-router"
    assert len(ctx.unloads) == 1


def test_registration_degrades_when_auxiliary_and_lifecycle_features_fail():
    ctx = DegradedCtx()

    register(ctx)

    assert ctx.aux == []
    registered_hooks = {name for name, _ in ctx.hooks}
    assert registered_hooks - {"pre_tool_call"} == {
        "on_session_start",
        "pre_llm_call",
        "post_tool_call",
        "post_llm_call",
    }
    assert ctx.commands[0]["name"] == "skill-router"


def test_registered_hook_pipeline_audits_a_loaded_primary(monkeypatch):
    ctx = Ctx()
    register(ctx)
    hooks = {name: callback for name, callback in ctx.hooks}
    runtime = hooks["pre_llm_call"].__self__
    owning_module = sys.modules[runtime.__class__.__module__]
    ctx.state.set("router.snapshot", {
        "profile": "default",
        "catalog_hash": "catalog",
        "entries": [{
            "name": "github",
            "description": "Manage pull requests",
            "readiness_status": "unknown",
            "requirements": {"skills": []},
            "alternatives": [],
            "policy_metadata_complete": True,
        }],
    })
    monkeypatch.setattr(runtime, "ensure_catalog", lambda force: False)
    monkeypatch.setattr(runtime.openviking, "find_scores", lambda task, entries: {})
    monkeypatch.setattr(owning_module, "select_skills", lambda *args, **kwargs: ([{
        "name": "github",
        "role": "primary",
        "order": 1,
        "reason": "GitHub task",
        "readiness_status": "unknown",
    }], "deterministic"))

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


def test_registered_profile_setup_cli_defaults_to_dry_run(monkeypatch, capsys):
    root_module = sys.modules[register.__module__]
    calls = []

    class Coordinator:
        def __init__(self, ctx, compatibility):
            pass

        def setup(self, profiles=None, apply=False):
            calls.append((profiles, apply))
            return SimpleNamespace(failed=(), render=lambda: "SETUP PLAN")

        def profiles(self):
            return SimpleNamespace(render=lambda: "PROFILE LIST")

        def sync(self):
            return SimpleNamespace(failed=(), render=lambda: "SYNC RESULT")

    monkeypatch.setattr(root_module, "ProfileSetupCoordinator", Coordinator)
    monkeypatch.setattr(root_module, "HermesCompatibility", CliCompatibility)
    ctx = Ctx()
    register(ctx)
    command = ctx.cli_commands[0]
    parser = argparse.ArgumentParser()
    command["setup_fn"](parser)

    args = parser.parse_args(["setup", "--profile", "alpha", "--dry-run"])
    result = command["handler_fn"](args)

    assert result == 0
    assert calls == [(["alpha"], False)]
    assert capsys.readouterr().out.strip() == "SETUP PLAN"


def test_registered_profiles_sync_returns_honest_partial_failure(monkeypatch, capsys):
    root_module = sys.modules[register.__module__]

    class Coordinator:
        def __init__(self, ctx, compatibility):
            pass

        def setup(self, profiles=None, apply=False):
            raise AssertionError("not setup")

        def profiles(self):
            raise AssertionError("not a plain roster")

        def sync(self):
            return SimpleNamespace(failed=("beta",), render=lambda: "SYNC PARTIAL")

    monkeypatch.setattr(root_module, "ProfileSetupCoordinator", Coordinator)
    monkeypatch.setattr(root_module, "HermesCompatibility", CliCompatibility)
    ctx = Ctx()
    register(ctx)
    command = ctx.cli_commands[0]
    parser = argparse.ArgumentParser()
    command["setup_fn"](parser)

    result = command["handler_fn"](parser.parse_args(["profiles", "--sync"]))

    assert result == 1
    assert capsys.readouterr().out.strip() == "SYNC PARTIAL"
