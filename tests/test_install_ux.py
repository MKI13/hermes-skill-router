from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_after_install_guides_review_before_explicit_safe_apply():
    text = (ROOT / "after-install.md").read_text(encoding="utf-8")

    assert "Hermes Skill Router installed" in text
    assert text.index("Review the detected profiles") < text.index("setup --apply")
    assert "deterministic routing" in text
    assert "warn enforcement" in text
    assert "shadow learning" in text
    assert "OpenViking disabled" in text
    assert "detected automatically" in text


def test_after_install_contains_no_profile_paths_or_automatic_mutation():
    text = (ROOT / "after-install.md").read_text(encoding="utf-8")

    assert "~/.hermes/profiles" not in text
    assert "/home/" not in text
    assert "--yes" not in text
    assert "plugins install" not in text
    assert "installing an MCP alone does not make it a routable skill" in text
