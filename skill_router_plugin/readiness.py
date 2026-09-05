"""Passive readiness and dependency checks for catalogued skills."""

from __future__ import annotations

import ast
from importlib.machinery import PathFinder
import os
import shutil
from typing import Any, Callable, Mapping

READY = "ready"
SETUP_REQUIRED = "setup_required"
DEPENDENCY_MISSING = "dependency_missing"
BROKEN = "broken"
DISABLED = "disabled"
UNKNOWN = "unknown"
READINESS_VERSION = 2

READINESS_STATUSES = (
    READY,
    SETUP_REQUIRED,
    DEPENDENCY_MISSING,
    BROKEN,
    DISABLED,
    UNKNOWN,
)
READINESS_PRIORITY = {
    READY: 0,
    UNKNOWN: 1,
    SETUP_REQUIRED: 2,
    DEPENDENCY_MISSING: 3,
    BROKEN: 4,
    DISABLED: 5,
}
_REQUIREMENT_KEYS = ("commands", "python_modules", "skills", "mcps", "config")


def evaluate_readiness(
    *,
    content: str,
    visible_skill_names: set[str],
    metadata_hints: Mapping[str, Any] | None,
    get_config: Callable[[str, Any], Any],
    content_expected: bool,
    mcp_readiness: Mapping[str, bool | None] | None = None,
    command_finder: Callable[[str], str | None] = shutil.which,
    module_finder: Callable[[str], Any] | None = None,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Evaluate declared requirements without changing the host environment."""
    empty_requirements = {key: [] for key in _REQUIREMENT_KEYS}
    hints = dict(metadata_hints or {})
    if content_expected and not content:
        return _result(
            BROKEN,
            empty_requirements,
            [],
            False,
            ["Skill file could not be read."],
        )

    try:
        frontmatter = _parse_frontmatter(content) if content else {}
        requirements, declared, invalid = _collect_requirements(frontmatter, hints)
        setup_declared, setup_invalid = _setup_declared(frontmatter, hints)
    except Exception:
        return _result(
            UNKNOWN,
            empty_requirements,
            [],
            False,
            ["Readiness check unavailable."],
        )

    status_hint = str(hints.get("status") or "").strip()
    if bool(hints.get("disabled")) or status_hint == DISABLED:
        return _result(DISABLED, requirements, [], False, ["Skill is disabled."])
    if invalid or setup_invalid:
        return _result(
            BROKEN,
            requirements,
            [],
            False,
            ["Invalid requirements declaration."],
        )
    if status_hint == BROKEN:
        return _result(BROKEN, requirements, [], False, ["Host reported a broken skill."])

    checks: list[dict[str, Any]] = []
    selected_module_finder = module_finder or _safe_find_spec
    missing_dependency = False
    unknown_dependency = False
    missing_config = False
    env = environment if environment is not None else os.environ
    try:
        for command in requirements["commands"]:
            available = command_finder(command) is not None
            checks.append(_check("command", command, available))
            missing_dependency = missing_dependency or not available
        for module in requirements["python_modules"]:
            available = selected_module_finder(module) is not None
            checks.append(_check("python_module", module, available))
            missing_dependency = missing_dependency or not available
        for skill in requirements["skills"]:
            available = skill in visible_skill_names
            checks.append(_check("skill", skill, available))
            missing_dependency = missing_dependency or not available
        for mcp in requirements["mcps"]:
            available = None if mcp_readiness is None else mcp_readiness.get(mcp, False)
            checks.append(_check("mcp", mcp, available))
            missing_dependency = missing_dependency or available is False
            unknown_dependency = unknown_dependency or available is None
        for key in requirements["config"]:
            configured = _configured(key, get_config, env)
            checks.append(_check("config", key, configured))
            missing_config = missing_config or not configured
    except Exception:
        return _result(
            UNKNOWN,
            requirements,
            checks,
            False,
            ["Readiness check unavailable."],
        )

    if missing_dependency:
        return _result(
            DEPENDENCY_MISSING,
            requirements,
            checks,
            False,
            _dependency_reasons(checks, missing=True),
        )
    if unknown_dependency:
        return _result(
            UNKNOWN,
            requirements,
            checks,
            False,
            _dependency_reasons(checks, unknown=True),
        )
    if setup_declared or missing_config or status_hint == SETUP_REQUIRED:
        reasons = _setup_reasons(checks)
        if setup_declared and not reasons:
            reasons = ["Declared setup is incomplete."]
        return _result(
            SETUP_REQUIRED,
            requirements,
            checks,
            True,
            reasons,
        )
    if declared or status_hint == READY:
        return _result(READY, requirements, checks, False, [])
    return _result(UNKNOWN, requirements, checks, False, ["No readiness requirements were declared."])


def readiness_sort_key(entry: Mapping[str, Any]) -> int:
    """Return the stable preference index for an entry's readiness status."""
    return READINESS_PRIORITY.get(str(entry.get("readiness_status") or UNKNOWN), READINESS_PRIORITY[UNKNOWN])


def _result(
    status: str,
    requirements: dict[str, list[str]],
    checks: list[dict[str, Any]],
    setup_needed: bool,
    reasons: list[str],
) -> dict[str, Any]:
    selected_status = status if status in READINESS_STATUSES else UNKNOWN
    missing = [
        {"type": str(check.get("type") or "dependency"), "name": str(check.get("name") or "")[:200]}
        for check in checks
        if check.get("available") is False and check.get("type") != "config"
    ][:50]
    unknown = [
        {"type": str(check.get("type") or "dependency"), "name": str(check.get("name") or "")[:200]}
        for check in checks
        if check.get("available") is None
    ][:50]
    setup = [
        str(check.get("name") or "")[:200]
        for check in checks
        if check.get("type") == "config" and check.get("available") is False
    ][:50]
    summary = {
        "declared": sum(len(requirements.get(key, [])) for key in _REQUIREMENT_KEYS),
        "checked": len(checks),
        "available": sum(check.get("available") is True for check in checks),
        "missing": len(missing),
        "unknown": len(unknown),
        "setup": len(setup),
    }
    return {
        "readiness_version": READINESS_VERSION,
        "readiness_status": selected_status,
        "setup_needed": setup_needed,
        "requirements": requirements,
        "dependency_checks": checks,
        "missing_dependencies": missing,
        "unknown_dependencies": unknown,
        "setup_requirements": setup,
        "readiness_summary": summary,
        "readiness_reasons": _dedupe_reasons(reasons)[:10],
    }


def _check(kind: str, name: str, available: bool | None) -> dict[str, Any]:
    state = "available" if available is True else "missing" if available is False else "unknown"
    return {"type": kind, "name": name, "available": available, "state": state}


def _dependency_reasons(
    checks: list[dict[str, Any]],
    *,
    missing: bool = False,
    unknown: bool = False,
) -> list[str]:
    reasons: list[str] = []
    labels = {
        "command": "command",
        "python_module": "Python module",
        "skill": "skill",
        "mcp": "MCP",
    }
    for check in checks:
        available = check.get("available")
        kind = str(check.get("type") or "dependency")
        if kind == "config":
            continue
        name = str(check.get("name") or "unknown")[:200]
        label = labels.get(kind, "dependency")
        if missing and available is False:
            reasons.append(f"Missing {label}: {name}.")
        elif unknown and available is None:
            reasons.append(f"Could not passively verify {label}: {name}.")
    return reasons or [
        "One or more declared dependencies are missing."
        if missing
        else "One or more declared dependencies could not be checked passively."
    ]


def _setup_reasons(checks: list[dict[str, Any]]) -> list[str]:
    return [
        f"Required config is not set: {str(check.get('name') or 'unknown')[:200]}."
        for check in checks
        if check.get("type") == "config" and check.get("available") is False
    ]


def _dedupe_reasons(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = " ".join(str(value or "").split())[:300]
        if text and text not in result:
            result.append(text)
    return result


def _safe_find_spec(module: str) -> Any:
    parts = module.split(".")
    spec = PathFinder.find_spec(parts[0])
    for index in range(1, len(parts)):
        if spec is None or spec.submodule_search_locations is None:
            return None
        spec = PathFinder.find_spec(
            ".".join(parts[:index + 1]),
            spec.submodule_search_locations,
        )
    return spec


def _configured(
    key: str,
    get_config: Callable[[str, Any], Any],
    environment: Mapping[str, str],
) -> bool:
    value = get_config(key, None)
    if value is not None and value != "":
        return True
    return bool(environment.get(key))


def _collect_requirements(
    frontmatter: Mapping[str, Any],
    hints: Mapping[str, Any],
) -> tuple[dict[str, list[str]], bool, bool]:
    output = {key: [] for key in _REQUIREMENT_KEYS}
    declared = False
    invalid = False
    candidates: list[tuple[Any, bool]] = []

    if "requirements" in hints:
        candidates.append((hints.get("requirements"), False))
    if "requirements" in frontmatter:
        candidates.append((frontmatter.get("requirements"), False))
    metadata = frontmatter.get("metadata")
    if isinstance(metadata, Mapping):
        hermes = metadata.get("hermes")
        if isinstance(hermes, Mapping) and "requirements" in hermes:
            candidates.append((hermes.get("requirements"), False))
    if "prerequisites" in frontmatter:
        candidates.append((frontmatter.get("prerequisites"), True))

    for candidate, legacy in candidates:
        declared = True
        if not isinstance(candidate, Mapping):
            invalid = True
            continue
        for key in _REQUIREMENT_KEYS:
            if key not in candidate:
                continue
            values, values_invalid = _names(candidate.get(key))
            invalid = invalid or values_invalid
            _extend_unique(output[key], values)
        if legacy and "env_vars" in candidate:
            values, values_invalid = _names(candidate.get("env_vars"))
            invalid = invalid or values_invalid
            _extend_unique(output["config"], values)

    if "required_environment_variables" in frontmatter:
        declared = True
        values, values_invalid = _environment_names(
            frontmatter.get("required_environment_variables")
        )
        invalid = invalid or values_invalid
        _extend_unique(output["config"], values)

    has_requirements = any(output.values())
    return output, declared and has_requirements, invalid


def _setup_declared(
    frontmatter: Mapping[str, Any],
    hints: Mapping[str, Any],
) -> tuple[bool, bool]:
    values: list[Any] = []
    for key in ("setup_required", "setup_needed"):
        if key in frontmatter:
            values.append(frontmatter.get(key))
        if key in hints:
            values.append(hints.get(key))
    invalid = any(not isinstance(value, bool) for value in values)
    return any(value is True for value in values), invalid


def _names(value: Any) -> tuple[list[str], bool]:
    if isinstance(value, str):
        text = value.strip()
        return ([text] if _valid_name(text) else []), not _valid_name(text)
    if not isinstance(value, list):
        return [], True
    result: list[str] = []
    invalid = False
    for item in value:
        if not isinstance(item, str) or not _valid_name(item.strip()):
            invalid = True
            continue
        _extend_unique(result, [item.strip()])
    return result, invalid


def _environment_names(value: Any) -> tuple[list[str], bool]:
    if not isinstance(value, list):
        return _names(value)
    names: list[str] = []
    invalid = False
    for item in value:
        if isinstance(item, str):
            selected = item.strip()
        elif isinstance(item, Mapping) and isinstance(item.get("name"), str):
            selected = str(item.get("name") or "").strip()
            if item.get("optional") is True:
                continue
        else:
            invalid = True
            continue
        if not _valid_name(selected):
            invalid = True
            continue
        _extend_unique(names, [selected])
    return names, invalid


def _valid_name(value: str) -> bool:
    return bool(value) and len(value) <= 200 and not any(ord(char) < 32 for char in value)


def _extend_unique(target: list[str], values: list[str]) -> None:
    for value in values:
        if value not in target:
            target.append(value)


def _parse_frontmatter(content: str) -> dict[str, Any]:
    if not content.startswith("---"):
        return {}
    end = content.find("\n---", 3)
    if end < 0:
        return {}
    lines = _yaml_lines(content[3:end])
    root: dict[str, Any] = {}
    stack: list[tuple[int, Any]] = [(-1, root)]
    for index, (indent, text) in enumerate(lines):
        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if text.startswith("- "):
            if not isinstance(parent, list):
                continue
            raw_item = text[2:].strip()
            if ":" in raw_item and not raw_item.startswith(("'", '"')):
                key, _, raw_value = raw_item.partition(":")
                item: dict[str, Any] = {key.strip(): _parse_scalar(raw_value.strip())}
                parent.append(item)
                stack.append((indent, item))
            else:
                parent.append(_parse_scalar(raw_item))
            continue
        if ":" not in text or not isinstance(parent, dict):
            continue
        key, _, raw_value = text.partition(":")
        key = key.strip()
        raw_value = raw_value.strip()
        if raw_value:
            parent[key] = _parse_scalar(raw_value)
            continue
        child: Any = {}
        if index + 1 < len(lines):
            next_indent, next_text = lines[index + 1]
            if next_indent > indent and next_text.startswith("- "):
                child = []
        parent[key] = child
        stack.append((indent, child))
    return root


def _yaml_lines(text: str) -> list[tuple[int, str]]:
    output: list[tuple[int, str]] = []
    for raw_line in text.splitlines():
        expanded = raw_line.expandtabs(2)
        stripped = _strip_comment(expanded).rstrip()
        if not stripped.strip():
            continue
        output.append((len(stripped) - len(stripped.lstrip(" ")), stripped.lstrip(" ")))
    return output


def _strip_comment(value: str) -> str:
    quote = ""
    for index, char in enumerate(value):
        if char in {"'", '"'}:
            if not quote:
                quote = char
            elif quote == char:
                quote = ""
        elif char == "#" and not quote and (index == 0 or value[index - 1].isspace()):
            return value[:index]
    return value


def _parse_scalar(value: str) -> Any:
    lowered = value.casefold()
    if lowered in {"true", "yes", "on"}:
        return True
    if lowered in {"false", "no", "off"}:
        return False
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        return [] if not inner else [_unquote(item.strip()) for item in inner.split(",")]
    if value.startswith(("'", '"')) and value.endswith(("'", '"')):
        try:
            return ast.literal_eval(value)
        except (SyntaxError, ValueError):
            return value[1:-1]
    return value


def _unquote(value: str) -> str:
    if value.startswith(("'", '"')) and value.endswith(("'", '"')):
        try:
            parsed = ast.literal_eval(value)
            return str(parsed)
        except (SyntaxError, ValueError):
            return value[1:-1]
    return value
