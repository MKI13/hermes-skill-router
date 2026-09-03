from __future__ import annotations

import json

from skill_router_plugin.catalog import base_plan_entry, rank_entries, scan_catalog, score_entry


class Compatibility:
    def __init__(self, content, mode, mcp_readiness=None):
        self.content = content
        self.mode = mode
        self.mcp_readiness = mcp_readiness

    def ensure_skills_tool_registration(self):
        return True

    def read_visible_skill_files(self, names, *, max_chars):
        return self.content, self.mode

    def readiness_hints(self, metadata):
        return {}

    def active_mcp_readiness(self):
        return self.mcp_readiness


def test_scan_catalog_reads_effective_skills_without_preprocessing():
    listing = json.dumps({
        "success": True,
        "skills": [
            {"name": "github", "description": "Manage GitHub work.", "category": "dev"},
            {"name": "skill-router:skill-router", "description": "self", "category": "plugin"},
        ],
    })

    class Ctx:
        def get_config(self, key, default=None):
            return default

        def dispatch_tool(self, name, args):
            assert (name, args) == ("skills_list", {})
            return listing

    compatibility = Compatibility({
        "github": "## When to Use\nUse for pull requests and issues.\n## Pitfalls\nAvoid for GitLab."
    }, "raw-path-current-hermes")

    catalog = scan_catalog(Ctx(), compatibility)

    assert catalog["count"] == 1
    assert catalog["skills"][0]["name"] == "github"
    assert "Use for pull requests" in catalog["skills"][0]["content"]
    assert catalog["reader_mode"] == "raw-path-current-hermes"
    assert len(catalog["catalog_hash"]) == 64


def test_metadata_only_fallback_keeps_visible_skills():
    listing = json.dumps({
        "success": True,
        "skills": [{"name": "github", "description": "Manage GitHub work."}],
    })

    class Ctx:
        def get_config(self, key, default=None):
            return default

        def dispatch_tool(self, name, args):
            return listing

    catalog = scan_catalog(Ctx(), Compatibility({}, "metadata-only"))

    assert catalog["count"] == 1
    assert catalog["skills"][0]["content"] == ""
    assert catalog["reader_mode"] == "metadata-only"


def test_missing_skills_list_dispatch_falls_back_without_crashing():
    class Ctx:
        def get_config(self, key, default=None):
            return default

        def dispatch_tool(self, name, args):
            raise RuntimeError("skills_list unavailable")

    catalog = scan_catalog(Ctx(), Compatibility({}, "raw-path-current-hermes"))

    assert catalog["count"] == 0
    assert catalog["reader_mode"] == "metadata-only"


def test_only_visible_skills_can_become_mcp_backed_routing_entries():
    content = """---
name: codebase-memory
description: Inspect indexed codebases.
requirements:
  mcps:
    - codebase-memory
---
# Codebase Memory
"""

    class Ctx:
        def __init__(self, skills):
            self.skills = skills

        def get_config(self, key, default=None):
            return default

        def dispatch_tool(self, name, args):
            return json.dumps({"success": True, "skills": self.skills})

    metadata = [{"name": "codebase-memory", "description": "Inspect indexed codebases."}]
    with_mcp = Compatibility(
        {"codebase-memory": content},
        "raw-path-current-hermes",
        {"codebase-memory": True},
    )
    without_mcp = Compatibility(
        {"codebase-memory": content},
        "raw-path-current-hermes",
        {},
    )

    profile_a = scan_catalog(Ctx(metadata), with_mcp)
    profile_b = scan_catalog(Ctx(metadata), without_mcp)
    profile_c = scan_catalog(Ctx([]), with_mcp)

    assert profile_a["skills"][0]["readiness_status"] == "ready"
    assert profile_b["skills"][0]["readiness_status"] == "dependency_missing"
    assert profile_c["skills"] == []


def test_later_mcp_configuration_changes_readiness_without_content_change():
    content = """---
name: codebase-memory
description: Inspect indexed codebases.
requirements:
  mcps: [codebase-memory]
---
# Codebase Memory
"""

    class Ctx:
        def get_config(self, key, default=None):
            return default

        def dispatch_tool(self, name, args):
            return json.dumps({
                "success": True,
                "skills": [{"name": "codebase-memory", "description": "Inspect indexed codebases."}],
            })

    compatibility = Compatibility(
        {"codebase-memory": content}, "raw-path-current-hermes", {}
    )
    before = scan_catalog(Ctx(), compatibility)
    compatibility.mcp_readiness = {"codebase-memory": True}
    after = scan_catalog(Ctx(), compatibility)

    assert before["skills"][0]["readiness_status"] == "dependency_missing"
    assert after["skills"][0]["readiness_status"] == "ready"
    assert before["skills"][0]["content_hash"] == after["skills"][0]["content_hash"]
    assert before["catalog_hash"] != after["catalog_hash"]


def test_mcp_requirement_changes_readiness_not_semantic_relevance_score():
    base = base_plan_entry({
        "name": "codebase-memory",
        "description": "Inspect indexed codebases.",
        "category": "development",
        "tags": [],
        "related_skills": [],
        "content": "## When to Use\nUse for code context.",
        "content_hash": "same",
        "readiness_status": "ready",
        "requirements": {"mcps": ["codebase-memory"]},
        "setup_needed": False,
    })
    missing = {**base, "readiness_status": "dependency_missing"}

    ready_score = score_entry("inspect codebase context", base)
    missing_score = score_entry("inspect codebase context", missing)

    assert ready_score["relevance_score"] == missing_score["relevance_score"]
    assert ready_score["readiness"] != missing_score["readiness"]


def test_malformed_success_listing_is_not_authoritative_empty_catalog():
    class Ctx:
        def __init__(self, payload):
            self.payload = payload

        def get_config(self, key, default=None):
            return default

        def dispatch_tool(self, name, args):
            return json.dumps(self.payload)

    compatibility = Compatibility({}, "raw-path-current-hermes")

    assert scan_catalog(Ctx({"success": True}), compatibility)["listing_available"] is False
    assert scan_catalog(Ctx({"success": True, "skills": [None]}), compatibility)["listing_available"] is False
    assert scan_catalog(
        Ctx({"success": True, "skills": [{"description": "missing name"}]}),
        compatibility,
    )["listing_available"] is False
    assert scan_catalog(Ctx({"success": True, "skills": []}), compatibility)["listing_available"] is True


def test_base_plan_extracts_triggers_and_ranker_prefers_matching_skill():
    github = base_plan_entry({
        "name": "github",
        "description": "Manage pull requests and issues.",
        "category": "dev",
        "tags": ["git"],
        "related_skills": [],
        "content": "## When to Use\nUse for pull requests.\n## Pitfalls\nAvoid for GitLab.",
        "content_hash": "a",
        "readiness_status": "ready",
        "setup_needed": False,
    })
    pdf = base_plan_entry({
        "name": "pdf",
        "description": "Read PDF documents.",
        "category": "documents",
        "tags": [],
        "related_skills": [],
        "content": "## When to Use\nUse for PDF files.",
        "content_hash": "b",
        "readiness_status": "ready",
        "setup_needed": False,
    })

    ranked = rank_entries("Create a GitHub pull request", [pdf, github])

    assert ranked[0][1]["name"] == "github"
    assert "Use for pull requests." in github["use_when"]
    assert "Avoid for GitLab." in github["avoid_when"]
