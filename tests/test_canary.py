from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

from skill_router_plugin.production import ProductionRoutingEnhancements


class State:
    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return deepcopy(self.values.get(key, default))

    def set(self, key, value):
        self.values[key] = deepcopy(value)


class Ctx:
    def __init__(self, settings=None):
        self.state = State()
        self.settings = settings or {}

    def get_config(self, key, default=None):
        return self.settings.get(key, default)


class Embedding:
    def cache_status(self):
        return {"entries": 1, "model": "local-test", "dimensions": 4}


class Runtime:
    def __init__(self):
        self.ctx = Ctx()
        self.profile = SimpleNamespace(scope_token="scope-a", name="ef-sinn-development")
        self.embedding = Embedding()
        self.entries = [{
            "name": "skill-router:codebase-memory",
            "description": "Inspect indexed repository code and architecture.",
            "category": "development",
            "content_hash": "abc",
            "use_when": ["repository architecture", "find implementation", "trace dependencies"],
            "avoid_when": ["email writing", "customer reply"],
            "keywords": ["repository", "code", "architecture", "implementation"],
            "works_with": ["github"],
            "readiness_status": "ready",
            "setup_needed": False,
            "requirements": {"mcps": ["codebase-memory"]},
            "policy_metadata_complete": True,
            "alternatives": [],
        }]
        self._snapshot = lambda: {"catalog_hash": "catalog", "entries": self.entries}
        self._routing_mode = lambda: "deterministic"
        self.ensure_catalog = lambda force=False: False
        self.pre_llm_call = lambda **kwargs: None
        self.command = lambda raw_args: f"base:{raw_args}"
        self._policy_result = lambda task, selected, entries, limit: {
            "policy_status": "valid",
            "selections": selected,
        }


class Compatibility:
    capabilities = SimpleNamespace(
        raw_skill_reader=True,
        skill_lifecycle=True,
        skill_execution_guard=True,
        skill_execution_audit=True,
        profile_discovery=True,
        mcp_discovery=True,
    )

    def active_mcp_readiness(self):
        return {"codebase-memory": True}


def test_canary_passes_on_ready_codebase_profile():
    enhancement = ProductionRoutingEnhancements(Runtime(), Compatibility())
    text = enhancement.canary_text()

    assert "Hermes Skill Router Canary" in text
    assert "Profile: ef-sinn-development" in text
    assert "Overall: PASS" in text
    assert "Codebase Memory skill is ready" in text
    assert "Follow-up continuity preserved the code workflow" in text
    assert "Topic switch does not reuse Codebase Memory" in text
    assert "Negation prevents Codebase Memory reuse" in text
    assert "OpenViking remains disabled" in text


def test_canary_warns_when_codebase_skill_missing():
    runtime = Runtime()
    runtime.entries = []
    enhancement = ProductionRoutingEnhancements(runtime, Compatibility())

    text = enhancement.canary_text()

    assert "Overall: WARN" in text
    assert "Codebase Memory MCP is ready but routing skill is missing" in text
