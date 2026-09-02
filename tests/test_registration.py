from __future__ import annotations

from __init__ import register


class State:
    def get(self, key, default=None):
        return default

    def set(self, key, value):
        pass


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
    }
    assert ctx.commands[0]["name"] == "skill-router"
    assert "inspect <skill>" in ctx.commands[0]["args_hint"]
    assert ctx.cli_commands[0]["name"] == "skill-router"
    assert len(ctx.unloads) == 1


def test_registration_degrades_when_auxiliary_and_lifecycle_features_fail():
    ctx = DegradedCtx()

    register(ctx)

    assert ctx.aux == []
    assert {name for name, _ in ctx.hooks} == {"on_session_start", "pre_llm_call"}
    assert ctx.commands[0]["name"] == "skill-router"
