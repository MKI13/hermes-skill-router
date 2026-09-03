"""Read the effective Hermes skill catalog without executing skill content."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterable

from .compat import HermesCompatibility
from .readiness import (
    BROKEN,
    DEPENDENCY_MISSING,
    DISABLED,
    READY,
    SETUP_REQUIRED,
    UNKNOWN,
    evaluate_readiness,
    readiness_sort_key,
)

_ROUTER_SKILLS = {"skill-router", "skill-router:skill-router"}
_WORD_RE = re.compile(r"[^\W_]{2,}", re.UNICODE)
_NEGATION_RE = re.compile(
    r"\b(?:avoid|do\s+not|don't|dont|exclude|kein(?:e[nrms]?)?|nicht|not|ohne|skip|vermeide|without)\b",
    re.IGNORECASE,
)
_READINESS_SCORE_ADJUSTMENT = {
    READY: 1.0,
    UNKNOWN: 0.0,
    SETUP_REQUIRED: -1.0,
    DEPENDENCY_MISSING: -2.0,
    BROKEN: -3.0,
    DISABLED: -4.0,
}
_NAME_TERM_WEIGHT = 8.0
_KEYWORD_TERM_WEIGHT = 4.0
_DESCRIPTION_TERM_WEIGHT = 3.0
_USE_WHEN_TERM_WEIGHT = 2.0
_EXACT_NAME_WEIGHT = 12.0
_OPENVIKING_WEIGHT = 20.0
_AVOID_WHEN_PENALTY = 12.0
_STOP_WORDS = {
    "about", "after", "also", "and", "are", "before", "das", "der", "die",
    "ein", "eine", "for", "from", "für", "ist", "mit", "oder", "the", "this",
    "und", "use", "using", "von", "when", "with", "you", "your", "zur",
}


def _json_object(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def scan_catalog(
    ctx: Any,
    compatibility: HermesCompatibility | None = None,
) -> dict[str, Any]:
    """Return the host-visible catalog and side-effect-free raw skill content.

    The public ``skills_list`` result is the visibility allowlist. Current Hermes
    has no public raw reader, so a small compatibility adapter resolves only those
    visible names to paths using the same ordered/quarantined iterators, then reads
    bytes directly. If the adapter is unavailable, metadata-only routing is safer
    than invoking ``skill_view`` during inventory.
    """
    compat = compatibility or HermesCompatibility(ctx)
    compat.ensure_skills_tool_registration()
    try:
        listing = _json_object(ctx.dispatch_tool("skills_list", {}))
    except Exception:
        listing = {}
    listed = listing.get("skills")
    listing_available = (
        listing.get("success") is True
        and isinstance(listed, list)
        and all(
            isinstance(row, dict) and bool(str(row.get("name") or "").strip())
            for row in listed
        )
    )
    metadata_rows = list(listed) if listing_available else []
    visible_names = {
        str(row.get("name") or "").strip()
        for row in metadata_rows
        if str(row.get("name") or "").strip() not in _ROUTER_SKILLS
    }
    max_chars = _bounded_int(ctx.get_config("max_skill_chars", 20000), 1000, 200000, 20000)
    if listing_available:
        raw_content, reader_mode = compat.read_visible_skill_files(
            visible_names,
            max_chars=max_chars,
        )
    else:
        raw_content, reader_mode = {}, "metadata-only"
    mcp_readiness = compat.active_mcp_readiness()
    records: list[dict[str, Any]] = []
    for metadata in metadata_rows:
        name = str(metadata.get("name") or "").strip()
        if not name or name in _ROUTER_SKILLS:
            continue
        description = str(metadata.get("description") or "").strip()[:1000]
        content = raw_content.get(name, "")
        category = str(metadata.get("category") or "").strip()[:200]
        hash_input = f"{name}\0{description}\0{category}\0{content}"
        readiness = evaluate_readiness(
            content=content,
            visible_skill_names=visible_names,
            metadata_hints=compat.readiness_hints(metadata),
            get_config=ctx.get_config,
            content_expected=reader_mode == "raw-path-current-hermes",
            mcp_readiness=mcp_readiness,
        )
        readiness_hash = hashlib.sha256(
            json.dumps(readiness, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        records.append({
            "name": name,
            "description": description,
            "category": category,
            "tags": [],
            "related_skills": [],
            "content": content,
            "content_hash": hashlib.sha256(hash_input.encode("utf-8")).hexdigest(),
            "readiness_hash": readiness_hash,
            **readiness,
        })

    records.sort(key=lambda item: item["name"].casefold())
    fingerprint_source = "\n".join(
        f"{item['name']}\0{item['content_hash']}\0{item['readiness_hash']}"
        for item in records
    )
    return {
        "catalog_hash": hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest(),
        "skills": records,
        "count": len(records),
        "reader_mode": reader_mode,
        "listing_available": listing_available,
    }


def _bounded_int(value: Any, minimum: int, maximum: int, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def base_plan_entry(record: dict[str, Any]) -> dict[str, Any]:
    """Build a deterministic plan entry used until model analysis completes."""
    content = str(record.get("content") or "")
    when_to_use = _section(content, ("when to use", "wann verwenden", "wann benutzen"))
    pitfalls = _section(content, ("pitfalls", "avoid", "nicht verwenden", "fallstricke"))
    terms = _dedupe(
        tokenize(" ".join([
            str(record.get("name") or ""),
            str(record.get("description") or ""),
            str(record.get("category") or ""),
            " ".join(_strings(record.get("tags"))),
            when_to_use,
        ]))
    )
    return {
        "name": record["name"],
        "description": record.get("description", ""),
        "category": record.get("category", ""),
        "content_hash": record["content_hash"],
        "use_when": _sentences(when_to_use, limit=6) or _sentences(record.get("description", ""), limit=2),
        "avoid_when": _sentences(pitfalls, limit=4),
        "keywords": terms[:40],
        "works_with": _strings(record.get("related_skills"))[:12],
        "alternatives": [],
        "readiness_status": record.get("readiness_status", UNKNOWN),
        "readiness_hash": record.get("readiness_hash", ""),
        "setup_needed": bool(record.get("setup_needed")),
        "requirements": record.get("requirements", {}),
        "dependency_checks": record.get("dependency_checks", []),
        "readiness_reasons": record.get("readiness_reasons", []),
        "policy_metadata_complete": True,
        "analysis": "deterministic",
    }


def rank_entries(task: str, entries: Iterable[dict[str, Any]]) -> list[tuple[float, dict[str, Any]]]:
    """Rank plan entries by lexical, retrieval, and readiness evidence."""
    ranked = [(score_entry(task, entry)["score"], entry) for entry in entries]
    return sorted(
        ranked,
        key=lambda item: (
            -item[0],
            readiness_sort_key(item[1]),
            str(item[1].get("name", "")).casefold(),
        ),
    )


def score_entry(task: str, entry: dict[str, Any]) -> dict[str, float]:
    """Return the deterministic score and its lexical, retrieval, and policy components."""
    task_terms = set(tokenize(task))
    name = str(entry.get("name") or "").strip()
    name_terms = set(tokenize(name.replace("-", " ")))
    keyword_terms = set(_strings(entry.get("keywords")))
    description_terms = set(tokenize(str(entry.get("description") or "")))
    use_when_terms = set(tokenize(" ".join(_strings(entry.get("use_when")))))
    breakdown: dict[str, float] = {
        "name": _NAME_TERM_WEIGHT * len(task_terms & name_terms),
        "keywords": _KEYWORD_TERM_WEIGHT * len(task_terms & keyword_terms),
        "description": _DESCRIPTION_TERM_WEIGHT * len(task_terms & description_terms),
        "use_when": _USE_WHEN_TERM_WEIGHT * len(task_terms & use_when_terms),
    }

    try:
        retrieval = max(0.0, min(1.0, float(entry.get("openviking_score") or 0.0)))
    except (TypeError, ValueError):
        retrieval = 0.0
    breakdown["openviking"] = _OPENVIKING_WEIGHT * retrieval
    negation_conflict = bool(name_terms & negated_terms(task)) or is_negated_name(task, name)
    exact_name = _contains_name(task, name) and not negation_conflict and not is_quoted_name(task, name)
    breakdown["exact_name"] = _EXACT_NAME_WEIGHT if exact_name else 0.0
    breakdown["avoid_when"] = -_AVOID_WHEN_PENALTY if _matches_avoid_when(task_terms, entry) else 0.0
    breakdown["negation"] = -100.0 if negation_conflict else 0.0
    breakdown["relevance_score"] = sum(breakdown.values())
    status = str(entry.get("readiness_status") or UNKNOWN)
    breakdown["readiness"] = _READINESS_SCORE_ADJUSTMENT.get(status, 0.0)
    breakdown["score"] = breakdown["relevance_score"] + breakdown["readiness"]
    return breakdown


def _contains_name(task: str, name: str) -> bool:
    if not name:
        return False
    normalized = str(task or "").casefold()
    needle = name.casefold()
    start = 0
    while True:
        index = normalized.find(needle, start)
        if index < 0:
            return False
        before = normalized[index - 1] if index else ""
        end = index + len(needle)
        after = normalized[end] if end < len(normalized) else ""
        if not _name_character(before) and not _name_character(after):
            return True
        start = index + 1


def is_negated_name(task: str, name: str) -> bool:
    """Return whether a standalone skill name occurs in a local negated clause."""
    if not name:
        return False
    normalized = str(task or "").casefold()
    needle = name.casefold()
    for negation in _NEGATION_RE.finditer(normalized):
        clause = re.split(r"[.;!?]|\b(?:aber|but|however|sondern)\b", normalized[negation.end():], 1)[0]
        index = clause.find(needle)
        if 0 <= index <= 60:
            before = clause[index - 1] if index else ""
            end = index + len(needle)
            after = clause[end] if end < len(clause) else ""
            if not _name_character(before) and not _name_character(after):
                return True
    return False


def negated_terms(task: str) -> set[str]:
    """Return nearby terms governed by a simple English or German negation."""
    normalized = str(task or "").casefold()
    terms: set[str] = set()
    for negation in _NEGATION_RE.finditer(normalized):
        clause = re.split(r"[.;!?]|\b(?:aber|but|however|sondern)\b", normalized[negation.end():], 1)[0]
        words = tokenize(clause)[:5]
        terms.update(word for word in words if word not in {"bitte", "it", "please", "to", "verwenden"})
    return terms


def is_quoted_name(task: str, name: str) -> bool:
    normalized = str(task or "").casefold()
    needle = name.casefold()
    for quote in ('"', "'", "`"):
        if f"{quote}{needle}{quote}" in normalized:
            return True
    return False


def _matches_avoid_when(task_terms: set[str], entry: dict[str, Any]) -> bool:
    for phrase in _strings(entry.get("avoid_when")):
        terms = set(tokenize(phrase))
        if terms and terms <= task_terms:
            return True
    return False


def _name_character(value: str) -> bool:
    return bool(value) and (value.isalnum() or value in {"_", "-", ":"})


def compact_entry(entry: dict[str, Any]) -> str:
    """Render one bounded plan line for model routing."""
    use_when = "; ".join(_strings(entry.get("use_when"))[:4])
    avoid_when = "; ".join(_strings(entry.get("avoid_when"))[:2])
    works_with = ", ".join(_strings(entry.get("works_with"))[:8])
    return (
        f"NAME={entry.get('name', '')} | DESCRIPTION={entry.get('description', '')} | "
        f"USE_WHEN={use_when} | AVOID_WHEN={avoid_when} | WORKS_WITH={works_with} | "
        f"READY={entry.get('readiness_status', 'unknown')} | "
        f"OPENVIKING_SCORE={float(entry.get('openviking_score') or 0.0):.4f}"
    )


def tokenize(text: str) -> list[str]:
    """Return normalized non-trivial terms with a small deterministic alias set."""
    words = [word for word in _WORD_RE.findall(str(text).casefold()) if word not in _STOP_WORDS]
    normalized: list[str] = []
    aliases = {
        "debug": "debugging",
        "debugged": "debugging",
        "debugger": "debugging",
        "failed": "failure",
        "failing": "failure",
        "prs": "pr",
        "requests": "request",
        "systematically": "systematic",
        "tests": "test",
    }
    for word in words:
        normalized.append(word)
        alias = aliases.get(word)
        if alias:
            normalized.append(alias)
    if "pull" in normalized and "request" in normalized:
        normalized.append("pr")
    return _dedupe(normalized)


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _sentences(text: Any, *, limit: int) -> list[str]:
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    if not compact:
        return []
    chunks = re.split(r"(?<=[.!?])\s+|\s*[;•]\s*", compact)
    return [chunk.strip(" -*\t")[:300] for chunk in chunks if chunk.strip(" -*\t")][:limit]


def _section(content: str, headings: tuple[str, ...]) -> str:
    lines = content.splitlines()
    start: int | None = None
    level = 0
    for index, line in enumerate(lines):
        match = re.match(r"^(#{2,6})\s+(.+?)\s*$", line)
        if not match:
            continue
        title = match.group(2).strip().casefold()
        if start is None and any(heading in title for heading in headings):
            start = index + 1
            level = len(match.group(1))
            continue
        if start is not None and len(match.group(1)) <= level:
            return "\n".join(lines[start:index])[:5000]
    return "\n".join(lines[start:])[:5000] if start is not None else ""
