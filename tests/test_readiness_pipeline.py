"""Repository integration fixtures, not live Hermes/profile acceptance tests."""
from __future__ import annotations

from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from skill_router_plugin.catalog import base_plan_entry, scan_catalog
from skill_router_plugin.doctor_readiness import render_readiness_doctor
from skill_router_plugin.inspection import render_skill_inspection
from skill_router_plugin.planner import analyze_changed_skills
from skill_router_plugin.runtime import SkillRouterRuntime, _fit_snapshot
from tests.test_runtime import Ctx as BaseCtx, Compatibility as BaseCompatibility

KEY = "SKILL_ROUTER_PIPELINE_TEST_CONFIG"
NEW_FIELDS = (
    "readiness_version", "missing_dependencies", "unknown_dependencies",
    "setup_requirements", "readiness_summary",
)
ALL_FIELDS = NEW_FIELDS + (
    "readiness_status", "readiness_hash", "setup_needed", "requirements",
    "dependency_checks", "readiness_reasons",
)
DOCUMENT = """---
name: pipeline-skill
description: Inspect repository implementation and dependencies.
requirements:
  mcps: [pipeline-mcp]
  config: [SKILL_ROUTER_PIPELINE_TEST_CONFIG]
---
# Pipeline skill
## When to Use
Inspect repository implementation and dependencies.
"""


class Context(BaseCtx):
    def __init__(self):
        super().__init__({"deep_refresh_on_start": False, "openviking_enabled": False})
        self.documents = {"pipeline-skill": DOCUMENT}
        self.scans = 0
        self.llm = SimpleNamespace(complete_structured=self.unexpected_model_call)

    @staticmethod
    def unexpected_model_call(**kwargs):
        raise AssertionError("Readiness-only refresh must not invoke an auxiliary model")

    def dispatch_tool(self, name, args):
        assert name == "skills_list", "Inventory must never execute skill_view"
        assert args == {}
        self.scans += 1
        return json.dumps({"success": True, "skills": [
            {"name": name, "description": "Inspect repository implementation", "category": "development"}
            for name in self.documents
        ]})


class Compatibility(BaseCompatibility):
    def __init__(self, ctx):
        super().__init__("full")
        self.ctx = ctx
        self.mcps = {"pipeline-mcp": False}

    def ensure_skills_tool_registration(self):
        pass

    def read_visible_skill_files(self, visible_names, *, max_chars):
        return {name: self.ctx.documents[name][:max_chars] for name in visible_names}, "raw-path-current-hermes"

    def active_mcp_readiness(self):
        return self.mcps

    def readiness_hints(self, metadata):
        return {}


@pytest.fixture
def pipeline(monkeypatch):
    monkeypatch.delenv(KEY, raising=False)
    ctx = Context()
    compat = Compatibility(ctx)
    return ctx, compat, SkillRouterRuntime(ctx, compat)


def assert_evidence(entry, record):
    for key in ALL_FIELDS:
        assert key in entry, key
        assert entry[key] == record[key], key


def test_scan_to_base_plan_preserves_every_readiness_field(pipeline):
    ctx, compat, _ = pipeline
    record = scan_catalog(ctx, compat)["skills"][0]
    assert record["readiness_status"] == "dependency_missing"
    assert record["setup_requirements"] == [KEY]
    plan = base_plan_entry(record)
    assert_evidence(plan, record)
    plan["dependency_checks"][0]["state"] = "changed-in-copy"
    plan["setup_requirements"].append("COPY_ONLY")
    assert record["dependency_checks"][0]["state"] == "missing"
    assert record["setup_requirements"] == [KEY]


@pytest.mark.parametrize("mcp,configured,status", [
    (False, False, "dependency_missing"),
    (None, False, "unknown"),
    (True, False, "setup_required"),
    (True, True, "ready"),
])
def test_scan_runtime_persistence_reload_inspect_doctor_and_policy(pipeline, mcp, configured, status):
    ctx, compat, runtime = pipeline
    compat.mcps["pipeline-mcp"] = mcp
    if configured:
        ctx.settings[KEY] = "private-fixture-value-not-for-output"
    record = scan_catalog(ctx, compat)["skills"][0]
    assert runtime.ensure_catalog(force=True) is True
    reloaded = SkillRouterRuntime(ctx, compat)
    entry = reloaded._snapshot()["entries"][0]
    assert_evidence(entry, record)
    assert entry["readiness_status"] == status
    text = reloaded.inspect_text("pipeline-skill")
    doctor = render_readiness_doctor(reloaded._snapshot())
    assert f"Readiness: {status}" in text
    assert "private-fixture-value-not-for-output" not in text + doctor + json.dumps(reloaded._snapshot())
    if not configured:
        assert "Setup required:" in text and f"- config: {KEY}" in text
    assert "{'declared':" not in text + doctor
    selected = [{"name": "pipeline-skill", "role": "primary", "order": 1}]
    result = reloaded._policy_result("Inspect repository implementation", selected, [entry], 4)
    if status == "dependency_missing":
        assert not result["selections"]
    elif status == "ready":
        assert result["selections"][0]["readiness_status"] == "ready"


def test_readiness_only_change_replaces_old_details_preserving_model_analysis(pipeline):
    ctx, compat, runtime = pipeline
    runtime.ensure_catalog(force=True)
    snapshot = runtime._snapshot()
    entry = snapshot["entries"][0]
    content_hash = entry["content_hash"]
    entry.update(analysis="model", use_when=["Preserved custom trigger"])
    runtime._save_snapshot(snapshot)
    compat.mcps["pipeline-mcp"] = True
    ctx.settings[KEY] = "configured-value"
    assert runtime.ensure_catalog(force=True) is True
    record = scan_catalog(ctx, compat)["skills"][0]
    refreshed = runtime._snapshot()["entries"][0]
    assert_evidence(refreshed, record)
    assert refreshed["content_hash"] == content_hash
    assert refreshed["analysis"] == "model"
    assert refreshed["use_when"] == ["Preserved custom trigger"]
    assert refreshed["missing_dependencies"] == []
    assert refreshed["setup_requirements"] == []


def test_unchanged_hash_repairs_old_snapshot_at_next_scan_without_reanalysis(pipeline):
    ctx, compat, runtime = pipeline
    runtime.ensure_catalog(force=True)
    snapshot = runtime._snapshot()
    original_hash = snapshot["catalog_hash"]
    for key in NEW_FIELDS:
        snapshot["entries"][0].pop(key, None)
    snapshot["entries"][0].update(analysis="model", use_when=["Keep this metadata"])
    runtime._save_snapshot(snapshot)
    before_generation = runtime._catalog_generation
    runtime.ensure_catalog(force=True)
    record = scan_catalog(ctx, compat)["skills"][0]
    repaired = runtime._snapshot()
    assert repaired["catalog_hash"] == original_hash
    assert_evidence(repaired["entries"][0], record)
    assert repaired["entries"][0]["analysis"] == "model"
    assert repaired["entries"][0]["use_when"] == ["Keep this metadata"]
    assert runtime._catalog_generation > before_generation


def test_unchanged_turns_keep_existing_scan_interval(pipeline):
    ctx, _, runtime = pipeline
    runtime.ensure_catalog(force=True)
    before = ctx.scans
    for _ in range(5):
        assert runtime.ensure_catalog(force=False) is False
    assert ctx.scans == before


def test_updated_and_removed_skills_do_not_retain_stale_diagnostics(pipeline):
    ctx, compat, runtime = pipeline
    runtime.ensure_catalog(force=True)
    ctx.documents["pipeline-skill"] = DOCUMENT.replace("pipeline-mcp", "replacement-mcp")
    runtime.ensure_catalog(force=True)
    entry = runtime._snapshot()["entries"][0]
    assert entry["missing_dependencies"] == [{"type": "mcp", "name": "replacement-mcp"}]
    del ctx.documents["pipeline-skill"]
    runtime.ensure_catalog(force=True)
    assert runtime._snapshot()["entries"] == []
    assert "Skill not found" in runtime.inspect_text("pipeline-skill")


def test_auxiliary_enrichment_cannot_replace_passive_readiness(pipeline):
    ctx, compat, _ = pipeline
    record = scan_catalog(ctx, compat)["skills"][0]
    ctx.llm = SimpleNamespace(complete_structured=lambda **kwargs: SimpleNamespace(parsed={"skills": [{
        "name": "pipeline-skill", "use_when": ["Enriched trigger"],
        "readiness_status": "ready", "setup_requirements": [], "missing_dependencies": [],
    }]}))
    entries, report = analyze_changed_skills(ctx, [record], [], batch_size=1, max_skill_chars=20000)
    assert report["calls"] == 1
    assert entries[0]["use_when"] == ["Enriched trigger"]
    assert_evidence(entries[0], record)


def test_cached_model_entry_refreshes_evidence_without_model_call(pipeline):
    ctx, compat, _ = pipeline
    record = scan_catalog(ctx, compat)["skills"][0]
    cached = base_plan_entry(record)
    cached.update(analysis="model", use_when=["Cached trigger"])
    compat.mcps["pipeline-mcp"] = True
    ctx.settings[KEY] = "configured-value"
    fresh = scan_catalog(ctx, compat)["skills"][0]
    entries, report = analyze_changed_skills(ctx, [fresh], [cached], batch_size=1, max_skill_chars=20000)
    assert report["calls"] == 0 and report["failures"] == []
    assert entries[0]["use_when"] == ["Cached trigger"]
    assert_evidence(entries[0], fresh)
    assert cached["readiness_status"] == "dependency_missing"


def test_first_compaction_preserves_readiness_evidence(pipeline):
    ctx, compat, _ = pipeline
    record = scan_catalog(ctx, compat)["skills"][0]
    entry = base_plan_entry(record)
    entry.update(description="d" * 40000, use_when=["x" * 30000])
    bounded = _fit_snapshot({"entries": [entry]}, 6000)
    assert bounded["state_compacted"] is True
    assert_evidence(bounded["entries"][0], record)
    assert len(json.dumps(bounded, ensure_ascii=False, separators=(",", ":")).encode()) <= 6000


def test_heavy_compaction_reports_omitted_details_instead_of_none_declared(pipeline):
    ctx, compat, _ = pipeline
    entry = base_plan_entry(scan_catalog(ctx, compat)["skills"][0])
    entry["dependency_checks"] = [{"type": "mcp", "name": "long-" + "x" * 180, "available": False}] * 50
    entry["description"] = "d" * 40000
    bounded = _fit_snapshot({"entries": [entry]}, 1600)
    assert bounded["entries"]
    assert bounded["entries"][0].get("readiness_details_omitted") is True
    text = render_skill_inspection(bounded, "pipeline-skill")
    assert "omitted" in text.lower()
    assert "none declared" not in text


def test_legacy_snapshots_keep_legacy_evidence_without_claiming_v2():
    snapshot = {"entries": [{"name": "legacy", "readiness_status": "setup_required",
        "dependency_checks": [{"type": "config", "name": KEY, "available": False}]}]}
    text = render_skill_inspection(snapshot, "legacy")
    assert f"config {KEY}: missing" in text
    assert "readiness_version" not in snapshot["entries"][0]


def test_structured_summary_uses_only_known_numeric_counters():
    snapshot = {"entries": [{"name": "fixture", "readiness_status": "unknown", "readiness_summary": {
        "declared": 2, "checked": 2, "available": 0, "missing": 1, "unknown": 0, "setup": 1,
        "private_field": "DO_NOT_RENDER_THIS_VALUE",
    }}]}
    for text in (render_skill_inspection(snapshot, "fixture"), render_readiness_doctor(snapshot)):
        assert "DO_NOT_RENDER_THIS_VALUE" not in text
        assert "declared=2" in text and "setup=1" in text


def test_doctor_understands_setup_key_names_without_a_summary():
    text = render_readiness_doctor({"entries": [{"name": "fixture", "readiness_status": "setup_required",
        "setup_requirements": [KEY]}]})
    assert f"config:{KEY}" in text
