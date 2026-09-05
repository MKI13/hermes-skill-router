# Hermes Skill Router

An always-on, profile-scoped skill planner for Hermes Agent with deterministic routing, direct local Ollama embeddings, conservative session follow-up continuity, passive readiness checks, execution audit/quality, and optional OpenViking support.

> Status: community release candidate **v0.7.1**. OpenViking remains **disabled by default** for the recommended v0.7.1 rollout.

## What v0.7.1 is for

The Router keeps Hermes in control while improving which installed skill is loaded for each task:

```text
User task
  -> Skill Router
     -> explicit/deterministic signals
     -> optional local embedding similarity
     -> conservative follow-up continuity
     -> readiness + dependency policy
  -> Hermes skill_view
  -> selected Skill
  -> MCP / tools used by that Skill
```

The Router never turns MCP servers into routable skills. MCP-backed workflows are exposed through ordinary Hermes skills with `requirements.mcps`.

## v0.7.1 highlights

- Bundled `codebase-memory` skill for the `codebase-memory` MCP identity.
- Canary now requires both the Codebase Memory routing skill and the active profile's `codebase-memory` MCP to be ready before reporting PASS.
- Conservative session follow-up routing for short requests such as “continue”, “fix it”, “test it”, or “commit it”.
- Follow-up context stores routing metadata only; no prompts, responses, tool payloads, files, or credentials.
- Richer versioned local embedding documents: name, description, category, tags, `use_when`, keywords, and `works_with`.
- `hermes skill-router doctor` / `/skill-router doctor` for safe end-to-end diagnostics.
- `hermes skill-router performance` / `/skill-router performance` for bounded local latency metrics.
- Configuration/documentation consistency checks in CI.
- OpenViking read/write controls remain available but `openviking_enabled` stays `false` by default.

## Why this is a plugin plus skills

A plain `SKILL.md` cannot stay active across turns or observe Hermes skill lifecycle events. This repository therefore contains:

- the native `skill-router` plugin for routing, policy, lifecycle, state, audit, quality, and diagnostics;
- the bundled operational `skill-router:skill-router` skill for Router commands and troubleshooting;
- the bundled `skill-router:codebase-memory` skill, whose readiness depends on the active profile's `codebase-memory` MCP definition.

Hermes still loads selected procedures through native `skill_view`. The Router does not inject copied skill documents as executable instructions.

## Requirements

- Hermes Agent with native plugin hooks used by the repository (`on_session_start`, `pre_llm_call`, `pre_tool_call`, `post_tool_call`, `post_llm_call`, and skill lifecycle support when available).
- Hermes `skills` toolset enabled.
- Python 3.11 or newer.
- For hybrid routing: a local Ollama-compatible `/api/embed` endpoint bound to a numeric loopback address.
- For Codebase Memory routing: an active-profile MCP server whose exact Hermes configuration key is `codebase-memory`.
- Optional: OpenViking 0.4.17.1-compatible APIs. It is not required for the v0.7.1 recommended configuration.

Compatibility is capability-detected rather than assumed from one Hermes version. CI keeps hard checks for known Hermes revisions and an informative `main` compatibility job.

## Install

Preferred Hermes-first workflow:

```text
Install the Skill Router from MKI13/hermes-skill-router.
```

Equivalent terminal flow:

```bash
hermes plugins install MKI13/hermes-skill-router --enable
hermes skill-router setup
hermes skill-router setup --dry-run
hermes skill-router setup --apply
hermes skill-router profiles
```

Setup uses official profile-scoped Hermes commands. It does not copy profile state or merge profile skill catalogs. New/removed/renamed profiles can be reconciled explicitly with:

```bash
hermes skill-router profiles --sync
```

## Recommended v0.7.1 configuration

For the current rollout, keep OpenViking paused and use deterministic or local hybrid routing:

```yaml
plugins:
  enabled: [skill-router]
  entries:
    skill-router:
      settings:
        routing_mode: hybrid
        enforcement_mode: warn
        learning_mode: shadow
        followup_context_enabled: true
        embedding_url: http://127.0.0.1:11436
        embedding_model: qwen3-embedding:0.6b
        embedding_dimensions: 1024
        openviking_enabled: false
```

The local embedding service remains optional. If it fails, hybrid routing fails open to the deterministic router.

## Local embedding safety

Hybrid/embedding mode keeps the existing strict boundary:

- numeric loopback HTTP origin only;
- no URL credentials, paths, queries, fragments, proxies, or redirects;
- bounded response size and timeout;
- exact vector count and dimension;
- finite, non-zero vectors;
- profile-scoped cache;
- deterministic fallback on any embedding failure.

v0.7.1 uses `EMBEDDING_DOCUMENT_VERSION = 2`. The cached vector identity includes this version plus the skill content/routing metadata fingerprint, so routing-document format changes cannot silently reuse stale vectors.

## Codebase Memory integration

The Router still routes only Hermes skills. Codebase Memory is therefore represented by the bundled `codebase-memory` skill:

```yaml
requirements:
  mcps:
    - codebase-memory
```

Use it for repository structure, source-code architecture, implementation lookup, symbols, dependencies, references, and impact analysis before code changes.

Do **not** use it for ordinary email, translation, web research, calendar, invoices, or other non-code tasks.

The Router never starts or reconfigures the MCP. `requirements.mcps` affects readiness only. If the MCP is present but no routable skill references it, `skill-router doctor` reports a warning instead of inventing a routing entry.

The v0.7.1 canary treats Codebase Memory as fully ready only when both the routing skill and the active profile MCP are ready. If either side is unavailable, the canary reports WARN and skips Codebase-Memory follow-up continuity checks.

## Follow-up routing

Hermes conversations often contain short turns such as:

```text
Analyze the repository and find the implementation.
-> PRIMARY: codebase-memory

Now fix it.
```

v0.7.1 may reuse the previous Primary Skill only when all of the following are true:

1. the message is a short referential follow-up;
2. normal routing produced no selection;
3. there is no explicit different skill request;
4. the previous skill is still present and not broken/disabled;
5. the message does not negate the previous skill;
6. no `avoid_when` exclusion matches;
7. the normal policy gate still accepts the result.

A clear topic switch such as “Write an email to the customer now” does not inherit Codebase Memory.

Stored follow-up metadata is limited to an opaque session key, previous primary/supporting skill names, routing category, policy status, and timestamp. No prompt or response text is retained.

## Commands

Inside Hermes:

```text
/skill-router status
/skill-router doctor
/skill-router performance
/skill-router events 20
/skill-router refresh
/skill-router plan
/skill-router inspect codebase-memory
/skill-router audit last
/skill-router quality last
/skill-router learning
/skill-router enforcement
/skill-router recommend inspect this repository and find the implementation
```

Terminal:

```bash
hermes skill-router status
hermes skill-router doctor
hermes skill-router performance
hermes skill-router events 20
hermes skill-router refresh --wait
hermes skill-router plan
hermes skill-router inspect codebase-memory
hermes skill-router audit last
hermes skill-router quality last
hermes skill-router learning
hermes skill-router enforcement
hermes skill-router recommend inspect this repository and find the implementation
```

### Doctor

`doctor` checks Hermes capabilities, catalog availability, routing policy/audit/quality/learning availability, local embeddings when the active routing mode needs them, and Codebase Memory MCP/skill readiness. It never prints secret values or complete paths.

Expected disabled OpenViking output:

```text
SKIP    OpenViking disabled by configuration
```

Overall statuses are `PASS`, `WARN`, and `BLOCKED`.

### Performance

`performance` records only bounded numeric timing metadata:

```text
catalog_ms
embedding_ms
selection_ms
policy_ms
total_ms
```

It reports the last sample plus total p50/p95 and embedding-cache diagnostics. Prompts, responses, tool arguments/results, files, and credentials are never stored.

## Readiness

Skills may declare:

```yaml
requirements:
  commands: [git, gh]
  python_modules: [requests]
  skills: [github]
  mcps: [codebase-memory]
  config: [GITHUB_TOKEN]
```

Readiness states remain `ready`, `unknown`, `setup_required`, `dependency_missing`, `broken`, and `disabled`. A skill without sufficient declarations remains `unknown`; the Router never silently assumes it is ready.

## Policy, enforcement, audit, quality, learning

The deterministic policy remains authoritative for every routing mode. It validates installed names, readiness, dependencies, alternatives, role ordering, and limits.

Execution guard modes are `off`, `warn`, `primary`, and `all`. Default remains `warn`.

Audit/quality remain technical diagnostics. They do not measure the correctness of the final domain answer.

Learning modes are `off` and `shadow`. No active learning mode exists in v0.7.1; shadow learning cannot change the real recommendation.

## OpenViking

OpenViking support remains in the codebase for compatibility, but the recommended v0.7.1 rollout keeps:

```yaml
openviking_enabled: false
```

When enabled later, separate `openviking_read_enabled` and `openviking_auto_write_enabled` controls remain available. Disabling the bridge prevents Router OpenViking reads/writes; Hermes' own memory-provider configuration remains independent.

## Configuration reference

Every key below is defined by `plugin.yaml`. CI verifies that both READMEs document the same keys and defaults.

| Setting | Type | Default |
|---|---|---|
| `routing_mode` | `str` | `deterministic` |
| `deep_refresh_on_start` | `bool` | `true` |
| `rescan_interval_seconds` | `int` | `60` |
| `max_skills_per_task` | `int` | `4` |
| `deterministic_min_score` | `int` | `20` |
| `deterministic_supporting_min_score` | `int` | `24` |
| `max_optional_supporting_skills` | `int` | `2` |
| `followup_context_enabled` | `bool` | `true` |
| `followup_context_max_sessions` | `int` | `32` |
| `embedding_url` | `str` | `"http://127.0.0.1:11436"` |
| `embedding_model` | `str` | `"qwen3-embedding:0.6b"` |
| `embedding_dimensions` | `int` | `1024` |
| `embedding_timeout_seconds` | `float` | `5.0` |
| `embedding_keep_alive` | `str` | `"5m"` |
| `embedding_batch_size` | `int` | `32` |
| `embedding_ambiguity_margin` | `float` | `0.02` |
| `embedding_min_score` | `float` | `0.35` |
| `embedding_weak_signal_min_score` | `float` | `0.45` |
| `performance_history_limit` | `int` | `100` |
| `max_audit_entries` | `int` | `100` |
| `learning_mode` | `str` | `shadow` |
| `learning_min_samples` | `int` | `5` |
| `enforcement_mode` | `str` | `warn` |
| `max_enforcement_blocks_per_turn` | `int` | `2` |
| `max_skill_chars` | `int` | `20000` |
| `analysis_batch_size` | `int` | `6` |
| `analysis_model_timeout_seconds` | `int` | `25` |
| `routing_catalog_chars` | `int` | `60000` |
| `routing_model_timeout_seconds` | `int` | `20` |
| `openviking_enabled` | `bool` | `false` |
| `openviking_read_enabled` | `bool` | `true` |
| `openviking_auto_write_enabled` | `bool` | `true` |
| `openviking_url` | `str` | `""` |
| `openviking_timeout_seconds` | `int` | `10` |
| `openviking_retrieval_limit` | `int` | `12` |
| `openviking_routing_timeout_seconds` | `int` | `3` |
| `openviking_score_threshold` | `float` | `0.15` |
| `openviking_plan_uri` | `str` | `"viking://~/resources/hermes-skill-router/{profile}/plan.md"` |

Allowed modes: `routing_mode` = `deterministic | hybrid | embedding | model`; `enforcement_mode` = `off | warn | primary | all`; `learning_mode` = `off | shadow`.

## Security and privacy

- Profile state is isolated by opaque canonical profile scope.
- Session continuity uses a hashed session key and routing metadata only.
- No prompts, responses, tool payloads/results, files, or credentials are written to follow-up/performance state.
- Codebase Memory MCP details are inspected passively; credentials and environment values are never printed.
- `skill_view` remains the execution path for selected skills.
- Missing/failed local embeddings fail open to deterministic routing.
- OpenViking remains disabled by default.

## Development and CI

```bash
python -m pytest -q
python scripts/benchmark-routing-quality.py
python scripts/check-doc-config-sync.py
python -m compileall -q .
hermes plugins doctor . --ci
```

CI tests Python 3.11, 3.12, and 3.13, pinned Hermes compatibility/security revisions, and a non-blocking Hermes `main` compatibility check.

## License

MIT. See `LICENSE`.
