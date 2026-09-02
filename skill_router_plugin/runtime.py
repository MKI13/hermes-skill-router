"""Profile-scoped runtime for the Hermes Skill Router plugin."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import shlex
import threading
import time
from typing import Any

from .catalog import base_plan_entry, scan_catalog
from .compat import HermesCompatibility
from .openviking import OpenVikingBridge
from .planner import analyze_changed_skills, select_skills
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
        self.openviking = OpenVikingBridge(ctx)
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._pending_reason = ""
        self._last_scan_monotonic = 0.0

    def stop(self) -> None:
        """Stop and join the owned refresh worker before plugin unload completes."""
        self._stop.set()
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
        profile = getattr(self.ctx, "profile_name", "default")
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

    def pre_llm_call(self, user_message: str = "", **kwargs: Any) -> str | None:
        """Inject ordered skill recommendations into the current user turn."""
        del kwargs
        task = str(user_message or "").strip()
        if not task:
            return None
        try:
            changed = self.ensure_catalog(force=False)
            if changed:
                self.request_deep_refresh("catalog-fingerprint-change")
            snapshot = self._snapshot()
            stored_entries = snapshot.get("entries") if isinstance(snapshot.get("entries"), list) else []
            scores = self.openviking.find_scores(task, stored_entries)
            entries = [
                {**entry, "openviking_score": scores.get(str(entry.get("name")), 0.0)}
                for entry in stored_entries
            ]
            selected, method = select_skills(
                self.ctx,
                task,
                entries,
                mode=self._routing_mode(),
                limit=self._int_setting("max_skills_per_task", 4, minimum=1, maximum=5),
                catalog_chars=self._int_setting("routing_catalog_chars", 60000, minimum=4000, maximum=250000),
                timeout_seconds=self._int_setting("routing_model_timeout_seconds", 20, minimum=1, maximum=25),
            )
        except Exception as exc:
            logger.warning("Skill Router task routing failed: %s", exc, exc_info=True)
            return (
                "[Skill Router]\nRouting failed for this turn. Inspect skills_list before "
                "executing and load every relevant skill with skill_view.\n[/Skill Router]"
            )

        if not selected:
            return (
                f"[Skill Router method={method}]\nNo installed skill was a strong match. "
                "Proceed normally, but inspect skills_list if the task has a specialized "
                "workflow.\n[/Skill Router]"
            )

        lines = [f"[Skill Router method={method} catalog={str(snapshot.get('catalog_hash', ''))[:12]}]"]
        for item in selected:
            readiness = _routing_readiness_suffix(item)
            lines.append(
                f"{item['order']}. {item['role'].upper()}: {item['name']}{readiness}"
            )
        lines.extend([
            "Before doing the task, call skill_view for every listed skill in this order. ",
            "Follow the primary workflow and merge only compatible supporting instructions.",
            "[/Skill Router]",
        ])
        return "\n".join(lines)

    def ensure_catalog(self, *, force: bool) -> bool:
        """Refresh the base plan when the scan interval or force flag requires it."""
        interval = self._int_setting("rescan_interval_seconds", 60, minimum=0, maximum=86400)
        now = time.monotonic()
        with self._lock:
            if not force and now - self._last_scan_monotonic < interval:
                return False
            self._last_scan_monotonic = now

        catalog = scan_catalog(self.ctx, self.compatibility)
        snapshot = self._snapshot()
        if not force and catalog["catalog_hash"] == snapshot.get("catalog_hash"):
            return False

        previous = {
            str(entry.get("name")): entry
            for entry in snapshot.get("entries", [])
            if isinstance(entry, dict) and entry.get("name")
        }
        entries: list[dict[str, Any]] = []
        for record in catalog["skills"]:
            existing = previous.get(record["name"])
            if existing and existing.get("content_hash") == record["content_hash"]:
                entries.append({
                    **existing,
                    "readiness_status": record.get("readiness_status", "unknown"),
                    "readiness_hash": record.get("readiness_hash", ""),
                    "setup_needed": bool(record.get("setup_needed")),
                    "requirements": record.get("requirements", {}),
                    "dependency_checks": record.get("dependency_checks", []),
                    "readiness_reasons": record.get("readiness_reasons", []),
                })
            else:
                entries.append(base_plan_entry(record))
        new_snapshot = {
            **snapshot,
            "profile": getattr(self.ctx, "profile_name", "default"),
            "catalog_hash": catalog["catalog_hash"],
            "catalog_scanned_at": _utc_now(),
            "reader_mode": catalog.get("reader_mode", "unknown"),
            "entries": entries,
            "dirty": True,
        }
        self._save_snapshot(new_snapshot)
        return True

    def request_deep_refresh(self, reason: str) -> bool:
        """Start one coalescing background refresh worker."""
        if self._stop.is_set():
            return False
        with self._lock:
            if self._stop.is_set():
                return False
            self._pending_reason = reason
            if self._worker is not None and self._worker.is_alive():
                return False
            self._worker = threading.Thread(
                target=self._deep_worker,
                name="hermes-skill-router-refresh",
                daemon=True,
            )
            self._worker.start()
            return True

    def deep_refresh(self, reason: str = "manual") -> dict[str, Any]:
        """Synchronously rebuild changed model-derived plan entries."""
        self.ensure_catalog(force=True)
        catalog = scan_catalog(self.ctx, self.compatibility)
        snapshot = self._snapshot()
        if catalog.get("catalog_hash") != snapshot.get("catalog_hash"):
            self.ensure_catalog(force=True)
            snapshot = self._snapshot()
        entries = snapshot.get("entries") if isinstance(snapshot.get("entries"), list) else []
        if self._routing_mode() == "deterministic":
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
        current = self._snapshot()
        if current.get("catalog_hash") != snapshot.get("catalog_hash"):
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
                _plan_markdown(getattr(self.ctx, "profile_name", "default"), analyzed)
            )
        except Exception as exc:
            openviking_report = {"enabled": True, "synced": 0, "failed": [str(exc)]}
            openviking_plan_written = False
        openviking_owned_names = openviking_report.get("owned_names", [])
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
        current.update({
            "entries": analyzed,
            "deep_analyzed_at": _utc_now(),
            "deep_reason": reason,
            "dirty": bool(report.get("failures")),
            "last_report": report,
        })
        if openviking_report.get("enabled"):
            current["openviking_owned_names"] = openviking_owned_names
        self._save_snapshot(current)
        return {**report, "saved": True, "reason": reason}

    def command(self, raw_args: str) -> str:
        """Handle `/skill-router` commands."""
        try:
            args = shlex.split(raw_args or "")
        except ValueError as exc:
            return f"Invalid arguments: {exc}"
        action = args[0].casefold() if args else "status"
        if action == "status":
            return self.status_text()
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
            selected, method = select_skills(
                self.ctx,
                task,
                snapshot.get("entries", []),
                mode=self._routing_mode(),
                limit=self._int_setting("max_skills_per_task", 4, minimum=1, maximum=5),
                catalog_chars=self._int_setting("routing_catalog_chars", 60000, minimum=4000, maximum=250000),
                timeout_seconds=self._int_setting("routing_model_timeout_seconds", 20, minimum=1, maximum=25),
            )
            if not selected:
                return f"No skill match ({method})."
            return f"Method: {method}\n" + "\n".join(
                f"{item['order']}. {item['name']} ({item['role']}, "
                f"{item.get('readiness_status', UNKNOWN)}): {item['reason']}"
                for item in selected
            )
        return "Usage: /skill-router [status|refresh|plan|inspect <skill>|recommend <task>]"

    def status_text(self) -> str:
        """Render profile plan status."""
        snapshot = self._snapshot()
        report = snapshot.get("last_report") if isinstance(snapshot.get("last_report"), dict) else {}
        ov_report = report.get("openviking") if isinstance(report.get("openviking"), dict) else {}
        running = bool(self._worker and self._worker.is_alive())
        entries = snapshot.get("entries") if isinstance(snapshot.get("entries"), list) else []
        readiness_counts = {status: 0 for status in READINESS_STATUSES}
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            status = str(entry.get("readiness_status") or UNKNOWN)
            readiness_counts[status if status in readiness_counts else UNKNOWN] += 1
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
            f"Indexed skills: {len(entries)}",
            *readiness_lines,
            f"Catalog hash: {str(snapshot.get('catalog_hash') or 'none')[:12]}",
            f"Catalog scan: {snapshot.get('catalog_scanned_at') or 'never'}",
            f"Skill reader: {snapshot.get('reader_mode') or 'unknown'}",
            f"Deep analysis: {snapshot.get('deep_analyzed_at') or 'never'}",
            f"Routing mode: {self._routing_mode()}",
            f"Refresh running: {running}",
            f"Last changed/analyzed: {report.get('changed', 0)} / calls: {report.get('calls', 0)}",
            f"Last failures: {len(report.get('failures', [])) if isinstance(report.get('failures'), list) else 0}",
            f"OpenViking enabled/synced: {self.openviking.enabled} / {ov_report.get('synced', 0)}",
            f"OpenViking failures: {len(ov_report.get('failed', [])) if isinstance(ov_report.get('failed'), list) else 0}",
            f"OpenViking plan written: {bool(report.get('openviking_plan_written'))}",
        ])

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
                availability = "available" if check.get("available") else "missing"
                lines.append(f"{kind} {name}: {availability}")
        else:
            lines.append("none declared")
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
        try:
            while not self._stop.is_set():
                with self._lock:
                    reason = self._pending_reason or "background"
                    self._pending_reason = ""
                started = time.monotonic()
                try:
                    self.deep_refresh(reason)
                    if reason.startswith("lifecycle:"):
                        remaining = _HERMES_SKILL_CACHE_SETTLE_SECONDS - (time.monotonic() - started)
                        if remaining > 0 and self._stop.wait(remaining):
                            return
                        self.deep_refresh(f"{reason}:cache-settled")
                except Exception:
                    logger.warning("Skill Router deep refresh failed", exc_info=True)
                with self._lock:
                    if self._pending_reason:
                        continue
                    if self._worker is current:
                        self._worker = None
                    return
        finally:
            with self._lock:
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
        return value if isinstance(value, dict) else {}

    def _save_snapshot(self, snapshot: dict[str, Any]) -> None:
        quota = int(getattr(self.ctx.state, "quota_bytes", 10 * 1024 * 1024))
        bounded = _fit_snapshot(snapshot, max(64 * 1024, int(quota * 0.9)))
        with self._lock:
            self.ctx.state.set(_STATE_KEY, bounded)

    def _routing_mode(self) -> str:
        mode = str(self.ctx.get_config("routing_mode", "model") or "model").casefold()
        return mode if mode in {"model", "deterministic"} else "model"

    def _bool_setting(self, key: str, default: bool) -> bool:
        value = self.ctx.get_config(key, default)
        return value if isinstance(value, bool) else default

    def _int_setting(self, key: str, default: int, *, minimum: int, maximum: int) -> int:
        value = self.ctx.get_config(key, default)
        if isinstance(value, bool) or not isinstance(value, int):
            value = default
        return max(minimum, min(maximum, value))


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
