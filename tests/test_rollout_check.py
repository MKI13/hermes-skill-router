from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

from skill_router_plugin.production import ProductionRoutingEnhancements


class State:
    def __init__(self): self.values = {}
    def get(self, key, default=None): return deepcopy(self.values.get(key, default))
    def set(self, key, value): self.values[key] = deepcopy(value)


class Ctx:
    def __init__(self, settings=None): self.state, self.settings = State(), settings or {}
    def get_config(self, key, default=None): return self.settings.get(key, default)


class Embedding:
    def rank(self, task, entries, *, catalog_hash): return {}
    def cache_status(self): return {"entries": 1, "model": "local-test", "dimensions": 4}


class Runtime:
    def __init__(self, settings=None):
        self.ctx = Ctx(settings)
        self.profile = SimpleNamespace(scope_token="scope-test", name="isolated-test")
        self.embedding = Embedding()
        self.entries = [{"name":"skill-router:codebase-memory","requirements":{"mcps":["codebase-memory"]},"readiness_status":"ready"}]
        self._snapshot = lambda: {"catalog_hash":"catalog", "entries":self.entries}
        self._routing_mode = lambda: str(self.ctx.get_config("routing_mode", "deterministic"))
        self.ensure_catalog = lambda force=False: False
        self.pre_llm_call = lambda **kwargs: None
        self.command = lambda raw_args: f"base:{raw_args}"
        self._policy_result = lambda *args, **kwargs: {"policy_status":"valid", "selections":[]}


class Compatibility:
    def __init__(self, *, raw=True, guard=True, mcp=True):
        self.capabilities = SimpleNamespace(raw_skill_reader=raw, skill_execution_guard=guard)
        self.mcp = mcp
    def active_mcp_readiness(self): return {"codebase-memory": self.mcp}


def test_rollout_check_ready_for_conservative_defaults():
    text = ProductionRoutingEnhancements(Runtime(), Compatibility()).rollout_text()
    assert "Decision: READY" in text
    assert "routing_mode=deterministic" in text
    assert "enforcement_mode=warn" in text
    assert "learning_mode=shadow" in text
    assert "OpenViking disabled" in text
    assert "Read-only:" in text


def test_rollout_check_review_when_optional_codebase_mcp_is_missing():
    text = ProductionRoutingEnhancements(Runtime(), Compatibility(mcp=False)).rollout_text()
    assert "Decision: REVIEW" in text
    assert "Codebase Memory MCP not configured or not ready in this profile" in text


def test_rollout_check_blocks_when_critical_hermes_capability_is_missing():
    text = ProductionRoutingEnhancements(Runtime(), Compatibility(raw=False)).rollout_text()
    assert "Decision: BLOCKED" in text
    assert "BLOCKED Hermes raw skill reader" in text


def test_rollout_check_reviews_non_conservative_modes_without_mutation():
    runtime = Runtime({"routing_mode":"model", "enforcement_mode":"primary", "learning_mode":"off", "openviking_enabled":True})
    text = ProductionRoutingEnhancements(runtime, Compatibility()).rollout_text()
    assert "Decision: REVIEW" in text
    assert "routing_mode=model is not recommended" in text
    assert "enforcement_mode=primary" in text
    assert "learning_mode=off" in text
    assert "OpenViking enabled" in text
