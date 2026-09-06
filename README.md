# Hermes Skill Router

An always-on, profile-scoped skill planner for Hermes Agent with deterministic routing, optional local Ollama embeddings, conservative follow-up continuity, readiness checks, execution audit/quality, and optional OpenViking support.

> **Development version v0.12.0 — unreleased.** Based on the merged v0.11.0 repository state. The new readiness-pipeline changes have not yet been validated in the intended isolated Hermes profile with its local model. A successful CI run is not production approval. OpenViking remains **disabled by default**.

## Architecture

```text
User task
  -> Skill Router
     -> explicit/deterministic signals
     -> optional local embedding similarity
     -> conservative session follow-up continuity
     -> readiness + dependency policy
     -> compact decision telemetry
  -> Hermes skill_view
  -> selected Skill
  -> MCP / tools used by that Skill
```

Hermes remains the executing agent. The Router recommends ordinary Hermes skills; it never turns an MCP server directly into a routable skill. MCP-backed procedures declare `requirements.mcps`. Selected procedures are loaded through native `skill_view`, not injected as copied executable skill documents.

The repository bundles the native `skill-router` plugin, the operational `skill-router:skill-router` skill, and `skill-router:codebase-memory` for the exact active-profile MCP identity `codebase-memory`.

## Current development scope

v0.12.0 fixes the Readiness 2.0 data path on top of the existing rollout preflight, confidence-aware policy and decision telemetry. It does not rebuild those components or change selection limits, routing scores, learning weights, scan intervals, or profile configuration.

A shared passive-evidence projection preserves `readiness_version`, `missing_dependencies`, `unknown_dependencies`, `setup_requirements`, and `readiness_summary` alongside existing readiness fields in new plans, cached model analysis and persisted snapshots. An older snapshot with the same catalog hash is repaired from actual checks during the next permitted scan, not by assuming readiness or invoking a new model analysis. Normal compaction retains this evidence; deeper quota compaction marks `readiness_details_omitted` instead of silently presenting missing details as no requirements.

`inspect` and Doctor accept setup key names as well as legacy type/name records. Structured summaries render only the known numeric counters, not arbitrary dictionary fields. Repository integration fixtures cover scanning, persistence/reload, readiness-only changes, updates/removal, model-enrichment boundaries and compaction. Live quality, reliability and token outcomes remain unmeasured.

The quality-first roadmap and native-versus-router evaluation protocol are recorded in [the development plan](docs/quality-first-plan.md). New work branches include their target version; merged history is retained and current package, runtime, skills and documentation versions stay synchronized.

Readiness reports distinguish missing commands, Python modules, other skills, MCP definitions, and required configuration keys. `inspect` groups missing dependencies, unverified dependencies, setup requirements, and the Router action. Doctor adds a bounded readiness summary rather than dumping the entire catalog.

Confidence-aware policy comparison can retain a clearly more relevant `unknown` primary or prefer a similarly relevant `ready` candidate. The existing safety/dependency policy and explicit user requests remain authoritative. Confidence labels are routing heuristics, not calibrated probabilities or evidence that a skill executed successfully.

Telemetry now travels through **Policy -> Runtime -> Audit** and is displayed by `recommend`, `audit`, `quality`, and the general `learning` summary. It does not change routing scores, quality scores, or shadow-learning weights.

## Requirements

- Hermes Agent with the native plugin hooks used here: `on_session_start`, `pre_llm_call`, `pre_tool_call`, `post_tool_call`, `post_llm_call`, and lifecycle support when available.
- Hermes `skills` toolset enabled and Python 3.11 or newer.
- For hybrid/embedding routing: a local Ollama-compatible `/api/embed` endpoint bound to a numeric loopback address.
- For Codebase Memory: an active-profile MCP configuration whose exact key is `codebase-memory`.
- Optional OpenViking APIs compatible with the existing bridge; not needed for the recommended configuration.

Capabilities are detected rather than inferred from a version string. CI runs the repository tests and plugin scans against pinned Hermes revisions, plus an informative current-`main` scan. These scans do not replace live Hermes integration tests.

## Installation and profile boundaries

An install without `--ref` selects the repository's current default branch, not a particular reviewed development snapshot:

```bash
hermes plugins install MKI13/hermes-skill-router --enable
```

Development validation must use an explicitly approved commit and an existing isolated test profile, after checking its configuration and backing up its Router state:

```bash
hermes --profile <test-profile> plugins install MKI13/hermes-skill-router --ref <reviewed-commit-sha> --enable
hermes --profile <test-profile> skill-router setup --dry-run --target-profile <test-profile>
```

Do not substitute a production profile. Review the setup plan before any separate `setup --apply`. No test-profile setup, gateway restart, merge, release, or multi-profile rollout is implied by this documentation.

`profiles` provides discovery; `profiles --sync` and `setup --apply` are explicit write operations. Setup uses Hermes profile-scoped mechanisms, not copied or symlinked profile state. Newly installed skills are discovered through lifecycle events and bounded rescanning; installing only an MCP does not create a routable skill.

## Conservative configuration

Start with the default deterministic routing and keep OpenViking paused:

```yaml
plugins:
  enabled: [skill-router]
  entries:
    skill-router:
      settings:
        routing_mode: deterministic
        enforcement_mode: warn
        learning_mode: shadow
        followup_context_enabled: true
        openviking_enabled: false
```

Local semantic routing is optional. After verifying the active profile's endpoint, the corresponding settings are:

```yaml
routing_mode: hybrid
embedding_url: http://127.0.0.1:11436
embedding_model: qwen3-embedding:0.6b
embedding_dimensions: 1024
```

The example endpoint must actually match the local service. Deterministic mode does not require it. Runtime embedding failures fall back to deterministic routing; hybrid/embedding preflight requires the configured endpoint to pass its health check.

## Commands and side effects

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
/skill-router inspect codebase-memory
/skill-router audit last
/skill-router quality last
/skill-router learning
/skill-router enforcement
/skill-router recommend inspect this repository and find the implementation
```

Terminal equivalents use `hermes --profile <profile> skill-router ...`; CLI refresh also supports `refresh --wait`.

`audit`, `quality`, and the general `learning` summary read existing observations. `recommend` displays a sample decision without creating an execution-audit entry. Commands that call catalog discovery can refresh **Router-owned caches/state**; `recommend` can also rebuild derived shadow state. Doctor, canary, and preflight therefore must not be interpreted as a guarantee of zero filesystem writes. They do not apply profile configuration, install skills or MCPs, or start/restart gateways. In hybrid/embedding mode, diagnostics can send a bounded loopback health request.

### Rollout preflight

```bash
hermes --profile <test-profile> skill-router rollout-check
hermes --profile <test-profile> skill-router doctor
hermes --profile <test-profile> skill-router canary
```

`rollout-check` reports `READY`, `REVIEW`, or `BLOCKED`. It checks critical Hermes capabilities, catalog/hash availability, routing/enforcement/learning settings, follow-up context, required embedding health, Codebase Memory configuration/skill availability, and paused OpenViking.

`READY` means the preflight permits controlled testing, not that live execution passed or other profiles may be changed automatically. `REVIEW` requires examination of warnings; `BLOCKED` indicates a hard preflight failure.

### Doctor and canary

Doctor reports `PASS`, `WARN`, or `BLOCKED`, with a readiness summary listing at most eight actionable skills and directing detailed inspection to `inspect`.

```text
SKIP    OpenViking disabled by configuration
```

The Codebase Memory canary requires an explicitly ready routing skill with consistent setup/policy metadata and a configured/enabled MCP. Missing MCP readiness yields WARN and skips the corresponding continuity checks. Passive MCP discovery is not a live RPC, search, or end-to-end execution test.

### Performance

`performance` reports bounded `catalog_ms`, `embedding_ms`, `selection_ms`, `policy_ms`, and `total_ms`, with total p50/p95 and embedding-cache diagnostics. It does not store prompt/response or tool-payload content in performance state.

## Routing decision telemetry

The existing profile-scoped audit stores an optional `routing_telemetry` object with exactly these fields:

| Field | Meaning |
|---|---|
| `confidence` | `high`, `medium`, `none`, or `not_assessed` |
| `original_primary` | Catalog-validated primary before policy changes, or empty |
| `final_primary` | Actual primary after policy validation, or empty |
| `fallback_applied` | Boolean automatic primary replacement; not an explicit user override |
| `fallback_reason` | Fixed code: `ready_within_margin`, `policy_replacement`, `unspecified`, or empty |

`none` describes a decision with no final primary. `not_assessed` is used when the confidence engine did not assess the final candidate or when an older record contains no telemetry. Historical records are not backfilled with invented measurements. A blocked result cannot claim that an intermediate fallback became executable.

Reasons are **allowlisted codes, not free text**. The telemetry path does not copy prompts, configuration values, tool payloads, or model explanations. Names come from the active catalog and are bounded and validated. Malformed values are normalized; telemetry failures do not invalidate an otherwise valid routing plan.

`audit last`, `quality last`, and `recommend` expose the five fields. Aggregate audit/quality/learning views show confidence counts, automatic replacements, and descriptive quality means for fallback/no-fallback cohorts. Only finalized, assessable quality records contribute to those means. Missing records are counted separately. History follows `max_audit_entries` and the summary processes at most 1,000 records.

**A high-confidence route can still fail to load its skill.** Confidence is not execution success. Cohort means are observational, not proof that fallback improves outcomes. The existing quality formula and shadow-learning weights are unchanged; no active learning is enabled.

## Readiness and policy

Skills may declare:

```yaml
requirements:
  commands: [git, gh]
  python_modules: [requests]
  skills: [github]
  mcps: [codebase-memory]
  config: [GITHUB_TOKEN]
```

States are `ready`, `unknown`, `setup_required`, `dependency_missing`, `broken`, and `disabled`. Missing declarations do not imply readiness. Readiness 2.0 adds `missing_dependencies`, `unknown_dependencies`, `setup_requirements`, `readiness_summary`, and checks with `available | missing | unknown`; configuration diagnostics name required keys, not their values. `readiness_version: 2` identifies the evidence format, independently of plugin version v0.12.0.

The policy validates installed names, readiness, declared dependencies, alternatives, roles, ordering, and limits. Explicit requests do not re-enable broken or disabled skills or waive unusable skill dependencies. A setup warning is not permission to install anything automatically.

Execution guard modes are `off`, `warn`, `primary`, and `all`; default `warn`. Learning modes are `off` and `shadow`; no active self-modifying routing is implemented.

## Codebase Memory and follow-up continuity

The bundled `codebase-memory` skill declares `requirements.mcps: [codebase-memory]`. Use it for repository structure, architecture, symbols, implementation lookup, dependencies, references, and impact analysis before code changes. Do not use it for ordinary email, translation, general research, calendar, invoices, or other non-code work.

The Router does not start, install, or reconfigure Codebase Memory. Each profile must expose its own authorized MCP configuration. This does not replace Hermes memory or require OpenViking.

Short referential follow-ups such as “continue”, “fix it”, “test it”, or “mach weiter” may reuse a previous primary only after normal routing abstains. Explicit requests, negation, `avoid_when`, broken/disabled readiness, and policy validation still take precedence. Topic switches discard stale workflow context.

Only routing metadata is retained in the bounded profile/session context: a hashed session key, previous skill names, routing category, policy status, and timestamp. No prompt or response text is retained there.

## Local embedding safety

Hybrid/embedding mode accepts numeric loopback HTTP origins only: no URL credentials, paths, queries, fragments, proxying, or redirects. Responses/timeouts are bounded; vector count and dimensions must match; vectors must be finite and non-zero. Caches remain profile-scoped.

Embedding routing documents contain bounded name, description, category, tags, `use_when`, keywords, and `works_with`. `avoid_when` remains an exclusion signal. `EMBEDDING_DOCUMENT_VERSION = 2` is a cache-format version, independent of the plugin version; it participates in cache identity with routing metadata fingerprints.

## OpenViking

```yaml
openviking_enabled: false
```

The optional bridge remains present but paused by default. `openviking_read_enabled` and `openviking_auto_write_enabled` are separate controls for a later explicitly reviewed activation. The master switch prevents Router bridge reads/writes; Hermes' independent memory-provider configuration is not modified.

## Configuration reference

CI checks these exact keys/defaults against `plugin.yaml` and the German README.

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

## Development and validation

```bash
python -m pytest -q
python scripts/benchmark-routing-quality.py
python scripts/check-doc-config-sync.py
python -m compileall -q .
hermes plugins doctor . --ci
```

Tests cover policy/audit integration, the production wrapper, finalization and reloads, profile/session separation, bounded history, malformed telemetry, secret-free reason codes, and unchanged quality/learning behavior. Version synchronization includes `pyproject.toml`, `plugin.yaml`, both bundled skills, package/runtime version, and current documentation markers.

GitHub CI runs Python 3.11/3.12/3.13, benchmarks, documentation synchronization, compilation, two pinned Hermes plugin scans, and an informative current-main scan. Repository integration is separate from release and production approval. Live isolated-profile testing with the intended local model, Codebase Memory, and embedding service remains required before production rollout; no live result is claimed here.

## License

MIT. See `LICENSE`.
