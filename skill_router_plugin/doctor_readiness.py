"""Bounded, secret-safe profile readiness summary for Doctor output."""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping

from .inspection import format_readiness_summary, readiness_items
from .readiness import BROKEN, DEPENDENCY_MISSING, DISABLED, READY, SETUP_REQUIRED, UNKNOWN

_ORDER = (BROKEN, DEPENDENCY_MISSING, SETUP_REQUIRED, UNKNOWN, DISABLED, READY)
_LABELS = {
    READY: "ready",
    UNKNOWN: "unknown",
    SETUP_REQUIRED: "setup required",
    DEPENDENCY_MISSING: "dependency missing",
    BROKEN: "broken",
    DISABLED: "disabled",
}


def render_readiness_doctor(snapshot: Mapping[str, Any], *, detail_limit: int = 8) -> str:
    """Summarize cached skill readiness without probing, repairing, or exposing values."""
    entries = snapshot.get("entries") if isinstance(snapshot.get("entries"), list) else []
    clean_entries = [entry for entry in entries if isinstance(entry, Mapping)]
    counts = Counter(str(entry.get("readiness_status") or UNKNOWN) for entry in clean_entries)

    lines = [
        "Skill Readiness Summary",
        f"Indexed: {len(clean_entries)}",
        " | ".join(f"{_LABELS[status]}={counts.get(status, 0)}" for status in _ORDER),
    ]

    actionable = [
        entry
        for entry in clean_entries
        if str(entry.get("readiness_status") or UNKNOWN)
        in {BROKEN, DEPENDENCY_MISSING, SETUP_REQUIRED, UNKNOWN}
    ]
    actionable.sort(key=_priority)

    if not actionable:
        lines.extend(["", "Actionable: none"])
        return "\n".join(lines)

    lines.extend(["", f"Actionable skills (showing up to {max(1, min(detail_limit, 20))}):"])
    for entry in actionable[: max(1, min(detail_limit, 20))]:
        name = _safe(entry.get("name") or "unknown")
        status = str(entry.get("readiness_status") or UNKNOWN)
        detail = _detail(entry)
        lines.append(f"- {name} [{status}]: {detail}")

    hidden = len(actionable) - max(1, min(detail_limit, 20))
    if hidden > 0:
        lines.append(f"- ... {hidden} more; use `hermes skill-router inspect <skill>` for details.")

    lines.extend([
        "",
        "Doctor action: review non-ready skills before relying on them as Primary. No repair was attempted.",
    ])
    return "\n".join(lines)


def _priority(entry: Mapping[str, Any]) -> tuple[int, str]:
    status = str(entry.get("readiness_status") or UNKNOWN)
    try:
        rank = _ORDER.index(status)
    except ValueError:
        rank = _ORDER.index(UNKNOWN)
    return rank, str(entry.get("name") or "").casefold()


def _detail(entry: Mapping[str, Any]) -> str:
    if entry.get("readiness_details_omitted") is True:
        return "readiness details omitted by state quota; refresh and inspect for current evidence"
    summary = format_readiness_summary(entry.get("readiness_summary"))
    # Preserve old textual summaries while rendering v2 counters by allowlist.
    if isinstance(entry.get("readiness_summary"), str) and summary:
        return _safe(summary, 240)

    missing = _items(entry.get("missing_dependencies"))
    setup = _items(entry.get("setup_requirements"), setup_keys=True)
    unknown = _items(entry.get("unknown_dependencies"))
    parts: list[str] = []
    if summary:
        parts.append(summary)
    if missing:
        parts.append("missing " + ", ".join(missing[:3]))
    if setup:
        parts.append("setup " + ", ".join(setup[:3]))
    if unknown:
        parts.append("unverified " + ", ".join(unknown[:3]))
    return _safe("; ".join(parts), 240) if parts else "inspect for cached readiness evidence"


def _items(value: Any, *, setup_keys: bool = False) -> list[str]:
    return [
        f"{_safe(item['type'], 40)}:{_safe(item['name'], 120)}"
        for item in readiness_items(value, setup_keys=setup_keys)[:10]
    ]


def _safe(value: Any, limit: int = 160) -> str:
    if not isinstance(value, str):
        return "unknown"
    text = " ".join(value.split()).strip()
    return text[:limit] or "unknown"
