from __future__ import annotations

import re
from typing import Any

from skill_router_plugin.planner import select_skills
from skill_router_plugin.policy import apply_routing_policy, detect_explicit_skill_names


def _entry(
    name: str,
    description: str,
    keywords: list[str],
    *,
    use_when: list[str] | None = None,
    works_with: list[str] | None = None,
    readiness_status: str = "unknown",
    requirements: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "keywords": keywords,
        "use_when": use_when or [description],
        "avoid_when": [],
        "works_with": works_with or [],
        "alternatives": [],
        "readiness_status": readiness_status,
        "setup_needed": readiness_status == "setup_required",
        "requirements": {"skills": requirements or []},
        "policy_metadata_complete": True,
    }


GOLDEN_CATALOG = [
    _entry(
        "github-pr-workflow",
        "GitHub PR lifecycle for branches, pull requests, CI, and merge.",
        ["github", "pr", "pull", "request", "branch", "merge"],
        works_with=["github-code-review"],
    ),
    _entry(
        "github-code-review",
        "Review GitHub pull request diffs and comments.",
        ["github", "code", "review", "pr", "diff"],
        works_with=["github-pr-workflow"],
    ),
    _entry("pdf", "Create, merge, inspect, and secure PDF documents.", ["pdf", "document", "merge", "secure"]),
    _entry("docx", "Create and inspect Word DOCX documents.", ["docx", "word", "document"]),
    _entry(
        "systematic-debugging",
        "Systematic root cause debugging for failures and bugs.",
        ["systematic", "debugging", "failure", "bug", "test"],
    ),
    _entry(
        "architecture-diagram",
        "Create architecture and infrastructure diagrams.",
        ["architecture", "diagram", "infrastructure"],
        works_with=["design-md"],
    ),
    _entry(
        "design-md",
        "Document visual design systems and component decisions.",
        ["design", "system", "component"],
        works_with=["architecture-diagram"],
    ),
    _entry(
        "hermes-skill-authoring",
        "Author and validate Hermes skill documentation.",
        ["hermes", "skill", "authoring", "documentation"],
    ),
    _entry("humanizer", "Rewrite prose in natural human language.", ["rewrite", "prose", "natural", "sentence"]),
    _entry(
        "himalaya",
        "Terminal mail client integration.",
        ["himalaya"],
    ),
    _entry(
        "google-calendar",
        "Calendar integration for events and appointments.",
        ["google"],
    ),
    _entry(
        "deployment-workflow",
        "Deploy an application with verified release steps.",
        ["deploy", "application", "release", "workflow"],
        requirements=["deployment-checks"],
    ),
    _entry("deployment-checks", "Validate deployment prerequisites and checks.", ["deploy", "checks", "validate"]),
    _entry("setup-tool", "Use a configured external workspace.", ["workspace", "external"], readiness_status="setup_required"),
    _entry("missing-tool", "Use a missing local dependency.", ["missing", "dependency"], readiness_status="dependency_missing"),
    _entry("broken-tool", "A broken specialized workflow.", ["broken", "workflow"], readiness_status="broken"),
    _entry("disabled-tool", "A disabled specialized workflow.", ["disabled", "workflow"], readiness_status="disabled"),
    _entry("ready-unrelated", "An unrelated ready workflow.", ["unrelated"], readiness_status="ready"),
]


class _Ctx:
    class _Llm:
        def complete_structured(self, **_kwargs: Any) -> Any:
            raise AssertionError("golden deterministic routing must not call an LLM")

    llm = _Llm()


def route_new(task: str) -> list[dict[str, Any]]:
    selected, _method = select_skills(
        _Ctx(),
        task,
        GOLDEN_CATALOG,
        mode="deterministic",
        limit=5,
        catalog_chars=60_000,
    )
    return apply_routing_policy(
        task=task,
        selected_skills=selected,
        catalog_entries=GOLDEN_CATALOG,
        max_skills=5,
        explicit_skill_names=detect_explicit_skill_names(task, GOLDEN_CATALOG),
    )["selections"]


_OLD_WORD_RE = re.compile(r"[^\W_]{2,}", re.UNICODE)
_OLD_STOP_WORDS = {
    "about", "after", "also", "and", "are", "before", "das", "der", "die",
    "ein", "eine", "for", "from", "für", "ist", "mit", "oder", "the", "this",
    "und", "use", "using", "von", "when", "with", "you", "your", "zur",
}
_OLD_READINESS = {
    "ready": 1.0,
    "unknown": 0.0,
    "setup_required": -1.0,
    "dependency_missing": -2.0,
    "broken": -3.0,
    "disabled": -4.0,
}


def _old_tokens(text: str) -> set[str]:
    return {word for word in _OLD_WORD_RE.findall(str(text).casefold()) if word not in _OLD_STOP_WORDS}


def _old_score(task: str, entry: dict[str, Any]) -> float:
    task_terms = _old_tokens(task)
    name = str(entry.get("name") or "")
    score = 8.0 * len(task_terms & _old_tokens(name.replace("-", " ")))
    score += 4.0 * len(task_terms & set(entry.get("keywords") or []))
    score += 3.0 * len(task_terms & _old_tokens(str(entry.get("description") or "")))
    score += 2.0 * len(task_terms & _old_tokens(" ".join(entry.get("use_when") or [])))
    if name.casefold() in task.casefold():
        score += 12.0
    score += _OLD_READINESS.get(str(entry.get("readiness_status") or "unknown"), 0.0)
    return score


def select_old(task: str, catalog: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    ranked = sorted(
        ((_old_score(task, entry), entry) for entry in catalog),
        key=lambda item: (-item[0], str(item[1]["name"]).casefold()),
    )
    return [
        {
            "name": entry["name"],
            "role": "primary" if index == 0 else "supporting",
            "reason": f"Legacy score {score:.0f}.",
            "order": index + 1,
            "readiness_status": entry["readiness_status"],
            "setup_needed": entry["setup_needed"],
        }
        for index, (score, entry) in enumerate([item for item in ranked if item[0] > 0][:limit])
    ]


def route_old(task: str) -> list[dict[str, Any]]:
    selected = select_old(task, GOLDEN_CATALOG)
    return apply_routing_policy(
        task=task,
        selected_skills=selected,
        catalog_entries=GOLDEN_CATALOG,
        max_skills=5,
        explicit_skill_names=detect_explicit_skill_names(task, GOLDEN_CATALOG),
    )["selections"]


def projection(items: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [{"name": str(item["name"]), "role": str(item["role"])} for item in items]
