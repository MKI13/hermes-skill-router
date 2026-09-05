from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_codebase_memory_skill_declares_mcp_requirement_and_version():
    text = (ROOT / "skills" / "codebase-memory" / "SKILL.md").read_text(encoding="utf-8")
    assert "name: codebase-memory" in text
    assert "version: 0.7.1" in text
    assert "requirements:" in text and "mcps:" in text and "- codebase-memory" in text
    assert "never starts, installs, reconfigures, or repairs the MCP" in text


def test_codebase_memory_skill_is_scoped_to_code_tasks():
    text = (ROOT / "skills" / "codebase-memory" / "SKILL.md").read_text(encoding="utf-8")
    assert "repository structure" in text
    assert "ordinary email writing" in text
    assert "general web research" in text
