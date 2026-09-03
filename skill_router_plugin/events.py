"""Bounded, profile-scoped technical events for skill catalog changes."""

from __future__ import annotations

from datetime import datetime, timezone
import threading
from typing import Any

from .profile_identity import ProfileIdentity

EVENT_STATE_KEY = "router.events"
EVENT_STATE_VERSION = 1
MAX_EVENTS = 50
ALLOWED_EVENTS = frozenset({
    "skill_detected",
    "skill_updated",
    "skill_removed",
    "skill_refresh_failed",
})

_ALLOWED_RESULTS = frozenset({"added", "changed", "removed", "failed", "unavailable"})
_ALLOWED_READINESS = frozenset({
    "ready",
    "setup_required",
    "dependency_missing",
    "broken",
    "disabled",
    "unknown",
})
_EVENT_LABELS = {
    "skill_detected": "Detected",
    "skill_updated": "Updated",
    "skill_removed": "Removed",
    "skill_refresh_failed": "Refresh failed",
}
_STATE_LOCK = threading.RLock()
_DEFAULT_RENDER_LIMIT = 20


class SkillRouterEvents:
    """Persist and render sanitized technical events for one profile scope."""

    def __init__(self, ctx: Any, profile: ProfileIdentity) -> None:
        self.ctx = ctx
        self.profile = profile
        self._lock = _STATE_LOCK

    def record(
        self,
        event: Any,
        *,
        skill_name: Any = "",
        result: Any = "",
        readiness: Any = "",
        **ignored: Any,
    ) -> None:
        """Append one allowed event while discarding non-technical payload fields."""
        del ignored
        if (
            not isinstance(event, str)
            or event not in ALLOWED_EVENTS
            or not _valid_scope_token(self.profile.scope_token)
        ):
            return
        entry = {
            "timestamp": _utc_now(),
            "event": event,
            "skill_name": _safe_text(skill_name, 200),
            "result": _allowed_value(result, _ALLOWED_RESULTS),
            "readiness": _allowed_value(readiness, _ALLOWED_READINESS),
        }
        try:
            with self._lock:
                entries = self._load_entries()
                entries.append(entry)
                self.ctx.state.set(EVENT_STATE_KEY, self._envelope(entries[-MAX_EVENTS:]))
        except Exception:
            return

    def recent(self, limit: Any = MAX_EVENTS) -> list[dict[str, str]]:
        """Return up to 50 newest normalized records in chronological order."""
        safe_limit = _limit(limit, MAX_EVENTS)
        try:
            with self._lock:
                entries = self._load_entries()
                return [dict(entry) for entry in entries[-safe_limit:]]
        except Exception:
            return []

    def last(self) -> dict[str, str] | None:
        """Return the newest normalized record, if one is available."""
        entries = self.recent(1)
        return entries[-1] if entries else None

    def render(self, limit: Any = _DEFAULT_RENDER_LIMIT) -> str:
        """Render recent events for the ``/skill-router events [1-50]`` command."""
        entries = self.recent(_limit(limit, _DEFAULT_RENDER_LIMIT))
        lines = ["Skill Router Events", ""]
        if not entries:
            lines.append("No events.")
            return "\n".join(lines)
        for entry in entries:
            label = _EVENT_LABELS[entry["event"]]
            detail = entry["skill_name"]
            qualifiers = [
                value
                for value in (entry["result"], entry["readiness"])
                if value
            ]
            if detail:
                line = f"{entry['timestamp']} — {label}: {detail}"
            else:
                line = f"{entry['timestamp']} — {label}"
            if qualifiers:
                line += f" ({', '.join(qualifiers)})"
            lines.append(line)
        return "\n".join(lines)

    def _load_entries(self) -> list[dict[str, str]]:
        if not _valid_scope_token(self.profile.scope_token):
            return []
        try:
            raw = self.ctx.state.get(EVENT_STATE_KEY, default={})
        except Exception:
            return []
        if not isinstance(raw, dict):
            return []
        if raw.get("version") != EVENT_STATE_VERSION:
            return []
        if raw.get("profile_scope") != self.profile.scope_token:
            return []
        entries = raw.get("entries")
        if not isinstance(entries, list):
            return []
        normalized: list[dict[str, str]] = []
        for value in entries[-MAX_EVENTS:]:
            entry = _normalize_entry(value)
            if entry is not None:
                normalized.append(entry)
        return normalized

    def _envelope(self, entries: list[dict[str, str]]) -> dict[str, Any]:
        return {
            "version": EVENT_STATE_VERSION,
            "profile": _safe_text(self.profile.name, 100),
            "profile_scope": self.profile.scope_token,
            "entries": entries[-MAX_EVENTS:],
        }


def _normalize_entry(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict) or value.get("event") not in ALLOWED_EVENTS:
        return None
    timestamp = _safe_text(value.get("timestamp"), 40)
    if not timestamp:
        return None
    return {
        "timestamp": timestamp,
        "event": value["event"],
        "skill_name": _safe_text(value.get("skill_name"), 200),
        "result": _allowed_value(value.get("result"), _ALLOWED_RESULTS),
        "readiness": _allowed_value(value.get("readiness"), _ALLOWED_READINESS),
    }


def _safe_text(value: Any, maximum: int) -> str:
    if not isinstance(value, str):
        return ""
    printable = "".join(char if ord(char) >= 32 and ord(char) != 127 else " " for char in value)
    return " ".join(printable.split())[:maximum]


def _allowed_value(value: Any, allowed: frozenset[str]) -> str:
    normalized = _safe_text(value, 80)
    return normalized if normalized in allowed else ""


def _valid_scope_token(value: Any) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= 200
        and all(ord(char) >= 32 and ord(char) != 127 for char in value)
    )


def _limit(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        selected = int(value)
    except (TypeError, ValueError, OverflowError):
        selected = default
    return max(1, min(selected, MAX_EVENTS))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
