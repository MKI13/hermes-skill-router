"""Feature-detected access to version-dependent Hermes APIs."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlsplit

_RAW_API_NAMES = (
    "get_project_skills_dirs",
    "get_scan_ordered_skills_dirs",
    "iter_project_skill_files",
    "iter_skill_index_files",
)
_EXACT_REVISION = re.compile(r"^[0-9a-f]{40}$")
_SAFE_SETUP_DEFAULTS = {
    "routing_mode": "deterministic",
    "enforcement_mode": "warn",
    "learning_mode": "shadow",
    "openviking_enabled": "false",
}


class ProfileDiscoveryError(RuntimeError):
    """Authoritative Hermes profile enumeration failed."""


@dataclass(frozen=True)
class DiscoveredProfile:
    """One live profile name returned by Hermes' authoritative profile API."""

    name: str
    enabled: bool = True


@dataclass(frozen=True)
class ProfileCommandResult:
    """Sanitized result of one Hermes CLI operation for a profile."""

    returncode: int
    stdout: str = ""


@dataclass(frozen=True)
class PluginInstallSpec:
    """Credential-free source and exact revision recorded by Hermes."""

    source: str
    revision: str = ""


@dataclass(frozen=True)
class ProfileInspection:
    """Minimal Router metadata observed through Hermes CLI commands."""

    name: str
    installed: bool
    enabled: bool
    version: str = ""
    skill_count: int | None = None
    routing_mode: str = ""
    enforcement_mode: str = ""
    learning_mode: str = ""
    openviking_enabled: bool | None = None
    settings: tuple[tuple[str, str | None], ...] = ()
    error: str = ""

    def setting(self, name: str) -> str | None:
        """Return one explicitly configured setup value."""
        return dict(self.settings).get(name)


@dataclass(frozen=True)
class CompatibilityCapabilities:
    """Detected Hermes capabilities used by the router."""

    raw_skill_reader: bool
    plugin_skill_lookup: bool
    skill_lifecycle: bool
    auxiliary_tasks: bool
    skills_tool_bootstrap: bool
    skill_execution_audit: bool
    skill_execution_guard: bool
    profile_discovery: bool
    profile_configuration: bool
    mcp_discovery: bool
    issues: tuple[str, ...]

    @property
    def status(self) -> str:
        """Return ``full`` only when every required capability is available."""
        required = (
            self.raw_skill_reader,
            self.plugin_skill_lookup,
            self.skill_lifecycle,
            self.auxiliary_tasks,
            self.skill_execution_audit,
            self.skill_execution_guard,
            self.profile_discovery,
            self.profile_configuration,
            self.mcp_discovery,
        )
        return "full" if all(required) else "degraded"


class HermesCompatibility:
    """Resolve internal Hermes APIs once and provide safe fallbacks."""

    def __init__(
        self,
        ctx: Any,
        *,
        module_loader: Callable[[str], Any] | None = None,
        command_runner: Callable[..., Any] | None = None,
        hermes_executable: str | None = None,
    ) -> None:
        self.ctx = ctx
        self._module_loader = module_loader or importlib.import_module
        self._command_runner = command_runner or subprocess.run
        self._hermes_executable = hermes_executable or _running_hermes_executable()
        self._issues: list[str] = []
        self._raw_functions: dict[str, Callable[..., Any]] = {}
        self._plugin_skill_lookup: Callable[[str], Any] | None = None
        self._raw_skill_reader = False
        self._plugin_lookup = False
        self._skill_lifecycle = callable(getattr(ctx, "register_hook", None))
        self._auxiliary_tasks = callable(getattr(ctx, "register_auxiliary_task", None))
        self._skill_execution_audit = callable(getattr(ctx, "register_hook", None))
        self._skill_execution_guard = callable(getattr(ctx, "register_hook", None))
        self._skills_tool_bootstrap = False
        self._profile_discovery = False
        self._profile_configuration = False
        self._profile_functions: dict[str, Callable[..., Any]] = {}
        self._install_metadata_reader: Callable[[], Any] | None = None
        self._active_home: Callable[[], Any] | None = None
        self._mcp_config_reader: Callable[[], Any] | None = None
        self._detect_internal_apis()
        self._detect_profile_apis()

    @property
    def capabilities(self) -> CompatibilityCapabilities:
        """Return an immutable snapshot of the current compatibility state."""
        return CompatibilityCapabilities(
            raw_skill_reader=self._raw_skill_reader,
            plugin_skill_lookup=self._plugin_lookup,
            skill_lifecycle=self._skill_lifecycle,
            auxiliary_tasks=self._auxiliary_tasks,
            skills_tool_bootstrap=self._skills_tool_bootstrap,
            skill_execution_audit=self._skill_execution_audit,
            skill_execution_guard=self._skill_execution_guard,
            profile_discovery=self._profile_discovery,
            profile_configuration=self._profile_configuration,
            mcp_discovery=self._mcp_config_reader is not None,
            issues=tuple(self._issues),
        )

    def status_lines(self) -> list[str]:
        """Render concise capability lines for ``/skill-router status``."""
        capabilities = self.capabilities
        raw = "available" if capabilities.raw_skill_reader else "unavailable -> metadata-only"
        plugin = "available" if capabilities.plugin_skill_lookup else "unavailable"
        lifecycle = "available" if capabilities.skill_lifecycle else "unavailable"
        auxiliary = "available" if capabilities.auxiliary_tasks else "unavailable"
        audit = "available" if capabilities.skill_execution_audit else "unavailable"
        guard = "available" if capabilities.skill_execution_guard else "unavailable"
        discovery = "available" if capabilities.profile_discovery else "degraded"
        configuration = "available" if capabilities.profile_configuration else "degraded"
        mcp = "available" if capabilities.mcp_discovery else "unavailable"
        return [
            f"Hermes compatibility: {capabilities.status}",
            f"Raw skill reader: {raw}",
            f"Plugin skill lookup: {plugin}",
            f"Lifecycle support: {lifecycle}",
            f"Auxiliary tasks: {auxiliary}",
            f"Skill execution audit: {audit}",
            f"Skill execution guard: {guard}",
            f"Profile discovery: {discovery}",
            f"Profile configuration: {configuration}",
            f"Native MCP config discovery: {mcp}",
        ]

    def active_mcp_readiness(self) -> dict[str, bool | None] | None:
        """Return passive readiness by exact active-profile MCP server identity.

        ``True`` means the server has an enabled, structurally recognizable
        profile configuration. ``False`` means it is explicitly disabled.
        ``None`` means a named definition cannot be assessed passively. A
        top-level ``None`` means the Hermes config API itself is unavailable.
        """
        if self._mcp_config_reader is None:
            return None
        try:
            config = self._mcp_config_reader() or {}
        except Exception as exc:
            self._record_issue("MCP discovery", exc)
            return None
        if not isinstance(config, Mapping):
            return None
        servers = config.get("mcp_servers")
        if servers is None:
            return {}
        if not isinstance(servers, Mapping):
            return None
        readiness: dict[str, bool | None] = {}
        for raw_name, raw_definition in servers.items():
            name = raw_name if isinstance(raw_name, str) else ""
            if not name.strip():
                continue
            if not isinstance(raw_definition, Mapping):
                readiness[name] = None
                continue
            enabled = _mcp_enabled(raw_definition.get("enabled", True))
            if enabled is not True:
                readiness[name] = enabled
                continue
            recognizable = any(
                isinstance(raw_definition.get(key), str)
                and bool(str(raw_definition.get(key)).strip())
                for key in ("command", "url")
            )
            readiness[name] = True if recognizable else None
        return readiness

    def readiness_hints(self, metadata: Mapping[str, Any]) -> dict[str, Any]:
        """Normalize passive readiness fields exposed by Hermes skill metadata."""
        hints: dict[str, Any] = {}
        raw_status = str(metadata.get("readiness_status") or "").casefold()
        status_map = {
            "available": "ready",
            "ready": "ready",
            "setup_needed": "setup_required",
            "setup_required": "setup_required",
            "unsupported": "disabled",
            "disabled": "disabled",
            "broken": "broken",
            "unknown": "unknown",
        }
        if raw_status in status_map:
            hints["status"] = status_map[raw_status]
        for key in ("setup_needed", "setup_required", "disabled", "requirements"):
            if key in metadata:
                hints[key] = metadata.get(key)
        return hints

    def ensure_skills_tool_registration(self) -> bool:
        """Load Hermes' skills tool module when plugin CLI mode needs registration."""
        if self._skills_tool_bootstrap:
            return True
        try:
            self._module_loader("tools.skills_tool")
        except Exception as exc:
            self._record_issue("skills tool bootstrap", exc)
            return False
        self._skills_tool_bootstrap = True
        return True

    def register_auxiliary_task(self, **kwargs: Any) -> bool:
        """Register the planner task when the host exposes that feature."""
        if not self._auxiliary_tasks:
            return False
        try:
            self.ctx.register_auxiliary_task(**kwargs)
        except Exception as exc:
            self._auxiliary_tasks = False
            self._record_issue("auxiliary task registration", exc)
            return False
        return True

    def register_skill_lifecycle(self, callback: Callable[..., Any]) -> bool:
        """Register the lifecycle hook when the host accepts that event."""
        if not self._skill_lifecycle:
            return False
        try:
            self.ctx.register_hook("on_skill_lifecycle", callback)
        except Exception as exc:
            self._skill_lifecycle = False
            self._record_issue("skill lifecycle registration", exc)
            return False
        return True

    def register_skill_execution_guard(self, callback: Callable[..., Any]) -> bool:
        """Register the directive hook used by the turn-scoped execution guard."""
        if not self._skill_execution_guard:
            return False

        def on_pre_tool_call(**kwargs: Any) -> Any:
            tool_name = str(kwargs.get("tool_name") or "")
            raw_args = kwargs.get("args")
            safe_args: dict[str, Any] = {}
            if tool_name == "skill_view" and isinstance(raw_args, dict):
                safe_args["name"] = raw_args.get("name") or raw_args.get("skill_name")
                safe_args["loads_primary_document"] = not bool(raw_args.get("file_path"))
            return callback(
                tool_name=tool_name,
                args=safe_args,
                task_id=kwargs.get("task_id", ""),
                turn_id=kwargs.get("turn_id", ""),
                session_id=kwargs.get("session_id", ""),
                tool_call_id=kwargs.get("tool_call_id", ""),
                api_request_id=kwargs.get("api_request_id", ""),
            )

        try:
            self.ctx.register_hook("pre_tool_call", on_pre_tool_call)
        except Exception as exc:
            self._skill_execution_guard = False
            self._record_issue("skill execution guard registration", exc)
            return False
        return True

    def register_skill_execution_audit(
        self,
        post_tool_callback: Callable[..., Any],
        post_llm_callback: Callable[..., Any],
    ) -> bool:
        """Register passive tool and turn observers when both hooks are accepted."""
        if not self._skill_execution_audit:
            return False

        def on_post_tool_call(**kwargs: Any) -> None:
            if self._skill_execution_audit:
                tool_name = str(kwargs.get("tool_name") or "")
                raw_args = kwargs.get("args")
                safe_args: dict[str, Any] = {}
                if tool_name == "skill_view" and isinstance(raw_args, dict):
                    safe_args["name"] = raw_args.get("name") or raw_args.get("skill_name")
                    safe_args["loads_primary_document"] = not bool(raw_args.get("file_path"))
                post_tool_callback(
                    tool_name=tool_name,
                    args=safe_args,
                    task_id=kwargs.get("task_id", ""),
                    turn_id=kwargs.get("turn_id", ""),
                    session_id=kwargs.get("session_id", ""),
                    tool_call_id=kwargs.get("tool_call_id", ""),
                    status=kwargs.get("status", ""),
                )

        def on_post_llm_call(**kwargs: Any) -> None:
            if self._skill_execution_audit:
                post_llm_callback(
                    task_id=kwargs.get("task_id", ""),
                    turn_id=kwargs.get("turn_id", ""),
                    session_id=kwargs.get("session_id", ""),
                )

        try:
            self.ctx.register_hook("post_tool_call", on_post_tool_call)
            self.ctx.register_hook("post_llm_call", on_post_llm_call)
        except Exception as exc:
            self._skill_execution_audit = False
            self._record_issue("skill execution audit registration", exc)
            return False
        return True

    def read_visible_skill_files(
        self,
        visible_names: set[str],
        *,
        max_chars: int,
    ) -> tuple[dict[str, str], str]:
        """Read approved skill files or return a metadata-only fallback."""
        if not self._raw_skill_reader or not self._plugin_lookup:
            return {}, "metadata-only"

        try:
            project_roots = {
                _resolved(path)
                for path in self._raw_functions["get_project_skills_dirs"]()
            }
            content_by_name: dict[str, str] = {}
            for root in self._raw_functions["get_scan_ordered_skills_dirs"]():
                iterator = (
                    self._raw_functions["iter_project_skill_files"](root)
                    if _resolved(root) in project_roots
                    else self._raw_functions["iter_skill_index_files"](root, "SKILL.md")
                )
                for skill_md in iterator:
                    safe_path = _contained_skill_path(Path(skill_md), Path(root))
                    if safe_path is None:
                        continue
                    content = _read_utf8(safe_path, max_chars)
                    name = _frontmatter_name(content) or safe_path.parent.name
                    if name in visible_names and ":" not in name and name not in content_by_name:
                        content_by_name[name] = content
        except Exception as exc:
            self._raw_skill_reader = False
            self._record_issue("raw skill reader", exc)
            return {}, "metadata-only"

        try:
            for name in visible_names:
                if ":" not in name:
                    continue
                path = self._plugin_skill_lookup(name) if self._plugin_skill_lookup else None
                if path is not None and Path(path).is_file():
                    content_by_name[name] = _read_utf8(Path(path), max_chars)
        except Exception as exc:
            self._plugin_lookup = False
            self._record_issue("plugin skill lookup", exc)
            return {}, "metadata-only"

        return content_by_name, "raw-path-current-hermes"

    def profile_scope_id(self) -> str:
        """Return an opaque stable token for the active Hermes home."""
        profile_name = str(getattr(self.ctx, "profile_name", "custom") or "custom")
        home: Any = None
        get_profile_dir = self._profile_functions.get("get_profile_dir")
        if get_profile_dir is not None and profile_name != "custom":
            try:
                home = get_profile_dir(profile_name)
            except Exception:
                home = None
        if home is None and self._active_home is not None:
            try:
                home = self._active_home()
            except Exception:
                home = None
        if home is None:
            state_path = getattr(getattr(self.ctx, "state", None), "path", None)
            if state_path is not None:
                try:
                    home = Path(state_path).resolve().parents[2]
                except (IndexError, OSError):
                    home = None
        identity = _resolved(home) if home is not None else f"unresolved:{profile_name}"
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        return f"home-v1:{digest}"

    def discover_profiles(self) -> list[DiscoveredProfile]:
        """Return live profiles through Hermes without reading their config files."""
        if not self._profile_discovery:
            return []
        list_names = self._profile_functions["list_profile_names"]
        exists = self._profile_functions["profile_exists"]
        get_dir = self._profile_functions["get_profile_dir"]
        validate = self._profile_functions["validate_profile_name"]
        discovered: dict[str, DiscoveredProfile] = {}
        try:
            raw_names = list_names()
        except Exception as exc:
            self._profile_discovery = False
            self._profile_configuration = False
            self._record_issue("profile discovery", exc)
            raise ProfileDiscoveryError("Hermes profile discovery failed") from exc
        if not isinstance(raw_names, (list, tuple, set)):
            self._profile_discovery = False
            self._profile_configuration = False
            raise ProfileDiscoveryError("Hermes profile discovery returned invalid data")
        for raw_name in raw_names:
            name = str(raw_name or "").strip()
            try:
                validate(name)
                if not exists(name):
                    continue
                _ = Path(get_dir(name)).expanduser().resolve(strict=False)
            except Exception as exc:
                self._profile_discovery = False
                self._profile_configuration = False
                self._record_issue(f"profile {name[:64] or '<empty>'}", exc)
                raise ProfileDiscoveryError(
                    "Hermes profile discovery failed during profile validation"
                ) from exc
            discovered[name] = DiscoveredProfile(name=name)
        return [discovered[name] for name in sorted(discovered)]

    def inspect_profile(self, profile_name: str) -> ProfileInspection:
        """Inspect only Router metadata exposed by Hermes CLI for one profile."""
        listing = self.run_profile_command(
            profile_name,
            ("plugins", "list", "--json", "--no-bundled"),
        )
        if listing.returncode != 0:
            return ProfileInspection(
                name=profile_name,
                installed=False,
                enabled=False,
                error=f"plugin inventory exited {listing.returncode}",
            )
        installed = False
        enabled = False
        version = ""
        try:
            plugin_entries = json.loads(listing.stdout)
        except (TypeError, ValueError):
            plugin_entries = None
        if not isinstance(plugin_entries, list):
            return ProfileInspection(
                name=profile_name,
                installed=False,
                enabled=False,
                error="plugin inventory returned invalid data",
            )
        for entry in plugin_entries:
            if not isinstance(entry, dict) or entry.get("name") != "skill-router":
                continue
            installed = True
            status = str(entry.get("status") or "").casefold()
            enabled = status == "enabled"
            version = str(entry.get("version") or "")[:40]
            break

        settings: list[tuple[str, str | None]] = []
        for key in _SAFE_SETUP_DEFAULTS:
            value: str | None = None
            for section in ("settings", "config"):
                result = self.run_profile_command(
                    profile_name,
                    ("config", "get", f"plugins.entries.skill-router.{section}.{key}"),
                )
                if result.returncode == 0:
                    value = result.stdout.strip()[:100]
                    break
            settings.append((key, value))

        skill_count: int | None = None
        routing_mode = ""
        enforcement_mode = ""
        learning_mode = ""
        openviking_enabled: bool | None = None
        error = ""
        if enabled:
            status = self.run_profile_command(profile_name, ("skill-router", "status"))
            if status.returncode != 0:
                error = f"router status exited {status.returncode}"
            else:
                fields = _status_fields(status.stdout)
                skill_count = _optional_int(fields.get("Indexed skills"))
                routing_mode = fields.get("Routing mode", "")[:40]
                enforcement_mode = fields.get("Enforcement mode", "")[:40]
                learning_mode = fields.get("Learning", "")[:40]
                raw_openviking = fields.get("OpenViking enabled/synced", "").split("/", 1)[0].strip()
                if raw_openviking in {"True", "False"}:
                    openviking_enabled = raw_openviking == "True"
        return ProfileInspection(
            name=profile_name,
            installed=installed,
            enabled=enabled,
            version=version,
            skill_count=skill_count,
            routing_mode=routing_mode,
            enforcement_mode=enforcement_mode,
            learning_mode=learning_mode,
            openviking_enabled=openviking_enabled,
            settings=tuple(settings),
            error=error,
        )

    def current_plugin_install_spec(self) -> PluginInstallSpec:
        """Return the scrubbed source and exact installed revision when recorded."""
        source = ""
        revision = ""
        if self._install_metadata_reader is not None:
            try:
                metadata = self._install_metadata_reader()
                entry = metadata.get("skill-router") if isinstance(metadata, dict) else None
                if isinstance(entry, dict):
                    candidate = _safe_install_source(entry.get("source"))
                    if candidate is not None:
                        source = candidate
                    candidate_revision = str(entry.get("revision") or "").casefold()
                    if _EXACT_REVISION.fullmatch(candidate_revision):
                        revision = candidate_revision
            except Exception as exc:
                self._record_issue("plugin install metadata", exc)
        return PluginInstallSpec(source=source, revision=revision)

    def run_profile_command(
        self,
        profile_name: str,
        argv: Sequence[str],
        *,
        timeout_seconds: int = 180,
    ) -> ProfileCommandResult:
        """Run one official Hermes CLI operation without a shell or stderr disclosure."""
        if not self._profile_configuration:
            return ProfileCommandResult(returncode=2)
        validate = self._profile_functions.get("validate_profile_name")
        try:
            if validate is None:
                raise RuntimeError("profile validation unavailable")
            validate(profile_name)
            executable = self._hermes_executable or shutil.which("hermes")
            if not executable:
                raise RuntimeError("Hermes executable unavailable")
            completed = self._command_runner(
                [executable, "--profile", profile_name, *argv],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(1, min(int(timeout_seconds), 600)),
                stdin=subprocess.DEVNULL,
                check=False,
            )
        except Exception as exc:
            self._record_issue("profile configuration", exc)
            return ProfileCommandResult(returncode=1)
        return ProfileCommandResult(
            returncode=int(getattr(completed, "returncode", 1)),
            stdout=str(getattr(completed, "stdout", "")),
        )

    def _detect_internal_apis(self) -> None:
        for module_name in ("hermes_cli.config", "hermes_agent.cli.config"):
            try:
                config_module = self._module_loader(module_name)
            except Exception:
                continue
            reader = getattr(config_module, "load_config_readonly", None)
            if callable(reader):
                self._mcp_config_reader = reader
                break
        if self._mcp_config_reader is None:
            self._issues.append("Hermes MCP config API is unavailable")

        try:
            skill_utils = self._module_loader("agent.skill_utils")
        except Exception as exc:
            self._record_issue("agent.skill_utils", exc)
        else:
            missing: list[str] = []
            for name in _RAW_API_NAMES:
                value = getattr(skill_utils, name, None)
                if callable(value):
                    self._raw_functions[name] = value
                else:
                    missing.append(name)
            self._raw_skill_reader = not missing
            if missing:
                self._issues.append("missing agent.skill_utils APIs: " + ", ".join(missing))

        try:
            plugins = self._module_loader("hermes_cli.plugins")
        except Exception as exc:
            self._skill_execution_guard = False
            self._record_issue("Hermes hook catalog", exc)
            self._record_issue("plugin skill lookup", exc)
            return

        valid_hooks = getattr(plugins, "VALID_HOOKS", None)
        if not isinstance(valid_hooks, (set, frozenset, list, tuple)) or "pre_tool_call" not in valid_hooks:
            self._skill_execution_guard = False
            self._issues.append("pre_tool_call is absent from the Hermes hook catalog")

        try:
            manager_factory = getattr(plugins, "get_plugin_manager", None)
            if not callable(manager_factory):
                raise AttributeError("get_plugin_manager is unavailable")
            manager = manager_factory()
            lookup = getattr(manager, "find_plugin_skill", None)
            if not callable(lookup):
                raise AttributeError("find_plugin_skill is unavailable")
        except Exception as exc:
            self._record_issue("plugin skill lookup", exc)
        else:
            self._plugin_skill_lookup = lookup
            self._plugin_lookup = True

    def _detect_profile_apis(self) -> None:
        profiles = None
        for module_name in ("hermes_cli.profiles", "hermes_agent.cli.profiles"):
            try:
                profiles = self._module_loader(module_name)
            except Exception:
                continue
            break
        required = (
            "list_profile_names",
            "profile_exists",
            "get_profile_dir",
            "validate_profile_name",
        )
        if profiles is None:
            self._issues.append("Hermes profile API is unavailable")
        else:
            missing = []
            for name in required:
                value = getattr(profiles, name, None)
                if callable(value):
                    self._profile_functions[name] = value
                else:
                    missing.append(name)
            self._profile_discovery = not missing
            if missing:
                self._issues.append("missing Hermes profile APIs: " + ", ".join(missing))

        for module_name in ("hermes_constants", "hermes_agent.constants"):
            try:
                constants = self._module_loader(module_name)
            except Exception:
                continue
            active_home = getattr(constants, "get_hermes_home", None)
            if callable(active_home):
                self._active_home = active_home
                break

        for module_name in ("hermes_cli.plugins_cmd", "hermes_agent.cli.plugins_cmd"):
            try:
                plugins_cmd = self._module_loader(module_name)
            except Exception:
                continue
            reader = getattr(plugins_cmd, "_read_install_metadata", None)
            if callable(reader):
                self._install_metadata_reader = reader
                break

        self._profile_configuration = self._profile_discovery and bool(
            self._hermes_executable or shutil.which("hermes")
        )
        if self._profile_discovery and not self._profile_configuration:
            self._issues.append("Hermes executable is unavailable for profile configuration")

    def _record_issue(self, capability: str, exc: Exception) -> None:
        detail = f"{capability}: {type(exc).__name__}: {exc}"
        if detail not in self._issues:
            self._issues.append(detail)


def _contained_skill_path(path: Path, root: Path) -> Path | None:
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root.resolve(strict=True))
    except (OSError, ValueError):
        return None
    return resolved if resolved.is_file() else None


def _read_utf8(path: Path, max_chars: int) -> str:
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        return handle.read(max_chars)


def _frontmatter_name(content: str) -> str:
    if not content.startswith("---"):
        return ""
    end = content.find("\n---", 3)
    if end < 0:
        return ""
    match = re.search(r"(?m)^name:\s*['\"]?([^'\"#\n]+)", content[3:end])
    return match.group(1).strip() if match else ""


def _resolved(path: Any) -> str:
    try:
        return str(Path(path).expanduser().resolve())
    except OSError:
        return str(Path(path).expanduser())


def _mcp_enabled(value: Any) -> bool | None:
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    return None


def _running_hermes_executable() -> str | None:
    candidate = Path(sys.argv[0]) if sys.argv else Path()
    if candidate.name.casefold() not in {"hermes", "hermes.exe"}:
        return None
    try:
        return str(candidate.resolve(strict=True))
    except OSError:
        return None


def _safe_install_source(value: Any) -> str | None:
    candidate = str(value or "").strip()
    if not candidate or "\x00" in candidate or "\n" in candidate or "\r" in candidate:
        return None
    if Path(candidate).is_absolute():
        return candidate
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", candidate):
        return candidate
    parsed = urlsplit(candidate)
    if (
        parsed.scheme == "file"
        and parsed.netloc in {"", "localhost"}
        and Path(parsed.path).is_absolute()
        and not parsed.query
        and not parsed.fragment
    ):
        return candidate
    if (
        parsed.scheme == "https"
        and parsed.hostname == "github.com"
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
        and re.fullmatch(r"/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?", parsed.path)
    ):
        return candidate
    return None


def _status_fields(output: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in output.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if key in {"Indexed skills", "Routing mode", "Enforcement mode", "Learning", "OpenViking enabled/synced"}:
            fields[key] = value.strip()
    return fields


def _optional_int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None
