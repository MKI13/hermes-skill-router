---
name: skill-router
description: Inspect routing plans, readiness, diagnostics, rollout readiness, performance, and execution audits.
version: 0.8.0
author: Hermes Skill Router contributors
license: MIT
metadata:
  hermes:
    tags: [skills, routing, orchestration, diagnostics, embeddings, openviking]
    category: productivity
---
# Skill Router Skill

This operational skill explains how to inspect and diagnose the always-on Hermes Skill Router plugin. It does not replace task-specific skills.

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

Terminal equivalents use `hermes skill-router ...`. Profile discovery and setup remain terminal-oriented through `profiles`, `profiles --sync`, `setup`, and explicit `setup --apply`.

## Routing Rules

Routing modes live under `plugins.entries.skill-router.settings.routing_mode`:

- `deterministic`: local deterministic term/relevance routing;
- `hybrid` or `embedding`: deterministic explicit-request handling plus direct local Ollama embeddings with deterministic fail-open;
- `model`: auxiliary-model selection with deterministic fallback.

All routes pass through the deterministic policy gate. The policy remains authoritative for readiness, dependency expansion, alternatives, role normalization, ordering, and the skill limit.

The Router never routes an MCP server directly. An MCP-backed workflow must be represented by a Hermes skill that declares `requirements.mcps`. The bundled `codebase-memory` skill is the reference integration for the `codebase-memory` MCP identity.

## Follow-up Continuity

v0.8.0 keeps a minimal profile- and session-scoped routing context for short referential follow-ups such as “mach weiter”, “teste es”, or “korrigiere das”. Only routing metadata is retained: previous primary/supporting skill names, routing category, policy status, timestamp, and an opaque session key.

Continuity is deliberately weak. It is used only when normal routing abstains and never overrides:

- an explicit skill request;
- skill-name negation;
- `avoid_when` evidence;
- broken/disabled readiness;
- the policy gate.

Clear topic changes discard the previous routing context.

## Local Embeddings

Hybrid routing embeds a compact, versioned routing fingerprint rather than the full `SKILL.md`. It includes name, description, category, tags, `use_when`, keywords, and `works_with`. `avoid_when` remains a deterministic exclusion signal. Cache identity includes the embedding document version so metadata-format changes cannot silently reuse stale vectors.

The existing safety boundary remains mandatory: numeric loopback HTTP origin only, no proxy, no redirects, bounded response size, bounded timeouts, exact vector dimension, finite non-zero vectors, and deterministic fallback on failure.

## Codebase Memory

The bundled `codebase-memory` skill should be used for repository structure, code architecture, symbols, dependencies, implementation lookup, impact analysis, and grounded context before development work. Its readiness depends on the active profile's exact `codebase-memory` MCP configuration. The Router does not start or reconfigure that MCP.

The production canary only reports Codebase Memory as ready when both the routing skill and the active profile's `codebase-memory` MCP are ready. If either side is unavailable, the canary reports WARN and skips the Codebase-Memory follow-up continuity checks.

## Rollout Check

`/skill-router rollout-check` and `hermes skill-router rollout-check` are read-only preflight checks for the active profile. They do not install, enable, start, stop, restart, or modify anything.

The result is one of:

- `READY`: conservative rollout defaults and required health checks are satisfied;
- `REVIEW`: no hard blocker exists, but one or more settings or optional dependencies require explicit review;
- `BLOCKED`: a critical capability, catalog state, routing mode, or required embedding health check prevents rollout.

The conservative target is deterministic or hybrid routing, `enforcement_mode: warn`, `learning_mode: shadow`, follow-up context enabled, and OpenViking paused. Codebase Memory readiness is reported separately so an absent profile MCP cannot be mistaken for a fully ready code workflow.

## Doctor

`/skill-router doctor` and `hermes skill-router doctor` perform safe diagnostics for Hermes capabilities, catalog state, local embeddings when required, Codebase Memory MCP/skill readiness, and Router subsystems. OpenViking is reported as `SKIP` when disabled.

Doctor must never print credentials, environment values, hidden paths, prompts, tool payloads, or skill contents.

## Performance

`/skill-router performance` and `hermes skill-router performance` expose bounded local timing metadata for catalog, embedding, selection, policy, and total routing latency, plus p50/p95 total latency and embedding cache diagnostics. No prompt or response content is stored for performance telemetry.

## Shadow Learning

`learning_mode: shadow` remains diagnostic-only. It cannot change real routing, policy, readiness, OpenViking evidence, or enforcement. There is no active-learning mode in v0.8.0.

## Procedure

1. Read the injected `[Skill Router]` block before starting the task.
2. Load every validated skill with `skill_view` in the listed order.
3. Treat the Primary Skill as the controlling workflow.
4. Apply Supporting Skills only where compatible and useful.
5. Respect setup/readiness warnings before depending on a skill.
6. Before a profile rollout, run `rollout-check`, then `doctor`, then the read-only `canary`.
7. If routing looks wrong, use `recommend`, `inspect`, `audit last`, and `performance` to isolate the problem.
8. Use `refresh` after manual skill changes not reflected by Hermes lifecycle events.

## Pitfalls

- Never invent installed skill names.
- Never assume another profile's catalog, MCP configuration, follow-up context, audit, quality, learning, or performance state applies to the active profile.
- Never route directly to MCP tools.
- Never substitute raw model output for a blocked policy result.
- Never treat audit, quality, shadow learning, or performance metrics as proof that Hermes' final domain answer is correct.
- A `READY` rollout check is permission to proceed with controlled testing, not permission to mutate other profiles automatically.
- OpenViking remains optional and disabled by default in the recommended v0.8.0 rollout.
