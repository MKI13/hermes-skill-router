# Changelog

## 0.12.0 — Unreleased

- Built on the merged v0.11.0 main revision rather than restarting or overwriting its feature branches. New development branch: `feat/v0.12.0-readiness-pipeline`.
- Preserve all passive Readiness 2.0 evidence through catalog-to-plan projection, cached model-analysis reuse, runtime snapshots, persistence/reload and normal state compaction. Nested evidence is independently copied.
- Refresh evidence independently of skill content/model metadata. Repair older same-hash snapshots from actual passive checks at the next permitted scan without extra per-message scans or model calls; invalidate stale in-flight catalog generations when repairing evidence.
- Accept actual setup key-name lists and legacy type/name records in inspect/Doctor. Render only known numeric summary counters, not arbitrary dictionary fields. Grouped diagnostics retain required skills and alternatives.
- Mark readiness details omitted by severe state-quota compaction explicitly. Missing diagnostic evidence is not reported as no declared requirements, and a later fresh scan clears the omission marker.
- Added repository regression fixtures for initial scan, four readiness states, persistence/reload, same-hash repair, changed prerequisites, skill updates/removal, model-enrichment boundaries, scan gating and compaction. The tests-only baseline reproduced 14 failing cases; those are fixture results, not live Hermes acceptance.
- Synchronize runtime, package, manifest, bundled skills and current documentation at 0.12.0. Keep readiness and embedding format versions at 2; they are not plugin release versions.
- Record the quality-first roadmap and native-versus-router evaluation protocol without claiming measured outcome improvements. Existing routing scores/limits, learning weights, config defaults, profile boundaries and OpenViking behavior are unchanged.
- No GEEKOM changes, live-profile test, main merge, release or production rollout is claimed for this development milestone.

## 0.11.0 — Unreleased

- Connected routing decision telemetry through Policy -> Runtime -> the existing profile-scoped Audit. The dedicated object contains only confidence, original/final primary, automatic fallback flag, and a fixed reason code.
- Added normalized telemetry to audit/recommend/quality diagnostics and observational fallback/no-fallback quality cohorts to aggregate audit, quality, and general shadow-learning views. Quality formulas and learning weights remain unchanged.
- Reject arbitrary reason text and malformed values; do not treat string booleans as consent to a fallback, explicit user overrides as automatic fallbacks, intermediate blocked plans as executable, or older unmeasured records as historical measurements.
- Added pipeline, reload/finalization, profile/session isolation, bounded history, privacy, malformed-input, and unchanged-scoring regression tests. Updated the old free-text audit assertion to distinguish an exact forbidden reason field from the new allowlisted fallback_reason code.
- Aligned previously stale 0.8.0 package/manifest/skill/runtime metadata with the actual 0.11.0 development milestone. Added a canonical Python runtime version and regression checks across distributed metadata and current documentation.
- Updated both READMEs and the operational skill. Clarified that diagnostic catalog refreshes may update Router-owned caches without applying profile configuration or gateway changes; this is not a guarantee of zero file writes.
- Fixed false-positive Codebase Memory readiness: Canary now requires an explicitly ready skill with consistent setup/policy metadata, not merely a skill that is neither broken nor disabled. Doctor and rollout preflight also distinguish available from ready. A ready candidate can be found even when an unusable referencing skill appears first.
- Validate raw routing/enforcement/learning modes and boolean flags before runtime fallback normalization can conceal invalid configuration. Diagnostics report BLOCKED without echoing invalid configuration values; runtime fallback behavior is unchanged.
- Require a valid catalog snapshot/hash for diagnostics. Malformed MCP requirements neither crash diagnostics nor imply readiness.
- Canary now validates the follow-up selection through the actual policy gate and cannot report PASS when that gate rejects the plan. Its output explicitly labels MCP readiness as configuration-only, not a live MCP or local-model test.
- Added 45 pre-merge regression cases. The correction passed all 515 repository tests plus the existing routing benchmark, version/config checks and plugin scans before documentation finalization.
- Repository integration and live acceptance are separate: the owner requested a repository-only merge after error checking while deferring the GEEKOM test. No live Hermes-profile validation, release, gateway changes, active learning or OpenViking activation is claimed. Isolated-profile validation remains required before production rollout.

## 0.10.0 — Development milestone, unreleased

- Added a conservative confidence decision engine and connected it to the policy's unknown-versus-ready primary comparison.
- Preserved explicit user choice and clearly more relevant unknown candidates; preferred ready candidates within a bounded relevance margin.
- Preserved input order for equal scores and recorded policy changes without alphabetically inventing a different original priority.

## 0.9.0 — Development milestone, unreleased

- Added structured passive readiness evidence for commands, Python modules, required skills, MCPs, and configuration keys.
- Added grouped inspect diagnostics and a bounded Doctor readiness summary with actionable skill ordering.
- Added readiness-aware primary-policy regression coverage and the ready-versus-unknown policy correction.

## 0.8.0

- Added a read-only `skill-router rollout-check` preflight with `READY`, `REVIEW`, and `BLOCKED` decisions before profile rollout.
- The preflight validates critical Hermes capabilities, catalog/hash availability, conservative routing/enforcement/learning settings, follow-up context, local embedding health when required, Codebase Memory MCP/skill state, and paused OpenViking state.
- `rollout-check` never installs, enables, starts, stops, restarts, or modifies profiles, skills, MCPs, gateways, or files.
- Added focused regression coverage for ready, review, blocked, and non-conservative rollout configurations.
- Kept runtime routing behavior, policy, Codebase Memory integration, shadow learning, and the default `openviking_enabled: false` unchanged.

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
