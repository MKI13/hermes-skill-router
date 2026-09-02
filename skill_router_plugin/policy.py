"""Deterministic validation and composition of routed skill selections."""

from __future__ import annotations

from typing import Any

from .readiness import (
    BROKEN,
    DEPENDENCY_MISSING,
    DISABLED,
    READY,
    READINESS_PRIORITY,
    SETUP_REQUIRED,
    UNKNOWN,
)

_POLICY_STATUSES = {"valid", "adjusted", "degraded", "blocked"}
_USABLE_DEPENDENCY_STATUSES = {READY, UNKNOWN}


def detect_explicit_skill_names(
    task: str,
    catalog_entries: list[dict[str, Any]],
) -> list[str]:
    """Return installed skill names mentioned as standalone task terms."""
    normalized = str(task or "").casefold()
    matches: list[tuple[int, str]] = []
    for entry in catalog_entries:
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        needle = name.casefold()
        start = 0
        while True:
            index = normalized.find(needle, start)
            if index < 0:
                break
            before = normalized[index - 1] if index else ""
            end = index + len(needle)
            after = normalized[end] if end < len(normalized) else ""
            if not _name_character(before) and not _name_character(after):
                matches.append((index, name))
                break
            start = index + 1
    return [name for _index, name in sorted(matches, key=lambda item: (item[0], item[1].casefold()))]


def apply_routing_policy(
    *,
    task: str,
    selected_skills: list[dict[str, Any]],
    catalog_entries: list[dict[str, Any]],
    max_skills: int,
    explicit_skill_names: list[str],
) -> dict[str, Any]:
    """Validate a model plan against catalog readiness and declared dependencies."""
    del task
    try:
        return _apply_policy(
            selected_skills=selected_skills,
            catalog_entries=catalog_entries,
            max_skills=max_skills,
            explicit_skill_names=explicit_skill_names,
        )
    except Exception:
        return {
            "selections": [],
            "warnings": ["policy-error"],
            "policy_status": "degraded",
            "changes": ["Policy validation failed; no skill recommendation was retained."],
        }


def _apply_policy(
    *,
    selected_skills: list[dict[str, Any]],
    catalog_entries: list[dict[str, Any]],
    max_skills: int,
    explicit_skill_names: list[str],
) -> dict[str, Any]:
    safe_limit = max(1, min(int(max_skills), 5))
    catalog = {
        str(entry.get("name")): entry
        for entry in catalog_entries
        if isinstance(entry, dict) and entry.get("name")
    }
    explicit_order = [name for name in explicit_skill_names if name in catalog]
    explicit = set(explicit_order)
    warnings: list[str] = []
    changes: list[str] = []
    changed = False
    degraded = False

    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(selected_skills if isinstance(selected_skills, list) else []):
        if not isinstance(item, dict):
            changed = True
            continue
        name = str(item.get("name") or "")
        if name not in catalog or name in seen:
            changed = True
            if name and name not in catalog:
                _append(changes, f"Removed unknown skill: {name}")
            continue
        seen.add(name)
        candidates.append(_candidate(name, item, catalog[name], index, "selected"))

    for name in explicit_skill_names:
        if name not in catalog or name in seen:
            continue
        seen.add(name)
        candidates.append(_candidate(name, {}, catalog[name], len(candidates), "explicit"))
        changed = True
        _append(changes, f"Added explicitly requested skill: {name}")

    if not candidates:
        status = "blocked" if selected_skills else "adjusted" if changed else "valid"
        return _result([], warnings, status, changes)

    fatal_explicit = [
        item for item in candidates
        if item["name"] in explicit and item["readiness_status"] in {BROKEN, DISABLED}
    ]
    if fatal_explicit:
        for item in fatal_explicit:
            status = item["readiness_status"]
            _append(warnings, f"requested-{status}:{item['name']}")
            _append(
                changes,
                f"Requested skill {item['name']} is {status} and was not made executable.",
            )
        return _result([], warnings, "blocked", changes)

    filtered: list[dict[str, Any]] = []
    for item in candidates:
        name = item["name"]
        status = item["readiness_status"]
        is_explicit = name in explicit
        if catalog[name].get("policy_metadata_complete") is False:
            degraded = True
            _append(warnings, f"policy-metadata-unavailable:{name}")
            if is_explicit:
                _append(changes, f"Requested skill {name} lacks complete policy metadata.")
                return _result([], warnings, "blocked", changes)
            changed = True
            _append(changes, f"Removed skill with incomplete policy metadata: {name}")
            continue
        if status in {BROKEN, DISABLED}:
            changed = True
            _append(changes, f"Removed {status} skill: {name}")
            _append(warnings, f"{status}:{name}")
            continue
        if status == DEPENDENCY_MISSING and not is_explicit:
            changed = True
            degraded = True
            _append(changes, f"Removed dependency-missing skill: {name}")
            _append(warnings, f"dependency-missing:{name}")
            continue
        if status == DEPENDENCY_MISSING:
            degraded = True
            _append(warnings, f"dependency-missing:{name}")
        filtered.append(item)

    if not filtered:
        return _result([], warnings, "blocked", changes)

    valid_candidates: list[dict[str, Any]] = []
    closures: dict[str, list[str]] = {}
    cycle_detected = False
    for item in filtered:
        closure, issues, has_cycle = _dependency_closure(item["name"], catalog)
        cycle_detected = cycle_detected or has_cycle
        for issue in issues:
            _append(warnings, issue)
        if issues and any(
            issue.startswith(("missing-dependency:", "unusable-dependency:"))
            for issue in issues
        ):
            degraded = True
            if item["name"] in explicit:
                _append(
                    changes,
                    f"Requested skill {item['name']} has unusable declared dependencies.",
                )
                return _result([], warnings, "blocked", changes)
            changed = True
            _append(changes, f"Removed skill with unusable dependencies: {item['name']}")
            continue
        closures[item["name"]] = closure
        valid_candidates.append(item)

    if cycle_detected:
        degraded = True
    if not valid_candidates:
        return _result([], warnings, "blocked", changes)

    has_normal_candidate = any(
        item["readiness_status"] in {READY, UNKNOWN} for item in valid_candidates
    )
    readiness_filtered: list[dict[str, Any]] = []
    for item in valid_candidates:
        if (
            item["readiness_status"] == SETUP_REQUIRED
            and item["name"] not in explicit
            and has_normal_candidate
        ):
            changed = True
            _append(
                changes,
                f"Preferred ready or unknown skill over setup-required skill: {item['name']}",
            )
            _append(warnings, f"setup-required:{item['name']}")
            continue
        if item["readiness_status"] == SETUP_REQUIRED:
            degraded = True
            _append(warnings, f"setup-required:{item['name']}")
        readiness_filtered.append(item)
    valid_candidates, alternatives_changed = _remove_alternative_conflicts(
        readiness_filtered,
        catalog,
        explicit,
        changes,
    )
    changed = changed or alternatives_changed
    if not valid_candidates:
        return _result([], warnings, "blocked", changes)

    primary = next(
        (
            item
            for explicit_name in explicit_order
            for item in valid_candidates
            if item["name"] == explicit_name
        ),
        next(
            (item for item in valid_candidates if item["requested_role"] == "primary"),
            valid_candidates[0],
        ),
    )
    for item in valid_candidates:
        normalized_role = "primary" if item is primary else "supporting"
        if item["requested_role"] != normalized_role:
            changed = True
            _append(changes, f"Normalized role for {item['name']} to {normalized_role}.")
        item["role"] = normalized_role

    primary_closure = closures[primary["name"]]
    if len(primary_closure) > safe_limit:
        _append(warnings, f"dependency-limit:{primary['name']}")
        _append(changes, f"Required dependency chain for {primary['name']} exceeds the skill limit.")
        return _result([], warnings, "blocked", changes)

    ordered_names = list(primary_closure)
    included = set(ordered_names)
    for item in valid_candidates:
        if item is primary or item["name"] in included:
            continue
        extra = [name for name in closures[item["name"]] if name not in included]
        if len(included) + len(extra) > safe_limit:
            changed = True
            _append(changes, f"Removed optional supporting skill to preserve dependencies: {item['name']}")
            continue
        ordered_names.extend(extra)
        included.update(extra)

    candidate_by_name = {item["name"]: item for item in valid_candidates}
    output: list[dict[str, Any]] = []
    raw_positions = {item["name"]: item["position"] for item in valid_candidates}
    for name in ordered_names:
        entry = catalog[name]
        selected = candidate_by_name.get(name)
        if selected is None:
            selected = _candidate(name, {}, entry, len(selected_skills) + len(output), "dependency")
            selected["role"] = "supporting"
            changed = True
            _append(changes, f"Added required skill: {name}")
        output.append({
            "name": name,
            "role": "primary" if name == primary["name"] else "supporting",
            "reason": selected["reason"],
            "order": len(output) + 1,
            "readiness_status": selected["readiness_status"],
            "setup_needed": selected["setup_needed"],
        })

    output_positions = {item["name"]: item["order"] for item in output}
    for parent in ordered_names:
        for dependency in _required_skills(catalog[parent]):
            if dependency not in output_positions:
                continue
            if output_positions[dependency] < output_positions[parent] and (
                dependency not in raw_positions
                or raw_positions[dependency] > raw_positions.get(parent, 10_000)
            ):
                changed = True
                _append(changes, f"Reordered dependency {dependency} before {parent}.")

    status = "degraded" if degraded else "adjusted" if changed else "valid"
    return _result(output[:safe_limit], warnings, status, changes)


def _candidate(
    name: str,
    selected: dict[str, Any],
    entry: dict[str, Any],
    position: int,
    source: str,
) -> dict[str, Any]:
    reason = " ".join(str(selected.get("reason") or "Relevant to the requested task.").split())[:300]
    return {
        "name": name,
        "requested_role": "primary" if selected.get("role") == "primary" else "supporting",
        "role": "supporting",
        "reason": reason,
        "position": position,
        "source": source,
        "readiness_status": str(entry.get("readiness_status") or UNKNOWN),
        "setup_needed": bool(entry.get("setup_needed")),
    }


def _remove_alternative_conflicts(
    candidates: list[dict[str, Any]],
    catalog: dict[str, dict[str, Any]],
    explicit: set[str],
    changes: list[str],
) -> tuple[list[dict[str, Any]], bool]:
    kept: list[dict[str, Any]] = []
    changed = False
    for candidate in candidates:
        conflict = next(
            (
                current for current in kept
                if _alternatives(candidate["name"], current["name"], catalog)
            ),
            None,
        )
        if conflict is None:
            kept.append(candidate)
            continue
        winner = _preferred_alternative(conflict, candidate, explicit)
        loser = candidate if winner is conflict else conflict
        if winner is candidate:
            kept[kept.index(conflict)] = candidate
        changed = True
        _append(changes, f"Removed alternative skill {loser['name']} in favor of {winner['name']}.")
    return kept, changed


def _preferred_alternative(
    first: dict[str, Any],
    second: dict[str, Any],
    explicit: set[str],
) -> dict[str, Any]:
    first_explicit = first["name"] in explicit
    second_explicit = second["name"] in explicit
    if first_explicit != second_explicit:
        return first if first_explicit else second
    first_priority = READINESS_PRIORITY.get(first["readiness_status"], READINESS_PRIORITY[UNKNOWN])
    second_priority = READINESS_PRIORITY.get(second["readiness_status"], READINESS_PRIORITY[UNKNOWN])
    if first_priority != second_priority:
        return first if first_priority < second_priority else second
    return first if first["position"] <= second["position"] else second


def _dependency_closure(
    root: str,
    catalog: dict[str, dict[str, Any]],
) -> tuple[list[str], list[str], bool]:
    ordered: list[str] = []
    permanent: set[str] = set()
    temporary: list[str] = []
    issues: list[str] = []
    cycle = False

    def visit(name: str) -> None:
        nonlocal cycle
        if name in permanent:
            return
        if name in temporary:
            cycle = True
            start = temporary.index(name)
            chain = temporary[start:] + [name]
            _append(issues, "dependency-cycle:" + "->".join(chain))
            return
        temporary.append(name)
        for dependency in _required_skills(catalog[name]):
            entry = catalog.get(dependency)
            if entry is None:
                _append(issues, f"missing-dependency:{name}->{dependency}")
                continue
            status = str(entry.get("readiness_status") or UNKNOWN)
            if status not in _USABLE_DEPENDENCY_STATUSES:
                _append(issues, f"unusable-dependency:{name}->{dependency}:{status}")
                continue
            visit(dependency)
        temporary.pop()
        permanent.add(name)
        if name not in ordered:
            ordered.append(name)

    visit(root)
    return ordered, issues, cycle


def _required_skills(entry: dict[str, Any]) -> list[str]:
    requirements = entry.get("requirements")
    if not isinstance(requirements, dict):
        return []
    values = requirements.get("skills")
    if not isinstance(values, list):
        return []
    output: list[str] = []
    for value in values:
        name = str(value or "").strip()
        if name and name not in output:
            output.append(name)
    return output


def _alternatives(
    first: str,
    second: str,
    catalog: dict[str, dict[str, Any]],
) -> bool:
    return (
        second in _string_list(catalog[first].get("alternatives"))
        or first in _string_list(catalog[second].get("alternatives"))
    )


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _result(
    selections: list[dict[str, Any]],
    warnings: list[str],
    status: str,
    changes: list[str],
) -> dict[str, Any]:
    return {
        "selections": selections,
        "warnings": warnings[:20],
        "policy_status": status if status in _POLICY_STATUSES else "degraded",
        "changes": changes[:20],
    }


def _append(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _name_character(value: str) -> bool:
    return bool(value) and (value.isalnum() or value in {"_", "-", ":"})
