# Hermes Skill Router

An always-on, profile-scoped skill planner for [Hermes Agent](https://github.com/NousResearch/hermes-agent) with optional [OpenViking](https://github.com/volcengine/OpenViking) indexing and retrieval.

The plugin inventories the effective skills of each Hermes profile, reads their `SKILL.md` instructions, creates a routing plan with a configurable Hermes auxiliary model, mirrors the catalog and plan into OpenViking, and recommends ordered skills before every user turn. Hermes still loads the selected procedures through its native `skill_view` security and readiness path.

> Status: early community release (`0.1.0`). Test it with your Hermes and OpenViking versions before unattended use.

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
6. **OpenViking:** profile-scoped mirror names are added/updated through `/api/v1/skills`; the generated plan is written to `viking://~/resources/hermes-skill-router/{profile}/plan.md` by default.
7. **Every task:** OpenViking `/api/v1/skills/find` supplies retrieval scores. The auxiliary model selects zero to five exact Hermes skill names and an execution order. Deterministic matching is the fallback.
8. **Policy gate:** deterministic validation applies catalog readiness, explicit user requests, alternatives, declared skill dependencies, role normalization, dependency-first ordering, and the configured skill limit. Model output never bypasses this gate.
9. **Execution:** a dynamic `[Skill Router]` block tells Hermes to call native `skill_view` for each validated skill before doing the task.
10. **Execution audit:** public `post_tool_call` and `post_llm_call` observers correlate successful `skill_view` calls with the validated routing decision. The audit is passive and never blocks, retries, or changes ranking.
11. **Updates:** `created`, `installed`, `patched`, `edited`, `archived`, `stale`, and `restored` lifecycle events queue an incremental refresh plus a cache-settled pass after Hermes' 30-second content-cache window. Periodic catalog fingerprint checks catch additional changes.

Each Hermes profile stores an independent plan and bounded audit history through `ctx.state`; profiles never inherit another profile's routing decisions or audit data.

## Requirements

- Hermes Agent with native plugin hooks, `ctx.llm`, plugin auxiliary tasks, system-prompt sections, and `on_skill_lifecycle` support.
- The Hermes `skills` toolset enabled.
- Python 3.11 or newer (Hermes runtime).
- Optional: OpenViking `0.4.17.1` with `/api/v1/skills`, `/api/v1/skills/find`, and `/api/v1/content/write`.

The plugin APIs were checked against Hermes main commit `d3e2ace1dde9f1d279f99c9ebc6bce2e761b025d` and validated with `hermes plugins doctor` on a local 2026.8.19-derived build. Hermes does not expose one global plugin API version, so run Doctor before enabling on another release.

No additional Python package is required. The OpenViking server should remain in its own environment or container; this plugin communicates over HTTP.

## Installation

Replace `OWNER` with the GitHub owner after publishing:

```bash
hermes plugins install OWNER/hermes-skill-router --enable
hermes skill-router refresh --wait
```

For a reproducible installation, pin a full commit:

```bash
hermes plugins install OWNER/hermes-skill-router \
  --ref 0123456789abcdef0123456789abcdef01234567 \
  --enable
hermes skill-router refresh --wait
```

### Multiple Hermes profiles

Install and build the plan separately for every profile that should use the router:

```bash
hermes --profile coding plugins install OWNER/hermes-skill-router --enable
hermes --profile coding skill-router refresh --wait

hermes --profile research plugins install OWNER/hermes-skill-router --enable
hermes --profile research skill-router refresh --wait
```

This is intentional: different profiles may expose different skills, tools, projects, and configuration.

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
/skill-router recommend research current inference providers
```

From the terminal:

```bash
hermes skill-router status
hermes skill-router refresh --wait
hermes skill-router plan
hermes skill-router inspect github
hermes skill-router audit
hermes skill-router audit last
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

Declared `requirements.skills` are expanded transitively and loaded before their dependent while the dependent keeps its primary role. Required dependencies displace optional supporting skills when the configured limit is reached. Missing or unusable dependencies block the affected primary, dependency cycles produce a degraded deterministic order and warning, and declared alternatives are resolved by explicit request, readiness, then original selection position. Policy statuses are `valid`, `adjusted`, `degraded`, and `blocked`.

## Routing execution audit

Each routed turn records a task hash, opaque Hermes task/turn/session identifiers, routing method, policy status, final validated recommendation names and roles, successful or failed `skill_view` observations, result, and whether the primary skill loaded. Results are `complete`, `partial`, `missed`, `not_applicable`, or `unknown`. A turn remains `unknown` when Hermes cannot expose both required observer hooks or when finalization is interrupted.

`/skill-router audit` summarizes the latest 20 entries, `/skill-router audit last` shows the latest recommendation and load result, and `/skill-router audit N` summarizes the latest `N` entries. The history is profile-local and bounded. Only a SHA-256 task hash is retained; prompts, task previews, responses, skill contents, tool results, errors, files, and credentials are never stored.

## Configuration

Settings live under the active profile:

```yaml
plugins:
  enabled: [skill-router]
  entries:
    skill-router:
      settings:
        routing_mode: model             # model | deterministic
        deep_refresh_on_start: true
        rescan_interval_seconds: 60
        max_skills_per_task: 4
        max_audit_entries: 100          # clamped to 10-1000
        max_skill_chars: 20000
        analysis_batch_size: 6
        analysis_model_timeout_seconds: 25
        routing_catalog_chars: 60000
        routing_model_timeout_seconds: 20
        openviking_enabled: true
        openviking_url: http://127.0.0.1:1933
        openviking_timeout_seconds: 10
        openviking_retrieval_limit: 12
        openviking_routing_timeout_seconds: 3
        openviking_score_threshold: 0.15
        openviking_plan_uri: "viking://~/resources/hermes-skill-router/{profile}/plan.md"
```

## Security and trust

- The plugin never injects copied OpenViking `SKILL.md` content as executable instructions. OpenViking returns ranking evidence; Hermes loads winners through native `skill_view`.
- Execution-audit observers discard prompt, response, tool-result, and error payloads at the compatibility boundary. The audit persists only identifiers, task hashes, skill names, roles, order, timestamps, routing/policy statuses, and outcomes.
- A policy failure discards the unvalidated selection and returns a degraded empty plan; it never falls back to raw model output.
- Catalog documents are explicitly labeled untrusted data in auxiliary-model analysis prompts.
- OpenViking mirror names include the Hermes profile and a stable digest. Mirrors removed from the effective Hermes catalog are deleted only when their names were previously recorded as router-owned.
- The HTTP bridge rejects URL userinfo, paths, query strings, redirects, proxies, metadata/link-local targets, and oversized responses. Credentialed non-loopback endpoints require HTTPS.
- The plugin runs as trusted in-process Python, like every native Hermes plugin. Review the code before enabling it.
- OpenViking mirrors may contain sensitive skill procedures. Use an OpenViking account/server with appropriate access controls.

## Current Hermes API limitations

Hermes currently has no documented public API that simultaneously provides exact raw `SKILL.md`, all discovery sources, provenance, and forced cache invalidation.

All version-dependent Hermes imports and path lookup calls are isolated in `skill_router_plugin/compat/hermes.py` and detected by capability rather than version number. This plugin uses public `skills_list` as the visibility allowlist, then the compatibility layer uses the ordered and quarantined Hermes iterators to read approved files directly. It never invokes `skill_view` during inventory, so scans cannot run skill setup or alter usage telemetry. If a required internal API is unavailable or incompatible, routing safely falls back to catalog metadata only.

`/skill-router status` reports `full` or `degraded` compatibility plus raw-reader, plugin-lookup, lifecycle-hook, auxiliary-task, and skill-execution-audit availability. Audit requires both public `post_tool_call` and `post_llm_call` hooks; missing hooks disable observation without affecting routing.

Additional limitations:

- `on_skill_lifecycle` has no `deleted` or `uninstalled` action. Fingerprint scans catch removals later.
- Hermes' flat skill catalog may cache in-place edits for roughly 30 seconds.
- An existing/resumed session's system prompt is immutable for prompt-cache safety. Dynamic recommendations still arrive through `pre_llm_call` each turn.
- Hermes bounds `pre_llm_call` callbacks to 30 seconds by default. Router retrieval and model timeouts are capped below that budget; a timeout fails open and Hermes proceeds without router context for that turn.
- A third-party plugin cannot auto-enable itself; installation requires explicit consent.

## Development

```bash
python -m pytest -q
python -m compileall -q .
hermes plugins doctor . --ci
```

`hermes plugins doctor` imports trusted plugin code; run it only after reviewing the checkout.

## License

MIT. See [LICENSE](LICENSE).
