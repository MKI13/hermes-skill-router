---
name: codebase-memory
description: Inspect indexed source code, repository structure, architecture, symbols, and dependencies through the configured Codebase Memory MCP server before planning code changes.
version: 0.7.0
author: Hermes Skill Router contributors
license: MIT
requirements:
  mcps:
    - codebase-memory
metadata:
  hermes:
    tags: [code, repository, architecture, dependencies, mcp, codebase-memory]
    category: development
---
# Codebase Memory

Use this skill when Hermes needs grounded technical context from an indexed codebase before explaining, planning, reviewing, or changing code.

## When to Use

Use Codebase Memory for tasks such as:

- locating an implementation, class, function, symbol, configuration, or relevant file;
- understanding repository structure or architecture;
- tracing dependencies, callers, references, or likely change impact;
- gathering context before editing an existing codebase;
- preparing precise repository context for a development agent or harness;
- checking how an existing feature is implemented before proposing a change.

Useful routing concepts include: codebase, repository, source code, architecture, implementation, function, class, symbol, dependency, caller, reference, path, module, refactor, bug location, impact analysis, Quellcode, Repository, Architektur, Implementierung, Funktion, Klasse, Abhängigkeit, Datei, Pfad, Fehlerursache.

## Do Not Use

Do not use this skill for ordinary email writing, customer communication, translation, general web research, calendar work, invoices, offers, image tasks, or conversations that do not require source-code context.

If the user explicitly asks not to use Codebase Memory, do not load this skill.

## Procedure

1. Confirm that the task actually requires repository or source-code context.
2. Use the Codebase Memory MCP tools exposed by the active Hermes profile. Do not assume filesystem paths or bypass Hermes' configured MCP identity.
3. Retrieve only the context needed for the current task: relevant projects, symbols, files, relationships, and architecture evidence.
4. Prefer structural/symbol retrieval before broad text retrieval when that is sufficient.
5. Distinguish retrieved facts from inference. If the indexed data is stale or incomplete, say so and request or trigger the normal repository refresh workflow rather than inventing code facts.
6. When another development skill is primary, use Codebase Memory only as supporting technical context when it materially improves correctness.

## Safety and Boundaries

- This skill never starts, installs, reconfigures, or repairs the MCP server by itself.
- This skill never treats the MCP as a routable skill; Hermes loads this SKILL.md through `skill_view`, then uses the MCP tools as capabilities.
- Never expose MCP credentials, environment variables, private transport details, or hidden profile paths.
- Do not write to a repository merely because code was inspected. Follow the active development/GitHub workflow and the user's approval requirements for changes.
