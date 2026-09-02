from __future__ import annotations

from skill_router_plugin.policy import apply_routing_policy, detect_explicit_skill_names


def entry(name, status="ready", *, requires=None, alternatives=None):
    return {
        "name": name,
        "readiness_status": status,
        "setup_needed": status == "setup_required",
        "requirements": {
            "commands": [],
            "python_modules": [],
            "skills": list(requires or []),
            "config": [],
        },
        "alternatives": list(alternatives or []),
    }


def selected(name, role="supporting", **extra):
    return {
        "name": name,
        "role": role,
        "reason": "Relevant skill",
        "order": 1,
        **extra,
    }


def policy(selections, catalog, *, explicit=None, limit=5):
    return apply_routing_policy(
        task="Example task",
        selected_skills=selections,
        catalog_entries=catalog,
        max_skills=limit,
        explicit_skill_names=list(explicit or []),
    )


def names(result):
    return [item["name"] for item in result["selections"]]


def roles(result):
    return [item["role"] for item in result["selections"]]


def test_exactly_one_primary_remains_unchanged():
    result = policy(
        [selected("github", "primary"), selected("review")],
        [entry("github"), entry("review")],
    )

    assert roles(result) == ["primary", "supporting"]
    assert result["policy_status"] == "valid"


def test_two_primaries_are_normalized_deterministically():
    result = policy(
        [selected("github", "primary"), selected("review", "primary")],
        [entry("github"), entry("review")],
    )

    assert roles(result) == ["primary", "supporting"]
    assert result["policy_status"] == "adjusted"


def test_supporting_only_selection_promotes_first_valid_skill():
    result = policy(
        [selected("github"), selected("review")],
        [entry("github"), entry("review")],
    )

    assert roles(result) == ["primary", "supporting"]
    assert result["policy_status"] == "adjusted"


def test_ready_and_unknown_are_allowed():
    result = policy(
        [selected("ready-skill", "primary"), selected("unknown-skill")],
        [entry("ready-skill"), entry("unknown-skill", "unknown")],
    )

    assert names(result) == ["ready-skill", "unknown-skill"]
    assert result["policy_status"] == "valid"


def test_setup_required_is_displaced_when_ready_candidate_exists():
    result = policy(
        [selected("setup", "primary"), selected("ready")],
        [entry("setup", "setup_required"), entry("ready")],
    )

    assert names(result) == ["ready"]
    assert roles(result) == ["primary"]
    assert result["policy_status"] == "adjusted"


def test_setup_required_is_retained_when_ready_candidate_is_not_usable():
    result = policy(
        [selected("setup", "primary"), selected("ready")],
        [
            entry("setup", "setup_required"),
            entry("ready", requires=["missing"]),
        ],
    )

    assert names(result) == ["setup"]
    assert result["policy_status"] == "degraded"


def test_dependency_missing_is_not_an_automatic_primary():
    result = policy(
        [selected("missing", "primary")],
        [entry("missing", "dependency_missing")],
    )

    assert result["selections"] == []
    assert result["policy_status"] == "blocked"


def test_broken_and_disabled_skills_are_removed_automatically():
    broken = policy([selected("broken", "primary")], [entry("broken", "broken")])
    disabled = policy([selected("disabled", "primary")], [entry("disabled", "disabled")])

    assert broken["selections"] == []
    assert broken["policy_status"] == "blocked"
    assert disabled["selections"] == []
    assert disabled["policy_status"] == "blocked"


def test_explicit_installed_skill_is_added_when_model_omits_it():
    result = policy([], [entry("github")], explicit=["github"])

    assert names(result) == ["github"]
    assert roles(result) == ["primary"]
    assert result["policy_status"] == "adjusted"


def test_explicit_skill_becomes_primary_over_model_primary():
    result = policy(
        [selected("other", "primary")],
        [entry("other"), entry("github")],
        explicit=["github"],
    )

    assert names(result) == ["github", "other"]
    assert roles(result) == ["primary", "supporting"]


def test_explicit_setup_required_skill_remains_visible():
    result = policy(
        [selected("setup", "primary")],
        [entry("setup", "setup_required")],
        explicit=["setup"],
    )

    assert names(result) == ["setup"]
    assert result["policy_status"] == "degraded"
    assert "setup-required:setup" in result["warnings"]


def test_explicit_dependency_missing_skill_is_degraded():
    result = policy(
        [selected("missing", "primary")],
        [entry("missing", "dependency_missing")],
        explicit=["missing"],
    )

    assert names(result) == ["missing"]
    assert result["policy_status"] == "degraded"


def test_explicit_disabled_skill_is_blocked_not_reenabled():
    result = policy(
        [selected("disabled", "primary")],
        [entry("disabled", "disabled")],
        explicit=["disabled"],
    )

    assert result["selections"] == []
    assert result["policy_status"] == "blocked"
    assert "requested-disabled:disabled" in result["warnings"]


def test_explicit_broken_skill_is_blocked_not_executable():
    result = policy(
        [selected("broken", "primary")],
        [entry("broken", "broken")],
        explicit=["broken"],
    )

    assert result["selections"] == []
    assert result["policy_status"] == "blocked"
    assert "requested-broken:broken" in result["warnings"]


def test_direct_dependency_is_added_before_primary():
    result = policy(
        [selected("pr-review", "primary")],
        [entry("pr-review", requires=["github"]), entry("github")],
    )

    assert names(result) == ["github", "pr-review"]
    assert roles(result) == ["supporting", "primary"]
    assert result["policy_status"] == "adjusted"
    assert "Added required skill: github" in result["changes"]


def test_transitive_dependencies_are_ordered_first():
    result = policy(
        [selected("a", "primary")],
        [entry("a", requires=["b"]), entry("b", requires=["c"]), entry("c")],
    )

    assert names(result) == ["c", "b", "a"]
    assert roles(result) == ["supporting", "supporting", "primary"]


def test_missing_dependency_blocks_unsafe_primary():
    result = policy(
        [selected("a", "primary")],
        [entry("a", requires=["missing"])],
    )

    assert result["selections"] == []
    assert result["policy_status"] == "blocked"
    assert "missing-dependency:a->missing" in result["warnings"]


def test_broken_dependency_blocks_unsafe_primary():
    result = policy(
        [selected("a", "primary")],
        [entry("a", requires=["b"]), entry("b", "broken")],
    )

    assert result["selections"] == []
    assert result["policy_status"] == "blocked"
    assert "unusable-dependency:a->b:broken" in result["warnings"]


def test_dependency_cycle_is_degraded_without_crashing():
    result = policy(
        [selected("a", "primary")],
        [entry("a", requires=["b"]), entry("b", requires=["a"])],
    )

    assert names(result) == ["b", "a"]
    assert result["policy_status"] == "degraded"
    assert any(warning.startswith("dependency-cycle:") for warning in result["warnings"])


def test_already_selected_dependency_is_not_duplicated():
    result = policy(
        [selected("a", "primary"), selected("b")],
        [entry("a", requires=["b"]), entry("b")],
    )

    assert names(result) == ["b", "a"]
    assert len(result["selections"]) == 2


def test_dependencies_displace_optional_supporting_skills_at_limit():
    result = policy(
        [selected("a", "primary"), selected("x"), selected("y")],
        [entry("a", requires=["b"]), entry("b"), entry("x"), entry("y")],
        limit=3,
    )

    assert names(result) == ["b", "a", "x"]
    assert len(result["selections"]) == 3
    assert any("Removed optional supporting skill" in change for change in result["changes"])


def test_alternative_skills_are_not_selected_together():
    result = policy(
        [selected("github", "primary"), selected("gitlab")],
        [entry("github", alternatives=["gitlab"]), entry("gitlab")],
    )

    assert names(result) == ["github"]
    assert result["policy_status"] == "adjusted"


def test_explicit_alternative_wins():
    result = policy(
        [selected("github", "primary"), selected("gitlab")],
        [entry("github", alternatives=["gitlab"]), entry("gitlab")],
        explicit=["gitlab"],
    )

    assert names(result) == ["gitlab"]
    assert roles(result) == ["primary"]


def test_better_readiness_wins_between_alternatives():
    result = policy(
        [selected("setup", "primary"), selected("ready")],
        [entry("setup", "setup_required", alternatives=["ready"]), entry("ready")],
    )

    assert names(result) == ["ready"]


def test_incomplete_policy_metadata_is_not_treated_as_safe():
    compacted = entry("github")
    compacted["policy_metadata_complete"] = False

    result = policy([selected("github", "primary")], [compacted])

    assert result["selections"] == []
    assert result["policy_status"] == "blocked"
    assert "policy-metadata-unavailable:github" in result["warnings"]


def test_unknown_model_fields_are_not_forwarded():
    result = policy(
        [selected("github", "primary", force=True, ignore_policy=True, skip_dependencies=True)],
        [entry("github")],
    )

    assert set(result["selections"][0]) == {
        "name",
        "role",
        "reason",
        "order",
        "readiness_status",
        "setup_needed",
    }


def test_explicit_skill_detection_uses_standalone_installed_names():
    catalog = [entry("git"), entry("github"), entry("code-review")]

    detected = detect_explicit_skill_names(
        "Benutze github und code-review, nicht irgendein githubish Wort.",
        catalog,
    )

    assert detected == ["github", "code-review"]
