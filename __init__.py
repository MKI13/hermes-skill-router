"""Hermes Skill Router plugin registration."""

from __future__ import annotations

from pathlib import Path

try:
    from .skill_router_plugin.compat import HermesCompatibility
    from .skill_router_plugin.runtime import SkillRouterRuntime
except ImportError:
    from skill_router_plugin.compat import HermesCompatibility
    from skill_router_plugin.runtime import SkillRouterRuntime


def register(ctx) -> None:
    """Register the profile-scoped router, hooks, command, and bundled skill."""
    compatibility = HermesCompatibility(ctx)
    runtime = SkillRouterRuntime(ctx, compatibility)
    skill_path = Path(__file__).parent / "skills" / "skill-router" / "SKILL.md"

    compatibility.register_auxiliary_task(
        key="skill_router_planner",
        display_name="Skill Router planner",
        description="Analyze installed skills and route each user task.",
        defaults={"provider": "auto", "model": "", "timeout": 120},
    )
    ctx.register_skill(
        "skill-router",
        skill_path,
        "Inspect and operate the active profile's skill routing plan.",
    )
    ctx.register_system_prompt_section(
        "skill-router.rules",
        runtime.system_prompt_section,
        position="after_memory",
        max_chars=2000,
    )
    ctx.register_hook("on_session_start", runtime.on_session_start)
    compatibility.register_skill_lifecycle(runtime.on_skill_lifecycle)
    ctx.register_hook("pre_llm_call", runtime.pre_llm_call)
    ctx.register_command(
        name="skill-router",
        handler=runtime.command,
        description="Inspect, refresh, or test the profile skill routing plan.",
        args_hint="[status|refresh|plan|recommend <task>]",
    )

    def setup_cli(parser) -> None:
        commands = parser.add_subparsers(dest="skill_router_action")
        commands.add_parser("status", help="Show routing-plan status")
        refresh = commands.add_parser("refresh", help="Refresh and analyze the skill plan")
        refresh.add_argument("--wait", action="store_true", help="Wait for deep model analysis")
        commands.add_parser("plan", help="Print the compact routing plan")
        recommend = commands.add_parser("recommend", help="Select skills for a sample task")
        recommend.add_argument("task", nargs="+")

    def handle_cli(args) -> int:
        action = getattr(args, "skill_router_action", None)
        if action == "status":
            print(runtime.status_text())
            return 0
        if action == "plan":
            print(runtime.plan_text())
            return 0
        if action == "recommend":
            print(runtime.command("recommend " + " ".join(args.task)))
            return 0
        if action == "refresh":
            if getattr(args, "wait", False):
                print(runtime.deep_refresh("manual-cli"))
            else:
                print(runtime.command("refresh"))
            return 0
        print("Usage: hermes skill-router {status|refresh|plan|recommend}")
        return 2

    ctx.register_cli_command(
        name="skill-router",
        help="Maintain and inspect the installed-skill routing plan",
        setup_fn=setup_cli,
        handler_fn=handle_cli,
        description="Build a profile-specific plan for selecting Hermes skills.",
    )
    ctx.on_unload(runtime.stop)
