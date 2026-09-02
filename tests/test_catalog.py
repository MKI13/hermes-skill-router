from __future__ import annotations

import json

from skill_router_plugin.catalog import base_plan_entry, rank_entries, scan_catalog


class Compatibility:
    def __init__(self, content, mode):
        self.content = content
        self.mode = mode

    def ensure_skills_tool_registration(self):
        return True

    def read_visible_skill_files(self, names, *, max_chars):
        return self.content, self.mode

    def readiness_hints(self, metadata):
        return {}


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
