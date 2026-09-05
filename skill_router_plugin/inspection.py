"""Human-readable, secret-safe readiness inspection for one routed skill."""

from __future__ import annotations

from typing import Any, Mapping

from .readiness import BROKEN, DEPENDENCY_MISSING, DISABLED, READY, SETUP_REQUIRED, UNKNOWN


def render_skill_inspection(snapshot: Mapping[str, Any], skill_name: str) -> str:
    """Render cached readiness evidence without probing or exposing configured values."""
    entries = snapshot.get("entries") if isinstance(snapshot.get("entries"), list) else []
    entry = next(
        (
            item
            for item in entries
            if isinstance(item, dict)
            and str(item.get("name") or "").casefold() == skill_name.casefold()
        ),
        None,
    )
    if entry is None:
        return f"Skill not found: {skill_name}"

    status = str(entry.get("readiness_status") or UNKNOWN)
    summary = str(entry.get("readiness_summary") or "").strip()
    lines = [
        f"Skill: {entry.get('name')}",
        f"Readiness: {status}",
    ]
    if summary:
        lines.append(f"Summary: {summary[:500]}")

    missing = _safe_items(entry.get("missing_dependencies"))
    unknown = _safe_items(entry.get("unknown_dependencies"))
    setup = _safe_items(entry.get("setup_requirements"))

    if missing:
        lines.extend(["", "Missing:"])
        lines.extend(_item_lines(missing))
    if unknown:
        lines.extend(["", "Unknown / not passively verifiable:"])
        lines.extend(_item_lines(unknown))
    if setup:
        lines.extend(["", "Setup required:"])
        lines.extend(_item_lines(setup))

    # Backward-compatible evidence for snapshots created before readiness_version=2.
    if not (missing or unknown or setup):
        checks = entry.get("dependency_checks")
        checks = checks if isinstance(checks, list) else []
        lines.extend(["", "Dependencies:"])
        if checks:
            for check in checks[:50]:
                if not isinstance(check, dict):
                    continue
                kind = _safe_text(check.get("type") or "dependency")
                name = _safe_text(check.get("name") or "unknown")
                state = str(check.get("state") or "").strip()
                if not state:
                    available = check.get("available")
                    state = "available" if available is True else "missing" if available is False else "unknown"
                lines.append(f"- {kind}: {name} [{state[:40]}]")
        else:
            lines.append("- none declared")

    reasons = entry.get("readiness_reasons")
    if isinstance(reasons, list):
        clean_reasons = [_safe_text(reason, 300) for reason in reasons[:5] if str(reason).strip()]
        if clean_reasons:
            lines.extend(["", "Reasons:"])
            lines.extend(f"- {reason}" for reason in clean_reasons)

    lines.extend(["", "Router action:", _router_action(status)])
    return "\n".join(lines)


def _safe_items(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    output: list[dict[str, str]] = []
    for item in value[:50]:
        if not isinstance(item, Mapping):
            continue
        kind = _safe_text(item.get("type") or "dependency")
        name = _safe_text(item.get("name") or "unknown")
        output.append({"type": kind, "name": name})
    return output


def _item_lines(items: list[dict[str, str]]) -> list[str]:
    return [f"- {item['type']}: {item['name']}" for item in items]


def _safe_text(value: Any, limit: int = 200) -> str:
    text = str(value or "").replace("\n", " ").replace("\r", " ").strip()
    return text[:limit] or "unknown"


def _router_action(status: str) -> str:
    if status == READY:
        return "Eligible for normal routing."
    if status == DEPENDENCY_MISSING:
        return "Do not select as Primary until requirements are satisfied."
    if status == SETUP_REQUIRED:
        return "Do not select as Primary until required setup is completed."
    if status == UNKNOWN:
        return "Treat as unverified; do not promote over a ready alternative."
    if status == BROKEN:
        return "Block from routing until the skill declaration or file is repaired."
    if status == DISABLED:
        return "Do not route; the skill is disabled."
    return "Treat as unverified; do not promote over a ready alternative."
