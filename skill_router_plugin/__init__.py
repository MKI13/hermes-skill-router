"""Implementation package for Hermes Skill Router."""

from __future__ import annotations

from .inspection import render_skill_inspection


def _install_readiness_inspection() -> None:
    """Attach the v0.9 inspection renderer without changing routing behavior."""
    from .runtime import SkillRouterRuntime

    def inspect_text(self: SkillRouterRuntime, skill_name: str) -> str:
        return render_skill_inspection(self._snapshot(), skill_name)

    SkillRouterRuntime.inspect_text = inspect_text


_install_readiness_inspection()
