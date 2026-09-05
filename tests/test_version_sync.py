from __future__ import annotations

from pathlib import Path
import re
import tomllib

import pytest

from skill_router_plugin import __version__
from skill_router_plugin.production import VERSION as PRODUCTION_VERSION
from skill_router_plugin.version import VERSION

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_and_package_versions_match_project_metadata():
    with (ROOT / "pyproject.toml").open("rb") as handle:
        project_version = tomllib.load(handle)["project"]["version"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", VERSION)
    assert VERSION == __version__ == PRODUCTION_VERSION == project_version


@pytest.mark.parametrize("path", [
    "plugin.yaml", "skills/skill-router/SKILL.md", "skills/codebase-memory/SKILL.md",
])
def test_distributed_manifest_and_skill_versions_match_runtime(path):
    text = (ROOT / path).read_text(encoding="utf-8")
    match = re.search(r"(?m)^version:\s*([^\s]+)\s*$", text)
    assert match is not None
    assert match.group(1).strip("\"'") == VERSION


@pytest.mark.parametrize("path, marker", [
    ("README.md", "unreleased"), ("README.de.md", "unveröffentlicht"),
])
def test_current_documentation_clearly_identifies_unreleased_development(path, marker):
    heading = (ROOT / path).read_text(encoding="utf-8").split("##", 1)[0]
    assert f"v{VERSION}" in heading
    assert marker in heading.casefold()


def test_changelog_current_milestone_is_not_a_published_release_claim():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    first_section = re.search(r"(?m)^## (.+)$", text)
    assert first_section is not None
    assert first_section.group(1) == f"{VERSION} — Unreleased"
