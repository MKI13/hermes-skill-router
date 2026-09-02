"""Turn-isolated execution guard for validated skill plans."""

from __future__ import annotations

from datetime import datetime, timezone
import threading
from typing import Any

from .readiness import READY, SETUP_REQUIRED, UNKNOWN

_ENFORCEABLE_READINESS = {READY, UNKNOWN, SETUP_REQUIRED}
_ALWAYS_ALLOWED_TOOLS = {"skill_view", "skills_list"}
_MODES = {"off", "warn", "primary", "all"}
_STATUSES = {
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


class SkillExecutionGuard:
    """Track required skill loads and gate task tools per Hermes turn identity."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._turns: dict[tuple[str, str], dict[str, Any]] = {}
        self._sequence = 0

    def start_turn(
        self,
        *,
        task_id: str,
        turn_id: str,
        session_id: str,
        policy_status: str,
        selections: list[dict[str, Any]],
        mode: str,
        max_blocks: int,
        available: bool,
    ) -> dict[str, Any]:
        """Create a fresh guard state from the final policy selection."""
        selected_mode = mode if mode in _MODES else "warn"
        safe_blocks = max(1, min(int(max_blocks), 5))
        identity = _identity(session_id=session_id, turn_id=turn_id, task_id=task_id)
        with self._lock:
            self._sequence += 1
            required, primary = _required_plan(selections, selected_mode)
            if policy_status == "blocked":
                status = "policy_blocked"
                required = []
                primary = ""
            elif identity is None or not available:
                status = "unavailable"
            elif selected_mode == "off" or not required:
                status = "not_required"
            else:
                status = "pending"
            state = {
                "task_id": _opaque(task_id),
                "turn_id": _opaque(turn_id),
                "session_id": _opaque(session_id),
                "policy_status": str(policy_status or "unknown")[:40],
                "required_skills": required,
                "primary_skill": primary,
                "loaded_skills": [],
                "failed_skills": [],
                "block_count": 0,
                "max_blocks": safe_blocks,
                "mode": selected_mode,
                "status": status,
                "primary_loaded_before_task_tools": None,
                "out_of_order_calls": [],
                "blocked_request_ids": [],
                "active": identity is not None,
                "sequence": self._sequence,
                "started_at": _utc_now(),
            }
            if identity is not None:
                self._turns[identity] = state
                self._prune()
            return _public_state(state)

    def before_tool_call(
        self,
        *,
        tool_name: str = "",
        args: Any = None,
        task_id: str = "",
        turn_id: str = "",
        session_id: str = "",
        tool_call_id: str = "",
        api_request_id: str = "",
    ) -> dict[str, str] | None:
        """Allow diagnostic/load tools and optionally block premature task tools."""
        if not tool_name:
            return None
        try:
            with self._lock:
                state = self._find(task_id=task_id, turn_id=turn_id, session_id=session_id)
                if state is None or not state.get("active"):
                    return None
                if tool_name == "skill_view":
                    self._observe_skill_view_order(state, args, tool_call_id)
                    return None
                if tool_name in _ALWAYS_ALLOWED_TOOLS:
                    return None
                if state["status"] in {
                    "not_required",
                    "policy_blocked",
                    "unavailable",
                    "error",
                    "satisfied",
                }:
                    if state["status"] == "satisfied":
                        self._record_first_allowed_task_tool(state)
                    return None
                missing = _missing(state)
                if not missing:
                    state["status"] = "satisfied"
                    self._record_first_allowed_task_tool(state)
                    return None
                if state["mode"] in {"off"}:
                    return None
                if state["mode"] == "warn":
                    state["status"] = "warned"
                    self._record_first_allowed_task_tool(state)
                    return None
                request_id = _opaque(api_request_id)
                if not request_id:
                    state["status"] = "unavailable"
                    self._record_first_allowed_task_tool(state)
                    return None
                if request_id and request_id in state["blocked_request_ids"]:
                    state["status"] = "blocked"
                    return {"action": "block", "message": _block_message(missing)}
                if state["status"] == "exhausted" or state["block_count"] >= state["max_blocks"]:
                    state["status"] = "exhausted"
                    self._record_first_allowed_task_tool(state)
                    return None
                state["block_count"] += 1
                if request_id:
                    state["blocked_request_ids"].append(request_id)
                state["status"] = "blocked"
                return {
                    "action": "block",
                    "message": _block_message(missing),
                }
        except Exception:
            self._mark_error(task_id=task_id, turn_id=turn_id, session_id=session_id)
            return None

    def after_tool_call(
        self,
        *,
        tool_name: str = "",
        args: Any = None,
        task_id: str = "",
        turn_id: str = "",
        session_id: str = "",
        tool_call_id: str = "",
        status: str = "",
    ) -> dict[str, Any] | None:
        """Count only successful, correctly ordered required ``skill_view`` calls."""
        try:
            with self._lock:
                state = self._find(task_id=task_id, turn_id=turn_id, session_id=session_id)
                if state is None or not state.get("active"):
                    return None
                if tool_name != "skill_view" or not isinstance(args, dict):
                    return _public_state(state)
                if args.get("loads_primary_document") is False:
                    return _public_state(state)
                name = _skill_name(args)
                if not name or name not in state["required_skills"]:
                    return _public_state(state)
                call_key = _call_key(tool_call_id, name)
                if call_key in state["out_of_order_calls"]:
                    state["out_of_order_calls"].remove(call_key)
                    return _public_state(state)
                if str(status).casefold() != "ok":
                    if name not in state["failed_skills"]:
                        state["failed_skills"].append(name)
                    return _public_state(state)
                expected = _next_required(state)
                if name == expected and name not in state["loaded_skills"]:
                    state["loaded_skills"].append(name)
                if not _missing(state):
                    state["status"] = "satisfied"
                elif state["status"] not in {"warned", "exhausted"}:
                    state["status"] = "pending"
                return _public_state(state)
        except Exception:
            self._mark_error(task_id=task_id, turn_id=turn_id, session_id=session_id)
            return None

    def finish_turn(
        self,
        *,
        task_id: str = "",
        turn_id: str = "",
        session_id: str = "",
    ) -> dict[str, Any] | None:
        """Return final guard metadata and deactivate the matching turn."""
        try:
            with self._lock:
                state = self._find(task_id=task_id, turn_id=turn_id, session_id=session_id)
                if state is None:
                    return None
                state["active"] = False
                return _public_state(state)
        except Exception:
            return None

    def snapshot(
        self,
        *,
        task_id: str = "",
        turn_id: str = "",
        session_id: str = "",
    ) -> dict[str, Any] | None:
        """Return owned metadata for one matching turn."""
        try:
            with self._lock:
                state = self._find(task_id=task_id, turn_id=turn_id, session_id=session_id)
                return _public_state(state) if state is not None else None
        except Exception:
            return None

    def current(self) -> dict[str, Any] | None:
        """Return the newest active turn for diagnostics."""
        with self._lock:
            active = [state for state in self._turns.values() if state.get("active")]
            if not active:
                return None
            return _public_state(max(active, key=lambda item: int(item.get("sequence") or 0)))

    def _observe_skill_view_order(
        self,
        state: dict[str, Any],
        args: Any,
        tool_call_id: str,
    ) -> None:
        if not isinstance(args, dict) or args.get("loads_primary_document") is False:
            return
        name = _skill_name(args)
        if not name or name not in state["required_skills"] or name in state["loaded_skills"]:
            return
        expected = _next_required(state)
        if name != expected:
            key = _call_key(tool_call_id, name)
            if key not in state["out_of_order_calls"]:
                state["out_of_order_calls"].append(key)
            if state["mode"] == "warn":
                state["status"] = "warned"

    def _record_first_allowed_task_tool(self, state: dict[str, Any]) -> None:
        if state["primary_loaded_before_task_tools"] is not None:
            return
        primary = state.get("primary_skill")
        state["primary_loaded_before_task_tools"] = bool(
            primary and primary in state["loaded_skills"]
        )

    def _find(
        self,
        *,
        task_id: str,
        turn_id: str,
        session_id: str,
    ) -> dict[str, Any] | None:
        identity = _identity(session_id=session_id, turn_id=turn_id, task_id=task_id)
        return self._turns.get(identity) if identity is not None else None

    def _mark_error(self, *, task_id: str, turn_id: str, session_id: str) -> None:
        try:
            with self._lock:
                state = self._find(task_id=task_id, turn_id=turn_id, session_id=session_id)
                if state is not None:
                    state["status"] = "error"
        except Exception:
            return

    def _prune(self) -> None:
        if len(self._turns) <= 100:
            return
        inactive = sorted(
            (
                item
                for item in self._turns.items()
                if not item[1].get("active")
            ),
            key=lambda item: int(item[1].get("sequence") or 0),
        )
        for identity, _state in inactive:
            if len(self._turns) <= 100:
                break
            self._turns.pop(identity, None)


def _required_plan(
    selections: list[dict[str, Any]],
    mode: str,
) -> tuple[list[str], str]:
    enforceable: list[tuple[str, str]] = []
    for item in selections if isinstance(selections, list) else []:
        if not isinstance(item, dict):
            continue
        status = str(item.get("readiness_status") or UNKNOWN)
        name = _skill_name(item)
        if not name or status not in _ENFORCEABLE_READINESS:
            continue
        role = "primary" if item.get("role") == "primary" else "supporting"
        enforceable.append((name, role))
    primary_index = next(
        (index for index, (_name, role) in enumerate(enforceable) if role == "primary"),
        None,
    )
    if primary_index is None:
        return [], ""
    primary = enforceable[primary_index][0]
    selected = enforceable if mode == "all" else enforceable[: primary_index + 1]
    names: list[str] = []
    for name, _role in selected:
        if name not in names:
            names.append(name)
    return names, primary


def _identity(*, session_id: str, turn_id: str, task_id: str) -> tuple[str, str] | None:
    session = _opaque(session_id)
    turn = _opaque(turn_id) or _opaque(task_id)
    return (session, turn) if session and turn else None


def _missing(state: dict[str, Any]) -> list[str]:
    loaded = set(state.get("loaded_skills", []))
    return [name for name in state.get("required_skills", []) if name not in loaded]


def _next_required(state: dict[str, Any]) -> str:
    missing = _missing(state)
    return missing[0] if missing else ""


def _block_message(missing: list[str]) -> str:
    if len(missing) == 1:
        instruction = f"skill_view {missing[0]}"
        heading = "Load the required skill first:"
    else:
        instruction = "\n".join(f"{index}. {name}" for index, name in enumerate(missing, 1))
        heading = "Load required skills in this order:"
    return (
        "Skill Router execution guard:\n\n"
        f"{heading}\n\n{instruction}\n\n"
        "The validated routing plan requires this before task tools are used."
    )


def _public_state(state: dict[str, Any] | None) -> dict[str, Any] | None:
    if state is None:
        return None
    status = str(state.get("status") or "error")
    return {
        "task_id": _opaque(state.get("task_id")),
        "turn_id": _opaque(state.get("turn_id")),
        "policy_status": str(state.get("policy_status") or "unknown")[:40],
        "required_skills": _name_list(state.get("required_skills")),
        "loaded_skills": _name_list(state.get("loaded_skills")),
        "failed_skills": _name_list(state.get("failed_skills")),
        "block_count": max(0, int(state.get("block_count") or 0)),
        "mode": str(state.get("mode") or "warn"),
        "status": status if status in _STATUSES else "error",
        "primary_loaded_before_task_tools": state.get("primary_loaded_before_task_tools")
        if isinstance(state.get("primary_loaded_before_task_tools"), bool)
        else None,
    }


def _name_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_opaque(item) for item in value[:5] if _opaque(item)]


def _skill_name(value: dict[str, Any]) -> str:
    text = " ".join(str(value.get("name") or value.get("skill_name") or "").split())
    return text[:200]


def _call_key(tool_call_id: str, name: str) -> str:
    selected = _opaque(tool_call_id)
    return f"id:{selected}" if selected else f"name:{name}"


def _opaque(value: Any) -> str:
    return " ".join(str(value or "").split())[:200]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
