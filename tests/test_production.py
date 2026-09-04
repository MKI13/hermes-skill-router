from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

from skill_router_plugin.production import EMBEDDING_DOCUMENT_VERSION, ProductionRoutingEnhancements


class State:
    def __init__(self): self.values = {}
    def get(self, key, default=None): return deepcopy(self.values.get(key, default))
    def set(self, key, value): self.values[key] = deepcopy(value)


class Ctx:
    def __init__(self, settings=None): self.state, self.settings = State(), settings or {}
    def get_config(self, key, default=None): return self.settings.get(key, default)


class Embedding:
    def __init__(self):
        self.rank = lambda task, entries, catalog_hash="": {}
        self.client_factory = lambda **kwargs: None
    def cache_status(self): return {"entries": 1, "model": "local-test", "dimensions": 4}


class Runtime:
    def __init__(self, ctx):
        self.ctx = ctx
        self.profile = SimpleNamespace(scope_token="scope-a", name="development")
        self.embedding = Embedding()
        self.pre_llm_call = lambda **kwargs: None
        self.command = lambda raw_args: f"base:{raw_args}"
        self.ensure_catalog = lambda force=False: False
        self._policy_result = lambda *args, **kwargs: {"policy_status": "valid", "selections": []}
        self._routing_mode = lambda: "deterministic"
        self.entries = [{"name": "skill-router:codebase-memory", "description": "Inspect repository code", "category": "development", "content_hash": "abc", "use_when": ["repository architecture", "find implementation"], "avoid_when": ["email writing"], "keywords": ["repository", "code", "architecture"], "works_with": ["github"], "readiness_status": "ready", "setup_needed": False, "requirements": {"mcps": ["codebase-memory"]}}]
        self._snapshot = lambda: {"catalog_hash": "catalog", "entries": self.entries}


class Compatibility:
    capabilities = SimpleNamespace(raw_skill_reader=True, skill_lifecycle=True, skill_execution_guard=True, skill_execution_audit=True, profile_discovery=True, mcp_discovery=True)
    def active_mcp_readiness(self): return {"codebase-memory": True}


def test_embedding_document_contains_routing_metadata_but_not_avoid_when():
    document = ProductionRoutingEnhancements.embedding_document({"name":"codebase-memory","description":"Inspect code","category":"development","tags":["repository"],"use_when":["find implementation"],"keywords":["symbol","dependency"],"works_with":["github"],"avoid_when":["email writing"]})
    assert EMBEDDING_DOCUMENT_VERSION == 2
    assert "codebase-memory" in document and "find implementation" in document and "symbol; dependency" in document and "github" in document
    assert "email writing" not in document


def test_followup_fallback_reuses_previous_primary_only_after_abstention():
    runtime = Runtime(Ctx()); enhancement = ProductionRoutingEnhancements(runtime, Compatibility())
    token = enhancement._followup.set({"previous_primary_skill":"skill-router:codebase-memory","previous_supporting_skills":[]})
    try: selected, method = enhancement.followup_fallback("Mach weiter und teste es.", runtime.entries, [], "deterministic")
    finally: enhancement._followup.reset(token)
    assert method == "session-followup" and selected[0]["name"] == "skill-router:codebase-memory" and selected[0]["role"] == "primary"


def test_followup_never_overrides_an_existing_selection():
    runtime = Runtime(Ctx()); enhancement = ProductionRoutingEnhancements(runtime, Compatibility())
    token = enhancement._followup.set({"previous_primary_skill":"skill-router:codebase-memory"}); existing=[{"name":"github","role":"primary","order":1}]
    try: selected, method = enhancement.followup_fallback("Mach weiter.", runtime.entries, existing, "deterministic")
    finally: enhancement._followup.reset(token)
    assert selected == existing and method == "deterministic"


def test_clear_topic_switch_is_not_followup():
    enhancement = ProductionRoutingEnhancements(Runtime(Ctx()), Compatibility())
    assert enhancement._is_followup("Mach weiter und korrigiere es.") is True
    assert enhancement._is_followup("Schreib jetzt eine E-Mail an den Kunden.") is False


def test_followup_state_is_session_scoped_and_contains_no_prompt_text():
    runtime = Runtime(Ctx()); enhancement = ProductionRoutingEnhancements(runtime, Compatibility())
    result = "[Skill Router method=deterministic policy=valid]\n1. PRIMARY: skill-router:codebase-memory [ready]\n[/Skill Router]"
    key = enhancement._session_key("session-secret-id"); enhancement._save_context(key, "Analysiere das Repository.", result)
    raw = runtime.ctx.state.values["router.followup_context.v1"]
    assert "session-secret-id" not in repr(raw) and "Analysiere das Repository" not in repr(raw)
    assert raw["sessions"][key]["previous_primary_skill"] == "skill-router:codebase-memory"


def test_doctor_reports_codebase_memory_and_paused_openviking():
    enhancement = ProductionRoutingEnhancements(Runtime(Ctx()), Compatibility()); text = enhancement.doctor_text()
    assert "Overall: PASS" in text
    assert "Codebase Memory MCP configured and enabled" in text and "Codebase Memory routing skill available" in text
    assert "SKIP    OpenViking disabled by configuration" in text
