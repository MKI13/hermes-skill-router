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


def test_readiness_breaks_ties_but_does_not_create_optional_support():
    ctx = FakeCtx([])
    common = {
        "description": "Deploy the application workflow.",
        "use_when": ["Deploy application workflow"],
        "avoid_when": [],
        "keywords": ["deploy", "application", "workflow"],
        "works_with": [],
        "setup_needed": False,
    }
    entries = [
        {**common, "name": "alpha", "readiness_status": "dependency_missing"},
        {**common, "name": "beta", "readiness_status": "ready"},
    ]

    selected, _method = select_skills(
        ctx,
        "Deploy the application workflow",
        entries,
        mode="deterministic",
        limit=2,
        catalog_chars=4000,
    )

    assert [item["name"] for item in selected] == ["beta"]


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


def test_ready_baseline_is_not_relevance():
    entries = [{
        "name": "unrelated-ready",
        "description": "Different work.",
        "use_when": [],
        "avoid_when": [],
        "keywords": [],
        "works_with": [],
        "readiness_status": "ready",
        "setup_needed": False,
    }]

    selected, _method = select_skills(
        FakeCtx([]),
        "17 + 25",
        entries,
        mode="deterministic",
        limit=4,
        catalog_chars=4000,
    )

    assert selected == []


def test_deterministic_threshold_is_inclusive_and_configurable():
    entry = {
        "name": "specialist",
        "description": "",
        "use_when": [],
        "avoid_when": [],
        "keywords": ["alpha", "bravo", "charlie", "delta", "echo"],
        "works_with": [],
        "readiness_status": "unknown",
        "setup_needed": False,
    }

    selected, _method = select_skills(
        FakeCtx([]),
        "alpha bravo charlie delta echo",
        [entry],
        mode="deterministic",
        limit=4,
        catalog_chars=4000,
        deterministic_min_score=20,
    )
    rejected, _method = select_skills(
        FakeCtx([]),
        "alpha bravo charlie delta",
        [entry],
        mode="deterministic",
        limit=4,
        catalog_chars=4000,
        deterministic_min_score=20,
    )

    assert [item["name"] for item in selected] == ["specialist"]
    assert rejected == []


def test_avoid_when_can_remove_a_borderline_match():
    entry = {
        "name": "specialist",
        "description": "",
        "use_when": [],
        "avoid_when": ["alpha bravo"],
        "keywords": ["alpha", "bravo", "charlie", "delta", "echo"],
        "works_with": [],
        "readiness_status": "unknown",
        "setup_needed": False,
    }

    selected, _method = select_skills(
        FakeCtx([]),
        "alpha bravo charlie delta echo",
        [entry],
        mode="deterministic",
        limit=4,
        catalog_chars=4000,
    )

    assert selected == []


def test_model_error_uses_same_strict_deterministic_gate():
    ctx = FakeCtx([])
    ctx.llm.complete_structured = lambda **_kwargs: (_ for _ in ()).throw(TimeoutError())
    entries = [{
        "name": "unrelated-ready",
        "description": "Different work.",
        "use_when": [],
        "avoid_when": [],
        "keywords": [],
        "works_with": [],
        "readiness_status": "ready",
        "setup_needed": False,
    }]

    selected, method = select_skills(
        ctx,
        "17 + 25",
        entries,
        mode="model",
        limit=4,
        catalog_chars=4000,
    )

    assert method == "deterministic-fallback"
    assert selected == []


def test_optional_support_requires_clear_multi_skill_evidence_and_is_capped():
    entries = [
        {
            "name": name,
            "description": "Alpha bravo workflow.",
            "use_when": ["alpha bravo workflow"],
            "avoid_when": [],
            "keywords": ["alpha", "bravo", "workflow"],
            "works_with": [other],
            "readiness_status": "unknown",
            "setup_needed": False,
        }
        for name, other in (("alpha-bravo", "charlie-delta"), ("charlie-delta", "alpha-bravo"))
    ] + [{
        "name": "echo-foxtrot",
        "description": "Echo foxtrot workflow.",
        "use_when": ["echo foxtrot workflow"],
        "avoid_when": [],
        "keywords": ["echo", "foxtrot", "workflow"],
        "works_with": [],
        "readiness_status": "unknown",
        "setup_needed": False,
    }]

    single, _method = select_skills(
        FakeCtx([]),
        "alpha bravo workflow",
        entries,
        mode="deterministic",
        limit=4,
        catalog_chars=4000,
    )
    combined, _method = select_skills(
        FakeCtx([]),
        "alpha bravo and charlie delta plus echo foxtrot workflow",
        entries,
        mode="deterministic",
        limit=4,
        catalog_chars=4000,
    )

    assert [item["name"] for item in single] == ["alpha-bravo"]
    assert len(combined) == 2
    assert [item["role"] for item in combined] == ["primary", "supporting"]


def test_hybrid_router_uses_semantic_top_two_only_when_margin_is_below_threshold():
    entries = [
        {
            "name": name,
            "description": f"{name} workflow",
            "use_when": [],
            "avoid_when": [],
            "keywords": [],
            "works_with": [],
            "readiness_status": "ready",
            "setup_needed": False,
        }
        for name in ("alpha", "beta", "gamma")
    ]
    ctx = FakeCtx([])

    ambiguous, method = select_skills(
        ctx,
        "semantic request and secondary workflow",
        entries,
        mode="hybrid",
        limit=5,
        catalog_chars=4000,
        embedding_scores={"alpha": 0.80, "beta": 0.781, "gamma": 0.77},
        embedding_ambiguity_margin=0.02,
        embedding_min_score=0.35,
        max_optional_supporting_skills=2,
    )
    clear, _ = select_skills(
        ctx,
        "semantic request and secondary workflow",
        entries,
        mode="hybrid",
        limit=5,
        catalog_chars=4000,
        embedding_scores={"alpha": 0.80, "beta": 0.77, "gamma": 0.76},
        embedding_ambiguity_margin=0.02,
        embedding_min_score=0.35,
        max_optional_supporting_skills=2,
    )

    assert method == "embedding"
    assert [item["name"] for item in ambiguous] == ["alpha", "beta"]
    assert [item["role"] for item in ambiguous] == ["primary", "supporting"]
    assert [item["name"] for item in clear] == ["alpha"]
    assert ctx.llm.calls == []


def test_hybrid_router_keeps_ambiguous_top_two_for_declared_relation():
    entries = [
        {
            "name": "alpha",
            "description": "First workflow.",
            "use_when": [],
            "avoid_when": [],
            "keywords": [],
            "works_with": ["beta"],
            "readiness_status": "ready",
            "setup_needed": False,
        },
        {
            "name": "beta",
            "description": "Second workflow.",
            "use_when": [],
            "avoid_when": [],
            "keywords": [],
            "works_with": [],
            "readiness_status": "ready",
            "setup_needed": False,
        },
    ]

    selected, method = select_skills(
        FakeCtx([]),
        "analyze the request and summarize the result",
        entries,
        mode="hybrid",
        limit=5,
        catalog_chars=4000,
        embedding_scores={"alpha": 0.80, "beta": 0.781},
        embedding_ambiguity_margin=0.02,
        embedding_min_score=0.35,
        max_optional_supporting_skills=1,
    )

    assert method == "embedding"
    assert [item["name"] for item in selected] == ["alpha", "beta"]


def test_hybrid_router_drops_negated_ambiguous_supporting_candidate():
    entries = [
        {
            "name": "alpha",
            "description": "Prepare documents.",
            "use_when": [],
            "avoid_when": [],
            "keywords": [],
            "works_with": [],
            "readiness_status": "ready",
            "setup_needed": False,
        },
        {
            "name": "docx",
            "description": "Create Microsoft Word documents.",
            "use_when": [],
            "avoid_when": [],
            "keywords": ["document"],
            "works_with": ["alpha"],
            "readiness_status": "ready",
            "setup_needed": False,
        },
    ]

    selected, method = select_skills(
        FakeCtx([]),
        "Prepare the document and do not use docx.",
        entries,
        mode="hybrid",
        limit=5,
        catalog_chars=4000,
        embedding_scores={"alpha": 0.80, "docx": 0.79},
        embedding_ambiguity_margin=0.02,
        embedding_min_score=0.35,
        max_optional_supporting_skills=1,
    )

    assert method == "embedding"
    assert [item["name"] for item in selected] == ["alpha"]


def test_hybrid_router_drops_ambiguous_top_two_without_multi_skill_intent():
    entries = [
        {
            "name": "skill-router:skill-router",
            "description": "Inspect routing plans, readiness, and execution audits.",
            "use_when": [],
            "avoid_when": [],
            "keywords": [],
            "works_with": [],
            "readiness_status": "ready",
            "setup_needed": False,
        },
        {
            "name": "comfyui",
            "description": "Generate images, video, and audio via diffusion workflows.",
            "use_when": [],
            "avoid_when": [],
            "keywords": [],
            "works_with": [],
            "readiness_status": "ready",
            "setup_needed": False,
        },
    ]

    for task in (
        "funktioniert jetzt besser? Mach einen kleinen schnellen Test.",
        "Funktioniert es jetzt besser und kannst du einen kleinen schnellen Test machen?",
        "Prüfe den Router mit einem kleinen Test.",
        "Test the router and report whether it works better now.",
    ):
        selected, method = select_skills(
            FakeCtx([]),
            task,
            entries,
            mode="hybrid",
            limit=5,
            catalog_chars=4000,
            embedding_scores={
                "skill-router:skill-router": 0.4844,
                "comfyui": 0.4711,
            },
            embedding_ambiguity_margin=0.02,
            embedding_min_score=0.35,
            max_optional_supporting_skills=1,
        )

        assert method == "embedding"
        assert [item["name"] for item in selected] == ["skill-router:skill-router"]


def test_hybrid_router_treats_wrong_supporting_skill_report_as_router_meta_request():
    entries = [
        {
            "name": name,
            "description": description,
            "use_when": [],
            "avoid_when": [],
            "keywords": [],
            "works_with": [],
            "readiness_status": "ready",
            "setup_needed": False,
        }
        for name, description in (
            ("skill-router:skill-router", "Inspect routing diagnostics."),
            ("comfyui", "Generate images with diffusion workflows."),
        )
    ]

    selected, method = select_skills(
        FakeCtx([]),
        (
            "Der bekannte Top-2-Fehler besteht noch: Beim alten Schnelltest wird "
            "comfyui weiterhin unnötig als Supporting Skill ergänzt."
        ),
        entries,
        mode="hybrid",
        limit=5,
        catalog_chars=4000,
        embedding_scores={"skill-router:skill-router": 0.1, "comfyui": 0.99},
    )

    assert method == "deterministic-router-meta"
    assert [item["name"] for item in selected] == ["skill-router:skill-router"]

    explicit, explicit_method = select_skills(
        FakeCtx([]),
        "Use comfyui as the primary skill.",
        entries,
        mode="hybrid",
        limit=5,
        catalog_chars=4000,
        embedding_scores={"skill-router:skill-router": 0.1, "comfyui": 0.99},
    )

    assert explicit_method == "deterministic-explicit"
    assert [item["name"] for item in explicit] == ["comfyui"]


def test_hybrid_router_prioritizes_its_operational_skill_for_router_meta_tasks():
    entries = [
        {
            "name": name,
            "description": description,
            "use_when": [],
            "avoid_when": [],
            "keywords": [],
            "works_with": [],
            "readiness_status": "ready",
            "setup_needed": False,
        }
        for name, description in (
            ("skill-router:skill-router", "Inspect routing diagnostics."),
            ("plan", "Write an implementation plan."),
            ("hermes-agent", "Configure Hermes Agent."),
        )
    ]

    selected, method = select_skills(
        FakeCtx([]),
        (
            "Ich sehe das du skill plan liest und dann skill hermes-agent. "
            "Solltest du nicht zuerst Skill Router lesen?"
        ),
        entries,
        mode="hybrid",
        limit=5,
        catalog_chars=4000,
        embedding_scores={
            "skill-router:skill-router": 0.1,
            "plan": 0.9,
            "hermes-agent": 0.8,
        },
    )

    assert method == "deterministic-router-meta"
    assert [item["name"] for item in selected] == ["skill-router:skill-router"]

    positive_german, positive_german_method = select_skills(
        FakeCtx([]),
        "Skill Router verwenden",
        entries,
        mode="hybrid",
        limit=5,
        catalog_chars=4000,
        embedding_scores={"skill-router:skill-router": 0.1, "plan": 0.9},
    )

    assert positive_german_method == "deterministic-router-meta"
    assert [item["name"] for item in positive_german] == ["skill-router:skill-router"]

    negated, negated_method = select_skills(
        FakeCtx([]),
        "Do not use Skill Router. Use plan.",
        entries,
        mode="hybrid",
        limit=5,
        catalog_chars=4000,
        embedding_scores={"skill-router:skill-router": 0.99, "plan": 0.8},
    )

    assert negated_method == "deterministic-explicit"
    assert [item["name"] for item in negated] == ["plan"]

    negated_only, negated_only_method = select_skills(
        FakeCtx([]),
        "Do not use Skill Router.",
        entries,
        mode="hybrid",
        limit=5,
        catalog_chars=4000,
        embedding_scores={"skill-router:skill-router": 0.99, "plan": 0.1},
    )

    assert negated_only_method == "deterministic-router-meta-negated"
    assert negated_only == []

    negated_german, negated_german_method = select_skills(
        FakeCtx([]),
        "Skill Router nicht verwenden.",
        entries,
        mode="hybrid",
        limit=5,
        catalog_chars=4000,
        embedding_scores={"skill-router:skill-router": 0.99, "plan": 0.1},
    )

    assert negated_german_method == "deterministic-router-meta-negated"
    assert negated_german == []

    without_german, without_german_method = select_skills(
        FakeCtx([]),
        "Ohne Skill Router.",
        entries,
        mode="hybrid",
        limit=5,
        catalog_chars=4000,
        embedding_scores={"skill-router:skill-router": 0.99, "plan": 0.1},
    )

    assert without_german_method == "deterministic-router-meta-negated"
    assert without_german == []


def test_hybrid_router_requires_stronger_embedding_for_no_lexical_signal():
    entries = [{
        "name": "blocked-page-recovery",
        "description": "Recover pages blocked by WAFs and paywalls.",
        "use_when": [],
        "avoid_when": [],
        "keywords": ["blocked", "page", "waf", "paywall"],
        "works_with": [],
        "readiness_status": "ready",
        "setup_needed": False,
    }]

    selected, method = select_skills(
        FakeCtx([]),
        "wo liegt dieser Fehler? warum hat er das gemacht?",
        entries,
        mode="hybrid",
        limit=5,
        catalog_chars=4000,
        embedding_scores={"blocked-page-recovery": 0.3541},
    )

    assert method == "embedding"
    assert selected == []


def test_hybrid_router_keeps_configured_floor_when_lexical_signal_exists():
    entries = [{
        "name": "blocked-page-recovery",
        "description": "Recover blocked pages.",
        "use_when": [],
        "avoid_when": [],
        "keywords": ["blocked", "page"],
        "works_with": [],
        "readiness_status": "ready",
        "setup_needed": False,
    }]

    selected, _method = select_skills(
        FakeCtx([]),
        "recover a blocked page",
        entries,
        mode="hybrid",
        limit=5,
        catalog_chars=4000,
        embedding_scores={"blocked-page-recovery": 0.40},
    )

    assert [item["name"] for item in selected] == ["blocked-page-recovery"]


def test_hybrid_router_gives_explicit_skill_deterministic_priority():
    entries = [
        {
            "name": name,
            "description": "Workflow",
            "use_when": [],
            "avoid_when": [],
            "keywords": [],
            "works_with": [],
            "readiness_status": "ready",
            "setup_needed": False,
        }
        for name in ("explicit-skill", "semantic-winner")
    ]

    selected, method = select_skills(
        FakeCtx([]),
        "Bitte explicit-skill verwenden",
        entries,
        mode="hybrid",
        limit=5,
        catalog_chars=4000,
        embedding_scores={"explicit-skill": 0.2, "semantic-winner": 0.99},
    )

    assert method == "deterministic-explicit"
    assert [item["name"] for item in selected] == ["explicit-skill"]


def test_hybrid_router_fails_open_to_strict_deterministic_routing():
    entries = [{
        "name": "pr-manager",
        "description": "Manage GitHub pull requests.",
        "use_when": ["open pull request"],
        "avoid_when": [],
        "keywords": ["github", "pull", "request", "review"],
        "works_with": [],
        "readiness_status": "ready",
        "setup_needed": False,
    }]

    selected, method = select_skills(
        FakeCtx([]),
        "Open a GitHub pull request",
        entries,
        mode="hybrid",
        limit=5,
        catalog_chars=4000,
        embedding_scores=None,
    )

    assert method == "deterministic-fallback"
    assert [item["name"] for item in selected] == ["pr-manager"]
