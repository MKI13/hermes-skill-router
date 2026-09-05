# Hermes Skill Router v0.8.0 — Isolated Live-Test Gate

This checklist is the final release gate before PR #2 may be merged and v0.8.0 released.

## Safety boundary

- Test only in the isolated Hermes profile `skillroutertest`.
- Do not modify productive Hermes profiles during this gate.
- Keep `openviking_enabled: false`.
- Keep `enforcement_mode: warn`.
- Keep `learning_mode: shadow`.
- Use the local test model `qwen3.5:4b` for the profile when available.
- Do not merge or publish v0.8.0 if any required routing case below fails.

## 1. Install the exact candidate branch

Install/update the plugin from the v0.8.0 candidate branch only in `skillroutertest`, then verify that the active plugin reports v0.8.0.

Candidate branch:

```text
feat/v0.8.0-routing-readme
```

## 2. Health checks

Run:

```bash
hermes --profile skillroutertest skill-router status
hermes --profile skillroutertest skill-router doctor
hermes --profile skillroutertest skill-router canary
```

Acceptance:

- Router loads without plugin/runtime errors.
- Doctor has no unexpected `BLOCKED` result.
- Canary has no unexpected `BLOCKED` result.
- OpenViking is reported disabled/skipped as configured.
- Profile isolation remains intact.

## 3. Deterministic routing checks

Run these samples with `recommend` and confirm the expected Primary Skill.

### Mail

```bash
hermes --profile skillroutertest skill-router recommend "Schreibe eine freundliche E-Mail an einen Kunden."
hermes --profile skillroutertest skill-router recommend "Antworte auf die Kundenmail."
```

Expected when the mail skill is installed and usable:

```text
PRIMARY: himalaya
```

### Calendar

```bash
hermes --profile skillroutertest skill-router recommend "Erstelle einen Termin im Kalender für morgen."
hermes --profile skillroutertest skill-router recommend "Schedule a calendar appointment tomorrow."
```

Expected when the calendar skill is installed and usable:

```text
PRIMARY: google-calendar
```

### GitHub

```bash
hermes --profile skillroutertest skill-router recommend "Open a GitHub PR."
hermes --profile skillroutertest skill-router recommend "Review a GitHub PR code diff."
```

Expected: the installed GitHub PR/review skill family is selected appropriately; no unrelated mail/calendar skill may appear.

## 4. No-skill / false-positive checks

These inputs must not force Himalaya or Calendar merely because of generic wording:

```bash
hermes --profile skillroutertest skill-router recommend "Hello"
hermes --profile skillroutertest skill-router recommend "Write a short message."
hermes --profile skillroutertest skill-router recommend "Erstelle ein Angebot für den Kunden."
```

Acceptance:

- No mail/calendar false positive.
- `Erstelle ein Angebot für den Kunden.` must not select `himalaya` solely because `Kunde` appears.
- A different genuinely relevant installed skill may be selected if its own metadata clearly matches the task.

## 5. Readiness checks

Verify that automatic routing strongly suppresses unusable candidates:

- `ready`: preferred normally.
- `unknown`: still usable when relevance is strong.
- `setup_required`: strongly down-ranked for automatic selection.
- `dependency_missing`: strongly down-ranked for automatic selection.
- `broken` / `disabled`: must not win automatic routing through lexical noise.

Explicit user requests remain subject to the normal Router policy and existing safety rules.

## 6. Real conversation checks

Use the `skillroutertest` profile interactively with `qwen3.5:4b` and perform at least these turns:

1. Ask for a customer email.
2. Follow with a short referential mail continuation.
3. Switch clearly to a calendar task.
4. Switch clearly to a GitHub/repository task.
5. Send a generic non-skill request.

Acceptance:

- Follow-up continuity works only when appropriate.
- Topic switches do not inherit the previous Primary Skill incorrectly.
- No duplicate/unnecessary Supporting Skill appears.
- No profile state leaks from or into productive profiles.

## Release decision

Only after all required checks pass:

1. mark PR #2 ready for review;
2. merge PR #2 into `main`;
3. verify `main` CI again;
4. create/tag release `v0.8.0`;
5. perform a post-release smoke test before broader rollout.
