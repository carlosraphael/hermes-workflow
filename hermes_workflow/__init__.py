# hermes_workflow/__init__.py
"""hermes-workflow: declarative workflow primitive over Hermes Kanban."""
from hermes_workflow.version import PLUGIN_VERSION


def register(ctx):
    """Called once at startup. Wiring is added by later tasks."""
    # Tools, CLI, slash, hooks, and skills are registered in later tasks.
    # Keeping register importable + crash-free is the smoke-test target.
    ctx.log.info("hermes-workflow %s loaded", PLUGIN_VERSION) if hasattr(ctx, "log") else None
