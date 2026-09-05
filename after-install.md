# Hermes Skill Router installed

Next:

1. Review the detected profiles:

   ```bash
   hermes skill-router setup
   ```

2. After reviewing the plan, apply the safe profile setup:

   ```bash
   hermes skill-router setup --apply
   ```

3. Verify the active profile with the safe diagnostics:

   ```bash
   hermes skill-router doctor
   ```

4. Before a production rollout, run the read-only active-profile canary:

   ```bash
   hermes skill-router canary
   ```

   For a specific Hermes profile, select it with Hermes' global profile selector, for example:

   ```bash
   hermes --profile ef-sinn-development skill-router canary
   ```

Defaults:

- deterministic routing
- warn enforcement
- shadow learning
- OpenViking disabled

New skills installed later are detected automatically. MCP-based capabilities should be exposed through Hermes skills; installing an MCP alone does not make it a routable skill.
