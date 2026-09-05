from __future__ import annotations

from skill_router_plugin.policy import apply_routing_policy


def entry(name, status, *, keywords):
    return {
        "name": name,
        "description": "",
        "keywords": list(keywords),
        "use_when": [],
        "avoid_when": [],
        "works_with": [],
        "alternatives": [],
        "readiness_status": status,
        "setup_needed": False,
        "requirements": {"commands": [], "python_modules": [], "skills": [], "config": []},
    }


def selected(name, role="supporting"):
    return {"name": name, "role": role, "reason": "Relevant", "order": 1}


def route(task, selections, catalog, *, explicit=None):
    return apply_routing_policy(
        task=task,
        selected_skills=selections,
        catalog_entries=catalog,
        max_skills=4,
        explicit_skill_names=list(explicit or []),
    )


def primary(result):
    return next(item["name"] for item in result["selections"] if item["role"] == "primary")


def test_ready_fallback_applies_when_relevance_is_close():
    catalog = [
        entry("unknown", "unknown", keywords=["deploy", "service", "blue", "green", "release"]),
        entry("ready", "ready", keywords=["deploy", "service", "blue", "green"]),
    ]
    result = route(
        "deploy service blue green release",
        [selected("unknown", "primary"), selected("ready")],
        catalog,
    )

    assert primary(result) == "ready"
    assert result["policy_status"] == "adjusted"


def test_unknown_primary_is_retained_when_clearly_more_relevant():
    catalog = [
        entry("unknown", "unknown", keywords=["deploy", "service", "blue", "green", "release", "production"]),
        entry("ready", "ready", keywords=["deploy"]),
    ]
    result = route(
        "deploy service blue green release production",
        [selected("unknown", "primary"), selected("ready")],
        catalog,
    )

    assert primary(result) == "unknown"


def test_explicit_unknown_is_never_overridden_by_confidence_fallback():
    catalog = [
        entry("unknown", "unknown", keywords=["deploy"]),
        entry("ready", "ready", keywords=["deploy", "service", "release"]),
    ]
    result = route(
        "use unknown for deploy service release",
        [selected("ready", "primary")],
        catalog,
        explicit=["unknown"],
    )

    assert primary(result) == "unknown"
