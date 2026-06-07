# src/hermes_workflow/__init__.py
"""hermes-workflow: declarative workflow primitive over Hermes Kanban."""
import pathlib

from hermes_workflow.version import PLUGIN_VERSION
from hermes_workflow import tools, hooks


def register(ctx):
    """Wire every hermes-workflow surface into the Hermes plugin context.

    Tools + CLI + slash are orchestrator-context mutators (they self-refuse inside
    a worker). Both hooks are bound to ``ctx`` via a closure because Hermes' hook
    invoke does NOT pass ctx (post_tool_call fan-out + pre_tool_call completion gate).
    """
    for cmd in tools.COMMANDS:
        ctx.register_tool(name=cmd.name, toolset="workflow", schema=cmd.schema,
                          handler=tools.make_tool_handler(ctx, cmd.fn))

    ctx.register_hook("post_tool_call", lambda **kw: hooks.on_tool_done(ctx=ctx, **kw))
    ctx.register_hook("pre_tool_call", lambda **kw: hooks.on_tool_pre(ctx=ctx, **kw))

    ctx.register_cli_command("workflow", help="manage hermes-workflow runs",
                             setup_fn=tools.cli_setup,
                             handler_fn=lambda args: tools.cli_dispatch(ctx, args))
    ctx.register_command("workflow", lambda raw: tools.slash_dispatch(ctx, raw),
                         description="Manage hermes-workflow runs",
                         args_hint=tools.command_names_hint())

    # Bundled skills are shipped in Phase 4; guard the (currently absent) dir so
    # register stays crash-free until then.
    skills_dir = pathlib.Path(__file__).parent / "skills"
    if skills_dir.is_dir():
        for child in sorted(p for p in skills_dir.iterdir() if (p / "SKILL.md").exists()):
            ctx.register_skill(child.name, child / "SKILL.md")

    getattr(ctx, "log", None) and ctx.log.info("hermes-workflow %s registered", PLUGIN_VERSION)
