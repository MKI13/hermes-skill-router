"""Bounded, profile-scoped observation of routed and loaded skills."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import threading
from typing import Any

_AUDIT_STATE_KEY = "router.audit"
_AUDIT_VERSION = 1
_RESULTS = {"complete", "partial", "missed", "not_applicable", "unknown"}


class SkillExecutionAudit:
    """Persist compact routing and skill-view execution metadata."""

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self._lock = threading.RLock()

    def record_decision(
        self,
        *,
        task: str,
        task_id: str,
        turn_id: str,
        session_id: str,
        method: str,
        recommended: list[dict[str, Any]],
        policy_status: str = "unknown",
        enforcement_mode: str = "off",
        enforcement_status: str = "not_required",
        block_count: int = 0,
        primary_loaded_before_task_tools: bool | None = None,
        execution_observable: bool,
    ) -> None:
        """Append one bounded decision without retaining the full user prompt."""
        try:
            compact_recommendations = _recommendations(recommended)
            now = _utc_now()
            entry = {
                "task_id": _opaque_id(task_id),
                "turn_id": _opaque_id(turn_id),
                "session_id": _opaque_id(session_id),
                "timestamp": now,
                "profile": str(getattr(self.ctx, "profile_name", "default"))[:100],
                "method": str(method or "unknown")[:40],
                "policy_status": _policy_status(policy_status),
                "enforcement_mode": _enforcement_mode(enforcement_mode),
                "enforcement_status": _enforcement_status(enforcement_status),
                "block_count": _block_count(block_count),
                "primary_loaded_before_task_tools": _optional_bool(
                    primary_loaded_before_task_tools
                ),
                "task_hash": hashlib.sha256(task.encode("utf-8", errors="replace")).hexdigest(),
                "recommended": compact_recommendations,
                "executions": [],
                "result": "unknown",
                "primary_loaded": None,
                "finalized": False,
            }
            if not compact_recommendations:
                entry["result"] = "not_applicable"
                entry["finalized"] = True
            elif not execution_observable:
                entry["finalized"] = True
            with self._lock:
                state = self._load_state()
                self._finalize_stale_entries(state["entries"], entry)
                state["entries"].append(entry)
                state["entries"] = state["entries"][-self._history_limit():]
                self._save_state(state)
        except Exception:
            return

    def observe_tool_call(
        self,
        *,
        tool_name: str = "",
        args: Any = None,
        task_id: str = "",
        turn_id: str = "",
        session_id: str = "",
        status: str = "",
        **kwargs: Any,
    ) -> None:
        """Record one sanitized ``skill_view`` outcome and ignore tool payloads."""
        del kwargs
        if tool_name != "skill_view" or not isinstance(args, dict):
            return
        if args.get("loads_primary_document") is False:
            return
        name = _skill_name(args)
        if not name:
            return
        try:
            with self._lock:
                state = self._load_state()
                entry = _find_open_entry(
                    state["entries"], task_id=task_id, turn_id=turn_id, session_id=session_id
                )
                if entry is None:
                    return
                recommended_names = {
                    str(item.get("name") or "")
                    for item in entry.get("recommended", [])
                    if isinstance(item, dict)
                }
                if name not in recommended_names:
                    return
                success = str(status).casefold() == "ok"
                executions = entry["executions"]
                existing = next(
                    (item for item in executions if item.get("name") == name),
                    None,
                )
                if existing is None:
                    executions.append({
                        "name": name,
                        "timestamp": _utc_now(),
                        "success": success,
                    })
                elif success and not existing.get("success"):
                    existing["success"] = True
                    existing["timestamp"] = _utc_now()
                self._save_state(state)
        except Exception:
            return

    def update_enforcement(
        self,
        *,
        task_id: str = "",
        turn_id: str = "",
        session_id: str = "",
        enforcement: dict[str, Any] | None,
    ) -> None:
        """Merge compact guard metadata into the matching open audit entry."""
        if not isinstance(enforcement, dict):
            return
        try:
            with self._lock:
                state = self._load_state()
                entry = _find_open_entry(
                    state["entries"], task_id=task_id, turn_id=turn_id, session_id=session_id
                )
                if entry is None:
                    return
                entry["enforcement_mode"] = _enforcement_mode(enforcement.get("mode"))
                entry["enforcement_status"] = _enforcement_status(enforcement.get("status"))
                entry["block_count"] = _block_count(enforcement.get("block_count"))
                entry["primary_loaded_before_task_tools"] = _optional_bool(
                    enforcement.get("primary_loaded_before_task_tools")
                )
                self._save_state(state)
        except Exception:
            return

    def finalize_turn(
        self,
        *,
        task_id: str = "",
        turn_id: str = "",
        session_id: str = "",
        **kwargs: Any,
    ) -> None:
        """Assess the matching decision after successful turn finalization."""
        del kwargs
        try:
            with self._lock:
                state = self._load_state()
                entry = _find_open_entry(
                    state["entries"], task_id=task_id, turn_id=turn_id, session_id=session_id
                )
                if entry is None:
                    return
                _assess(entry)
                entry["finalized"] = True
                self._save_state(state)
        except Exception:
            return

    def status_fields(self, *, available: bool) -> tuple[str, int, str]:
        """Return availability, bounded entry count, and latest result."""
        try:
            with self._lock:
                entries = self._load_state()["entries"]
        except Exception:
            entries = []
        return (
            "available" if available else "unavailable",
            len(entries),
            str(entries[-1].get("result") or "unknown") if entries else "none",
        )

    def summary_text(self, limit: int = 20) -> str:
        """Render aggregate results for the latest bounded entries."""
        entries = self._recent_entries(limit)
        counts = {result: 0 for result in _RESULTS}
        for entry in entries:
            result = str(entry.get("result") or "unknown")
            counts[result if result in counts else "unknown"] += 1
        assessable = [
            entry for entry in entries
            if isinstance(entry.get("primary_loaded"), bool)
        ]
        primary_loaded = sum(1 for entry in assessable if entry.get("primary_loaded") is True)
        return "\n".join([
            "Skill Router Audit",
            "",
            f"Last {len(entries)} routed tasks:",
            f"Complete: {counts['complete']}",
            f"Partial: {counts['partial']}",
            f"Missed: {counts['missed']}",
            f"Not applicable: {counts['not_applicable']}",
            f"Unknown: {counts['unknown']}",
            "",
            "Primary skill loaded:",
            f"{primary_loaded} / {len(assessable)} assessable tasks",
        ])

    def last_text(self) -> str:
        """Render the latest decision and observed executions."""
        entries = self._recent_entries(1)
        if not entries:
            return "Skill Router Audit\n\nNo audit entries."
        entry = entries[-1]
        recommended = entry.get("recommended", [])
        executions = entry.get("executions", [])
        loaded = {
            str(item.get("name")): bool(item.get("success"))
            for item in executions
            if isinstance(item, dict) and item.get("name")
        }
        task_label = str(entry.get("task_hash") or "unknown")[:12]
        lines = [
            f"Task: {task_label}",
            f"Routing method: {entry.get('method', 'unknown')}",
            f"Policy: {entry.get('policy_status', 'unknown')}",
            f"Enforcement: {entry.get('enforcement_mode', 'off')}",
            f"Guard: {entry.get('enforcement_status', 'not_required')}",
            "",
            "Recommended:",
        ]
        if recommended:
            for item in recommended:
                role = str(item.get("role") or "supporting").upper()
                lines.append(f"{item.get('order')}. {item.get('name')} [{role}]")
        else:
            lines.append("none")
        lines.extend(["", "Loaded:"])
        if recommended:
            for item in recommended:
                name = str(item.get("name") or "")
                if name not in loaded:
                    answer = "no"
                else:
                    answer = "yes" if loaded[name] else "error"
                lines.append(f"{name}: {answer}")
        else:
            lines.append("none")
        primary = entry.get("primary_loaded")
        primary_text = "yes" if primary is True else "no" if primary is False else "unknown"
        before_tools = entry.get("primary_loaded_before_task_tools")
        before_tools_text = (
            "yes" if before_tools is True else "no" if before_tools is False else "unknown"
        )
        lines.extend([
            "",
            f"Primary loaded before task tools: {before_tools_text}",
            f"Blocks: {entry.get('block_count', 0)}",
            f"Result: {entry.get('result', 'unknown')}",
            f"Primary loaded: {primary_text}",
        ])
        return "\n".join(lines)

    def _recent_entries(self, limit: int) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), self._history_limit()))
        try:
            with self._lock:
                entries = self._load_state()["entries"]
        except Exception:
            return []
        return entries[-safe_limit:]

    def _history_limit(self) -> int:
        return self._int_setting("max_audit_entries", 100, minimum=10, maximum=1000)

    def _int_setting(self, key: str, default: int, *, minimum: int, maximum: int) -> int:
        value = self.ctx.get_config(key, default)
        if isinstance(value, bool) or not isinstance(value, int):
            value = default
        return max(minimum, min(maximum, value))

    def _load_state(self) -> dict[str, Any]:
        try:
            raw = self.ctx.state.get(_AUDIT_STATE_KEY, default={})
        except Exception:
            return _empty_state()
        if not isinstance(raw, dict) or raw.get("version") != _AUDIT_VERSION:
            return _empty_state()
        entries = raw.get("entries")
        if not isinstance(entries, list):
            return _empty_state()
        normalized = [
            selected for item in entries
            if isinstance(item, dict)
            for selected in [_normalize_entry(item)]
            if selected is not None
        ]
        return {"version": _AUDIT_VERSION, "entries": normalized[-self._history_limit():]}

    def _save_state(self, state: dict[str, Any]) -> None:
        try:
            self.ctx.state.set(_AUDIT_STATE_KEY, state)
        except Exception:
            return

    @staticmethod
    def _finalize_stale_entries(entries: list[dict[str, Any]], new_entry: dict[str, Any]) -> None:
        new_turn = str(new_entry.get("turn_id") or "")
        new_task = str(new_entry.get("task_id") or "")
        new_session = str(new_entry.get("session_id") or "")
        for entry in entries:
            if entry.get("finalized") or not new_session:
                continue
            if entry.get("session_id") != new_session:
                continue
            same_identity = (
                (new_turn and entry.get("turn_id") == new_turn)
                or (new_task and entry.get("task_id") == new_task)
            )
            if not same_identity:
                entry["result"] = "unknown"
                entry["primary_loaded"] = None
                entry["finalized"] = True


def _empty_state() -> dict[str, Any]:
    return {"version": _AUDIT_VERSION, "entries": []}


def _recommendations(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values[:5]:
        if not isinstance(value, dict):
            continue
        name = _safe_name(value.get("name"))
        if not name or name in seen:
            continue
        seen.add(name)
        output.append({
            "name": name,
            "role": "primary" if value.get("role") == "primary" else "supporting",
            "order": len(output) + 1,
        })
    return output


def _normalize_entry(value: dict[str, Any]) -> dict[str, Any] | None:
    recommended = _recommendations(value.get("recommended", []))
    executions: list[dict[str, Any]] = []
    seen: set[str] = set()
    raw_executions = value.get("executions")
    if isinstance(raw_executions, list):
        for item in raw_executions[:20]:
            if not isinstance(item, dict):
                continue
            name = _safe_name(item.get("name"))
            if not name or name in seen:
                continue
            seen.add(name)
            executions.append({
                "name": name,
                "timestamp": str(item.get("timestamp") or "")[:40],
                "success": bool(item.get("success")),
            })
    result = str(value.get("result") or "unknown")
    if result not in _RESULTS:
        result = "unknown"
    primary = value.get("primary_loaded")
    if not isinstance(primary, bool):
        primary = None
    normalized = {
        "task_id": _opaque_id(value.get("task_id")),
        "turn_id": _opaque_id(value.get("turn_id")),
        "session_id": _opaque_id(value.get("session_id")),
        "timestamp": str(value.get("timestamp") or "")[:40],
        "profile": str(value.get("profile") or "default")[:100],
        "method": str(value.get("method") or "unknown")[:40],
        "policy_status": _policy_status(value.get("policy_status")),
        "enforcement_mode": _enforcement_mode(value.get("enforcement_mode")),
        "enforcement_status": _enforcement_status(value.get("enforcement_status")),
        "block_count": _block_count(value.get("block_count")),
        "primary_loaded_before_task_tools": _optional_bool(
            value.get("primary_loaded_before_task_tools")
        ),
        "task_hash": str(value.get("task_hash") or "")[:64],
        "recommended": recommended,
        "executions": executions,
        "result": result,
        "primary_loaded": primary,
        "finalized": bool(value.get("finalized")),
    }
    return normalized


def _find_open_entry(
    entries: list[dict[str, Any]],
    *,
    task_id: str,
    turn_id: str,
    session_id: str,
) -> dict[str, Any] | None:
    selected_turn = _opaque_id(turn_id)
    selected_task = _opaque_id(task_id)
    selected_session = _opaque_id(session_id)
    for entry in reversed(entries):
        if entry.get("finalized"):
            continue
        if selected_session and entry.get("session_id") != selected_session:
            continue
        if selected_turn and entry.get("turn_id") == selected_turn:
            return entry
        if selected_task and entry.get("task_id") == selected_task:
            return entry
    return None


def _assess(entry: dict[str, Any]) -> None:
    recommended = entry.get("recommended", [])
    if not recommended:
        entry["result"] = "not_applicable"
        entry["primary_loaded"] = None
        return
    loaded = {
        str(item.get("name"))
        for item in entry.get("executions", [])
        if isinstance(item, dict) and item.get("success") is True
    }
    recommended_names = [str(item.get("name")) for item in recommended]
    matched = set(recommended_names) & loaded
    if len(matched) == len(recommended_names):
        entry["result"] = "complete"
    elif matched:
        entry["result"] = "partial"
    else:
        entry["result"] = "missed"
    primary = next(
        (str(item.get("name")) for item in recommended if item.get("role") == "primary"),
        recommended_names[0],
    )
    entry["primary_loaded"] = primary in loaded


def _skill_name(args: dict[str, Any]) -> str:
    return _safe_name(args.get("name") or args.get("skill_name"))


def _safe_name(value: Any) -> str:
    text = " ".join(str(value or "").split()).strip()[:200]
    if not text or any(ord(char) < 32 for char in text):
        return ""
    return text


def _opaque_id(value: Any) -> str:
    return " ".join(str(value or "").split())[:200]


def _enforcement_mode(value: Any) -> str:
    selected = str(value or "off")
    return selected if selected in {"off", "warn", "primary", "all"} else "off"


def _enforcement_status(value: Any) -> str:
    selected = str(value or "not_required")
    allowed = {
        "not_required",
        "policy_blocked",
        "pending",
        "satisfied",
        "warned",
        "blocked",
        "exhausted",
        "unavailable",
        "error",
    }
    return selected if selected in allowed else "error"


def _block_count(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(0, min(value, 5))


def _optional_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _policy_status(value: Any) -> str:
    selected = str(value or "unknown")
    return selected if selected in {"valid", "adjusted", "degraded", "blocked"} else "unknown"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
