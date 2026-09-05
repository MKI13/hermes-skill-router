from __future__ import annotations

from skill_router_plugin.catalog import base_plan_entry, scan_catalog
from skill_router_plugin.readiness import DEPENDENCY_MISSING, READINESS_VERSION


class Ctx:
    def dispatch_tool(self, name, args):
        assert name == "skills_list"
        assert args == {}
        return '{"success": true, "skills": [{"name": "new-skill", "description": "New skill", "category": "development"}]}'

    def get_config(self, key, default=None):
        return default


class Compatibility:
    def ensure_skills_tool_registration(self):
        return None

    def read_visible_skill_files(self, visible_names, *, max_chars):
        assert visible_names == {"new-skill"}
        assert max_chars >= 1000
        return {
            "new-skill": (
                "---\n"
                "name: new-skill\n"
                "description: New skill\n"
                "requirements:\n"
                "  commands: [definitely-missing-readiness-command]\n"
                "  mcps: [missing-mcp]\n"
                "---\n"
                "# New Skill\n"
            )
        }, "raw-path-current-hermes"

    def active_mcp_readiness(self):
        return {}

    def readiness_hints(self, metadata):
        return {}


def test_new_skill_catalog_scan_gets_actionable_readiness_2_evidence():
    catalog = scan_catalog(
        Ctx(),
        Compatibility(),
    )
    assert catalog["count"] == 1
    record = catalog["skills"][0]
    assert record["readiness_version"] == READINESS_VERSION == 2
    assert record["readiness_status"] == DEPENDENCY_MISSING
    assert record["missing_dependencies"] == [
        {"type": "command", "name": "definitely-missing-readiness-command"},
        {"type": "mcp", "name": "missing-mcp"},
    ]
    assert record["readiness_reasons"] == [
        "Missing command: definitely-missing-readiness-command.",
        "Missing MCP: missing-mcp.",
    ]

    plan = base_plan_entry(record)
    assert plan["readiness_status"] == DEPENDENCY_MISSING
    assert [item["state"] for item in plan["dependency_checks"]] == ["missing", "missing"]
    assert plan["readiness_reasons"] == record["readiness_reasons"]
