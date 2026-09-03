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

Defaults:

- deterministic routing
- warn enforcement
- shadow learning
- OpenViking disabled

New skills installed later are detected automatically. MCP-based capabilities should be exposed through Hermes skills; installing an MCP alone does not make it a routable skill.
