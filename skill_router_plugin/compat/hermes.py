"""Feature-detected access to version-dependent Hermes APIs."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
from pathlib import Path
import re
from typing import Any, Callable, Mapping

_RAW_API_NAMES = (
    "get_project_skills_dirs",
    "get_scan_ordered_skills_dirs",
    "iter_project_skill_files",
    "iter_skill_index_files",
)


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
        )
        return "full" if all(required) else "degraded"


class HermesCompatibility:
    """Resolve internal Hermes APIs once and provide safe fallbacks."""

    def __init__(
        self,
        ctx: Any,
        *,
        module_loader: Callable[[str], Any] | None = None,
    ) -> None:
        self.ctx = ctx
        self._module_loader = module_loader or importlib.import_module
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
        self._detect_internal_apis()

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
        return [
            f"Hermes compatibility: {capabilities.status}",
            f"Raw skill reader: {raw}",
            f"Plugin skill lookup: {plugin}",
            f"Lifecycle support: {lifecycle}",
            f"Auxiliary tasks: {auxiliary}",
            f"Skill execution audit: {audit}",
            f"Skill execution guard: {guard}",
        ]

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

    def _detect_internal_apis(self) -> None:
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
