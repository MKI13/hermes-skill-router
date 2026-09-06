"""Human-readable, secret-safe readiness inspection for one routed skill."""

from __future__ import annotations

from typing import Any, Mapping

from .readiness import BROKEN, DEPENDENCY_MISSING, DISABLED, READY, SETUP_REQUIRED, UNKNOWN

_SUMMARY_KEYS = ("declared", "checked", "available", "missing", "unknown", "setup")


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
    summary = format_readiness_summary(entry.get("readiness_summary"))
    omitted = entry.get("readiness_details_omitted") is True
    lines = [
        f"Skill: {entry.get('name')}",
        f"Readiness: {status}",
    ]
    if summary:
        lines.append(f"Summary: {summary}")
    if omitted:
        lines.append("Readiness details omitted by the state quota; refresh the catalog for current evidence.")

    missing = readiness_items(entry.get("missing_dependencies"))
    unknown = readiness_items(entry.get("unknown_dependencies"))
    setup = readiness_items(entry.get("setup_requirements"), setup_keys=True)

    if missing:
        lines.extend(["", "Missing:"])
        lines.extend(_item_lines(missing))
    if unknown:
        lines.extend(["", "Unknown / not passively verifiable:"])
        lines.extend(_item_lines(unknown))
    if setup:
        lines.extend(["", "Setup required:"])
        lines.extend(_item_lines(setup))

    # Preserve the legacy evidence format for old snapshots and existing operators.
    # Missing measurements are not equivalent to having no declared requirements.
    if not (missing or unknown or setup):
        checks = entry.get("dependency_checks")
        checks = checks if isinstance(checks, list) else []
        lines.extend(["", "Dependencies:"])
        if checks:
            for check in checks[:50]:
                if not isinstance(check, dict):
                    continue
                kind = _safe_text(check.get("type") or "dependency").replace("_", " ")
                name = _safe_text(check.get("name") or "unknown")
                state = check.get("state")
                if state not in ("available", "missing", "unknown"):
                    available = check.get("available")
                    state = "available" if available is True else "missing" if available is False else "unknown"
                lines.append(f"{kind} {name}: {state}")
        elif omitted:
            lines.append("details omitted; declared requirements were not cleared")
        else:
            requirements = entry.get("requirements")
            declared = isinstance(requirements, dict) and any(
                isinstance(value, list) and value for value in requirements.values()
            )
            lines.append("declared requirements have no cached checks" if declared else "none declared")

        lines.extend(["", f"Setup needed: {'true' if entry.get('setup_needed') else 'false'}"])

    # Grouped v2 diagnostics must not hide required skills or alternatives.
    requirements = entry.get("requirements") if isinstance(entry.get("requirements"), dict) else {}
    required_skills = requirements.get("skills") if isinstance(requirements.get("skills"), list) else []
    alternatives = entry.get("alternatives") if isinstance(entry.get("alternatives"), list) else []
    if required_skills:
        lines.extend(["", "Required skills:"])
        lines.extend(f"- {_safe_text(name)}" for name in required_skills[:20])
    if alternatives:
        lines.extend(["", "Alternatives:"])
        lines.extend(f"- {_safe_text(name)}" for name in alternatives[:20])

    reasons = entry.get("readiness_reasons")
    if isinstance(reasons, list):
        clean_reasons = [_safe_text(reason, 300) for reason in reasons[:5] if isinstance(reason, str) and reason.strip()]
        if clean_reasons:
            lines.extend(["", "Reasons:"])
            lines.extend(f"- {reason}" for reason in clean_reasons)

    lines.extend(["", "Router action:", _router_action(status)])
    return "\n".join(lines)


def format_readiness_summary(value: Any) -> str:
    """Render known numeric counters; retain legacy text, never stringify a dict."""
    if isinstance(value, Mapping):
        parts = []
        for key in _SUMMARY_KEYS:
            count = value.get(key)
            if type(count) is int and 0 <= count <= 1_000_000:
                parts.append(f"{key}={count}")
        return " | ".join(parts)
    if isinstance(value, str) and value.strip():
        return _safe_text(value, 500)
    return ""


def readiness_items(value: Any, *, setup_keys: bool = False) -> list[dict[str, str]]:
    """Accept v2 config-key strings and legacy type/name records, not values."""
    if not isinstance(value, list):
        return []
    output: list[dict[str, str]] = []
    for item in value[:50]:
        if setup_keys and isinstance(item, str):
            if item.strip():
                output.append({"type": "config", "name": _safe_text(item)})
            continue
        if not isinstance(item, Mapping):
            continue
        kind = _safe_text(item.get("type") or "dependency").replace("_", " ")
        name = _safe_text(item.get("name") or "unknown")
        output.append({"type": kind, "name": name})
    return output


def _item_lines(items: list[dict[str, str]]) -> list[str]:
    return [f"- {item['type']}: {item['name']}" for item in items]


def _safe_text(value: Any, limit: int = 200) -> str:
    if not isinstance(value, str):
        return "unknown"
    text = " ".join(value.split()).strip()
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
