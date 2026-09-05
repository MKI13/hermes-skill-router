from __future__ import annotations

from skill_router_plugin.policy import apply_routing_policy


def entry(name, status="ready", *, alternatives=None):
    return {
        "name": name,
        "readiness_status": status,
        "setup_needed": status == "setup_required",
        "requirements": {"commands": [], "python_modules": [], "skills": [], "config": []},
        "alternatives": list(alternatives or []),
    }


def selected(name, role="supporting"):
    return {"name": name, "role": role, "reason": "Relevant skill", "order": 1}


def route(selections, catalog, *, explicit=None):
    return apply_routing_policy(
        task="Example task",
        selected_skills=selections,
        catalog_entries=catalog,
        max_skills=5,
        explicit_skill_names=list(explicit or []),
    )


def names(result):
    return [item["name"] for item in result["selections"]]


def test_ready_displaces_unknown_primary_when_both_are_normal_candidates():
    result = route(
        [selected("unknown", "primary"), selected("ready")],
        [entry("unknown", "unknown"), entry("ready")],
    )

    assert names(result) == ["ready", "unknown"]
    assert result["selections"][0]["role"] == "primary"
    assert result["policy_status"] == "adjusted"
    assert "Preferred ready skill as Primary over unknown skill: unknown" in result["changes"]


def test_unknown_remains_primary_when_no_ready_candidate_exists():
    result = route(
        [selected("unknown", "primary")],
        [entry("unknown", "unknown")],
    )

    assert names(result) == ["unknown"]
    assert result["selections"][0]["role"] == "primary"


def test_explicit_unknown_still_wins_over_ready_candidate():
    result = route(
        [selected("ready", "primary")],
        [entry("ready"), entry("unknown", "unknown")],
        explicit=["unknown"],
    )

    assert names(result)[0] == "unknown"
    assert result["selections"][0]["role"] == "primary"


def test_setup_required_never_becomes_primary_when_ready_candidate_exists():
    result = route(
        [selected("setup", "primary"), selected("ready")],
        [entry("setup", "setup_required"), entry("ready")],
    )

    assert names(result) == ["ready"]
    assert result["selections"][0]["role"] == "primary"


def test_dependency_missing_never_becomes_primary_when_ready_candidate_exists():
    result = route(
        [selected("missing", "primary"), selected("ready")],
        [entry("missing", "dependency_missing"), entry("ready")],
    )

    assert names(result) == ["ready"]
    assert result["selections"][0]["role"] == "primary"


def test_broken_never_becomes_primary_when_ready_candidate_exists():
    result = route(
        [selected("broken", "primary"), selected("ready")],
        [entry("broken", "broken"), entry("ready")],
    )

    assert names(result) == ["ready"]
    assert result["selections"][0]["role"] == "primary"
