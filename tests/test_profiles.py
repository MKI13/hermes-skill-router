from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path

from skill_router_plugin.profiles import (
    PROFILE_ROSTER_STATE_KEY,
    SAFE_PROFILE_DEFAULTS,
    ProfileSetupCoordinator,
    list_profiles,
    setup_profiles,
    sync_profiles,
)


@dataclass(frozen=True)
class Profile:
    name: str
    path: Path
    enabled: bool = True


@dataclass(frozen=True)
class Inspection:
    name: str
    installed: bool
    enabled: bool = True
    version: str = ""
    skill_count: int | None = None
    settings: tuple[tuple[str, str | None], ...] = ()
    error: str = ""


@dataclass(frozen=True)
class InstallSpec:
    source: str
    revision: str


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""


class State:
    def __init__(self):
        self.values = {}
        self.writes = []

    def get(self, key, default=None):
        return deepcopy(self.values.get(key, default))

    def set(self, key, value):
        self.values[key] = deepcopy(value)
        self.writes.append((key, deepcopy(value)))


class Ctx:
    def __init__(self):
        self.state = State()


class Compatibility:
    profile_scope_id = "scope-alpha"

    def __init__(self, names=("alpha",), inspections=None):
        self.names = list(names)
        self.inspections = inspections or {
            name: Inspection(name, installed=True, settings=full_settings())
            for name in names
        }
        self.commands = []
        self.failures = set()
        self.inspect_failures = set()
        self.install_spec = InstallSpec(
            "OWNER/hermes-skill-router",
            "0123456789abcdef0123456789abcdef01234567",
        )

    def discover_profiles(self):
        return [Profile(name, Path("/profiles") / name) for name in self.names]

    def inspect_profile(self, name):
        if name in self.inspect_failures:
            raise RuntimeError("SECRET inspection detail")
        return self.inspections[name]

    def current_plugin_install_spec(self):
        return self.install_spec

    def run_profile_command(self, name, argv, timeout_seconds=30):
        call = (name, tuple(argv), timeout_seconds)
        self.commands.append(call)
        if (name, tuple(argv)) in self.failures:
            return CommandResult(2, "SECRET command output")
        self._apply_command(name, argv)
        return CommandResult(0, "SECRET command output")

    def _apply_command(self, name, argv):
        inspection = self.inspections[name]
        settings = dict(inspection.settings)
        if argv[:2] == ["plugins", "install"]:
            self.inspections[name] = replace(inspection, installed=True, enabled=True)
        elif argv[:3] == ["plugins", "disable", "skill-router"]:
            self.inspections[name] = replace(inspection, enabled=False)
        elif argv[:3] == ["plugins", "remove", "skill-router"]:
            self.inspections[name] = replace(inspection, installed=False, enabled=False)
        elif argv[:3] == ["config", "set", "--force"]:
            settings[argv[3].rsplit(".", 1)[-1]] = argv[4]
            self.inspections[name] = replace(inspection, settings=tuple(settings.items()))
        elif argv[:2] == ["config", "unset"]:
            settings.pop(argv[2].rsplit(".", 1)[-1], None)
            self.inspections[name] = replace(inspection, settings=tuple(settings.items()))


def full_settings(**overrides):
    values = dict(SAFE_PROFILE_DEFAULTS)
    values.update(overrides)
    return tuple(values.items())


def test_default_setup_is_read_only_for_one_profile():
    ctx = Ctx()
    compatibility = Compatibility(
        inspections={"alpha": Inspection("alpha", installed=False, enabled=False)}
    )

    summary = setup_profiles(ctx, compatibility)

    assert summary.dry_run is True
    assert summary.planned == ("alpha",)
    assert summary.configured == ()
    assert summary.profiles[0].actions == (
        "install_plugin",
        "set:routing_mode",
        "set:enforcement_mode",
        "set:learning_mode",
        "set:openviking_enabled",
    )
    assert compatibility.commands == []
    assert ctx.state.writes == []


def test_apply_configures_all_live_profiles_and_uses_pinned_child_cli():
    ctx = Ctx()
    compatibility = Compatibility(
        names=("alpha", "beta", "gamma"),
        inspections={
            "alpha": Inspection("alpha", installed=False, enabled=False),
            "beta": Inspection("beta", installed=True, settings=(("routing_mode", "model"),)),
            "gamma": Inspection("gamma", installed=True, settings=full_settings()),
        },
    )

    summary = setup_profiles(ctx, compatibility, apply=True)

    assert summary.configured == ("alpha", "beta")
    assert summary.untouched == ("gamma",)
    rendered = summary.render()
    assert "Profiles detected: 3" in rendered
    assert "Configured: 2" in rendered
    assert "Preserved: 1" in rendered
    assert "Failed: 0" in rendered
    assert "New skills installed later will be discovered automatically." in rendered
    install = compatibility.commands[0]
    assert install == (
        "alpha",
        (
            "plugins",
            "install",
            "OWNER/hermes-skill-router",
            "--ref",
            "0123456789abcdef0123456789abcdef01234567",
            "--enable",
        ),
        180,
    )
    assert all(call[0] != "gamma" for call in compatibility.commands)


def test_existing_values_and_disabled_installation_are_preserved():
    ctx = Ctx()
    compatibility = Compatibility(
        inspections={
            "alpha": Inspection(
                "alpha",
                installed=True,
                enabled=False,
                settings=(
                    ("routing_mode", "model"),
                    ("custom_secret", "SECRET"),
                ),
            )
        }
    )

    summary = setup_profiles(ctx, compatibility, apply=True)

    assert summary.untouched == ("alpha",)
    assert compatibility.commands == []
    assert compatibility.inspections["alpha"].enabled is False
    settings = dict(compatibility.inspections["alpha"].settings)
    assert settings == {
        "routing_mode": "model",
        "custom_secret": "SECRET",
    }


def test_partial_failure_rolls_back_new_work_and_continues_other_profiles():
    ctx = Ctx()
    compatibility = Compatibility(
        names=("alpha", "beta"),
        inspections={
            "alpha": Inspection("alpha", installed=False, enabled=False),
            "beta": Inspection("beta", installed=True, settings=()),
        },
    )
    failing_argv = (
        "config",
        "set",
        "--force",
        "plugins.entries.skill-router.settings.learning_mode",
        "shadow",
    )
    compatibility.failures.add(("alpha", failing_argv))

    summary = setup_profiles(ctx, compatibility, apply=True)

    assert summary.failed == ("alpha",)
    assert summary.configured == ("beta",)
    assert compatibility.inspections["alpha"].installed is False
    assert dict(compatibility.inspections["alpha"].settings) == {}
    alpha_argv = [call[1] for call in compatibility.commands if call[0] == "alpha"]
    assert ("plugins", "disable", "skill-router") in alpha_argv
    assert ("plugins", "remove", "skill-router") in alpha_argv
    assert (
        "config",
        "unset",
        "plugins.entries.skill-router.settings.enforcement_mode",
    ) in alpha_argv


def test_apply_is_idempotent_after_success():
    ctx = Ctx()
    compatibility = Compatibility(
        inspections={"alpha": Inspection("alpha", installed=False, enabled=False)}
    )

    first = setup_profiles(ctx, compatibility, apply=True)
    command_count = len(compatibility.commands)
    second = setup_profiles(ctx, compatibility, apply=True)

    assert first.configured == ("alpha",)
    assert second.untouched == ("alpha",)
    assert len(compatibility.commands) == command_count


def test_selective_target_does_not_touch_other_profiles_and_reports_unknown():
    ctx = Ctx()
    compatibility = Compatibility(
        names=("alpha", "beta", "gamma"),
        inspections={
            name: Inspection(name, installed=True, settings=())
            for name in ("alpha", "beta", "gamma")
        },
    )

    summary = ProfileSetupCoordinator(ctx, compatibility).setup(
        ("beta", "missing"), apply=True
    )

    assert summary.configured == ("beta",)
    assert summary.failed == ("missing",)
    assert {call[0] for call in compatibility.commands} == {"beta"}


def test_broken_profile_does_not_prevent_other_profile_setup():
    ctx = Ctx()
    compatibility = Compatibility(
        names=("alpha", "beta"),
        inspections={
            "alpha": Inspection("alpha", installed=True, settings=()),
            "beta": Inspection("beta", installed=True, settings=()),
        },
    )
    compatibility.inspect_failures.add("alpha")

    summary = setup_profiles(ctx, compatibility, apply=True)

    assert summary.failed == ("alpha",)
    assert summary.configured == ("beta",)


def test_sync_detects_new_removed_and_currently_configured_names():
    ctx = Ctx()
    ctx.state.set(
        PROFILE_ROSTER_STATE_KEY,
        {"version": 1, "scope_id": "scope-alpha", "names": ["alpha", "gamma"]},
    )
    ctx.state.writes.clear()
    compatibility = Compatibility(
        names=("alpha", "beta"),
        inspections={
            "alpha": Inspection("alpha", installed=True, settings=full_settings()),
            "beta": Inspection("beta", installed=False, enabled=False),
        },
    )

    summary = sync_profiles(ctx, compatibility)

    assert summary.profiles == ("alpha", "beta")
    assert summary.new == ("beta",)
    assert summary.removed == ("gamma",)
    assert summary.configured == ("alpha", "beta")
    assert compatibility.commands[0][0] == "beta"
    assert compatibility.commands[0][1][:2] == ("plugins", "install")
    assert ctx.state.values[PROFILE_ROSTER_STATE_KEY] == {
        "version": 1,
        "scope_id": "scope-alpha",
        "names": ["alpha", "beta"],
    }


def test_sync_dry_run_makes_no_state_write_when_roster_changes():
    ctx = Ctx()
    ctx.state.values[PROFILE_ROSTER_STATE_KEY] = {
        "version": 1,
        "scope_id": "scope-alpha",
        "names": ["alpha"],
    }
    compatibility = Compatibility(names=("alpha", "beta"))

    summary = sync_profiles(ctx, compatibility, dry_run=True)

    assert summary.dry_run is True
    assert summary.new == ("beta",)
    assert ctx.state.writes == []
    assert ctx.state.values[PROFILE_ROSTER_STATE_KEY]["names"] == ["alpha"]


def test_copied_inventory_scope_mismatch_is_not_treated_as_removed_profiles():
    ctx = Ctx()
    ctx.state.values[PROFILE_ROSTER_STATE_KEY] = {
        "version": 1,
        "scope_id": "scope-from-copy",
        "names": ["gamma"],
    }
    compatibility = Compatibility(names=("alpha", "beta"))

    summary = sync_profiles(ctx, compatibility)

    assert summary.scope_mismatch is True
    assert summary.new == ("alpha", "beta")
    assert summary.removed == ()
    assert ctx.state.values[PROFILE_ROSTER_STATE_KEY]["scope_id"] == "scope-alpha"


def test_roster_is_metadata_only_and_separate_from_setup_and_sync():
    ctx = Ctx()
    compatibility = Compatibility(
        names=("alpha", "beta"),
        inspections={
            "alpha": Inspection(
                "alpha",
                installed=True,
                enabled=True,
                version="0.3.0",
                skill_count=7,
                settings=(("custom_secret", "SECRET"),),
            ),
            "beta": Inspection("beta", installed=True, enabled=False),
        },
    )

    roster = list_profiles(ctx, compatibility)

    assert [(item.name, item.installed, item.enabled) for item in roster.profiles] == [
        ("alpha", True, True),
        ("beta", True, False),
    ]
    assert "alpha\n  Router: enabled (0.3.0)\n  Skills: 7" in roster.render()
    assert "beta\n  Router: disabled" in roster.render()
    assert "SECRET" not in repr(roster)
    assert compatibility.commands == []
    assert ctx.state.writes == []


def test_none_inspection_values_are_missing_not_explicit_settings():
    ctx = Ctx()
    compatibility = Compatibility(
        inspections={
            "alpha": Inspection(
                "alpha",
                installed=True,
                settings=tuple((key, None) for key in SAFE_PROFILE_DEFAULTS),
            )
        }
    )

    summary = setup_profiles(ctx, compatibility)

    assert summary.planned == ("alpha",)
    assert summary.profiles[0].actions == tuple(
        f"set:{key}" for key in SAFE_PROFILE_DEFAULTS
    )


def test_results_and_roster_do_not_expose_secrets_or_profile_paths():
    ctx = Ctx()
    compatibility = Compatibility(
        inspections={
            "alpha": Inspection(
                "alpha",
                installed=True,
                settings=(("custom_secret", "SECRET-CONFIG"),),
            )
        }
    )
    compatibility.failures.add((
        "alpha",
        (
            "config",
            "set",
            "--force",
            "plugins.entries.skill-router.settings.routing_mode",
            "deterministic",
        ),
    ))

    setup_summary = setup_profiles(ctx, compatibility, apply=True)
    sync_summary = sync_profiles(ctx, compatibility)
    rendered = repr((setup_summary, sync_summary, ctx.state.values))

    assert setup_summary.failed == ("alpha",)
    assert "SECRET" not in rendered
    assert "/profiles" not in rendered


def test_selective_dry_run_never_recommends_a_broader_apply():
    summary = setup_profiles(
        Ctx(),
        Compatibility(
            names=("alpha", "beta"),
            inspections={
                "alpha": Inspection("alpha", installed=False, enabled=False),
                "beta": Inspection("beta", installed=False, enabled=False),
            },
        ),
        profiles=("beta",),
    )

    rendered = summary.render()

    assert [item.name for item in summary.profiles] == ["beta"]
    assert "hermes skill-router setup --apply" not in rendered
    assert "same setup selection" in rendered


def test_sync_preserves_prior_roster_when_discovery_fails():
    ctx = Ctx()
    prior = {"version": 1, "scope_id": "scope-alpha", "names": ["alpha"]}
    ctx.state.set(PROFILE_ROSTER_STATE_KEY, prior)
    ctx.state.writes.clear()
    compatibility = Compatibility()

    def fail_discovery():
        raise RuntimeError("SECRET discovery detail")

    compatibility.discover_profiles = fail_discovery

    summary = sync_profiles(ctx, compatibility)
    roster = list_profiles(ctx, compatibility)

    assert summary.failed == ("profile discovery",)
    assert summary.new == ()
    assert summary.removed == ()
    assert ctx.state.get(PROFILE_ROSTER_STATE_KEY) == prior
    assert ctx.state.writes == []
    assert roster.error == "Profile discovery failed"
    assert "SECRET" not in summary.render()
    assert "SECRET" not in roster.render()


def test_apply_fails_closed_when_current_install_is_not_exactly_pinned():
    ctx = Ctx()
    compatibility = Compatibility(
        names=("alpha", "beta"),
        inspections={
            "alpha": Inspection("alpha", installed=True, settings=full_settings()),
            "beta": Inspection("beta", installed=False, enabled=False),
        },
    )
    compatibility.install_spec = InstallSpec("OWNER/hermes-skill-router", "main")

    summary = setup_profiles(ctx, compatibility, apply=True)

    assert summary.failed == ("beta",)
    assert compatibility.commands == []
    assert "pinned install source unavailable" in summary.render()


def test_legacy_explicit_setting_is_preserved_during_apply():
    ctx = Ctx()
    compatibility = Compatibility(
        inspections={
            "alpha": Inspection(
                "alpha",
                installed=True,
                enabled=True,
                settings=(("routing_mode", "model"),),
            )
        }
    )

    summary = setup_profiles(ctx, compatibility, apply=True)

    assert summary.configured == ("alpha",)
    assert "preserve:routing_mode" in summary.profiles[0].actions
    assert all(
        call[1][-2:] != ("plugins.entries.skill-router.settings.routing_mode", "deterministic")
        for call in compatibility.commands
    )
