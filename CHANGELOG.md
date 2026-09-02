# Changelog

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
