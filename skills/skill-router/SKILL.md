---
name: skill-router
description: Inspect routing plans, readiness, diagnostics, rollout readiness, performance, and execution audits.
version: 0.12.0
author: Hermes Skill Router contributors
license: MIT
metadata:
  hermes:
    tags: [skills, routing, orchestration, diagnostics, embeddings, openviking]
    category: productivity
---
# Skill Router Skill

This operational skill explains how to inspect and diagnose the always-on Hermes Skill Router plugin. It does not replace task-specific skills.

This branch is development version v0.12.0, unreleased. Repository CI is not a live-profile validation or permission to deploy.

## When to Use

Use this skill when the user asks to:

- inspect which installed skills should handle a task;
- diagnose wrong, missing, stale, or unnecessary Primary/Supporting Skill recommendations;
- run Router health, rollout-preflight, or performance checks;
- refresh or inspect the profile-local routing plan;
- inspect readiness, audit, quality, enforcement, or shadow-learning state;
- discover Hermes profiles or apply the Router's explicit profile setup workflow.

Do not load this skill merely because another skill was recommended. Follow the injected `[Skill Router]` plan instead.

## Commands

Inside Hermes:

```text
/skill-router status
/skill-router doctor
/skill-router rollout-check
/skill-router canary
/skill-router performance
/skill-router events 20
/skill-router refresh
/skill-router plan
/skill-router inspect <skill>
/skill-router audit last
/skill-router quality last
/skill-router learning
/skill-router enforcement
/skill-router recommend <task>
```

Terminal equivalents use `hermes --profile <profile> skill-router ...`. Profile discovery and setup remain terminal-oriented through `profiles`, `profiles --sync`, `setup`, and explicit `setup --apply`. The apply/sync operations change configuration and need the user's authorization.

## Routing Rules

Routing modes live under `plugins.entries.skill-router.settings.routing_mode`:

- `deterministic`: local deterministic term/relevance routing;
- `hybrid` or `embedding`: deterministic explicit-request handling plus direct local Ollama embeddings with deterministic fail-open;
- `model`: auxiliary-model selection with deterministic fallback.

All routes pass through the deterministic policy gate. The policy remains authoritative for readiness, dependency expansion, alternatives, role normalization, ordering, and the skill limit. Confidence-aware comparisons do not waive these checks. An explicit request does not make a broken or disabled skill executable.

The Router never routes an MCP server directly. An MCP-backed workflow must be represented by a Hermes skill that declares `requirements.mcps`. The bundled `codebase-memory` skill is the reference integration for the `codebase-memory` MCP identity.

## Follow-up Continuity

The Router keeps a minimal profile- and session-scoped routing context for short referential follow-ups such as “mach weiter”, “teste es”, or “korrigiere das”. Only routing metadata is retained: previous primary/supporting skill names, routing category, policy status, timestamp, and an opaque session key.

Continuity is used only when normal routing abstains and never overrides explicit skill requests, skill-name negation, `avoid_when`, broken/disabled readiness, or the policy gate. Clear topic changes discard previous routing context.

## Local Embeddings

Hybrid routing embeds a compact, versioned routing fingerprint rather than the full `SKILL.md`. It includes name, description, category, tags, `use_when`, keywords, and `works_with`. `avoid_when` remains a deterministic exclusion signal. Cache identity includes the embedding document version so metadata-format changes cannot silently reuse stale vectors.

Numeric loopback HTTP origin only, no proxy, no redirects, bounded response size and timeouts, exact vector dimension, finite non-zero vectors, and deterministic fallback on failure remain mandatory. The embedding document format version is independent of the plugin version.

## Codebase Memory

Use the bundled skill for repository structure, code architecture, symbols, dependencies, implementation lookup, impact analysis, and grounded context before development work. It depends on the active profile's exact `codebase-memory` MCP configuration. The Router does not start or reconfigure that MCP.

The canary requires an explicitly ready routing skill with consistent setup/policy metadata and a configured/enabled MCP before its Codebase-Memory checks report PASS. An unavailable side yields WARN and skipped continuity checks. Passive MCP discovery is not a real search or end-to-end MCP execution test.

## Diagnostics and Rollout Check

`rollout-check` returns `READY`, `REVIEW`, or `BLOCKED`; `doctor` and `canary` return `PASS`, `WARN`, or `BLOCKED`. They diagnose the active profile, not other profiles.

Doctor adds a bounded readiness summary. `inspect <skill>` groups missing dependencies, unknown dependencies, setup requirements, and a routing recommendation. Configuration diagnostics name keys rather than exposing their values.

Readiness 2.0 evidence is preserved across catalog, cached model metadata and stored plans. Old snapshots are refreshed from actual passive checks at the next allowed scan; they are not silently declared ready. The numeric summary includes only known counters. Setup key strings and legacy type/name records are both supported. If quota compaction removes diagnostic details, `readiness_details_omitted` explicitly distinguishes missing evidence from no declared requirements. Readiness format version 2 is independent of plugin v0.12.0.

These checks do not install, enable, start, stop, restart, or reconfigure skills, MCPs, profiles, or gateways. However, catalog discovery can refresh Router-owned caches/state. Hybrid/embedding health checks can contact the configured numeric loopback endpoint. Do not claim these commands guarantee zero file writes or zero network requests.

Conservative defaults are deterministic routing, `enforcement_mode: warn`, `learning_mode: shadow`, follow-up context enabled, and OpenViking paused. Hybrid is optional after verifying the local service. `READY` permits controlled testing; it never authorizes automatic rollout.

## Decision Telemetry

Policy -> Runtime -> Audit retains only `confidence`, `original_primary`, `final_primary`, `fallback_applied`, and `fallback_reason` in `routing_telemetry`. The original/final names come from the current catalog. `fallback_reason` is a fixed code, never model-generated explanatory text.

`audit last`, `quality last`, and `recommend` show the five fields. `recommend` does not append execution-audit entries but may refresh catalog/derived state. General audit/quality/learning summaries show bounded observational counts and quality cohorts. Only finalized, assessable quality records enter cohort means.

Interpret the fields carefully:

- `not_assessed`: no confidence assessment for the final candidate, including old records without telemetry;
- `none`: no final primary;
- `high` / `medium`: routing heuristics, not correctness probabilities or execution outcomes;
- `fallback_applied`: automatic primary replacement, not an explicit override or proof of success;
- reason codes: `ready_within_margin`, `policy_replacement`, `unspecified`, or empty.

Blocked plans cannot claim that an intermediate primary replacement became executable. Missing historical metadata must stay unobserved. Telemetry must not copy prompts, configuration values, model explanations, or tool payloads. It must not change selection, quality scoring, enforcement, or learning weights.

## Performance and Shadow Learning

`performance` exposes bounded local timing metadata for catalog, embedding, selection, policy, and total latency, plus p50/p95 and cache diagnostics. No prompt/response content is stored in performance telemetry.

`learning_mode: shadow` remains diagnostic-only. It cannot change real routing, policy, readiness, OpenViking evidence, or enforcement. There is no active-learning mode. Observational fallback quality differences are not evidence of a causal improvement.

## Procedure

1. Read the injected `[Skill Router]` block before starting the task.
2. Load every validated skill with `skill_view` in the listed order.
3. Treat the Primary Skill as the controlling workflow; merge Supporting Skills only where compatible.
4. Respect setup/readiness warnings before depending on a skill.
5. Before rollout, review the target profile and run `rollout-check`, `doctor`, and `canary`; obtain real isolated-profile validation separately.
6. Diagnose bad routing with `recommend`, `inspect`, `audit last`, `quality last`, and `performance`.
7. Use `refresh` after manual skill changes not reflected by lifecycle events.

## Pitfalls

Never invent installed names or reuse another profile's catalog, MCP configuration, follow-up context, audit, quality, or learning state. Never route directly to MCPs, replace a blocked policy with raw model output, or assume technical metrics prove a final answer correct. OpenViking remains optional and disabled by default; no profile rollout is automatic.
