# Hermes Skill Router

An always-on, profile-scoped skill planner for [Hermes Agent](https://github.com/NousResearch/hermes-agent) with optional [OpenViking](https://github.com/volcengine/OpenViking) indexing and retrieval.

The plugin inventories the effective skills of each Hermes profile, reads their `SKILL.md` instructions, creates a routing plan with a configurable Hermes auxiliary model, mirrors the catalog and plan into OpenViking, and recommends ordered skills before every user turn. Hermes still loads the selected procedures through its native `skill_view` security and readiness path.

> Status: early community release (`0.4.0`). Test it with your Hermes and OpenViking versions before unattended use.

## Why this is a plugin plus a skill

A plain `SKILL.md` is loaded on demand. It cannot remain active, observe skill lifecycle events, or inject routing guidance before every request. This repository therefore contains:

- a native Hermes plugin for lifecycle, planning, persistence, OpenViking sync, and per-turn routing;
- a bundled `skill-router:skill-router` operational skill for status, refresh, diagnostics, and routing rules;
- no permanent model tool schema.

## Behavior

1. **Install/enable:** the plugin registers an always-on bounded system-prompt rule, lifecycle hooks, commands, and a `skill_router_planner` auxiliary task.
2. **Initial plan:** `hermes skill-router refresh --wait` scans and analyzes the current profile immediately. Without the command, the first new session creates a deterministic base plan and starts deep analysis in the background.
3. **Catalog:** Hermes `skills_list` supplies the effective visible catalog: trusted project skills, profile-local skills, external directories, and enabled plugin skills, subject to Hermes filtering.
4. **Readiness:** declared command, Python-module, skill, and configuration requirements are checked passively during catalog refresh and cached with the plan. No setup action is executed.
5. **Deep analysis:** only new or changed skill documents are sent in bounded batches to the configured auxiliary model.
6. **OpenViking:** profile-scoped mirror names are added/updated through `/api/v1/skills`; the generated plan is written under `viking://~/resources/hermes-skill-router/{profile-scope}/plan.md` by default.
7. **Every task:** when enabled, OpenViking `/api/v1/skills/find` supplies retrieval scores. The auxiliary model selects zero to five exact Hermes skill names and an execution order. Deterministic routing uses a strict no-skill gate, including after a model timeout or error.
8. **Policy gate:** deterministic validation applies catalog readiness, explicit user requests, alternatives, declared skill dependencies, role normalization, dependency-first ordering, and the configured skill limit. Model output never bypasses this gate.
9. **Execution guard:** the final policy plan initializes a turn-isolated guard. The default warns only; optional hard modes use `pre_tool_call` to require successful ordered `skill_view` loads before task tools.
10. **Execution:** a dynamic `[Skill Router]` block tells Hermes to call native `skill_view` for each validated skill before doing the task.
11. **Execution audit:** public `post_tool_call` and `post_llm_call` observers correlate successful `skill_view` calls and compact guard outcomes with the validated routing decision. The audit itself never blocks, retries, or changes ranking.
12. **Quality evaluation:** each finalized audit receives a versioned deterministic score for technical routing and execution quality.
13. **Shadow learning:** current-version, high-confidence quality history is rebuilt into profile-local skill-role aggregates and conservative diagnostic biases. A separate shadow comparison is recorded, while the real selection remains unchanged.
14. **Updates:** `created`, `installed`, `patched`, `edited`, `archived`, `stale`, and `restored` lifecycle events queue an incremental refresh plus a cache-settled pass after Hermes' 30-second content-cache window. Periodic catalog fingerprint checks catch additional changes.

Each Hermes profile stores an independent plan and bounded audit history through `ctx.state`; profiles never inherit another profile's routing decisions or audit data. Every snapshot, audit, learning envelope, and setup roster carries an opaque canonical-home scope token, so state copied by profile cloning or renaming is rejected before catalog use or OpenViking reconciliation. The token does not reveal the profile path.

## Requirements

- Hermes Agent with native plugin hooks including `pre_tool_call`, `post_tool_call`, and `post_llm_call`, plus `ctx.llm`, plugin auxiliary tasks, system-prompt sections, and `on_skill_lifecycle` support. Missing execution hooks degrade safely.
- The Hermes `skills` toolset enabled.
- Python 3.11 or newer (Hermes runtime).
- Optional: OpenViking `0.4.17.1` with `/api/v1/skills`, `/api/v1/skills/find`, and `/api/v1/content/write`.

The plugin APIs were checked against Hermes main commit `d3e2ace1dde9f1d279f99c9ebc6bce2e761b025d` and validated with `hermes plugins doctor` on a local 2026.8.19-derived build. Hermes does not expose one global plugin API version, so run Doctor before enabling on another release.

No additional Python package is required. The OpenViking server should remain in its own environment or container; this plugin communicates over HTTP.

## Installation

Install the plugin once in the active profile, then let its read-only setup plan discover the profiles Hermes currently owns:

```bash
hermes plugins install MKI13/hermes-skill-router --enable
hermes skill-router setup
```

Hermes Git plugins are physically installed and activated per profile. The Router follows that native model: `setup --apply` invokes the official profile-scoped Hermes installer and config commands sequentially, so the user does not repeat them manually for every profile.

Review the dry-run, then apply it:

```bash
hermes skill-router setup --dry-run
hermes skill-router setup --apply
hermes skill-router profiles
```

The initial settings are `deterministic`, `warn`, `shadow`, and OpenViking disabled. Existing Router settings and intentionally disabled installations are preserved. Limit a Canary rollout without embedding any profile names in Router logic:

```bash
hermes skill-router setup --target-profile <profile>
hermes skill-router setup --target-profile <profile> --apply
```

The Router also accepts `--profile` as requested by its CLI. Current Hermes releases pre-parse that spelling as a global selector wherever it appears, so pass the invoking profile first when using the exact alias: `hermes --profile <invoking-profile> skill-router setup --profile <target-profile> --apply`. `--target-profile` avoids that host-CLI ambiguity.

Use `hermes skill-router profiles --sync` after creating, deleting, or renaming profiles. This explicit sync applies missing safe Router setup through official Hermes commands, records only the detected names in the invoking profile's own inventory state, and reports new or removed names. It does not delete profiles, overwrite explicit settings, re-enable disabled installations, or merge profile state.

For a reproducible first installation, Hermes also accepts the release's full commit:

```bash
hermes plugins install MKI13/hermes-skill-router \
  --ref <40-character-release-commit> \
  --enable
```

Every profile keeps its own plugin config, visible skill catalog, readiness, audit, and learning state. A setup failure in one profile is reported without rolling back successful profiles.

## Configure the planner model

Run:

```bash
hermes model
```

Open **Auxiliary models** and configure **Skill Router planner**. To use the same local model infrastructure as OpenViking, point this Hermes auxiliary task at that same local provider/endpoint.

OpenViking's own embedding model, VLM, and optional query planner are internal OpenViking components. Hermes does not automatically inherit them, and OpenViking does not expose its configured VLM as a generic completion endpoint. The router therefore uses:

- OpenViking for skill indexing, semantic retrieval, and plan storage;
- Hermes `ctx.llm` via `auxiliary.skill_router_planner` for plan generation and final skill selection.

## OpenViking setup

Start and verify OpenViking separately:

```bash
openviking-server init
openviking-server doctor
openviking-server
```

Hermes' built-in OpenViking memory provider can be configured independently:

```bash
hermes memory setup openviking
hermes memory status
```

The memory provider stores/recalls conversation memory, but it does **not** automatically ingest Hermes skills or route tasks to skills. This plugin adds that missing workflow.

Connection resolution:

1. `plugins.entries.skill-router.settings.openviking_url`
2. `OPENVIKING_URL`
3. `OPENVIKING_ENDPOINT`
4. `http://127.0.0.1:1933`

Optional authentication and identity are read from the standard environment variables:

- `OPENVIKING_API_KEY`
- `OPENVIKING_ACCOUNT`
- `OPENVIKING_USER`

OpenViking failures are fail-open: Hermes continues with its local plan and deterministic fallback.

## Commands

Inside a session:

```text
/skill-router status
/skill-router refresh
/skill-router plan
/skill-router inspect github
/skill-router audit
/skill-router audit last
/skill-router quality
/skill-router quality last
/skill-router learning
/skill-router learning github
/skill-router learning last
/skill-router learning rebuild
/skill-router learning reset
/skill-router enforcement
/skill-router recommend research current inference providers
```

From the terminal:

```bash
hermes skill-router setup
hermes skill-router setup --apply
hermes skill-router setup --target-profile <profile> --apply
hermes skill-router profiles
hermes skill-router profiles --sync
hermes skill-router status
hermes skill-router refresh --wait
hermes skill-router plan
hermes skill-router inspect github
hermes skill-router audit
hermes skill-router audit last
hermes skill-router quality
hermes skill-router quality last
hermes skill-router learning
hermes skill-router learning github
hermes skill-router learning last
hermes skill-router learning rebuild
hermes skill-router learning reset
hermes skill-router enforcement
hermes skill-router recommend research current inference providers
```

## Readiness declarations

A skill can declare passive requirements in its `SKILL.md` frontmatter:

```yaml
requirements:
  commands: [git, gh]
  python_modules: [requests]
  skills: [github]
  config: [GITHUB_TOKEN]
```

Hermes' legacy `prerequisites.commands` and `prerequisites.env_vars` fields are also recognized. A skill with no declaration remains `unknown`; it is never assumed ready. Missing commands, modules, or skills produce `dependency_missing`. Missing declared configuration or `setup_required: true` produces `setup_required`. The router reports names and availability only and never prints configured values, installs dependencies, logs in, or changes configuration.

Use `/skill-router inspect <skill-name>` to view the cached evidence. Readiness is recalculated with catalog refreshes rather than on every turn.

## Deterministic routing policy

`skill_router_plugin/policy.py` validates model and deterministic selections without performing semantic reranking. It ignores unknown model fields, keeps at most one primary role, promotes the first valid supporting-only selection, removes automatic broken or disabled selections, and retains setup-required or dependency-missing skills only under the documented explicit/fallback rules. An explicitly requested broken or disabled skill produces `policy=blocked` and no executable recommendation; Hermes itself continues normally.

Declared `requirements.skills` are expanded transitively and loaded before their dependent while the dependent keeps its primary role. Final dependency selections carry bounded `required_by_dependency` and `required_for` metadata so execution quality can verify declared edges without semantic inference. Required dependencies displace optional supporting skills when the configured limit is reached. Missing or unusable dependencies block the affected primary, dependency cycles produce a degraded deterministic order and warning, and declared alternatives are resolved by explicit request, readiness, then original selection position. Policy statuses are `valid`, `adjusted`, `degraded`, and `blocked`.

Deterministic routing requires a relevance score of at least `deterministic_min_score` (default `20`) for an implicit primary. This default separates the anonymized 76-skill production score aggregate's no-skill ceiling (`17`) from its intended-skill floor (`24`); the privacy-safe aggregate is committed in `tests/fixtures/production_score_calibration.json`. Readiness affects ordering and policy but cannot create relevance by itself. A boundary-matched explicit skill request bypasses the score threshold but remains subject to readiness and policy; locally negated or quoted names are not treated as explicit requests. At most `max_optional_supporting_skills` (default `1`) non-explicit supporting skill is retained; it needs a separate multi-skill intent, a score of at least `deterministic_supporting_min_score` (default `24`), and either a declared `works_with` relationship or two matching name terms within 12 points of the primary. Declared dependencies do not consume this optional-supporting allowance. `avoid_when` matches subtract 12 points. OpenViking evidence of at least `0.9` remains sufficient for a primary. `/skill-router recommend <task>` reports the top candidate, its relevance score, and the required score when no skill matches.

## Controlled skill execution

`skill_router_plugin/enforcement.py` tracks only the final policy plan for the current Hermes turn. The default `warn` mode allows every tool but records a premature task-tool attempt. `primary` requires the dependency-ordered plan through the primary skill, while `all` requires every executable final selection in policy order. `off` disables checks without disabling audit. Only successful `skill_view` calls satisfy the guard; `skill_view`, `skills_list`, and additional non-required skill loads remain allowed.

Hard modes use Hermes' public `pre_tool_call` block directive. Calls from one Hermes API request share one budget slot, so parallel tool calls cannot bypass the guard. After the configured block limit the turn becomes `exhausted` and fails open, preventing a permanent loop. Missing turn or API-request identity, unavailable hooks, and guard exceptions caught by the plugin also fail open. A blocked policy plan is never enforced. `/skill-router enforcement` reports capability, configured mode and limit, and compact current-turn state without changing configuration.

## Routing execution audit

Each routed turn records a task hash, opaque Hermes task/turn/session identifiers, routing method, policy status, final validated recommendation names and roles, successful or failed `skill_view` observations, result, and whether the primary skill loaded. It also stores enforcement mode/status, block count, and whether the primary loaded before the first allowed task tool. Results are `complete`, `partial`, `missed`, `not_applicable`, or `unknown`. A turn remains `unknown` when Hermes cannot expose both required observer hooks or when finalization is interrupted.

`/skill-router audit` summarizes the latest 20 entries, `/skill-router audit last` shows the latest recommendation and load result, and `/skill-router audit N` summarizes the latest `N` entries. The history is profile-local and bounded. Only a SHA-256 task hash is retained; prompts, task previews, responses, skill contents, tool results, errors, files, and credentials are never stored.

## Routing quality evaluation

`skill_router_plugin/quality.py` assigns each finalized audit a deterministic `quality_version: 1` record with a score from 0.0 to 1.0, grade, confidence, technical signals, and explicit penalties. It evaluates whether the routing process completed cleanly: policy status, successful required loads, dependency order, guard behavior, load errors, and whether the primary loaded before task tools. It does not evaluate whether Hermes' final domain answer was correct.

Scoring starts at 1.0 and applies centralized penalties. Adjusted or degraded policy, partial or missed audit results, missing primary/dependency/supporting loads, `skill_view` errors, warnings, blocks, exhaustion, late primary loading, and dependency-order violations reduce the score. A safely blocked policy is assessable safety behavior rather than an automatic failure. A no-recommendation `not_applicable` turn, unfinished audit, or unavailable observer is unassessable with unknown score, grade, and confidence.

Grades are `excellent` at 0.90, `good` at 0.75, `acceptable` at 0.55, `poor` at 0.30, and `failed` below 0.30. Confidence is high when finalized observer data, complete Hermes identities, load results, task-tool timing, and dependency ordering are available; missing technical evidence lowers it to medium or low. Model and deterministic routing use identical rules. `/skill-router quality`, `/skill-router quality N`, and `/skill-router quality last` expose aggregate and latest technical results. Quality remains passive: it never changes ranking, policy, readiness, enforcement, OpenViking scores, or skill metadata.

## Shadow learning

`skill_router_plugin/learning.py` deterministically rebuilds `learning_version: 1` aggregates from the bounded profile audit at `router.learning`. Only assessable current-version quality records captured in `shadow` mode with high or medium confidence are usable. High confidence has weight 1.0; medium has weight 0.35; low, unknown, incompatible, and unassessable records are ignored. A gentle `0.985` recency decay favors newer bounded observations without deleting older evidence.

Evidence is assigned only to the recommended skill it describes: successful or missing load, that skill's load error, timely primary loading, and the declared dependency edge order. Turn-level quality and completion are not copied into a skill score. Primary, supporting, and dependency observations remain separate. Shadow primary bias uses primary-role evidence only, requires at least `learning_min_samples` raw samples plus 50% effective weighted evidence, and applies conservative shrinkage around a neutral technical score. The result is clamped to `-0.20` through `+0.20`.

The real planner and policy receive exactly the existing unmodified selection. Shadow comparison considers only non-dependency selections with the actual primary's readiness class; broken, disabled, dependency-missing, and differently ready candidates cannot be promoted. Any explicit skill request suppresses shadow reordering. The comparison stores only actual primary, shadow primary, mode, and changed flag in the bounded audit; it is never injected, enforced, audited as an actual recommendation, sent to OpenViking, or used as routing feedback.

`/skill-router learning` reads the current aggregate, `/skill-router learning <skill>` shows role counts and technical rates, and `/skill-router learning last` shows the latest actual-versus-shadow comparison. `learning rebuild` regenerates state from retained audit/quality history. `learning reset` clears only `router.learning`; it preserves audit, quality, plan, and OpenViking data, so a later explicit or routing-triggered rebuild can restore the derived aggregates. `learning_mode: off` records no usable learning observations and performs no shadow reordering. No `active` mode exists.

## Configuration

Settings live under the active profile:

```yaml
plugins:
  enabled: [skill-router]
  entries:
    skill-router:
      settings:
        routing_mode: deterministic     # deterministic | model
        deep_refresh_on_start: true
        rescan_interval_seconds: 60
        max_skills_per_task: 4
        deterministic_min_score: 20
        deterministic_supporting_min_score: 24
        max_optional_supporting_skills: 1
        max_audit_entries: 100          # clamped to 10-1000
        learning_mode: shadow           # off | shadow; no active mode
        learning_min_samples: 5         # clamped to 3-100 and audit limit
        enforcement_mode: warn          # off | warn | primary | all
        max_enforcement_blocks_per_turn: 2  # clamped to 1-5
        max_skill_chars: 20000
        analysis_batch_size: 6
        analysis_model_timeout_seconds: 25
        routing_catalog_chars: 60000
        routing_model_timeout_seconds: 20
        openviking_enabled: false
        openviking_url: http://127.0.0.1:1933
        openviking_timeout_seconds: 10
        openviking_retrieval_limit: 12
        openviking_routing_timeout_seconds: 3
        openviking_score_threshold: 0.15
        openviking_plan_uri: "viking://~/resources/hermes-skill-router/{profile}/plan.md"
```

## Security and trust

- The plugin never injects copied OpenViking `SKILL.md` content as executable instructions. OpenViking returns ranking evidence; Hermes loads winners through native `skill_view`.
- Execution observers discard prompt, response, task-tool arguments, tool-result, and error payloads at the compatibility boundary. The audit persists only identifiers, task hashes, skill names, roles, order, timestamps, routing/policy/enforcement statuses, bounded block counts, and outcomes.
- A policy failure discards the unvalidated selection and returns a degraded empty plan; it never falls back to raw model output.
- Quality evaluation reads only sanitized bounded audit metadata and makes no model call. It has no path back into routing or ranking.
- Shadow learning stores only bounded technical aggregates by skill and role. It copies no task hash, prompt, response, tool argument/result, error text, file, credential, or skill content, and it cannot modify routing metadata or OpenViking.
- Catalog documents are explicitly labeled untrusted data in auxiliary-model analysis prompts.
- OpenViking mirror names include the Hermes profile and a stable digest. Mirrors removed from the effective Hermes catalog are deleted only when their names were previously recorded as router-owned.
- The HTTP bridge rejects URL userinfo, paths, query strings, redirects, proxies, metadata/link-local targets, and oversized responses. Credentialed non-loopback endpoints require HTTPS.
- The plugin runs as trusted in-process Python, like every native Hermes plugin. Review the code before enabling it.
- OpenViking mirrors may contain sensitive skill procedures. Use an OpenViking account/server with appropriate access controls.

## Current Hermes API limitations

Hermes currently has no documented public API that simultaneously provides exact raw `SKILL.md`, all discovery sources, provenance, and forced cache invalidation.

All version-dependent Hermes imports and path lookup calls are isolated in `skill_router_plugin/compat/hermes.py` and detected by capability rather than version number. This plugin uses public `skills_list` as the visibility allowlist, then the compatibility layer uses the ordered and quarantined Hermes iterators to read approved files directly. It never invokes `skill_view` during inventory, so scans cannot run skill setup or alter usage telemetry. If a required internal API is unavailable or incompatible, routing safely falls back to catalog metadata only.

`/skill-router status` reports `full` or `degraded` compatibility plus raw-reader, plugin-lookup, lifecycle-hook, auxiliary-task, execution-audit, and execution-guard availability. Audit requires the public `post_tool_call` and `post_llm_call` hooks. Hard enforcement additionally requires `pre_tool_call`; if its registration fails, the guard reports unavailable and fails open without affecting routing or audit.

Additional limitations:

- `on_skill_lifecycle` has no `deleted` or `uninstalled` action. Fingerprint scans catch removals later.
- Hermes' flat skill catalog may cache in-place edits for roughly 30 seconds.
- An existing/resumed session's system prompt is immutable for prompt-cache safety. Dynamic recommendations still arrive through `pre_llm_call` each turn.
- Hermes bounds `pre_llm_call` callbacks to 30 seconds by default. Router retrieval and model timeouts are capped below that budget; a timeout fails open and Hermes proceeds without router context for that turn.
- A third-party plugin cannot auto-enable itself; installation requires explicit consent.

## Development

```bash
python -m pytest -q
python scripts/benchmark-routing-quality.py
python -m compileall -q .
hermes plugins doctor . --ci
```

`hermes plugins doctor` imports trusted plugin code; run it only after reviewing the checkout.

## License

MIT. See [LICENSE](LICENSE).
