# Changelog

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
