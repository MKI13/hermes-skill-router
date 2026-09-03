"""Hermes Skill Router plugin registration."""

from __future__ import annotations

from pathlib import Path

try:
    from .skill_router_plugin.compat import HermesCompatibility
    from .skill_router_plugin.profiles import ProfileSetupCoordinator
    from .skill_router_plugin.runtime import SkillRouterRuntime
except ImportError:
    from skill_router_plugin.compat import HermesCompatibility
    from skill_router_plugin.profiles import ProfileSetupCoordinator
    from skill_router_plugin.runtime import SkillRouterRuntime


def register(ctx) -> None:
    """Register the profile-scoped router, hooks, command, and bundled skill."""
    compatibility = HermesCompatibility(ctx)
    runtime = SkillRouterRuntime(ctx, compatibility)
    profile_setup = ProfileSetupCoordinator(ctx, compatibility)
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
        "Inspect the active profile's routing plan, readiness, and execution audit.",
    )
    ctx.register_system_prompt_section(
        "skill-router.rules",
        runtime.system_prompt_section,
        position="after_memory",
        max_chars=2000,
    )
    ctx.register_hook("on_session_start", runtime.on_session_start)
    compatibility.register_skill_lifecycle(runtime.on_skill_lifecycle)
    compatibility.register_skill_execution_guard(runtime.on_pre_tool_call)
    compatibility.register_skill_execution_audit(
        runtime.on_post_tool_call,
        runtime.on_post_llm_call,
    )
    ctx.register_hook("pre_llm_call", runtime.pre_llm_call)
    ctx.register_command(
        name="skill-router",
        handler=runtime.command,
        description="Inspect events, audit, refresh, or test the profile skill routing plan.",
        args_hint=(
            "[status|events [N]|refresh|plan|inspect <skill>|audit [last|N]|quality [last|N]|learning [last|reset|rebuild|<skill>]|enforcement|recommend <task>]"
        ),
    )

    def setup_cli(parser) -> None:
        commands = parser.add_subparsers(dest="skill_router_action")
        commands.add_parser("status", help="Show routing-plan status")
        events = commands.add_parser("events", help="Show recent skill catalog changes")
        events.add_argument("limit", nargs="?", type=int, default=20)
        profiles = commands.add_parser("profiles", help="Show discovered Hermes profiles")
        profiles.add_argument("--sync", action="store_true", help="Apply missing safe setup and save the name-only roster")
        setup = commands.add_parser("setup", help="Plan or apply adaptive profile setup")
        setup_mode = setup.add_mutually_exclusive_group()
        setup_mode.add_argument("--apply", action="store_true", help="Apply the displayed setup plan")
        setup_mode.add_argument("--dry-run", action="store_true", help="Explicitly make no changes")
        setup_mode.add_argument("--sync", action="store_true", help="Apply missing safe setup and update the profile roster")
        setup.add_argument("--target-profile", "--profile", action="append", dest="setup_profiles", help="Limit setup to one detected profile")
        refresh = commands.add_parser("refresh", help="Refresh and analyze the skill plan")
        refresh.add_argument("--wait", action="store_true", help="Wait for deep model analysis")
        commands.add_parser("plan", help="Print the compact routing plan")
        inspect = commands.add_parser("inspect", help="Show cached readiness evidence for one skill")
        inspect.add_argument("skill_name")
        audit = commands.add_parser("audit", help="Show recent routing execution audits")
        audit.add_argument("selector", nargs="?", default="")
        quality = commands.add_parser("quality", help="Show technical routing quality")
        quality.add_argument("selector", nargs="?", default="")
        learning = commands.add_parser("learning", help="Show or rebuild shadow learning")
        learning.add_argument("selector", nargs="?", default="")
        commands.add_parser("enforcement", help="Show current execution guard state")
        recommend = commands.add_parser("recommend", help="Select skills for a sample task")
        recommend.add_argument("task", nargs="+")

    def handle_cli(args) -> int:
        action = getattr(args, "skill_router_action", None)
        if action == "status":
            print(runtime.status_text())
            return 0
        if action == "events":
            print(runtime.command(f"events {getattr(args, 'limit', 20)}"))
            return 0
        if action == "profiles":
            if not compatibility.capabilities.profile_discovery:
                print("Hermes Skill Router Profiles\n\nProfile discovery: degraded")
                return 2
            if getattr(args, "sync", False):
                summary = profile_setup.sync()
                print(summary.render())
                return 1 if summary.failed else 0
            summary = profile_setup.profiles()
            print(summary.render())
            return 1 if summary.error else 0
        if action == "setup":
            if not compatibility.capabilities.profile_discovery:
                print("Hermes Skill Router Setup\n\nProfile discovery: degraded")
                return 2
            if getattr(args, "apply", False) and not compatibility.capabilities.profile_configuration:
                print("Hermes Skill Router Setup\n\nProfile configuration: degraded")
                return 2
            if getattr(args, "sync", False):
                summary = profile_setup.sync()
                print(summary.render())
                return 1 if summary.failed else 0
            summary = profile_setup.setup(
                getattr(args, "setup_profiles", None),
                apply=bool(getattr(args, "apply", False)),
            )
            print(summary.render())
            return 1 if summary.failed else 0
        if action == "plan":
            print(runtime.plan_text())
            return 0
        if action == "inspect":
            print(runtime.command("inspect " + args.skill_name))
            return 0
        if action == "audit":
            selector = getattr(args, "selector", "")
            print(runtime.command("audit" + (" " + selector if selector else "")))
            return 0
        if action == "quality":
            selector = getattr(args, "selector", "")
            print(runtime.command("quality" + (" " + selector if selector else "")))
            return 0
        if action == "learning":
            selector = getattr(args, "selector", "")
            print(runtime.command("learning" + (" " + selector if selector else "")))
            return 0
        if action == "enforcement":
            print(runtime.command("enforcement"))
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
        print("Usage: hermes skill-router {status|events|profiles|setup|refresh|plan|inspect|audit|quality|learning|enforcement|recommend}")
        return 2

    ctx.register_cli_command(
        name="skill-router",
        help="Maintain and inspect the installed-skill routing plan",
        setup_fn=setup_cli,
        handler_fn=handle_cli,
        description="Build a profile-specific plan for selecting Hermes skills.",
    )
    ctx.on_unload(runtime.stop)
