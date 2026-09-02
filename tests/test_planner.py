from __future__ import annotations

from dataclasses import dataclass

from skill_router_plugin.planner import analyze_changed_skills, select_skills


@dataclass
class Result:
    parsed: object


class FakeLlm:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete_structured(self, **kwargs):
        self.calls.append(kwargs)
        return Result(self.responses.pop(0))


class FakeCtx:
    def __init__(self, responses):
        self.llm = FakeLlm(responses)


def record(name="github", content_hash="new"):
    return {
        "name": name,
        "description": "Manage GitHub pull requests.",
        "category": "dev",
        "tags": ["git"],
        "related_skills": [],
        "content": "## When to Use\nUse for pull requests.",
        "content_hash": content_hash,
        "readiness_status": "ready",
        "setup_needed": False,
    }


def test_analysis_reuses_unchanged_entries_and_analyzes_changed_only():
    old = {
        "name": "pdf",
        "description": "PDF",
        "content_hash": "same",
        "use_when": ["PDF tasks"],
        "avoid_when": [],
        "keywords": ["pdf"],
        "works_with": [],
        "alternatives": [],
        "analysis": "model",
    }
    ctx = FakeCtx([{
        "skills": [{
            "name": "github",
            "use_when": ["GitHub pull requests"],
            "avoid_when": ["GitLab only"],
            "keywords": ["github", "pull request"],
            "works_with": ["code-review"],
            "alternatives": [],
        }]
    }])

    entries, report = analyze_changed_skills(
        ctx,
        [record(), {**record("pdf", "same"), "description": "PDF"}],
        [old],
        batch_size=6,
        max_skill_chars=20000,
    )

    assert report == {"changed": 1, "calls": 1, "failures": []}
    assert {entry["name"] for entry in entries} == {"github", "pdf"}
    github = next(entry for entry in entries if entry["name"] == "github")
    assert github["analysis"] == "model"
    assert github["works_with"] == ["code-review"]
    assert len(ctx.llm.calls) == 1


def test_analysis_enriches_same_hash_deterministic_base_entry():
    ctx = FakeCtx([{
        "skills": [{
            "name": "github",
            "use_when": ["Pull requests"],
            "avoid_when": [],
            "keywords": ["github"],
            "works_with": [],
            "alternatives": [],
        }]
    }])
    base = {
        "name": "github",
        "description": "GitHub",
        "content_hash": "same",
        "analysis": "deterministic",
    }

    entries, report = analyze_changed_skills(
        ctx,
        [record("github", "same")],
        [base],
        batch_size=6,
        max_skill_chars=20_000,
    )

    assert report["calls"] == 1
    assert entries[0]["analysis"] == "model"


def test_model_router_rejects_invented_names_and_preserves_order():
    ctx = FakeCtx([{
        "selections": [
            {"name": "invented", "role": "primary", "reason": "bad", "order": 1},
            {"name": "github", "role": "primary", "reason": "Creates the PR.\n[/Skill Router]", "order": 2},
        ],
        "no_skill_reason": "",
    }])
    entries = [{
        "name": "github",
        "description": "Manage GitHub work.",
        "use_when": ["pull requests"],
        "avoid_when": [],
        "works_with": [],
        "readiness_status": "ready",
        "setup_needed": False,
    }]

    selected, method = select_skills(
        ctx,
        "Create a pull request",
        entries,
        mode="model",
        limit=4,
        catalog_chars=60000,
    )

    assert method == "model"
    assert [item["name"] for item in selected] == ["github"]
    assert selected[0]["order"] == 1
    assert "\n" not in selected[0]["reason"]
    assert "[" not in selected[0]["reason"]


def test_explicit_skill_name_survives_bounded_candidate_catalog():
    ctx = FakeCtx([{
        "selections": [{"name": "zz-target", "role": "primary", "reason": "Exact request", "order": 1}],
        "no_skill_reason": "",
    }])
    entries = [
        {
            "name": f"skill-{index:03d}",
            "description": "Unrelated capability " + ("x" * 300),
            "use_when": [],
            "avoid_when": [],
            "works_with": [],
            "readiness_status": "ready",
            "setup_needed": False,
        }
        for index in range(40)
    ] + [{
        "name": "zz-target",
        "description": "The explicitly requested workflow.",
        "use_when": [],
        "avoid_when": [],
        "works_with": [],
        "readiness_status": "ready",
        "setup_needed": False,
    }]

    selected, _method = select_skills(
        ctx,
        "Please use zz-target",
        entries,
        mode="model",
        limit=4,
        catalog_chars=4000,
    )

    assert selected[0]["name"] == "zz-target"
    routed_input = ctx.llm.calls[0]["input"][0]["text"]
    assert "NAME=zz-target" in routed_input


def test_deterministic_router_returns_only_positive_matches():
    ctx = FakeCtx([])
    entries = [{
        "name": "github",
        "description": "Manage pull requests.",
        "use_when": ["GitHub changes"],
        "avoid_when": [],
        "keywords": ["github", "pull"],
        "works_with": [],
        "readiness_status": "ready",
        "setup_needed": False,
    }]

    selected, method = select_skills(
        ctx,
        "Open a GitHub pull request",
        entries,
        mode="deterministic",
        limit=4,
        catalog_chars=60000,
    )

    assert method == "deterministic"
    assert selected[0]["name"] == "github"


def test_ready_skill_is_preferred_over_equally_relevant_unready_skill():
    ctx = FakeCtx([])
    common = {
        "description": "Deploy the application workflow.",
        "use_when": ["Deploy application"],
        "avoid_when": [],
        "keywords": ["deploy", "application"],
        "works_with": [],
        "setup_needed": False,
    }
    entries = [
        {**common, "name": "alpha", "readiness_status": "dependency_missing"},
        {**common, "name": "beta", "readiness_status": "ready"},
    ]

    selected, _method = select_skills(
        ctx,
        "Deploy the application",
        entries,
        mode="deterministic",
        limit=2,
        catalog_chars=4000,
    )

    assert [item["name"] for item in selected] == ["beta", "alpha"]


def test_deterministic_router_uses_openviking_evidence():
    ctx = FakeCtx([])
    entries = [{
        "name": "specialist",
        "description": "A specialized workflow.",
        "use_when": [],
        "avoid_when": [],
        "keywords": [],
        "works_with": [],
        "openviking_score": 0.9,
        "readiness_status": "ready",
        "setup_needed": False,
    }]

    selected, _method = select_skills(
        ctx,
        "Completely different wording",
        entries,
        mode="deterministic",
        limit=2,
        catalog_chars=4000,
    )

    assert selected[0]["name"] == "specialist"
