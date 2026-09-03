"""Safe setup and inventory coordination for live Hermes profiles."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable, Mapping, Sequence

PROFILE_ROSTER_STATE_KEY = "router.profile_roster"
PROFILE_ROSTER_VERSION = 1
PLUGIN_NAME = "skill-router"
_EXACT_REVISION = re.compile(r"^[0-9a-f]{40}$")
SETTING_PREFIX = "plugins.entries.skill-router.settings"
SAFE_PROFILE_DEFAULTS: Mapping[str, str] = {
    "routing_mode": "deterministic",
    "enforcement_mode": "warn",
    "learning_mode": "shadow",
    "openviking_enabled": "false",
}


@dataclass(frozen=True)
class ProfileRosterEntry:
    """Non-sensitive Router metadata for one live profile."""

    name: str
    installed: bool
    enabled: bool
    version: str = ""
    skill_count: int | None = None
    routing_mode: str = ""
    enforcement_mode: str = ""
    learning_mode: str = ""
    openviking_enabled: bool | None = None
    error: str = ""


@dataclass(frozen=True)
class ProfileRosterSummary:
    """Renderable metadata-only profile roster."""

    profiles: tuple[ProfileRosterEntry, ...]
    error: str = ""

    def render(self) -> str:
        """Render the roster without paths, settings, or command output."""
        lines = ["Hermes Skill Router Profiles", ""]
        if self.error:
            return "\n".join(lines + [self.error])
        lines.append(f"Profiles detected: {len(self.profiles)}")
        for profile in self.profiles:
            lines.extend(("", profile.name))
            if profile.error:
                lines.append("  Router: inspection failed")
                continue
            if not profile.installed:
                lines.append("  Router: not configured")
                continue
            state = "enabled" if profile.enabled else "disabled"
            version = f" ({profile.version})" if profile.version else ""
            lines.append(f"  Router: {state}{version}")
            if profile.skill_count is not None:
                lines.append(f"  Skills: {profile.skill_count}")
            if profile.routing_mode:
                lines.append(f"  Routing: {profile.routing_mode}")
            if profile.enforcement_mode:
                lines.append(f"  Enforcement: {profile.enforcement_mode}")
            if profile.learning_mode:
                lines.append(f"  Learning: {profile.learning_mode}")
            if profile.openviking_enabled is not None:
                lines.append(
                    "  OpenViking: " + ("enabled" if profile.openviking_enabled else "disabled")
                )
        return "\n".join(lines)


@dataclass(frozen=True)
class ProfileSetupResult:
    """Sanitized outcome for one selected profile."""

    name: str
    status: str
    actions: tuple[str, ...] = ()
    error: str = ""


@dataclass(frozen=True)
class ProfileSetupSummary:
    """Aggregate setup result with no command output or configuration values."""

    dry_run: bool
    profiles: tuple[ProfileSetupResult, ...]

    @property
    def configured(self) -> tuple[str, ...]:
        """Return profiles changed successfully by an apply run."""
        return self._names("configured")

    @property
    def failed(self) -> tuple[str, ...]:
        """Return profiles whose inspection or setup failed."""
        return self._names("failed")

    @property
    def untouched(self) -> tuple[str, ...]:
        """Return profiles that already had every required value."""
        return self._names("untouched")

    @property
    def planned(self) -> tuple[str, ...]:
        """Return profiles that a dry run reports as needing setup."""
        return self._names("planned")

    def render(self) -> str:
        """Render compact outcomes without inspected values or command output."""
        mode = "dry-run" if self.dry_run else "apply"
        lines = [
            "Hermes Skill Router Setup",
            "",
            f"Detected profiles: {len(self.profiles)}",
            "",
            "Recommended initial mode:",
            "routing: deterministic",
            "enforcement: warn",
            "learning: shadow",
            "OpenViking: disabled",
            "",
            f"Plan ({mode}):",
        ]
        for profile in self.profiles:
            detail = f" ({', '.join(profile.actions)})" if profile.actions else ""
            error = f": {profile.error}" if profile.error else ""
            lines.append(f"- {profile.name}: {profile.status}{detail}{error}")
        if self.dry_run and self.planned:
            lines.extend(("", "Rerun the same setup selection with --apply."))
        if not self.dry_run:
            lines.extend((
                "",
                f"{len(self.configured)} configured",
                f"{len(self.failed)} failed",
                f"{len(self.untouched)} untouched",
            ))
        return "\n".join(lines)

    def _names(self, status: str) -> tuple[str, ...]:
        return tuple(item.name for item in self.profiles if item.status == status)


@dataclass(frozen=True)
class ProfileSyncSummary:
    """Name-only comparison between the live roster and profile-local state."""

    dry_run: bool
    scope_id: str
    profiles: tuple[str, ...]
    new: tuple[str, ...]
    removed: tuple[str, ...]
    configured: tuple[str, ...]
    failed: tuple[str, ...] = ()
    scope_mismatch: bool = False

    def render(self) -> str:
        """Render only profile names and synchronization categories."""
        mode = "dry-run" if self.dry_run else "saved"
        lines = ["Hermes Skill Router Profile Sync", "", f"Result: {mode}"]
        for name in self.new:
            lines.append(f"New profile detected: {name}")
        for name in self.removed:
            lines.append(f"Removed profile: {name}")
        lines.append(
            "Configured profiles: " + (", ".join(self.configured) if self.configured else "none")
        )
        lines.append("Failed profiles: " + (", ".join(self.failed) if self.failed else "none"))
        if self.scope_mismatch:
            lines.append("- prior roster: ignored (scope mismatch)")
        return "\n".join(lines)


class ProfileSetupCoordinator:
    """Coordinate non-destructive profile setup through injected Hermes APIs."""

    def __init__(self, ctx: Any, compatibility: Any, *, timeout_seconds: int = 180) -> None:
        self.ctx = ctx
        self.compatibility = compatibility
        self.timeout_seconds = timeout_seconds

    def profiles(self) -> ProfileRosterSummary:
        """Return metadata-only status for every currently discovered profile."""
        entries: list[ProfileRosterEntry] = []
        try:
            discovered = self._discover()
        except Exception:
            return ProfileRosterSummary((), error="Profile discovery failed")
        for profile in discovered:
            name = str(profile.name)
            try:
                inspection = self.compatibility.inspect_profile(name)
            except Exception:
                entries.append(
                    ProfileRosterEntry(name, installed=False, enabled=False, error="inspection failed")
                )
                continue
            inspection_error = str(getattr(inspection, "error", "") or "")
            entries.append(
                ProfileRosterEntry(
                    name=name,
                    installed=bool(getattr(inspection, "installed", False)),
                    enabled=bool(getattr(inspection, "enabled", False)),
                    version=str(getattr(inspection, "version", "") or "")[:40],
                    skill_count=(
                        int(inspection.skill_count)
                        if getattr(inspection, "skill_count", None) is not None
                        else None
                    ),
                    routing_mode=str(getattr(inspection, "routing_mode", "") or "")[:40],
                    enforcement_mode=str(
                        getattr(inspection, "enforcement_mode", "") or ""
                    )[:40],
                    learning_mode=str(getattr(inspection, "learning_mode", "") or "")[:40],
                    openviking_enabled=getattr(inspection, "openviking_enabled", None),
                    error="inspection failed" if inspection_error else "",
                )
            )
        return ProfileRosterSummary(tuple(entries))

    def setup(
        self,
        profiles: Iterable[str] | None = None,
        *,
        apply: bool = False,
    ) -> ProfileSetupSummary:
        """Inspect selected live profiles and optionally apply only missing setup."""
        try:
            discovered = self._discover()
        except Exception:
            return ProfileSetupSummary(
                dry_run=not apply,
                profiles=(ProfileSetupResult("profile discovery", "failed", error="failed"),),
            )
        selected, missing = _select_profiles(discovered, profiles)
        outcomes: list[ProfileSetupResult] = [
            ProfileSetupResult(name=name, status="failed", error="profile not found")
            for name in missing
        ]
        install_spec: Any | None = None
        install_spec_loaded = False

        for profile in selected:
            name = str(profile.name)
            try:
                inspection = self.compatibility.inspect_profile(name)
            except Exception:
                outcomes.append(ProfileSetupResult(name, "failed", error="inspection failed"))
                continue
            inspection_error = str(getattr(inspection, "error", "") or "")
            if inspection_error:
                outcomes.append(ProfileSetupResult(name, "failed", error="inspection failed"))
                continue

            installed = bool(getattr(inspection, "installed", False))
            if installed and not bool(getattr(inspection, "enabled", False)):
                outcomes.append(ProfileSetupResult(name, "untouched", ("preserve:disabled",)))
                continue
            explicit_settings = _explicit_settings(inspection)
            preserved = tuple(f"preserve:{key}" for key in explicit_settings)
            missing_settings = tuple(
                key for key in SAFE_PROFILE_DEFAULTS if key not in explicit_settings
            )
            changes = (() if installed else ("install_plugin",)) + tuple(
                f"set:{key}" for key in missing_settings
            )
            if not changes:
                outcomes.append(ProfileSetupResult(name, "untouched", preserved))
                continue
            if not installed and not install_spec_loaded:
                try:
                    install_spec = self.compatibility.current_plugin_install_spec()
                except Exception:
                    install_spec = None
                install_spec_loaded = True
            if not installed and not _valid_install_spec(install_spec):
                outcomes.append(ProfileSetupResult(
                    name,
                    "failed",
                    changes + preserved,
                    "pinned install source unavailable",
                ))
                continue
            if not apply:
                outcomes.append(ProfileSetupResult(name, "planned", changes + preserved))
                continue

            result = self._apply_profile(
                name,
                install_spec=install_spec,
                install_plugin=not installed,
                missing_settings=missing_settings,
            )
            outcomes.append(ProfileSetupResult(
                result.name,
                result.status,
                result.actions + preserved,
                result.error,
            ))

        return ProfileSetupSummary(dry_run=not apply, profiles=tuple(outcomes))

    def sync(self, *, dry_run: bool = False) -> ProfileSyncSummary:
        """Compare live names with the scoped roster and optionally persist names."""
        scope_source = getattr(self.compatibility, "profile_scope_id", "")
        scope_id = str(scope_source() if callable(scope_source) else scope_source)
        try:
            discovered = self._discover()
        except Exception:
            return ProfileSyncSummary(
                dry_run=dry_run,
                scope_id=scope_id,
                profiles=(),
                new=(),
                removed=(),
                configured=(),
                failed=("profile discovery",),
            )
        names = tuple(_unique_names(discovered))
        setup_summary = self.setup(apply=not dry_run)
        if any(item.name == "profile discovery" for item in setup_summary.profiles):
            return ProfileSyncSummary(
                dry_run=dry_run,
                scope_id=scope_id,
                profiles=(),
                new=(),
                removed=(),
                configured=(),
                failed=("profile discovery",),
            )
        prior = self._load_roster()
        prior_scope = str(prior.get("scope_id") or "")
        scope_mismatch = bool(prior_scope and prior_scope != scope_id)
        previous_names = () if scope_mismatch else _stored_names(prior)
        previous_set = set(previous_names)
        current_set = set(names)
        configured: list[str] = []
        failed: list[str] = list(setup_summary.failed)
        for name in names:
            try:
                inspection = self.compatibility.inspect_profile(name)
            except Exception:
                if name not in failed:
                    failed.append(name)
                continue
            if not str(getattr(inspection, "error", "") or "") and bool(
                getattr(inspection, "installed", False)
            ):
                configured.append(name)
            elif str(getattr(inspection, "error", "") or "") and name not in failed:
                failed.append(name)

        if not dry_run:
            self.ctx.state.set(
                PROFILE_ROSTER_STATE_KEY,
                {
                    "version": PROFILE_ROSTER_VERSION,
                    "scope_id": scope_id,
                    "names": list(names),
                },
            )
        return ProfileSyncSummary(
            dry_run=dry_run,
            scope_id=scope_id,
            profiles=names,
            new=tuple(name for name in names if name not in previous_set),
            removed=tuple(name for name in previous_names if name not in current_set),
            configured=tuple(configured),
            failed=tuple(failed),
            scope_mismatch=scope_mismatch,
        )

    def _apply_profile(
        self,
        name: str,
        *,
        install_spec: Any,
        install_plugin: bool,
        missing_settings: Sequence[str],
    ) -> ProfileSetupResult:
        installed_here = False
        added_settings: list[str] = []
        if install_plugin:
            source, revision = _install_source_and_revision(install_spec)
            if not source or not _EXACT_REVISION.fullmatch(revision):
                return ProfileSetupResult(
                    name,
                    "failed",
                    error="pinned install source unavailable",
                )
            argv = ["plugins", "install", source, "--ref", revision]
            argv.append("--enable")
            if not self._command_ok(name, argv):
                return ProfileSetupResult(name, "failed", error="plugin install failed")
            installed_here = True

        for key in missing_settings:
            argv = [
                "config",
                "set",
                "--force",
                f"{SETTING_PREFIX}.{key}",
                SAFE_PROFILE_DEFAULTS[key],
            ]
            if not self._command_ok(name, argv):
                self._rollback(name, added_settings, installed_here)
                return ProfileSetupResult(name, "failed", error="configuration failed")
            added_settings.append(key)

        actions = (() if not installed_here else ("installed_plugin",)) + tuple(
            f"set:{key}" for key in added_settings
        )
        return ProfileSetupResult(name, "configured", actions)

    def _rollback(self, name: str, added_settings: Sequence[str], installed_here: bool) -> None:
        for key in reversed(added_settings):
            self._command_ok(
                name,
                ["config", "unset", f"{SETTING_PREFIX}.{key}"],
            )
        if installed_here:
            self._command_ok(name, ["plugins", "disable", PLUGIN_NAME])
            self._command_ok(name, ["plugins", "remove", PLUGIN_NAME])

    def _command_ok(self, name: str, argv: Sequence[str]) -> bool:
        try:
            result = self.compatibility.run_profile_command(
                name,
                list(argv),
                timeout_seconds=self.timeout_seconds,
            )
        except Exception:
            return False
        return int(getattr(result, "returncode", 1)) == 0

    def _discover(self) -> tuple[Any, ...]:
        return tuple(self.compatibility.discover_profiles())

    def _load_roster(self) -> dict[str, Any]:
        try:
            value = self.ctx.state.get(PROFILE_ROSTER_STATE_KEY, default={})
        except TypeError:
            value = self.ctx.state.get(PROFILE_ROSTER_STATE_KEY, {})
        return value if isinstance(value, dict) else {}


def list_profiles(ctx: Any, compatibility: Any) -> ProfileRosterSummary:
    """Return a metadata-only roster without retaining a coordinator."""
    return ProfileSetupCoordinator(ctx, compatibility).profiles()


def setup_profiles(
    ctx: Any,
    compatibility: Any,
    profiles: Iterable[str] | None = None,
    *,
    apply: bool = False,
    timeout_seconds: int = 180,
) -> ProfileSetupSummary:
    """Run profile setup without requiring callers to retain a coordinator."""
    return ProfileSetupCoordinator(
        ctx,
        compatibility,
        timeout_seconds=timeout_seconds,
    ).setup(profiles, apply=apply)


def sync_profiles(
    ctx: Any,
    compatibility: Any,
    *,
    dry_run: bool = False,
) -> ProfileSyncSummary:
    """Run a name-only profile roster synchronization."""
    return ProfileSetupCoordinator(ctx, compatibility).sync(dry_run=dry_run)


def _install_source_and_revision(install_spec: Any) -> tuple[str, str]:
    source = str(getattr(install_spec, "source", "") or "")
    revision = str(
        getattr(install_spec, "revision", "")
        or getattr(install_spec, "ref", "")
        or ""
    ).casefold()
    return source, revision


def _valid_install_spec(install_spec: Any) -> bool:
    source, revision = _install_source_and_revision(install_spec)
    return bool(source and _EXACT_REVISION.fullmatch(revision))


def _select_profiles(
    discovered: Sequence[Any],
    requested: Iterable[str] | None,
) -> tuple[tuple[Any, ...], tuple[str, ...]]:
    by_name = {str(profile.name): profile for profile in discovered}
    if requested is None:
        return tuple(by_name.values()), ()
    selected_names = (requested,) if isinstance(requested, str) else requested
    names = tuple(dict.fromkeys(str(name) for name in selected_names))
    return (
        tuple(by_name[name] for name in names if name in by_name),
        tuple(name for name in names if name not in by_name),
    )


def _unique_names(discovered: Sequence[Any]) -> list[str]:
    return list(dict.fromkeys(str(profile.name) for profile in discovered))


def _explicit_settings(inspection: Any) -> tuple[str, ...]:
    raw_settings = getattr(inspection, "settings", ())
    try:
        explicit = {
            str(key)
            for key, value in raw_settings
            if value is not None and str(key) in SAFE_PROFILE_DEFAULTS
        }
    except (TypeError, ValueError):
        explicit = set()
    return tuple(key for key in SAFE_PROFILE_DEFAULTS if key in explicit)


def _stored_names(roster: Mapping[str, Any]) -> tuple[str, ...]:
    raw = roster.get("names")
    if not isinstance(raw, list) or not all(isinstance(name, str) for name in raw):
        return ()
    return tuple(dict.fromkeys(raw))
