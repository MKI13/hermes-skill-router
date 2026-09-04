#!/usr/bin/env python3
"""Verify manifest version/config keys/defaults stay synchronized with both READMEs."""

from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugin.yaml"
DOCS = (ROOT / "README.md", ROOT / "README.de.md")
PYPROJECT = ROOT / "pyproject.toml"
SKILL = ROOT / "skills" / "skill-router" / "SKILL.md"
CODEBASE_SKILL = ROOT / "skills" / "codebase-memory" / "SKILL.md"


def _manifest() -> tuple[str, list[tuple[str, str]]]:
    text = PLUGIN.read_text(encoding="utf-8")
    version_match = re.search(r"(?m)^version:\s*([^\s]+)\s*$", text)
    if not version_match:
        raise AssertionError("plugin.yaml version missing")
    version = version_match.group(1).strip('"\'')
    lines = text.splitlines()
    rows: list[tuple[str, str]] = []
    for index, line in enumerate(lines):
        match = re.match(r"^  ([a-z0-9_]+):\s*$", line)
        if not match:
            continue
        key = match.group(1)
        default = None
        for nested in lines[index + 1:index + 9]:
            if re.match(r"^  [a-z0-9_]+:\s*$", nested):
                break
            default_match = re.match(r"^    default:\s*(.*?)\s*$", nested)
            if default_match:
                default = default_match.group(1)
                break
        if default is None:
            raise AssertionError(f"{key}: default missing")
        rows.append((key, default))
    return version, rows


def main() -> int:
    version, rows = _manifest()
    failures: list[str] = []
    for doc in DOCS:
        text = doc.read_text(encoding="utf-8")
        if f"v{version}" not in text and f"**{version}**" not in text:
            failures.append(f"{doc.name}: version {version} not documented")
        for key, default in rows:
            row_re = re.compile(rf"\|\s*`{re.escape(key)}`\s*\|[^\n]*\|\s*`{re.escape(default.strip())}`\s*\|")
            if not row_re.search(text):
                failures.append(f"{doc.name}: missing/default mismatch for {key}={default}")
        for value in ("deterministic | hybrid | embedding | model", "off | warn | primary | all", "off | shadow"):
            if value not in text:
                failures.append(f"{doc.name}: missing allowed-mode declaration: {value}")
    if f'version = "{version}"' not in PYPROJECT.read_text(encoding="utf-8"):
        failures.append("pyproject.toml version mismatch")
    for skill in (SKILL, CODEBASE_SKILL):
        if f"version: {version}" not in skill.read_text(encoding="utf-8"):
            failures.append(f"{skill.relative_to(ROOT)} version mismatch")
    if failures:
        print("Documentation/config synchronization FAILED:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print(f"Documentation/config synchronization PASS: version={version}, keys={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
