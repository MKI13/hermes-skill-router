# Live-routing repair and isolated retest

## Status and scope

This document describes the `fix/live-routing-regressions` candidate on the unreleased 0.11.0 code line. It is not a report of a successful real Hermes/local-model run. Repository fixtures and Actions jobs cannot establish that a model actually emits tool calls. No profile installation, service change, merge, release or rollout is authorized by this guide alone.

The owner-provided live report concerned an older candidate. This repair starts from the current merged baseline, `f36549ca31ca5d876f122f08a36d12ba0df64fe7`, retaining its diagnostic fixes. Do not reinstall an old candidate merely because its CI was green. Record the exact new tested commit and tree.

## Repaired routing contract

### Structured follow-up state

Session continuity consumes the current turn's validated policy selections, not the human-readable `[Skill Router]` output. A Readiness marker such as `readiness-unknown` is never part of the skill identity. Per-turn capture is context-local; session state is profile-scoped, bounded, and read/modified/written under an in-process lock.

Names must match the current usable catalog exactly. Legacy corrupt names are ignored, not guessed by stripping suffixes. A new valid route replaces them through normal operation. Blocked, failed or no-match decisions clear that session's stale workflow context. This is metadata continuity, not proof the prior skill executed. Cross-process transactional storage remains the host's responsibility; an in-process lock is not a distributed lock.

### Exclusion before positive matching

Bounded English/German prefix exclusions and German postfix exclusions are checked. Examples covered by regressions include `Nutze arxiv nicht`, `Verwende den Skill arxiv dafür nicht`, qualified skill names, and `Nutze arxiv nicht und stattdessen pdf`. Contrast clauses and `nicht nur` must not negate an otherwise positive request.

Exclusions are checked again by the final policy, including for model/embedding selections and required-skill expansion. A required skill that the user excludes cannot be quietly reintroduced. These are conservative lexical rules, not a complete natural-language or security classifier; novel phrasing still needs review and regression coverage.

### Diagnosis is not executable routing

`dependency_missing`, `setup_required`, `broken`, `disabled`, or a positive setup-needed flag cannot produce an executable primary or supporting recommendation. This also applies to explicit requests. An explicitly unavailable workflow is blocked and diagnosed rather than silently replaced with a different workflow. `inspect <skill>` remains available for diagnosis without executing it.

For automatic selections, an unusable candidate is removed while a usable already selected candidate may remain, subject to the existing relevance, dependency and alternative policy. `unknown` remains usable unless another safety/readiness constraint disqualifies it. Required dependencies must be usable and metadata-consistent. The Router does not install missing components, re-enable skills, or manufacture a successful fallback event.

Three former permissive unit expectations and the two golden cases `negative_setup_explicit` / `negative_missing_explicit` now require blocking, not executable selection. Cases are retained, not skipped; the fixture schema and case count are unchanged. Historical benchmark totals against the old expectations are therefore not directly comparable.

## Isolated retest procedure

Use only the already prepared, explicitly designated test profile. Discover and verify its current configuration before changes. Do not create a substitute or use a production profile. Preserve its targeted Router installation/state backup, local model selection, and unrelated services.

1. **Pin identity and local-only routes.** Record actual loaded plugin commit, tree, runtime version, Hermes version and local model. Check every auxiliary task including title generation before the first run, not after a failure. Do not allow silent cloud fallback. An error from a remote provider still counts as a prohibited remote attempt for a local-only test. Apply only authorized profile-scoped changes.
2. **Prove native tool calling separately.** With harmless input and a restricted `skills` toolset, verify an actual `skill_view` invocation and observed successful tool completion. A model saying it loaded a skill, or printing function-call-like text, is not execution. When tool calling fails, report that execution-path failure separately from Router selection and stop short of an end-to-end PASS. Do not auto-load skills or fabricate audit events to make the test pass.
3. **Run diagnostics and integration checks.** Run Router Doctor, Canary and rollout preflight with real outputs and exit codes. Check intended Codebase Memory MCP availability and a harmless authorized search separately from passive configuration readiness. Do not start, install or reconfigure shared MCP services merely to eliminate a warning. Validate the configured loopback embedding service; an embedding health request alone does not test hybrid selection. Keep OpenViking disabled.
4. **Exercise the actual runtime.** Test normal and explicit selection, a same-session short follow-up with an `unknown` skill, reload and a different session, topic changes, the exclusion examples above, unusable explicit roots and dependencies, and a genuinely observed automatic ready/unknown confidence fallback. Use harmless fixtures and operations, never customer data or production writes. In a deliberate negative test, a correctly blocked plan is the expected PASS for that individual case, not overall readiness approval.
5. **Verify evidence after reload.** Exact previous skill identity, profile/session separation, final primary and fallback telemetry must match the observed decisions. Confirm the five telemetry fields, no prompt/payload leakage, real execution evidence and truthful unknown/failed records. A clean exit code or green CI is insufficient when no skill was loaded.
6. **Make a commit-specific decision.** The report must distinguish selection, execution, diagnostic readiness, negative tests, and untested integration paths. Unexecuted or required-skipped checks remain pending/BLOCKED, never a global PASS. Before any separately authorized merge, refresh both branch heads and require the candidate to match the tested content. Revalidate changed content. No force update, automatic release, global gateway restart or production-profile rollout.

## Evidence hygiene

Public evidence contains only synthetic examples and bounded technical results: commit/tree IDs, commands without secrets, test identifiers, statuses and exit codes. Do not copy private reports wholesale. Exclude personal filesystem paths, authentication material, configuration values, customer content, prompts and tool payloads from public logs and pull requests.

## Deutsche Kurzfassung

Die Reparatur speichert Folgekontext aus strukturierten Policy-Daten statt aus Anzeigezeilen. Ausschlüsse wie „Nutze arxiv nicht“ gelten auch bei der letzten Policy-Prüfung und für Abhängigkeiten. Fehlende Voraussetzungen werden erklärt, aber nicht durch eine ausdrückliche Skill-Nennung übergangen. `inspect` bleibt nutzbar.

Der Nachtest erfolgt ausschließlich im vorhandenen isolierten Testprofil, mit vollständig lokal gebundenen Haupt- und Hilfsmodellen. Echte Toolaufrufe, Codebase Memory und der tatsächliche Routing-Pfad werden getrennt geprüft. Ein geschriebener Toolaufruf ist kein ausgeführter Toolaufruf. CI-PASS ist keine Live-Freigabe; Merge und produktiver Rollout bleiben getrennte Entscheidungen.
