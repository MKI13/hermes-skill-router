"""Profile-scoped runtime for the Hermes Skill Router plugin."""

from __future__ import annotations

from contextvars import copy_context
from datetime import datetime, timezone
import json
import logging
import math
import shlex
import threading
import time
from typing import Any

from .audit import SkillExecutionAudit
from .catalog import base_plan_entry, scan_catalog
from .compat import HermesCompatibility
from .enforcement import SkillExecutionGuard
from .embedding import EmbeddingCatalogRouter
from .events import SkillRouterEvents
from .learning import (
    ShadowLearning,
    compare_shadow_ranking,
    empty_learning_state,
    learning_last,
    learning_skill,
    learning_summary,
)
from .openviking import OpenVikingBridge
from .planner import (
    DEFAULT_DETERMINISTIC_MIN_SCORE,
    DEFAULT_DETERMINISTIC_SUPPORTING_MIN_SCORE,
    DEFAULT_EMBEDDING_WEAK_SIGNAL_MIN_SCORE,
    DEFAULT_MAX_OPTIONAL_SUPPORTING_SKILLS,
    analyze_changed_skills,
    deterministic_routing_diagnostics,
    select_skills,
)
from .policy import apply_routing_policy, detect_explicit_skill_names
from .profile_identity import legacy_audit_matches_profile, resolve_profile_identity
from .readiness import (
    BROKEN,
    DEPENDENCY_MISSING,
    DISABLED,
    READY,
    READINESS_STATUSES,
    SETUP_REQUIRED,
    UNKNOWN,
)

logger = logging.getLogger(__name__)
_STATE_KEY = "router.snapshot"
_REBUILD_ACTIONS = {"created", "installed", "patched", "edited", "archived", "stale", "restored"}
_HERMES_SKILL_CACHE_SETTLE_SECONDS = 31.0
_READINESS_LABELS = {
    READY: "Ready",
    UNKNOWN: "Unknown",
    SETUP_REQUIRED: "Setup required",
    DEPENDENCY_MISSING: "Dependency missing",
    BROKEN: "Broken",
    DISABLED: "Disabled",
}


class SkillRouterRuntime:
    """Maintain one independent routing plan for the active Hermes profile."""

    def __init__(
        self,
        ctx: Any,
        compatibility: HermesCompatibility | None = None,
    ) -> None:
        self.ctx = ctx
        self.compatibility = compatibility or HermesCompatibility(ctx)
        self.profile = resolve_profile_identity(ctx, self.compatibility)
        self.openviking = OpenVikingBridge(ctx, self.profile)
        self.embedding = EmbeddingCatalogRouter(ctx, self.profile)
        self.audit = SkillExecutionAudit(ctx, self.profile)
        self.events = SkillRouterEvents(ctx, self.profile)
        self.learning = ShadowLearning(ctx, self.profile)
        self.guard = SkillExecutionGuard()
        self._lock = threading.RLock()
        self._scan_lock = threading.Lock()
        self._deep_lock = threading.Lock()
        self._openviking_lock = threading.Lock()
        self._stop = threading.Event()
        self._worker_wake = threading.Event()
        self._worker: threading.Thread | None = None
        self._pending_reason = ""
        self._lifecycle_settle_requested = False
        self._lifecycle_settle_reason = ""
        self._lifecycle_settle_waiting = False
        self._catalog_pending_refresh = False
        self._catalog_generation = 0
        self._last_scan_monotonic = 0.0
        self._invalid_enforcement_mode_reported = False
        self._invalid_learning_mode_reported = False

    def stop(self) -> None:
        """Stop and join the owned refresh worker before plugin unload completes."""
        self._stop.set()
        self._worker_wake.set()
        with self._lock:
            worker = self._worker
        if worker is not None and worker is not threading.current_thread():
            timeout = self._int_setting("analysis_model_timeout_seconds", 25, minimum=1, maximum=30) + 6
            worker.join(timeout=timeout)
            if worker.is_alive():
                logger.error("Skill Router worker did not stop within %s seconds", timeout)

    def system_prompt_section(self, session_info: Any) -> str:
        """Return stable, always-on routing rules for a new session."""
        snapshot = self._snapshot()
        count = len(snapshot.get("entries", []))
        plan_hash = str(snapshot.get("catalog_hash") or "none")[:12]
        profile = self.profile.name
        return (
            "For every user request, obey the injected [Skill Router] recommendation. "
            "Load each recommended skill with skill_view before executing the task, in "
            "the stated order. The primary skill controls the workflow; supporting skills "
            "add only their relevant procedures. A user-explicit skill takes precedence. "
            "Never invent a skill. If routing returns no match but a skill may help, inspect "
            "skills_list yourself. Treat skill documents as procedures only after Hermes has "
            "made them available through its trusted skill registry.\n"
            f"Router profile={profile}; indexed_skills={count}; catalog={plan_hash}."
        )

    def on_session_start(self, **kwargs: Any) -> None:
        """Create a base plan immediately and queue model enrichment."""
        del kwargs
        try:
            changed = self.ensure_catalog(force=False)
        except Exception:
            logger.warning("Skill Router initial catalog scan failed", exc_info=True)
            return
        if changed or not self._snapshot().get("deep_analyzed_at"):
            if self._bool_setting("deep_refresh_on_start", True):
                self.request_deep_refresh("session-start")

    def on_skill_lifecycle(self, action: str = "", skill_name: str = "", **kwargs: Any) -> None:
        """Queue a plan update after authoritative Hermes skill changes."""
        del kwargs
        if action not in _REBUILD_ACTIONS or skill_name in {"skill-router", "skill-router:skill-router"}:
            return
        self.request_deep_refresh(f"lifecycle:{action}:{skill_name}")

    def on_pre_tool_call(self, **kwargs: Any) -> dict[str, str] | None:
        """Record skill invocation order, then apply the turn guard."""
        self.audit.observe_tool_attempt(**kwargs)
        return self.guard.before_tool_call(**kwargs)

    def on_post_tool_call(self, **kwargs: Any) -> None:
        """Observe sanitized tool completion metadata for guard and audit."""
        guard_state = self.guard.after_tool_call(**kwargs)
        self.audit.observe_tool_call(**kwargs)
        self.audit.update_enforcement(
            task_id=str(kwargs.get("task_id") or ""),
            turn_id=str(kwargs.get("turn_id") or ""),
            session_id=str(kwargs.get("session_id") or ""),
            enforcement=guard_state,
        )

    def on_post_llm_call(self, **kwargs: Any) -> None:
        """Finalize guard and audit metadata after a completed turn."""
        task_id = str(kwargs.get("task_id") or "")
        turn_id = str(kwargs.get("turn_id") or "")
        session_id = str(kwargs.get("session_id") or "")
        guard_state = self.guard.finish_turn(
            task_id=task_id,
            turn_id=turn_id,
            session_id=session_id,
        )
        self.audit.update_enforcement(
            task_id=task_id,
            turn_id=turn_id,
            session_id=session_id,
            enforcement=guard_state,
        )
        self.audit.finalize_turn(**kwargs)
        self._rebuild_learning()

    def pre_llm_call(
        self,
        user_message: str = "",
        task_id: str = "",
        turn_id: str = "",
        session_id: str = "",
        **kwargs: Any,
    ) -> str | None:
        """Inject recommendations and retain only compact routing metadata."""
        del kwargs
        task = str(user_message or "").strip()
        if not task:
            return None
        try:
            changed = self.ensure_catalog(force=False)
            if changed:
                self.request_deep_refresh("catalog-fingerprint-change")
            snapshot = self._snapshot()
            raw_entries = snapshot.get("entries")
            stored_entries: list[dict[str, Any]] = raw_entries if isinstance(raw_entries, list) else []
            learning_state = self._rebuild_learning()
            routing_mode = self._routing_mode()
            embedding_scores: dict[str, float] | None = None
            if routing_mode in {"hybrid", "embedding"}:
                if not detect_explicit_skill_names(task, stored_entries):
                    try:
                        embedding_scores = self.embedding.rank(
                            task,
                            stored_entries,
                            catalog_hash=str(snapshot.get("catalog_hash") or ""),
                        )
                    except Exception as exc:
                        logger.warning(
                            "Skill Router embedding unavailable; using deterministic fallback: %s",
                            type(exc).__name__,
                        )
                entries = list(stored_entries)
            else:
                scores = self.openviking.find_scores(task, stored_entries)
                entries = [
                    {**entry, "openviking_score": scores.get(str(entry.get("name")), 0.0)}
                    for entry in stored_entries
                ]
            max_skills = self._int_setting("max_skills_per_task", 4, minimum=1, maximum=5)
            selected, method = select_skills(
                self.ctx,
                task,
                entries,
                mode=routing_mode,
                limit=max_skills,
                catalog_chars=self._int_setting("routing_catalog_chars", 60000, minimum=4000, maximum=250000),
                timeout_seconds=self._int_setting("routing_model_timeout_seconds", 20, minimum=1, maximum=25),
                deterministic_min_score=self._int_setting(
                    "deterministic_min_score",
                    DEFAULT_DETERMINISTIC_MIN_SCORE,
                    minimum=1,
                    maximum=100,
                ),
                deterministic_supporting_min_score=self._int_setting(
                    "deterministic_supporting_min_score",
                    DEFAULT_DETERMINISTIC_SUPPORTING_MIN_SCORE,
                    minimum=1,
                    maximum=100,
                ),
                max_optional_supporting_skills=self._int_setting(
                    "max_optional_supporting_skills",
                    DEFAULT_MAX_OPTIONAL_SUPPORTING_SKILLS,
                    minimum=0,
                    maximum=2,
                ),
                embedding_scores=embedding_scores,
                embedding_ambiguity_margin=self._float_setting(
                    "embedding_ambiguity_margin", 0.02, minimum=0.0, maximum=1.0
                ),
                embedding_min_score=self._float_setting(
                    "embedding_min_score", 0.35, minimum=-1.0, maximum=1.0
                ),
                embedding_weak_signal_min_score=self._float_setting(
                    "embedding_weak_signal_min_score",
                    DEFAULT_EMBEDDING_WEAK_SIGNAL_MIN_SCORE,
                    minimum=-1.0,
                    maximum=1.0,
                ),
            )
            policy = self._policy_result(task, selected, entries, max_skills)
            selected = policy["selections"]
            shadow = self._shadow_result(task, selected, entries, learning_state)
        except Exception as exc:
            logger.warning("Skill Router task routing failed: %s", exc, exc_info=True)
            return (
                "[Skill Router]\nRouting failed for this turn. Inspect skills_list before "
                "executing and load every relevant skill with skill_view.\n[/Skill Router]"
            )

        guard_state = self._guard_result(
            task_id=task_id,
            turn_id=turn_id,
            session_id=session_id,
            policy_status=str(policy.get("policy_status") or "degraded"),
            selections=selected,
        )
        self.audit.record_decision(
            task=task,
            task_id=task_id,
            turn_id=turn_id,
            session_id=session_id,
            method=method,
            recommended=selected,
            policy_status=str(policy.get("policy_status") or "degraded"),
            enforcement_mode=str(guard_state.get("mode") or "off"),
            enforcement_status=str(guard_state.get("status") or "unavailable"),
            block_count=int(guard_state.get("block_count") or 0),
            primary_loaded_before_task_tools=guard_state.get(
                "primary_loaded_before_task_tools"
            ),
            execution_observable=self.compatibility.capabilities.skill_execution_audit,
            learning_mode=str(shadow.get("learning_mode") or "off"),
            actual_primary=str(shadow.get("actual_primary") or ""),
            shadow_primary=str(shadow.get("shadow_primary") or ""),
            shadow_changed=bool(shadow.get("shadow_changed")),
        )
        self._rebuild_learning()

        policy_status = str(policy.get("policy_status") or "degraded")
        if not selected:
            if policy_status == "blocked":
                detail = _safe_policy_detail(policy)
                return (
                    f"[Skill Router method={method} policy=blocked]\n"
                    f"{detail}\nDo not treat the unavailable skill as an executable workflow. "
                    "Proceed normally or explain the unavailable skill if relevant.\n"
                    "[/Skill Router]"
                )
            no_selection = (
                "No installed skill was a strong match."
                if policy_status == "valid"
                else "No installed skill passed routing policy."
            )
            return (
                f"[Skill Router method={method} policy={policy_status}]\n"
                f"{no_selection} Proceed normally, but inspect skills_list if the task has "
                "a specialized workflow.\n"
                "[/Skill Router]"
            )

        lines = [
            f"[Skill Router method={method} policy={policy_status} "
            f"catalog={str(snapshot.get('catalog_hash', ''))[:12]}]"
        ]
        for item in selected:
            readiness = _routing_readiness_suffix(item)
            lines.append(
                f"{item['order']}. {item['role'].upper()}: {item['name']}{readiness}"
            )
        if policy_status == "adjusted":
            lines.append("Policy adjusted the model selection to satisfy deterministic routing rules.")
        elif policy_status == "degraded":
            lines.append("Policy retained a limited plan; review the readiness markers before relying on it.")
        lines.extend([
            "Before doing the task, call skill_view for every listed skill in this order. ",
            "Follow the primary workflow and merge only compatible supporting instructions.",
            "[/Skill Router]",
        ])
        return "\n".join(lines)

    def ensure_catalog(self, *, force: bool) -> bool:
        """Refresh the base plan when the scan interval or force flag requires it."""
        refreshed = self._refresh_catalog(force=force)
        return bool(refreshed and refreshed[0])

    def _refresh_catalog(
        self,
        *,
        force: bool,
    ) -> tuple[bool, dict[str, Any], dict[str, Any], int] | None:
        """Scan once and publish one authoritative catalog generation."""
        interval = self._int_setting("rescan_interval_seconds", 60, minimum=0, maximum=86400)
        now = time.monotonic()
        with self._scan_lock:
            with self._lock:
                if (
                    not force
                    and self._last_scan_monotonic > 0.0
                    and now - self._last_scan_monotonic < interval
                ):
                    return None
            try:
                catalog = scan_catalog(self.ctx, self.compatibility)
            except Exception:
                with self._lock:
                    self._catalog_pending_refresh = True
                self.events.record("skill_refresh_failed", result="failed")
                raise
            if catalog.get("listing_available", True) is not True:
                with self._lock:
                    self._catalog_pending_refresh = True
                self.events.record("skill_refresh_failed", result="unavailable")
                return None

            with self._lock:
                snapshot = self._snapshot()
                changed = catalog.get("catalog_hash") != snapshot.get("catalog_hash")
                self._last_scan_monotonic = time.monotonic()
                self._catalog_pending_refresh = False
                if not changed:
                    current_snapshot = {
                        **snapshot,
                        "catalog_scanned_at": _utc_now(),
                        "reader_mode": catalog.get("reader_mode", "unknown"),
                    }
                    self._save_snapshot(current_snapshot)
                    return False, catalog, current_snapshot, self._catalog_generation

                previous = {
                    str(entry.get("name")): entry
                    for entry in snapshot.get("entries", [])
                    if isinstance(entry, dict) and entry.get("name")
                }
                entries: list[dict[str, Any]] = []
                for record in catalog.get("skills", []):
                    existing = previous.get(record["name"])
                    if existing and existing.get("content_hash") == record.get("content_hash"):
                        entries.append({
                            **existing,
                            "readiness_status": record.get("readiness_status", UNKNOWN),
                            "readiness_hash": record.get("readiness_hash", ""),
                            "setup_needed": bool(record.get("setup_needed")),
                            "requirements": record.get("requirements", {}),
                            "dependency_checks": record.get("dependency_checks", []),
                            "readiness_reasons": record.get("readiness_reasons", []),
                            "policy_metadata_complete": True,
                        })
                    else:
                        entries.append(base_plan_entry(record))
                new_snapshot = {
                    **snapshot,
                    "profile": self.profile.name,
                    "profile_scope": self.profile.scope_token,
                    "catalog_hash": catalog.get("catalog_hash", ""),
                    "catalog_scanned_at": _utc_now(),
                    "reader_mode": catalog.get("reader_mode", "unknown"),
                    "entries": entries,
                    "dirty": True,
                }
                self._save_snapshot(new_snapshot)
                self._catalog_generation += 1
                generation = self._catalog_generation

            self._record_catalog_deltas(previous, catalog.get("skills", []))
            return True, catalog, new_snapshot, generation

    def _record_catalog_deltas(
        self,
        previous: dict[str, dict[str, Any]],
        records: list[dict[str, Any]],
    ) -> None:
        current = {
            str(record.get("name")): record
            for record in records
            if isinstance(record, dict) and record.get("name")
        }
        for name in sorted(current, key=str.casefold):
            record = current[name]
            old = previous.get(name)
            readiness = str(record.get("readiness_status") or UNKNOWN)
            if old is None:
                self.events.record(
                    "skill_detected", skill_name=name, result="added", readiness=readiness
                )
            elif (
                old.get("content_hash") != record.get("content_hash")
                or old.get("readiness_hash") != record.get("readiness_hash")
            ):
                self.events.record(
                    "skill_updated", skill_name=name, result="changed", readiness=readiness
                )
        for name in sorted(set(previous) - set(current), key=str.casefold):
            self.events.record(
                "skill_removed",
                skill_name=name,
                result="removed",
                readiness=str(previous[name].get("readiness_status") or UNKNOWN),
            )

    def request_deep_refresh(self, reason: str) -> bool:
        """Start one coalescing background refresh worker."""
        if self._stop.is_set():
            return False
        with self._lock:
            if self._stop.is_set():
                return False
            self._pending_reason = reason
            self._catalog_pending_refresh = True
            if reason.startswith("lifecycle:"):
                self._lifecycle_settle_requested = True
                self._lifecycle_settle_reason = reason
            self._worker_wake.set()
            if self._worker is not None and self._worker.is_alive():
                return False
            worker_context = copy_context()
            self._worker = threading.Thread(
                target=worker_context.run,
                args=(self._deep_worker,),
                name="hermes-skill-router-refresh",
                daemon=True,
            )
            self._worker.start()
            return True

    def deep_refresh(self, reason: str = "manual") -> dict[str, Any]:
        """Synchronously rebuild changed model-derived plan entries."""
        with self._deep_lock:
            return self._deep_refresh_once(reason)

    def _deep_refresh_once(self, reason: str) -> dict[str, Any]:
        refreshed = self._refresh_catalog(force=True)
        if refreshed is None:
            return {
                "changed": 0,
                "calls": 0,
                "failures": ["catalog-unavailable"],
                "saved": False,
                "reason": "catalog-unavailable",
            }
        _catalog_changed, catalog, snapshot, generation = refreshed
        entries = snapshot.get("entries") if isinstance(snapshot.get("entries"), list) else []
        if self._routing_mode() != "model":
            analyzed = entries
            report = {"changed": 0, "calls": 0, "failures": []}
        else:
            analyzed, report = analyze_changed_skills(
                self.ctx,
                catalog.get("skills", []),
                entries,
                batch_size=self._int_setting("analysis_batch_size", 6, minimum=1, maximum=25),
                max_skill_chars=self._int_setting("max_skill_chars", 20000, minimum=1000, maximum=200000),
                timeout_seconds=self._int_setting("analysis_model_timeout_seconds", 25, minimum=1, maximum=30),
                should_stop=self._stop.is_set,
            )
        if self._stop.is_set():
            return {**report, "saved": False, "reason": "plugin-unloaded"}
        with self._openviking_lock:
            if not self._catalog_is_current(generation, catalog):
                self.request_deep_refresh("catalog-changed-during-analysis")
                return {**report, "saved": False, "reason": "catalog-changed"}
            try:
                openviking_report = self.openviking.sync_skills(
                    catalog.get("skills", []),
                    analyzed,
                    previous_owned=set(snapshot.get("openviking_owned_names", [])),
                    should_stop=self._stop.is_set,
                )
                openviking_plan_written = False if self._stop.is_set() else self.openviking.write_plan(
                    _plan_markdown(self.profile.name, analyzed)
                )
            except Exception as exc:
                openviking_report = {"enabled": True, "synced": 0, "failed": [str(exc)]}
                openviking_plan_written = False
            openviking_summary = {
                key: value for key, value in openviking_report.items() if key != "owned_names"
            }
            report = {
                **report,
                "openviking": openviking_summary,
                "openviking_plan_written": openviking_plan_written,
            }
            if self._stop.is_set():
                return {**report, "saved": False, "reason": "plugin-unloaded"}
            with self._lock:
                if not self._catalog_is_current(generation, catalog):
                    self._retain_openviking_ownership(openviking_report)
                    self.request_deep_refresh("catalog-changed-during-sync")
                    return {**report, "saved": False, "reason": "catalog-changed"}
                current = self._snapshot()
                current.update({
                    "entries": analyzed,
                    "deep_analyzed_at": _utc_now(),
                    "deep_reason": reason,
                    "dirty": bool(report.get("failures")),
                    "last_report": report,
                })
                owned_names = openviking_report.get("owned_names")
                if openviking_report.get("enabled") and isinstance(owned_names, list):
                    current["openviking_owned_names"] = owned_names
                self._save_snapshot(current)
                self._catalog_pending_refresh = False
            return {**report, "saved": True, "reason": reason}

    def _retain_openviking_ownership(self, report: dict[str, Any]) -> None:
        """Retain ownership of mirrors created before a stale sync was rejected."""
        owned_names = report.get("owned_names")
        if not report.get("enabled") or not isinstance(owned_names, list):
            return
        current = self._snapshot()
        retained = {
            str(name)
            for name in current.get("openviking_owned_names", [])
            if isinstance(name, str) and name
        }
        retained.update(str(name) for name in owned_names if isinstance(name, str) and name)
        current["openviking_owned_names"] = sorted(retained)
        self._save_snapshot(current)

    def _catalog_is_current(self, generation: int, catalog: dict[str, Any]) -> bool:
        with self._lock:
            return (
                generation == self._catalog_generation
                and self._snapshot().get("catalog_hash") == catalog.get("catalog_hash")
            )

    def command(self, raw_args: str) -> str:
        """Handle `/skill-router` commands."""
        try:
            args = shlex.split(raw_args or "")
        except ValueError as exc:
            return f"Invalid arguments: {exc}"
        action = args[0].casefold() if args else "status"
        if action == "status":
            return self.status_text()
        if action == "events":
            detail = args[1].casefold() if len(args) > 1 else ""
            if len(args) > 2:
                return "Usage: /skill-router events [1-50]"
            if not detail:
                return self.events.render()
            try:
                limit = int(detail)
            except ValueError:
                return "Usage: /skill-router events [1-50]"
            if limit < 1 or limit > 50:
                return "Usage: /skill-router events [1-50]"
            return self.events.render(limit)
        if action == "enforcement":
            return self.enforcement_text()
        if action == "learning":
            detail = " ".join(args[1:]).strip()
            minimum = self._learning_min_samples()
            if detail.casefold() == "reset":
                self.learning.reset(minimum)
                if not self.learning.write_succeeded():
                    return "Skill Router Learning\n\nLearning state reset failed; existing state may remain."
                return (
                    "Skill Router Learning\n\nLearning state reset. Audit and quality history "
                    "were retained. The next rebuild can derive learning again."
                )
            if detail.casefold() == "rebuild":
                state = self._rebuild_learning()
                if not self.learning.write_succeeded():
                    return "Learning state rebuild failed; existing state may remain."
                return (
                    "Learning state rebuilt from bounded quality history.\n\n"
                    + learning_summary(state, self._learning_mode())
                )
            state = self.learning.state(minimum)
            if detail.casefold() == "last":
                return learning_last(state)
            if detail:
                return learning_skill(state, detail)
            return learning_summary(state, self._learning_mode())
        if action == "quality":
            detail = args[1].casefold() if len(args) > 1 else ""
            if detail == "last":
                return self.audit.quality_last_text()
            if not detail:
                return self.audit.quality_summary_text(20)
            try:
                limit = int(detail)
            except ValueError:
                return "Usage: /skill-router quality [last|1-1000]"
            if limit < 1 or limit > 1000:
                return "Usage: /skill-router quality [last|1-1000]"
            return self.audit.quality_summary_text(limit)
        if action == "audit":
            detail = args[1].casefold() if len(args) > 1 else ""
            if detail == "last":
                return self.audit.last_text()
            if not detail:
                return self.audit.summary_text(20)
            try:
                limit = int(detail)
            except ValueError:
                return "Usage: /skill-router audit [last|1-1000]"
            if limit < 1 or limit > 1000:
                return "Usage: /skill-router audit [last|1-1000]"
            return self.audit.summary_text(limit)
        if action == "inspect":
            name = " ".join(args[1:]).strip()
            if not name:
                return "Usage: /skill-router inspect <skill-name>"
            self.ensure_catalog(force=False)
            return self.inspect_text(name)
        if action == "refresh":
            changed = self.ensure_catalog(force=True)
            started = self.request_deep_refresh("manual-slash-command")
            return (
                f"Skill catalog refreshed (changed={changed}). "
                f"Deep analysis {'started' if started else 'already running'} in the background."
            )
        if action == "plan":
            return self.plan_text()
        if action == "recommend":
            task = " ".join(args[1:]).strip()
            if not task:
                return "Usage: /skill-router recommend <task>"
            self.ensure_catalog(force=False)
            snapshot = self._snapshot()
            entries = snapshot.get("entries", [])
            if not isinstance(entries, list):
                entries = []
            routing_mode = self._routing_mode()
            embedding_scores: dict[str, float] | None = None
            if routing_mode in {"hybrid", "embedding"} and not detect_explicit_skill_names(task, entries):
                try:
                    embedding_scores = self.embedding.rank(
                        task,
                        entries,
                        catalog_hash=str(snapshot.get("catalog_hash") or ""),
                    )
                except Exception as exc:
                    logger.warning(
                        "Skill Router embedding unavailable; using deterministic fallback: %s",
                        type(exc).__name__,
                    )
            max_skills = self._int_setting("max_skills_per_task", 4, minimum=1, maximum=5)
            selected, method = select_skills(
                self.ctx,
                task,
                entries,
                mode=routing_mode,
                limit=max_skills,
                catalog_chars=self._int_setting("routing_catalog_chars", 60000, minimum=4000, maximum=250000),
                timeout_seconds=self._int_setting("routing_model_timeout_seconds", 20, minimum=1, maximum=25),
                deterministic_min_score=self._int_setting(
                    "deterministic_min_score",
                    DEFAULT_DETERMINISTIC_MIN_SCORE,
                    minimum=1,
                    maximum=100,
                ),
                deterministic_supporting_min_score=self._int_setting(
                    "deterministic_supporting_min_score",
                    DEFAULT_DETERMINISTIC_SUPPORTING_MIN_SCORE,
                    minimum=1,
                    maximum=100,
                ),
                max_optional_supporting_skills=self._int_setting(
                    "max_optional_supporting_skills",
                    DEFAULT_MAX_OPTIONAL_SUPPORTING_SKILLS,
                    minimum=0,
                    maximum=2,
                ),
                embedding_scores=embedding_scores,
                embedding_ambiguity_margin=self._float_setting(
                    "embedding_ambiguity_margin", 0.02, minimum=0.0, maximum=1.0
                ),
                embedding_min_score=self._float_setting(
                    "embedding_min_score", 0.35, minimum=-1.0, maximum=1.0
                ),
                embedding_weak_signal_min_score=self._float_setting(
                    "embedding_weak_signal_min_score",
                    DEFAULT_EMBEDDING_WEAK_SIGNAL_MIN_SCORE,
                    minimum=-1.0,
                    maximum=1.0,
                ),
            )
            policy = self._policy_result(task, selected, entries, max_skills)
            validated = policy["selections"]
            shadow = self._shadow_result(
                task,
                validated,
                entries,
                self._rebuild_learning(),
            )
            lines = [f"Method: {method}", f"Policy: {policy['policy_status']}", ""]
            if validated:
                lines.extend(
                    f"{item['order']}. {item['name']} ({item['role']}, "
                    f"{item.get('readiness_status', UNKNOWN)}): {item['reason']}"
                    for item in validated
                )
            else:
                lines.append(
                    "No skill match."
                    if policy.get("policy_status") == "valid"
                    else "No skill passed routing policy."
                )
                if method in {"deterministic", "deterministic-fallback"}:
                    diagnostics = deterministic_routing_diagnostics(
                        task,
                        entries,
                        min_score=self._int_setting(
                            "deterministic_min_score",
                            DEFAULT_DETERMINISTIC_MIN_SCORE,
                            minimum=1,
                            maximum=100,
                        ),
                        supporting_min_score=self._int_setting(
                            "deterministic_supporting_min_score",
                            DEFAULT_DETERMINISTIC_SUPPORTING_MIN_SCORE,
                            minimum=1,
                            maximum=100,
                        ),
                    )
                    if diagnostics.get("top_candidate"):
                        lines.extend([
                            "",
                            f"Top candidate: {diagnostics['top_candidate']}",
                            f"Score: {diagnostics['score']:.1f}",
                            f"Required score: {diagnostics['required_score']}",
                        ])
            changes = policy.get("changes") if isinstance(policy.get("changes"), list) else []
            if changes:
                lines.extend(["", "Policy changes:"])
                lines.extend(f"- {str(change)[:300]}" for change in changes[:10])
            warnings = policy.get("warnings") if isinstance(policy.get("warnings"), list) else []
            if warnings:
                lines.extend(["", "Policy warnings:"])
                lines.extend(f"- {str(warning)[:200]}" for warning in warnings[:10])
            if shadow.get("learning_mode") == "shadow" and shadow.get("actual_primary"):
                lines.extend([
                    "",
                    f"Shadow primary: {shadow.get('shadow_primary') or shadow['actual_primary']}",
                    f"Shadow changed primary: {'yes' if shadow.get('shadow_changed') else 'no'}",
                    "No routing behavior was changed.",
                ])
            return "\n".join(lines)
        return (
            "Usage: /skill-router "
            "[status|refresh|plan|inspect <skill>|events [1-50]|audit [last|N]|quality [last|N]|learning [last|reset|rebuild|<skill>]|enforcement|recommend <task>]"
        )

    def status_text(self) -> str:
        """Render profile plan status."""
        snapshot = self._snapshot()
        report = snapshot.get("last_report") if isinstance(snapshot.get("last_report"), dict) else {}
        ov_report = report.get("openviking") if isinstance(report.get("openviking"), dict) else {}
        with self._lock:
            running = bool(self._worker and self._worker.is_alive())
            pending = bool(
                self._catalog_pending_refresh
                or self._pending_reason
                or self._lifecycle_settle_requested
                or self._lifecycle_settle_waiting
                or running
                or snapshot.get("dirty")
            )
        recent_events = self.events.recent(50)
        last_change = next(
            (
                item
                for item in reversed(recent_events)
                if item.get("event") in {"skill_detected", "skill_updated", "skill_removed"}
            ),
            None,
        )
        if last_change is None:
            last_change_text = "never"
        else:
            event_label = {
                "skill_detected": "detected",
                "skill_updated": "updated",
                "skill_removed": "removed",
            }[last_change["event"]]
            last_change_text = (
                f"{last_change.get('skill_name') or 'unknown'} {event_label} "
                f"at {last_change.get('timestamp') or 'unknown'}"
            )
        entries = snapshot.get("entries") if isinstance(snapshot.get("entries"), list) else []
        readiness_counts = {status: 0 for status in READINESS_STATUSES}
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            status = str(entry.get("readiness_status") or UNKNOWN)
            readiness_counts[status if status in readiness_counts else UNKNOWN] += 1
        _audit_availability, audit_entries, last_audit = self.audit.status_fields(
            available=self.compatibility.capabilities.skill_execution_audit
        )
        quality_records, last_quality = self.audit.quality_status_fields()
        learning_state = self.learning.state(self._learning_min_samples())
        learning_skills = learning_state.get("skills")
        if not isinstance(learning_skills, dict):
            learning_skills = {}
        shadow_comparisons = learning_state.get("shadow_comparisons")
        if not isinstance(shadow_comparisons, list):
            shadow_comparisons = []
        shadow_changes = sum(
            1
            for item in shadow_comparisons
            if isinstance(item, dict) and item.get("shadow_changed") is True
        )
        readiness_lines = [
            "Skill readiness:",
            *[
                f"{_READINESS_LABELS[status]}: {readiness_counts[status]}"
                for status in (READY, UNKNOWN, SETUP_REQUIRED, DEPENDENCY_MISSING, BROKEN, DISABLED)
            ],
        ]
        return "\n".join([
            "Hermes Skill Router",
            f"Profile: {getattr(self.ctx, 'profile_name', 'default')}",
            *self.compatibility.status_lines(),
            f"Audit entries: {audit_entries}",
            f"Last audit: {last_audit}",
            "Quality evaluation: enabled",
            f"Quality records: {quality_records}",
            f"Last quality: {last_quality}",
            f"Learning: {self._learning_mode()}",
            f"Learning records: {len(learning_skills)} skills",
            f"Shadow primary changes: {shadow_changes}",
            f"Indexed skills: {len(entries)}",
            *readiness_lines,
            f"Catalog hash: {str(snapshot.get('catalog_hash') or 'none')[:12]}",
            f"Catalog scan: {snapshot.get('catalog_scanned_at') or 'never'}",
            f"Last skill change: {last_change_text}",
            f"Catalog pending refresh: {'yes' if pending else 'no'}",
            f"Skill reader: {snapshot.get('reader_mode') or 'unknown'}",
            f"Deep analysis: {snapshot.get('deep_analyzed_at') or 'never'}",
            f"Routing mode: {self._routing_mode()}",
            "Routing policy: enabled",
            f"Enforcement mode: {self._enforcement_mode()}",
            f"Refresh running: {running}",
            f"Last changed/analyzed: {report.get('changed', 0)} / calls: {report.get('calls', 0)}",
            f"Last failures: {len(report.get('failures', [])) if isinstance(report.get('failures'), list) else 0}",
            f"OpenViking enabled/synced: {self.openviking.enabled} / {ov_report.get('synced', 0)}",
            f"OpenViking failures: {len(ov_report.get('failed', [])) if isinstance(ov_report.get('failed'), list) else 0}",
            f"OpenViking plan written: {bool(report.get('openviking_plan_written'))}",
        ])

    def enforcement_text(self) -> str:
        """Render current guard diagnostics without changing configuration."""
        available = self.compatibility.capabilities.skill_execution_guard
        lines = [
            "Skill Router Enforcement",
            "",
            f"Mode: {self._enforcement_mode()}",
            f"Capability: {'available' if available else 'unavailable'}",
            "Max blocks per turn: "
            + str(self._int_setting("max_enforcement_blocks_per_turn", 2, minimum=1, maximum=5)),
            "",
        ]
        current = self.guard.current()
        if current is None:
            lines.append("Current turn: none")
            return "\n".join(lines)
        lines.extend([
            "Current turn:",
            f"Status: {current.get('status', 'error')}",
            f"Required: {', '.join(current.get('required_skills', [])) or 'none'}",
            f"Loaded: {', '.join(current.get('loaded_skills', [])) or 'none'}",
            f"Failed: {', '.join(current.get('failed_skills', [])) or 'none'}",
            f"Blocks: {current.get('block_count', 0)}",
        ])
        return "\n".join(lines)

    def plan_text(self) -> str:
        """Render a compact human-readable plan."""
        snapshot = self._snapshot()
        entries = snapshot.get("entries") if isinstance(snapshot.get("entries"), list) else []
        if not entries:
            return "No plan yet. Run `/skill-router refresh`."
        lines = [f"Skill routing plan ({len(entries)} skills):"]
        for entry in entries:
            triggers = "; ".join(str(value) for value in entry.get("use_when", [])[:3])
            status = str(entry.get("readiness_status") or UNKNOWN)
            lines.append(
                f"- {entry.get('name')} [{status}]: {triggers or entry.get('description', '')}"
            )
        return "\n".join(lines)

    def inspect_text(self, skill_name: str) -> str:
        """Render cached readiness evidence without exposing configured values."""
        snapshot = self._snapshot()
        entries = snapshot.get("entries") if isinstance(snapshot.get("entries"), list) else []
        entry = next(
            (
                item for item in entries
                if isinstance(item, dict)
                and str(item.get("name") or "").casefold() == skill_name.casefold()
            ),
            None,
        )
        if entry is None:
            return f"Skill not found: {skill_name}"
        status = str(entry.get("readiness_status") or UNKNOWN)
        checks = entry.get("dependency_checks") if isinstance(entry.get("dependency_checks"), list) else []
        lines = [
            f"Skill: {entry.get('name')}",
            f"Readiness: {status}",
            "",
            "Dependencies:",
        ]
        if checks:
            for check in checks:
                if not isinstance(check, dict):
                    continue
                kind = str(check.get("type") or "dependency").replace("_", " ")
                name = str(check.get("name") or "unknown")[:200]
                raw_availability = check.get("available")
                if raw_availability is True:
                    availability = "available"
                elif raw_availability is False:
                    availability = "missing"
                else:
                    availability = "unknown"
                lines.append(f"{kind} {name}: {availability}")
        else:
            lines.append("none declared")
        requirements = entry.get("requirements") if isinstance(entry.get("requirements"), dict) else {}
        required_skills = requirements.get("skills") if isinstance(requirements.get("skills"), list) else []
        alternatives = entry.get("alternatives") if isinstance(entry.get("alternatives"), list) else []
        if required_skills:
            lines.extend(["", "Required skills:"])
            lines.extend(f"- {str(name)[:200]}" for name in required_skills[:20])
        if alternatives:
            lines.extend(["", "Alternatives:"])
            lines.extend(f"- {str(name)[:200]}" for name in alternatives[:20])
        lines.append("")
        lines.append(f"Setup needed: {'true' if entry.get('setup_needed') else 'false'}")
        reasons = entry.get("readiness_reasons")
        if isinstance(reasons, list):
            lines.extend(
                f"Reason: {str(reason)[:300]}"
                for reason in reasons[:5]
                if str(reason).strip()
            )
        return "\n".join(lines)

    def _deep_worker(self) -> None:
        current = threading.current_thread()
        settle_deadline: float | None = None
        settle_reason = "lifecycle"
        try:
            while not self._stop.is_set():
                with self._lock:
                    reason = self._pending_reason
                    self._pending_reason = ""
                    if self._lifecycle_settle_requested:
                        self._lifecycle_settle_requested = False
                        settle_deadline = time.monotonic() + _HERMES_SKILL_CACHE_SETTLE_SECONDS
                        settle_reason = self._lifecycle_settle_reason or settle_reason
                        self._lifecycle_settle_reason = ""
                if reason:
                    try:
                        self.deep_refresh(reason)
                    except Exception:
                        logger.warning("Skill Router deep refresh failed", exc_info=True)
                    continue

                if settle_deadline is not None:
                    remaining = max(0.0, settle_deadline - time.monotonic())
                    with self._lock:
                        if self._pending_reason or self._lifecycle_settle_requested:
                            continue
                        self._lifecycle_settle_waiting = True
                        self._worker_wake.clear()
                        if self._stop.is_set():
                            self._lifecycle_settle_waiting = False
                            return
                    woke = self._worker_wake.wait(remaining)
                    with self._lock:
                        self._lifecycle_settle_waiting = False
                        pending = bool(self._pending_reason or self._lifecycle_settle_requested)
                    if self._stop.is_set():
                        return
                    if woke or pending:
                        continue
                    try:
                        self.deep_refresh(f"{settle_reason}:cache-settled")
                    except Exception:
                        logger.warning("Skill Router cache-settled refresh failed", exc_info=True)
                    settle_deadline = None
                    continue

                with self._lock:
                    if self._pending_reason or self._lifecycle_settle_requested:
                        continue
                    if self._worker is current:
                        self._worker = None
                    return
        finally:
            with self._lock:
                self._lifecycle_settle_waiting = False
                if self._worker is current:
                    self._worker = None
                restart_reason = self._pending_reason if not self._stop.is_set() else ""
            if restart_reason:
                self.request_deep_refresh(restart_reason)

    def _snapshot(self) -> dict[str, Any]:
        try:
            value = self.ctx.state.get(_STATE_KEY, default={})
        except Exception:
            logger.warning("Skill Router state read failed", exc_info=True)
            return {}
        if not isinstance(value, dict):
            return {}
        stored_scope = value.get("profile_scope")
        if stored_scope == self.profile.scope_token:
            return value
        if stored_scope is not None:
            return {}
        try:
            raw_audit = self.ctx.state.get("router.audit", default={})
        except Exception:
            raw_audit = {}
        if self.profile.name != "custom" and (
            value.get("profile") == self.profile.name
            or legacy_audit_matches_profile(raw_audit, self.profile)
        ):
            return {
                **value,
                "profile": self.profile.name,
                "profile_scope": self.profile.scope_token,
            }
        return {}

    def _save_snapshot(self, snapshot: dict[str, Any]) -> None:
        quota = int(getattr(self.ctx.state, "quota_bytes", 10 * 1024 * 1024))
        scoped = {
            **snapshot,
            "profile": self.profile.name,
            "profile_scope": self.profile.scope_token,
        }
        bounded = _fit_snapshot(scoped, max(64 * 1024, int(quota * 0.9)))
        with self._lock:
            self.ctx.state.set(_STATE_KEY, bounded)

    def _guard_result(
        self,
        *,
        task_id: str,
        turn_id: str,
        session_id: str,
        policy_status: str,
        selections: list[dict[str, Any]],
    ) -> dict[str, Any]:
        try:
            return self.guard.start_turn(
                task_id=task_id,
                turn_id=turn_id,
                session_id=session_id,
                policy_status=policy_status,
                selections=selections,
                mode=self._enforcement_mode(),
                max_blocks=self._int_setting(
                    "max_enforcement_blocks_per_turn", 2, minimum=1, maximum=5
                ),
                available=self.compatibility.capabilities.skill_execution_guard,
            )
        except Exception:
            logger.warning("Skill Router execution guard initialization failed", exc_info=True)
            return {
                "mode": self._enforcement_mode(),
                "status": "unavailable",
                "block_count": 0,
                "primary_loaded_before_task_tools": None,
            }

    def _policy_result(
        self,
        task: str,
        selected: list[dict[str, Any]],
        entries: list[dict[str, Any]],
        max_skills: int,
    ) -> dict[str, Any]:
        """Apply policy fail-closed for recommendations and fail-open for Hermes."""
        try:
            explicit = (
                []
                if any(item.get("router_meta_override") is True for item in selected)
                else detect_explicit_skill_names(task, entries)
            )
            result = apply_routing_policy(
                task=task,
                selected_skills=selected,
                catalog_entries=entries,
                max_skills=max_skills,
                explicit_skill_names=explicit,
            )
            if not isinstance(result, dict) or not isinstance(result.get("selections"), list):
                raise ValueError("invalid policy result")
            if result.get("policy_status") not in {"valid", "adjusted", "degraded", "blocked"}:
                raise ValueError("invalid policy status")
            return result
        except Exception:
            logger.warning("Skill Router policy validation failed", exc_info=True)
            return {
                "selections": [],
                "warnings": ["policy-error"],
                "policy_status": "degraded",
                "changes": ["Policy validation failed; no skill recommendation was retained."],
            }

    def _shadow_result(
        self,
        task: str,
        selections: list[dict[str, Any]],
        entries: list[dict[str, Any]],
        learning_state: dict[str, Any],
    ) -> dict[str, Any]:
        actual = next(
            (
                str(item.get("name") or "")
                for item in selections
                if isinstance(item, dict) and item.get("role") == "primary"
            ),
            "",
        )
        try:
            return compare_shadow_ranking(
                selections,
                learning_state,
                explicit_skill_names=detect_explicit_skill_names(task, entries),
                mode=self._learning_mode(),
            )
        except Exception:
            logger.warning("Skill Router shadow comparison failed", exc_info=True)
            return {
                "learning_mode": self._learning_mode(),
                "actual_primary": actual,
                "shadow_primary": actual,
                "shadow_changed": False,
            }

    def _rebuild_learning(self) -> dict[str, Any]:
        try:
            return self.learning.rebuild(
                self.audit.history,
                self._learning_min_samples(),
            )
        except Exception:
            logger.warning("Skill Router learning rebuild failed", exc_info=True)
            return empty_learning_state(self._learning_min_samples())

    def _learning_mode(self) -> str:
        mode = str(self.ctx.get_config("learning_mode", "shadow") or "shadow").casefold()
        if mode in {"off", "shadow"}:
            return mode
        if not self._invalid_learning_mode_reported:
            logger.warning("Invalid learning_mode %r; using shadow", mode[:100])
            self._invalid_learning_mode_reported = True
        return "shadow"

    def _learning_min_samples(self) -> int:
        history_limit = self._int_setting("max_audit_entries", 100, minimum=10, maximum=1000)
        return self._int_setting(
            "learning_min_samples",
            5,
            minimum=3,
            maximum=min(100, history_limit),
        )

    def _enforcement_mode(self) -> str:
        mode = str(self.ctx.get_config("enforcement_mode", "warn") or "warn").casefold()
        if mode in {"off", "warn", "primary", "all"}:
            return mode
        if not self._invalid_enforcement_mode_reported:
            logger.warning("Invalid enforcement_mode %r; using warn", mode[:100])
            self._invalid_enforcement_mode_reported = True
        return "warn"

    def _routing_mode(self) -> str:
        mode = str(
            self.ctx.get_config("routing_mode", "deterministic") or "deterministic"
        ).casefold()
        return mode if mode in {"model", "deterministic", "hybrid", "embedding"} else "deterministic"

    def _bool_setting(self, key: str, default: bool) -> bool:
        value = self.ctx.get_config(key, default)
        return value if isinstance(value, bool) else default

    def _int_setting(self, key: str, default: int, *, minimum: int, maximum: int) -> int:
        value = self.ctx.get_config(key, default)
        if isinstance(value, bool) or not isinstance(value, int):
            value = default
        return max(minimum, min(maximum, value))

    def _float_setting(
        self,
        key: str,
        default: float,
        *,
        minimum: float,
        maximum: float,
    ) -> float:
        value = self.ctx.get_config(key, default)
        if isinstance(value, bool):
            return default
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            parsed = default
        if not math.isfinite(parsed):
            parsed = default
        return max(minimum, min(maximum, parsed))


def _fit_snapshot(snapshot: dict[str, Any], max_bytes: int) -> dict[str, Any]:
    def size(value: dict[str, Any]) -> int:
        return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))

    if size(snapshot) <= max_bytes:
        return snapshot
    compact = {**snapshot}
    compact["entries"] = [
        {
            "name": str(entry.get("name") or "")[:200],
            "description": str(entry.get("description") or "")[:300],
            "category": str(entry.get("category") or "")[:100],
            "content_hash": str(entry.get("content_hash") or "")[:64],
            "use_when": [str(value)[:200] for value in entry.get("use_when", [])[:3]],
            "avoid_when": [str(value)[:200] for value in entry.get("avoid_when", [])[:2]],
            "keywords": [str(value)[:80] for value in entry.get("keywords", [])[:16]],
            "works_with": [str(value)[:200] for value in entry.get("works_with", [])[:8]],
            "alternatives": [str(value)[:200] for value in entry.get("alternatives", [])[:8]],
            "analysis": entry.get("analysis", "deterministic"),
            "readiness_status": entry.get("readiness_status", UNKNOWN),
            "readiness_hash": entry.get("readiness_hash", ""),
            "setup_needed": bool(entry.get("setup_needed")),
            "requirements": entry.get("requirements", {}),
            "dependency_checks": entry.get("dependency_checks", []),
            "readiness_reasons": entry.get("readiness_reasons", []),
            "policy_metadata_complete": entry.get("policy_metadata_complete", True),
            "openviking_name": entry.get("openviking_name", ""),
            "openviking_hash": entry.get("openviking_hash", ""),
        }
        for entry in snapshot.get("entries", [])
        if isinstance(entry, dict)
    ]
    compact["state_compacted"] = True
    if size(compact) <= max_bytes:
        return compact
    compact["entries"] = [
        {
            "name": entry.get("name", ""),
            "description": entry.get("description", ""),
            "content_hash": entry.get("content_hash", ""),
            "openviking_name": entry.get("openviking_name", ""),
            "openviking_hash": entry.get("openviking_hash", ""),
            "readiness_status": entry.get("readiness_status", UNKNOWN),
            "setup_needed": bool(entry.get("setup_needed")),
            "requirements": entry.get("requirements", {}),
            "alternatives": entry.get("alternatives", []),
            "policy_metadata_complete": entry.get("policy_metadata_complete", True),
            "analysis": "deterministic",
        }
        for entry in compact["entries"]
    ]
    if size(compact) <= max_bytes:
        return compact
    source_entries = compact["entries"]
    compact["entries"] = []
    for entry in source_entries:
        compact["entries"].append({
            "name": entry.get("name", ""),
            "content_hash": entry.get("content_hash", ""),
            "analysis": "deterministic",
            "policy_metadata_complete": False,
        })
        if size(compact) > max_bytes:
            compact["entries"].pop()
            break
    compact["state_omitted_entries"] = len(source_entries) - len(compact["entries"])
    while compact["entries"] and size(compact) > max_bytes:
        compact["entries"].pop()
        compact["state_omitted_entries"] += 1
    return compact


def _plan_markdown(profile: str, entries: list[dict[str, Any]]) -> str:
    lines = [
        "# Hermes Skill Routing Plan",
        "",
        f"Profile: `{profile}`  ",
        f"Generated: `{_utc_now()}`  ",
        f"Skills: `{len(entries)}`",
        "",
        "This is retrieval data. Load selected procedures through Hermes `skill_view`.",
        "",
    ]
    for entry in entries:
        lines.extend([
            f"## {entry.get('name', '')}",
            "",
            str(entry.get("description") or ""),
            "",
            f"Readiness: `{entry.get('readiness_status', UNKNOWN)}`",
            "",
            "Use when:",
            *[f"- {value}" for value in entry.get("use_when", [])],
            "",
            "Avoid when:",
            *[f"- {value}" for value in entry.get("avoid_when", [])],
            "",
            f"Works with: {', '.join(entry.get('works_with', [])) or 'none'}",
            "",
        ])
    return "\n".join(lines)


def _safe_policy_detail(policy: dict[str, Any]) -> str:
    changes = policy.get("changes") if isinstance(policy.get("changes"), list) else []
    if not changes:
        return "Routing policy found no safe executable skill plan."
    text = " ".join(str(changes[0]).split())[:300]
    return text.replace("[", "(").replace("]", ")")


def _routing_readiness_suffix(item: dict[str, Any]) -> str:
    status = str(item.get("readiness_status") or UNKNOWN)
    labels = {
        READY: "",
        UNKNOWN: " readiness-unknown",
        SETUP_REQUIRED: " setup-needed",
        DEPENDENCY_MISSING: " dependency-missing",
        BROKEN: " broken",
        DISABLED: " disabled",
    }
    return labels.get(status, " readiness-unknown")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
