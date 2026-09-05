from __future__ import annotations

from skill_router_plugin.inspection import render_skill_inspection


def render(entry):
    return render_skill_inspection({"entries": [entry], "catalog_hash": "abc"}, entry["name"])


def test_inspect_readiness2_renders_grouped_diagnostics_and_router_action():
    text = render({
        "name": "github-development",
        "readiness_status": "dependency_missing",
        "readiness_summary": "Missing 2 dependencies; setup required for 1 config item.",
        "missing_dependencies": [
            {"type": "command", "name": "gh"},
            {"type": "mcp", "name": "codebase-memory"},
        ],
        "unknown_dependencies": [],
        "setup_requirements": [
            {"type": "config", "name": "GITHUB_TOKEN"},
        ],
        "dependency_checks": [],
        "readiness_reasons": ["One or more declared dependencies are missing."],
    })

    assert "Skill: github-development" in text
    assert "Readiness: dependency_missing" in text
    assert "Summary: Missing 2 dependencies; setup required for 1 config item." in text
    assert "Missing:" in text
    assert "- command: gh" in text
    assert "- mcp: codebase-memory" in text
    assert "Setup required:" in text
    assert "- config: GITHUB_TOKEN" in text
    assert "Router action:" in text
    assert "Do not select as Primary until requirements are satisfied." in text


def test_inspect_readiness2_unknown_is_explained_without_blocking_claim():
    text = render({
        "name": "remote-skill",
        "readiness_status": "unknown",
        "readiness_summary": "1 dependency could not be checked passively.",
        "missing_dependencies": [],
        "unknown_dependencies": [
            {"type": "mcp", "name": "remote-mcp"},
        ],
        "setup_requirements": [],
        "dependency_checks": [],
        "readiness_reasons": [],
    })

    assert "Unknown / not passively verifiable:" in text
    assert "- mcp: remote-mcp" in text
    assert "Treat as unverified; do not promote over a ready alternative." in text


def test_inspect_ready_skill_has_positive_action():
    text = render({
        "name": "ready-skill",
        "readiness_status": "ready",
        "readiness_summary": "All declared requirements are available.",
        "missing_dependencies": [],
        "unknown_dependencies": [],
        "setup_requirements": [],
        "dependency_checks": [],
        "readiness_reasons": [],
    })

    assert "Router action:" in text
    assert "Eligible for normal routing." in text


def test_inspection_never_includes_unrelated_cached_secret_values():
    secret = "do-not-print-this-token"
    text = render({
        "name": "secret-safe",
        "readiness_status": "setup_required",
        "readiness_summary": "Setup required for 1 config item.",
        "missing_dependencies": [],
        "unknown_dependencies": [],
        "setup_requirements": [{"type": "config", "name": "API_TOKEN"}],
        "configured_value": secret,
    })

    assert "API_TOKEN" in text
    assert secret not in text
