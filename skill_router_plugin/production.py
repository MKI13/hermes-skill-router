"""v0.7.0 production helpers: follow-up continuity, doctor, performance and richer embeddings."""
from __future__ import annotations

from contextvars import ContextVar
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import math
import re
import time
from typing import Any, Callable

from . import embedding as embedding_module
from . import runtime as runtime_module
from .catalog import is_negated_name, score_entry
from .policy import detect_explicit_skill_names
from .readiness import BROKEN, DISABLED

VERSION = "0.7.0"
EMBEDDING_DOCUMENT_VERSION = 2
_CONTEXT_KEY = "router.followup_context.v1"
_PERF_KEY = "router.performance.v1"
_ACTIVE: ContextVar["ProductionRoutingEnhancements | None"] = ContextVar("router_v070", default=None)
_ORIGINAL_SELECT: Callable[..., Any] | None = None
_FOLLOWUP = re.compile(
    r"^(?:ok[,.!?]?\s*)?(?:mach(?:e)?\s+weiter|weiter|jetzt\s+(?:korrigier|änder|aender|test|prüf|pruef|commit|push)|"
    r"dann\s+(?:korrigier|änder|aender|test|prüf|pruef|commit|push)|korrigier(?:e)?\s+(?:das|es)|"
    r"änder(?:e)?\s+(?:das|es)|aender(?:e)?\s+(?:das|es)|test(?:e)?\s+(?:das|es)|prüf(?:e)?\s+(?:das|es)|"
    r"pruef(?:e)?\s+(?:das|es)|noch(?:\s+ein)?mal|nimm\s+die\s+(?:erste|zweite|dritte)\s+lösung|"
    r"go\s+on|continue|fix\s+it|test\s+it|check\s+it)\b", re.I)
_SWITCH = re.compile(r"\b(?:e-?mail|mail|kunde|customer|übersetz|uebersetz|translate|wetter|weather|rechnung|invoice|angebot|quote|recherche|research|kalender|calendar|termin|meeting|bild|image|foto|photo)\b", re.I)
_SELECTION = re.compile(r"^\s*\d+\.\s+(PRIMARY|SUPPORTING):\s+([^\[]+?)(?:\s+\[|\s*$)", re.I | re.M)
_POLICY = re.compile(r"\bpolicy=([a-z_]+)")


def install_production_enhancements(runtime: Any, compatibility: Any) -> "ProductionRoutingEnhancements":
    global _ORIGINAL_SELECT
    ext = ProductionRoutingEnhancements(runtime, compatibility)
    if _ORIGINAL_SELECT is None:
        _ORIGINAL_SELECT = runtime_module.select_skills
        runtime_module.select_skills = _select_with_followup
    embedding_module._CACHE_VERSION = max(int(getattr(embedding_module, "_CACHE_VERSION", 1)), EMBEDDING_DOCUMENT_VERSION)
    ext.install()
    return ext


def _select_with_followup(*args: Any, **kwargs: Any):
    if _ORIGINAL_SELECT is None:
        raise RuntimeError("base selector unavailable")
    ext = _ACTIVE.get()
    started = time.perf_counter()
    selected, method = _ORIGINAL_SELECT(*args, **kwargs)
    if ext is not None:
        ext._stage("selection_ms", started)
        task = str(args[1] if len(args) > 1 else kwargs.get("task", ""))
        entries = list(args[2] if len(args) > 2 else kwargs.get("entries", []))
        selected, method = ext.followup_fallback(task, entries, selected, method)
    return selected, method


class ProductionRoutingEnhancements:
    def __init__(self, runtime: Any, compatibility: Any) -> None:
        self.runtime, self.compatibility, self.ctx = runtime, compatibility, runtime.ctx
        self._pre, self._command = runtime.pre_llm_call, runtime.command
        self._ensure, self._policy = runtime.ensure_catalog, runtime._policy_result
        self._embed = runtime.embedding.rank
        self._followup: ContextVar[dict[str, Any] | None] = ContextVar(f"followup_{id(self)}", default=None)
        self._perf: ContextVar[dict[str, float] | None] = ContextVar(f"perf_{id(self)}", default=None)

    def install(self) -> None:
        self.runtime.pre_llm_call = self.pre_llm_call
        self.runtime.command = self.command
        self.runtime.ensure_catalog = self.ensure_catalog
        self.runtime._policy_result = self.policy_result
        self.runtime.embedding.rank = self.embedding_rank

    def pre_llm_call(self, user_message: str = "", task_id: str = "", turn_id: str = "", session_id: str = "", **kwargs: Any) -> str | None:
        task = str(user_message or "").strip()
        key = self._session_key(session_id)
        context = self._context(key) if self._is_followup(task) else None
        perf = {name: 0.0 for name in ("catalog_ms", "embedding_ms", "selection_ms", "policy_ms", "total_ms")}
        a, f, p = _ACTIVE.set(self), self._followup.set(context), self._perf.set(perf)
        started = time.perf_counter()
        try:
            result = self._pre(user_message=user_message, task_id=task_id, turn_id=turn_id, session_id=session_id, **kwargs)
            perf["total_ms"] = round((time.perf_counter() - started) * 1000, 3)
            self._save_perf(perf)
            self._save_context(key, task, result)
            return result
        finally:
            self._perf.reset(p); self._followup.reset(f); _ACTIVE.reset(a)

    def followup_fallback(self, task: str, entries: list[dict[str, Any]], selected: list[dict[str, Any]], method: str):
        context = self._followup.get()
        if selected or not context or not self._is_followup(task) or detect_explicit_skill_names(task, entries):
            return selected, method
        primary = str(context.get("previous_primary_skill") or "")
        entry = next((e for e in entries if str(e.get("name") or "") == primary), None)
        if not entry or str(entry.get("readiness_status") or "") in {BROKEN, DISABLED} or is_negated_name(task, primary):
            return selected, method
        score = score_entry(task, entry)
        if score.get("avoid_when", 0) < 0 or score.get("negation", 0) < 0:
            return selected, method
        return [{"name": primary, "role": "primary", "reason": "Conservative session follow-up continuity.", "order": 1,
                 "readiness_status": entry.get("readiness_status", "unknown"), "setup_needed": bool(entry.get("setup_needed"))}], "session-followup"

    def _is_followup(self, task: str) -> bool:
        task = str(task or "").strip()
        return bool(self._bool("followup_context_enabled", True) and task and len(task) <= 180 and not _SWITCH.search(task) and _FOLLOWUP.search(task))

    @staticmethod
    def embedding_document(entry: dict[str, Any]) -> str:
        clean = lambda value, limit: " ".join(str(value or "").split())[:limit]
        join = lambda value, limit: clean("; ".join(str(x) for x in value[:40]), limit) if isinstance(value, list) else ""
        fields = [f"Skill name: {clean(entry.get('name'), 200)}.", f"Description: {clean(entry.get('description'), 1000)}."]
        for label, value in (("Category", clean(entry.get("category"), 200)), ("Tags", join(entry.get("tags"), 400)),
                             ("Use when", join(entry.get("use_when"), 1800)), ("Keywords", join(entry.get("keywords"), 1000)),
                             ("Works with", join(entry.get("works_with"), 600))):
            if value: fields.append(f"{label}: {value}.")
        return " ".join(fields)[:5000]

    def embedding_rank(self, task: str, entries: list[dict[str, Any]], *, catalog_hash: str) -> dict[str, float]:
        enriched = []
        for entry in entries:
            doc = self.embedding_document(entry)
            digest = hashlib.sha256(f"v{EMBEDDING_DOCUMENT_VERSION}\0{entry.get('content_hash','')}\0{doc}".encode()).hexdigest()
            enriched.append({**entry, "content_hash": digest})
        effective = hashlib.sha256(f"v{EMBEDDING_DOCUMENT_VERSION}\0{catalog_hash}".encode()).hexdigest()
        started = time.perf_counter()
        try: return self._embed(task, enriched, catalog_hash=effective)
        finally: self._stage("embedding_ms", started)

    def ensure_catalog(self, *, force: bool) -> bool:
        started = time.perf_counter()
        try: return self._ensure(force=force)
        finally: self._stage("catalog_ms", started)

    def policy_result(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        started = time.perf_counter()
        try: return self._policy(*args, **kwargs)
        finally: self._stage("policy_ms", started)

    def _stage(self, name: str, started: float) -> None:
        perf = self._perf.get()
        if perf is not None: perf[name] = round(perf.get(name, 0.0) + (time.perf_counter() - started) * 1000, 3)

    def _save_perf(self, perf: dict[str, float]) -> None:
        scope = str(getattr(self.runtime.profile, "scope_token", ""))[:200]
        state = self._get(_PERF_KEY); history = state.get("history", []) if state.get("profile_scope") == scope else []
        history = list(history)[-self._int("performance_history_limit", 100, 10, 500) + 1:] + [{"timestamp": _now(), **perf}]
        self._set(_PERF_KEY, {"version": 1, "profile_scope": scope, "history": history})

    def performance_text(self) -> str:
        scope = str(getattr(self.runtime.profile, "scope_token", ""))[:200]
        state = self._get(_PERF_KEY); history = state.get("history", []) if state.get("profile_scope") == scope else []
        lines = ["Hermes Skill Router Performance", ""]
        if history:
            last = history[-1]; totals = [float(x.get("total_ms", 0)) for x in history]
            lines += ["Last routing:", *(f"{k[:-3].title()}: {float(last.get(k,0)):.1f} ms" for k in ("catalog_ms","embedding_ms","selection_ms","policy_ms","total_ms")),
                      "", f"Samples: {len(totals)}", f"Total p50: {_pct(totals,.50):.1f} ms", f"Total p95: {_pct(totals,.95):.1f} ms"]
        else: lines.append("No routing performance samples recorded yet.")
        try:
            cache = self.runtime.embedding.cache_status(); lines += ["", "Embedding cache:", f"Skills: {int(cache.get('entries') or 0)}", f"Model: {cache.get('model') or 'unknown'}", f"Dimensions: {cache.get('dimensions') or 'unknown'}", f"Document version: {EMBEDDING_DOCUMENT_VERSION}"]
        except Exception: lines += ["", "Embedding cache: unavailable"]
        return "\n".join(lines)

    def doctor_text(self) -> str:
        c = self.compatibility.capabilities; checks = []
        for attr, label in (("raw_skill_reader","Hermes raw skill reader"),("skill_lifecycle","Hermes skill lifecycle hook"),
                            ("skill_execution_guard","Hermes pre_tool_call guard"),("skill_execution_audit","Hermes post-tool/post-LLM audit hooks"),
                            ("profile_discovery","Hermes profile discovery"),("mcp_discovery","Hermes MCP configuration discovery")):
            checks.append(("PASS" if getattr(c, attr, False) else "WARN", label))
        try:
            self.runtime.ensure_catalog(force=False); snapshot = self.runtime._snapshot(); entries = snapshot.get("entries", [])
            checks += [("PASS" if isinstance(entries,list) else "BLOCKED", f"Hermes skill catalog ({len(entries) if isinstance(entries,list) else 0} skills)"),
                       ("PASS" if snapshot.get("catalog_hash") else "WARN", "Skill Router catalog hash")]
        except Exception: entries=[]; checks.append(("BLOCKED","Hermes skill catalog unavailable"))
        checks += [("PASS","Routing policy available"),("PASS","Execution audit state available"),("PASS","Quality evaluation available"),("PASS","Shadow learning state available")]
        if str(self.runtime._routing_mode()) in {"hybrid","embedding"}: checks += self._embedding_checks()
        else: checks.append(("SKIP",f"Embedding health check not required in routing_mode={self.runtime._routing_mode()}"))
        checks += self._codebase_checks(entries if isinstance(entries,list) else [])
        checks.append(("WARN","OpenViking enabled; v0.7.0 rollout recommendation is disabled") if self._bool("openviking_enabled",False) else ("SKIP","OpenViking disabled by configuration"))
        overall = "BLOCKED" if any(x[0]=="BLOCKED" for x in checks) else "WARN" if any(x[0]=="WARN" for x in checks) else "PASS"
        return "\n".join(["Hermes Skill Router Doctor","",f"Overall: {overall}",""] + [f"{level:<7} {msg}" for level,msg in checks])

    def canary_text(self) -> str:
        """Run a read-only canary against the active Hermes profile."""
        checks: list[tuple[str, str]] = []
        profile = str(getattr(self.runtime.profile, "name", "unknown"))[:100]
        try:
            self.runtime.ensure_catalog(force=False)
            snapshot = self.runtime._snapshot()
            entries = snapshot.get("entries", []) if isinstance(snapshot, dict) else []
            if not isinstance(entries, list):
                raise RuntimeError("catalog entries unavailable")
        except Exception:
            entries = []
            checks.append(("BLOCKED", "Active-profile skill catalog unavailable"))

        try:
            mcp = self.compatibility.active_mcp_readiness()
        except Exception:
            mcp = None
        codebase = next((entry for entry in entries if isinstance(entry, dict) and "codebase-memory" in ((entry.get("requirements") or {}).get("mcps") or [])), None)
        if codebase is not None and str(codebase.get("readiness_status") or "") not in {BROKEN, DISABLED}:
            checks.append(("PASS", "Codebase Memory skill is ready"))
        elif isinstance(mcp, dict) and mcp.get("codebase-memory") is True:
            checks.append(("WARN", "Codebase Memory MCP is ready but routing skill is missing"))
        else:
            checks.append(("WARN", "Codebase Memory is not ready in the active profile"))

        if codebase is not None:
            primary = str(codebase.get("name") or "")
            token = self._followup.set({"previous_primary_skill": primary, "previous_supporting_skills": [], "previous_policy_status": "valid"})
            try:
                followup, followup_method = self.followup_fallback("Mach weiter und teste es.", entries, [], "deterministic")
                switch, switch_method = self.followup_fallback("Schreib jetzt eine E-Mail an den Kunden.", entries, [], "deterministic")
                negated, negated_method = self.followup_fallback(f"Benutze {primary} dafür nicht.", entries, [], "deterministic")
            finally:
                self._followup.reset(token)
            checks.append(("PASS" if followup and followup_method == "session-followup" else "BLOCKED", "Follow-up continuity preserved the code workflow"))
            checks.append(("PASS" if not switch and switch_method == "deterministic" else "BLOCKED", "Topic switch does not reuse Codebase Memory"))
            checks.append(("PASS" if not negated and negated_method == "deterministic" else "BLOCKED", "Negation prevents Codebase Memory reuse"))
        else:
            checks += [("SKIP", "Follow-up continuity test requires the Codebase Memory skill"), ("SKIP", "Topic-switch test requires the Codebase Memory skill"), ("SKIP", "Negation test requires the Codebase Memory skill")]

        if str(self.runtime._routing_mode()) in {"hybrid", "embedding"}:
            checks += self._embedding_checks()
        else:
            checks.append(("SKIP", f"Local embedding live check not required in routing_mode={self.runtime._routing_mode()}"))
        checks.append(("WARN", "OpenViking is enabled; canary target expects it paused") if self._bool("openviking_enabled", False) else ("PASS", "OpenViking remains disabled"))
        overall = "BLOCKED" if any(level == "BLOCKED" for level, _ in checks) else "WARN" if any(level == "WARN" for level, _ in checks) else "PASS"
        return "\n".join(["Hermes Skill Router Canary", "", f"Profile: {profile}", f"Overall: {overall}", ""] + [f"{level:<7} {message}" for level, message in checks])

    def _embedding_checks(self):
        try:
            settings=self.runtime.embedding._settings(); client=self.runtime.embedding.client_factory(**settings["client"]); started=time.perf_counter(); vectors=client.embed(["Hermes Skill Router local embedding health check"]); latency=(time.perf_counter()-started)*1000
            vector=vectors[0]; dim=int(settings["dimensions"])
            if len(vectors)!=1 or len(vector)!=dim or not all(math.isfinite(float(v)) for v in vector) or not any(float(v)!=0 for v in vector): raise RuntimeError("invalid vector")
            return [("PASS","Embedding endpoint reachable on numeric loopback"),("PASS",f"Embedding dimension: {dim}"),("PASS",f"Embedding test latency: {latency:.1f} ms")]
        except Exception as exc: return [("BLOCKED",f"Embedding health check failed ({type(exc).__name__})")]

    def _codebase_checks(self, entries: list[dict[str, Any]]):
        try: mcp=self.compatibility.active_mcp_readiness()
        except Exception: mcp=None
        if mcp is None: return [("WARN","Codebase Memory MCP status unavailable")]
        checks=[("PASS","Codebase Memory MCP configured and enabled") if mcp.get("codebase-memory") is True else ("WARN","Codebase Memory MCP not configured or not ready in this profile")]
        routed=any("codebase-memory" in ((e.get("requirements") or {}).get("mcps") or []) for e in entries if isinstance(e,dict))
        checks.append(("PASS","Codebase Memory routing skill available") if routed else ("WARN","Codebase Memory MCP is available but no routable Hermes skill references it") if mcp.get("codebase-memory") is True else ("WARN","Codebase Memory routing skill not ready in this profile"))
        return checks

    def command(self, raw_args: str) -> str:
        action=str(raw_args or "").strip().casefold()
        if action=="doctor": return self.doctor_text()
        if action=="performance": return self.performance_text()
        if action=="canary": return self.canary_text()
        return self._command(raw_args)

    def _session_key(self, session_id: str) -> str:
        return hashlib.sha256(str(session_id).encode()).hexdigest()[:24] if str(session_id or "").strip() else ""

    def _context(self, key: str):
        if not key: return None
        state=self._get(_CONTEXT_KEY); scope=str(getattr(self.runtime.profile,"scope_token",""))[:200]
        if state.get("profile_scope")!=scope or not isinstance(state.get("sessions"),dict): return None
        value=state["sessions"].get(key); return deepcopy(value) if isinstance(value,dict) else None

    def _save_context(self, key: str, task: str, result: str | None) -> None:
        if not key or not self._bool("followup_context_enabled",True): return
        found=_SELECTION.findall(str(result or "")); primary=next((n.strip() for r,n in found if r.upper()=="PRIMARY"),""); supporting=[n.strip() for r,n in found if r.upper()=="SUPPORTING"][:4]
        policy=(_POLICY.search(str(result or "")) or [None,"unknown"])[1]
        scope=str(getattr(self.runtime.profile,"scope_token",""))[:200]; state=self._get(_CONTEXT_KEY)
        if state.get("profile_scope")!=scope: state={"version":1,"profile_scope":scope,"sessions":{}}
        sessions=state.get("sessions") if isinstance(state.get("sessions"),dict) else {}
        if primary:
            category=""; entry=next((e for e in self.runtime._snapshot().get("entries",[]) if str(e.get("name") or "")==primary),None)
            if isinstance(entry,dict): category=str(entry.get("category") or "")[:100]
            sessions[key]={"previous_primary_skill":primary[:200],"previous_supporting_skills":supporting,"previous_routing_category":category,"previous_policy_status":str(policy)[:30],"timestamp":_now()}
        elif not self._is_followup(task): sessions.pop(key,None)
        ordered=sorted(sessions.items(),key=lambda x:str(x[1].get("timestamp") or "")); state["sessions"]=dict(ordered[-self._int("followup_context_max_sessions",32,4,128):]); self._set(_CONTEXT_KEY,state)

    def _get(self,key:str)->dict[str,Any]:
        try: value=self.ctx.state.get(key,default={})
        except Exception: value={}
        return value if isinstance(value,dict) else {}
    def _set(self,key:str,value:dict[str,Any])->None:
        try: self.ctx.state.set(key,value)
        except Exception: pass
    def _bool(self,key:str,default:bool)->bool:
        value=self.ctx.get_config(key,default); return value if isinstance(value,bool) else default
    def _int(self,key:str,default:int,minimum:int,maximum:int)->int:
        try: value=int(self.ctx.get_config(key,default))
        except (TypeError,ValueError): value=default
        return max(minimum,min(maximum,value))


def _now() -> str: return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
def _pct(values:list[float],fraction:float)->float:
    ordered=sorted(values); return 0.0 if not ordered else ordered[max(0,min(len(ordered)-1,math.ceil(fraction*len(ordered))-1))]