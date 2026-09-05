# Changelog

## 0.8.0

- Added conservative deterministic intent aliases for known mail and calendar skill families so installed skills such as `himalaya` and calendar integrations can be selected from German or English task wording without globally forcing a match.
- Strengthened readiness weighting for automatic routing: `setup_required` and `dependency_missing` candidates are suppressed much more strongly, while `broken` and `disabled` candidates cannot win through lexical noise.
- Expanded the golden routing fixture with German and English mail/calendar cases plus an additional generic no-skill message case.
- Added Hermes-terminal-style `HERMES SKILL ROUTER` branding to both `README.md` and `README.de.md` and expanded the documented command surface for Hermes and terminal use.
- Kept deterministic routing, warn enforcement, shadow learning, and `openviking_enabled: false` as the recommended rollout defaults.

## 0.7.1

- Fixed the production canary so Codebase Memory reports PASS only when both the routable `codebase-memory` skill and the active profile's `codebase-memory` MCP are ready.
- Added a regression for the case where the routing skill is present but its required MCP is missing or not ready.
- Canary now reports WARN and skips Codebase-Memory follow-up continuity checks whenever full Codebase Memory readiness is unavailable.
- Kept routing behavior, policy, embeddings, shadow learning, enforcement, and the default `openviking_enabled: false` unchanged.

## 0.7.0

- Added a bundled `codebase-memory` Hermes skill that declares `requirements.mcps: [codebase-memory]`, keeping MCP servers as capabilities rather than direct routing targets.
- Added conservative profile- and session-scoped follow-up continuity for short referential turns; previous Primary Skill reuse occurs only after normal routing abstains and remains subject to explicit requests, negation, exclusions, readiness, and policy.
- Added versioned local embedding routing documents containing name, description, category, tags, `use_when`, keywords, and `works_with`; cache identity now includes embedding document version and routing metadata.
- Added `skill-router doctor` with passive Hermes/catalog/Codebase-Memory checks and a bounded local embedding health request in hybrid/embedding modes; disabled OpenViking is reported as skipped.
- Added `skill-router performance` with bounded profile-local catalog, embedding, selection, policy, and total latency samples plus p50/p95 and embedding-cache diagnostics.
- Added CI synchronization checks across `plugin.yaml`, `pyproject.toml`, bundled skill metadata, `README.md`, and `README.de.md`.
- Expanded deterministic benchmark reporting with false-positive/supporting precision and p50/p95 latency metrics.
- Added pinned Hermes compatibility/security checks plus a non-blocking Hermes `main` compatibility job.
- Kept `openviking_enabled: false` as the default and preserved the existing OpenViking bridge without making it part of the v0.7.0 rollout.

## 0.6.2

- Required multi-skill intent plus non-negated lexical or declared `works_with` evidence before an ambiguous semantic Top-2 may become an optional supporting skill; negation and `avoid_when` exclusions remain authoritative.
- Added a regression for the production prompt that previously attached `comfyui` to an unrelated Skill Router quick test while preserving intended ambiguous Top-2 routing for genuinely combined tasks.
- Treat reports about a wrong or unnecessary Primary/Supporting Skill as Router diagnostics before explicit skill-name matching, so naming the bad recommendation cannot select it again.

## 0.6.1

- Kept the qualified `skill-router:skill-router` operational skill in the routable catalog so Router status and diagnosis requests resolve to their own workflow instead of unrelated skills.
- Added a configurable `0.45` weak-signal cosine floor when a semantic winner has no lexical evidence in the current message, preventing low-confidence referential follow-ups from forcing a skill.
- Added deterministic priority for Skill Router meta-requests, even when the message mentions other skills, while honoring explicit requests not to use the Router workflow.
- Added focused regressions for Router meta-priority and negation, self-routing, low-signal abstention, and lexical-evidence routing.

## 0.6.0

- Added direct numeric-loopback-only Ollama embedding routing with proxy and redirect refusal, bounded responses, strict vector validation, and configurable five-minute keep-alive.
- Added profile-scoped catalog vector caches keyed by profile scope, catalog/content identity, endpoint, model, and dimensions; only skill names and descriptions are embedded.
- Added `hybrid`/`embedding` routing: explicit skill requests retain deterministic priority, semantic Top-2 is used only below the `0.02` ambiguity margin, and failures fall open to deterministic routing without a generative LLM call.
- Preserved readiness, dependency expansion, policy validation, enforcement, audit, quality, shadow learning, and independent OpenViking read/write gates.
- Added loopback/SSRF, redirect, response-size, timeout, malformed-vector, cache-isolation, concurrency, runtime, and real-service benchmark coverage.

## 0.5.0

- Added automatic, coalesced catalog updates for Hermes skill lifecycle events with cache-settled and interval-gated fingerprint fallbacks.
- Added a bounded, profile-scoped technical skill-event history plus `/skill-router events` and compact pending/last-change status.
- Added passive `requirements.mcps` readiness through compatibility-wrapped active-profile Hermes configuration discovery without starting or routing MCP tools.
- Preserved authoritative catalogs and Router-owned OpenViking mirrors during transient skill-discovery failures, while removing successfully observed deleted skills.
- Added Hermes-first `after-install.md` guidance and clearer setup summaries without automatic apply.

## 0.4.0

- Added compatibility-wrapped discovery of all live Hermes profiles and metadata-only `profiles` reporting.
- Added read-only-by-default adaptive setup, selective apply, partial-failure rollback, and lifecycle-aware roster sync through official profile-scoped Hermes commands.
- Added safe initial defaults while preserving explicit settings and intentionally disabled installations.
- Scoped snapshots, audits, shadow learning, OpenViking ownership, and profile inventory to opaque canonical-home identities so cloned or renamed profile state cannot cross profile boundaries.
- Kept routing, readiness, audit, learning, and optional OpenViking behavior strictly profile-local; no active learning or hard-enforcement changes were made.

## 0.3.0

- Added a calibrated deterministic no-skill gate with explicit-request preservation and readiness-independent relevance.
- Limited normal deterministic routing to one optional supporting skill while preserving declared dependency expansion.
- Applied the strict deterministic gate after model errors and timeouts and added no-match score diagnostics to `recommend`.
- Added a 44-case anonymized golden routing set plus legacy-versus-calibrated quality and 76-skill overhead measurement.
- Made no enforcement, active-learning, OpenViking integration, or Codebase Memory changes.

## 0.2.1

- Reworked artificial secret and network test fixtures so the standard Hermes plugin security scanner can assess the repository without false-positive dangerous findings.
- Added a CI gate using an exact Hermes commit to require a safe plugin scan; no production security check is disabled.
- Made no routing, policy, enforcement, audit, quality, or shadow-learning behavior changes.

## 0.2.0

- Added a feature-detected Hermes compatibility layer for skill discovery and execution hooks.
- Added passive skill-readiness checks and deterministic routing policy validation.
- Added bounded execution enforcement, execution audit, and versioned technical quality evaluation.
- Added profile-scoped shadow learning with role-specific evidence, conservative bias, deterministic rebuild, and diagnostic actual-versus-shadow comparisons.
- Added learning inspection, reset, and rebuild commands. Shadow learning never changes real routing, policy, OpenViking scores, skill metadata, or enforcement.

## 0.1.0

- Published the initial profile-scoped skill catalog, planner, OpenViking bridge, and per-turn recommendation plugin.
