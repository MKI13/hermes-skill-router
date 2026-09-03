# Hermes Skill Router

An always-on, profile-scoped skill planner for [Hermes Agent](https://github.com/NousResearch/hermes-agent) with deterministic routing, direct local Ollama embeddings, and optional [OpenViking](https://github.com/volcengine/OpenViking) indexing and retrieval.

The plugin inventories the effective skills of each Hermes profile, preserves Hermes readiness and dependency policy, and recommends ordered skills before every user turn. Hybrid mode embeds only each skill's name and description through a loopback-only Ollama endpoint, caches catalog vectors per profile, and makes no generative LLM routing call. Hermes still loads selected procedures through its native `skill_view` security and readiness path.

> Status: early community release (`0.6.0`). Test it with your Hermes and Ollama versions before unattended use.

## Why this is a plugin plus a skill

A plain `SKILL.md` is loaded on demand. It cannot remain active, observe skill lifecycle events, or inject routing guidance before every request. This repository therefore contains:

- a native Hermes plugin for lifecycle, planning, persistence, OpenViking sync, and per-turn routing;
- a bundled `skill-router:skill-router` operational skill for status, refresh, diagnostics, and routing rules;
- no permanent model tool schema.

## Behavior

1. **Install/enable:** the plugin registers an always-on bounded system-prompt rule, lifecycle hooks, commands, and a `skill_router_planner` auxiliary task.
2. **Initial plan:** the first new session scans the active profile, creates a deterministic base plan, and queues background reconciliation. Model metadata enrichment occurs only in model routing mode. `refresh` remains a diagnostic fallback rather than an installation step.
3. **Catalog:** Hermes `skills_list` supplies the effective visible catalog: trusted project skills, profile-local skills, external directories, and enabled plugin skills, subject to Hermes filtering.
4. **Readiness:** declared command, Python-module, skill, MCP-server, and configuration requirements are checked passively during catalog refresh and cached with the plan. No dependency, MCP connection, or setup action is executed.
5. **Deep analysis:** only `model` mode sends new or changed skill documents to the configured auxiliary model. Hybrid mode makes no generative routing or analysis call.
6. **Hybrid embeddings:** a loopback-only, proxy-free, no-redirect Ollama adapter embeds only skill name plus description. Profile-local vectors are cached by profile scope, catalog hash, content hash, endpoint, model, and dimension.
7. **Every task:** an explicitly requested installed skill takes deterministic priority. Otherwise hybrid mode ranks by cosine similarity, adds Top-2 only when the Top-1 minus Top-2 margin is below the configured `0.02`, and retains at most two optional skills. Endpoint, timeout, malformed-response, or cache failures fail open to the strict deterministic router. OpenViking and auxiliary-model modes remain separately available.
8. **Policy gate:** deterministic validation applies catalog readiness, explicit user requests, alternatives, declared skill dependencies, role normalization, dependency-first ordering, and the configured skill limit. Model output never bypasses this gate.
9. **Execution guard:** the final policy plan initializes a turn-isolated guard. The default warns only; optional hard modes use `pre_tool_call` to require successful ordered `skill_view` loads before task tools.
10. **Execution:** a dynamic `[Skill Router]` block tells Hermes to call native `skill_view` for each validated skill before doing the task.
11. **Execution audit:** public `post_tool_call` and `post_llm_call` observers correlate successful `skill_view` calls and compact guard outcomes with the validated routing decision. The audit itself never blocks, retries, or changes ranking.
12. **Quality evaluation:** each finalized audit receives a versioned deterministic score for technical routing and execution quality.
13. **Shadow learning:** current-version, high-confidence quality history is rebuilt into profile-local skill-role aggregates and conservative diagnostic biases. A separate shadow comparison is recorded, while the real selection remains unchanged.
14. **Updates:** `created`, `installed`, `patched`, `edited`, `archived`, `stale`, and `restored` lifecycle events queue one coalesced incremental refresh plus a cache-settled pass after Hermes' 30-second content-cache window. Interval-gated session-start and pre-turn catalog fingerprint checks catch changes without lifecycle events.

Each Hermes profile stores an independent plan and bounded audit history through `ctx.state`; profiles never inherit another profile's routing decisions or audit data. Every snapshot, audit, learning envelope, and setup roster carries an opaque canonical-home scope token, so state copied by profile cloning or renaming is rejected before catalog use or OpenViking reconciliation. The token does not reveal the profile path.

## Requirements

- Hermes Agent with native plugin hooks including `pre_tool_call`, `post_tool_call`, and `post_llm_call`, plus `ctx.llm`, plugin auxiliary tasks, system-prompt sections, and `on_skill_lifecycle` support. Missing execution hooks degrade safely.
- The Hermes `skills` toolset enabled.
- Python 3.11 or newer (Hermes runtime).
- Optional: OpenViking `0.4.17.1` with `/api/v1/skills`, `/api/v1/skills/find`, and `/api/v1/content/write`.

The lifecycle, profile, and native MCP configuration APIs were checked against Hermes main commit `a399ac2fd13da28630d3a90c255d0be458dded61` and validated with `hermes plugins doctor`. Hermes does not expose one global plugin API version, so run Doctor before enabling on another release.

No additional Python package is required. The OpenViking server should remain in its own environment or container; this plugin communicates over HTTP.

## Quick install

The preferred Hermes-first workflow is to ask Hermes: **“Install the Skill Router from `MKI13/hermes-skill-router`.”** Hermes can then use its normal terminal, plugin-install, approval, and after-install mechanisms. Users do not need to locate or edit profile directories.

The equivalent terminal workflow installs the plugin once in the active profile, then lets its read-only setup plan discover the profiles Hermes currently owns:

```bash
hermes plugins install MKI13/hermes-skill-router --enable
hermes skill-router setup
```

The installer displays `after-install.md`. Review the detected profiles before explicitly applying the setup plan; installation never applies profile changes automatically.

Hermes Git plugins are physically installed and activated per profile. The Router follows that native model: `setup --apply` invokes the official profile-scoped Hermes installer and config commands sequentially, so the user does not repeat them manually for every profile.

Review the dry-run, then apply it:

```bash
hermes skill-router setup --dry-run
hermes skill-router setup --apply
hermes skill-router profiles
```

Use `hermes skill-router profiles --sync` after creating, deleting, or renaming profiles. This explicit sync applies missing safe Router setup through official Hermes commands, records only the detected names in the invoking profile's own inventory state, and reports new or removed names. It does not delete profiles, overwrite explicit settings, re-enable disabled installations, or merge profile state.

For a reproducible first installation, Hermes also accepts the release's full commit:

```bash
hermes plugins install MKI13/hermes-skill-router \
  --ref <40-character-release-commit> \
  --enable
```

Every profile keeps its own plugin config, visible skill catalog, readiness, audit, and learning state. A setup failure in one profile is reported without rolling back successful profiles.

## How profile discovery works

The compatibility layer asks Hermes for its live profile names and inspects each profile through profile-scoped Hermes commands. Setup never scans guessed directory names, copies plugin state, or combines visible skills across profiles. New, removed, and renamed profiles are reflected by the next explicit `profiles --sync`; the stored roster contains only names and an opaque scope token.

## How new skills are discovered

Hermes lifecycle events for created, installed, patched, edited, archived, stale, and restored skills trigger one coalesced background refresh immediately, followed by a cache-settled check after Hermes' content cache window. New and changed skills receive fresh readiness and routing metadata; content analysis runs only when the skill's analysis inputs changed. Successful authoritative scans remove skills that are no longer visible. Because Hermes exposes no delete/uninstall lifecycle event and manual file edits can emit no event, session-start and bounded per-turn fingerprint checks provide the fallback.

Use `/skill-router events [N]` or `hermes skill-router events [N]` to inspect up to 50 profile-local technical change records. They contain only timestamps, event kinds, skill names, outcomes, and readiness—never skill content, prompts, configuration, errors, or credentials. `status` shows only the last skill change and whether a refresh is pending.

## How MCP-backed skills work

The Router still routes only Hermes skills. An MCP server remains a Hermes tool capability and is never scored or selected directly. A routable skill may declare its exact active-profile MCP server identity:

```yaml
---
name: codebase-memory
description: Inspect an indexed codebase and retrieve structural code context.
requirements:
  mcps:
    - codebase-memory
---
```

The identity is the exact key under the active profile's Hermes `mcp_servers` configuration. The compatibility layer reads only server names, a passive enabled flag, and whether the definition has a recognizable transport; it never copies environment variables, headers, tokens, or credentials and never starts, probes, reloads, or calls an MCP server. Missing or disabled servers produce `dependency_missing`; unavailable or structurally ambiguous discovery produces `unknown`. A later profile-local MCP configuration change is reflected on session start or the next catalog/readiness fingerprint check.

**Installing an MCP alone does not make it a routable skill.** Create or install a Hermes Skill that references the MCP and instructs Hermes to use its tools after `skill_view` loads the skill. An MCP present without that skill creates no Router catalog entry. MCP requirements affect readiness, not semantic relevance scoring, and no MCP inventory is shared across profiles.

## Safe defaults

Adaptive setup fills only missing values with deterministic routing, warn enforcement, shadow learning, and OpenViking disabled. It preserves explicit settings and intentionally disabled installations. Setup is a dry-run unless `--apply` or `--sync` is explicit.

## Canary setup

Limit a rollout with a profile name discovered at runtime:

```bash
hermes skill-router setup --target-profile <profile>
hermes skill-router setup --target-profile <profile> --apply
```

Current Hermes releases reserve `--profile` as a global selector wherever it appears. The Router alias therefore requires `hermes --profile <invoking-profile> skill-router setup --profile <target-profile> --apply`; prefer `--target-profile` to avoid ambiguity.

## Configure hybrid routing

Run a dedicated Ollama service bound on the host to a numeric loopback address, then set:

```bash
hermes config set plugins.entries.skill-router.settings.routing_mode hybrid
hermes config set plugins.entries.skill-router.settings.embedding_url http://127.0.0.1:11436
hermes config set plugins.entries.skill-router.settings.embedding_model qwen3-embedding:0.6b
hermes config set plugins.entries.skill-router.settings.embedding_dimensions 1024
hermes config set plugins.entries.skill-router.settings.embedding_keep_alive 5m
hermes config set plugins.entries.skill-router.settings.embedding_ambiguity_margin 0.02
hermes config set plugins.entries.skill-router.settings.max_optional_supporting_skills 2
```

Only numeric loopback HTTP origins are accepted. URL credentials, paths, query strings, fragments, redirects, environment proxies, oversized responses, wrong vector counts/dimensions, and non-finite vectors are rejected. Hybrid failures fall back to deterministic routing without blocking Hermes.

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
/skill-router events 20
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
hermes skill-router events 20
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
  mcps: [codebase-memory]
  config: [GITHUB_TOKEN]
```

Hermes' legacy `prerequisites.commands` and `prerequisites.env_vars` fields are also recognized. A skill with no declaration remains `unknown`; it is never assumed ready. Missing commands, modules, skills, or configured/enabled MCP servers produce `dependency_missing`. An unavailable passive MCP discovery API produces `unknown`. Missing declared configuration or `setup_required: true` produces `setup_required`. The router reports names and availability only and never prints configured values, starts MCP connections, installs dependencies, logs in, or changes configuration.

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
        routing_mode: deterministic     # deterministic | hybrid | embedding | model
        deep_refresh_on_start: true
        rescan_interval_seconds: 60
        max_skills_per_task: 4
        deterministic_min_score: 20
        deterministic_supporting_min_score: 24
        max_optional_supporting_skills: 2
        embedding_url: http://127.0.0.1:11436
        embedding_model: qwen3-embedding:0.6b
        embedding_dimensions: 1024
        embedding_timeout_seconds: 5.0
        embedding_keep_alive: 5m
        embedding_batch_size: 32
        embedding_ambiguity_margin: 0.02
        embedding_min_score: 0.35
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

## Troubleshooting and Hermes API limitations

Hermes currently has no documented public API that simultaneously provides exact raw `SKILL.md`, all discovery sources, provenance, and forced cache invalidation.

All version-dependent Hermes imports and path lookup calls are isolated in `skill_router_plugin/compat/hermes.py` and detected by capability rather than version number. This plugin uses public `skills_list` as the visibility allowlist, then the compatibility layer uses the ordered and quarantined Hermes iterators to read approved files directly. It never invokes `skill_view` during inventory, so scans cannot run skill setup or alter usage telemetry. If a required internal API is unavailable or incompatible, routing safely falls back to catalog metadata only.

`/skill-router status` reports `full` or `degraded` compatibility plus raw-reader, plugin-lookup, lifecycle-hook, native-MCP-config-discovery, auxiliary-task, execution-audit, and execution-guard availability. Start with `status`, then inspect `events` when a skill change is not reflected. `refresh --wait` remains the explicit diagnostic fallback. Audit requires the public `post_tool_call` and `post_llm_call` hooks. Hard enforcement additionally requires `pre_tool_call`; if its registration fails, the guard reports unavailable and fails open without affecting routing or audit.

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
