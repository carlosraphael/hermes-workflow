# tests/unit/test_command_registry.py
"""Single-source command registry (issue #15).

``COMMANDS`` is the one place that enumerates the workflow commands; the CLI
subparsers, the CLI/slash dispatch routing, and the usage hint are all *derived*
from it. These tests assert that derivation as a relationship (not a snapshot),
so adding a command can't half-land — e.g. a subparser with no dispatch route, or
a dispatch route the CLI never exposes.

Pure unit tier: imports ``hermes_workflow`` only (no board, no Hermes).
"""
import argparse

from hermes_workflow import tools


def _subparser_names(parser):
    """Names of the sub-subparsers ``cli_setup`` added to ``parser``."""
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return set(action.choices)
    return set()


def test_tool_name_is_workflow_prefixed_cli_name():
    # The runtime CLI/slash subcommand is the tool name minus the `workflow_`
    # prefix (CONTEXT.md naming taxonomy: tool `workflow_start` -> CLI `start`).
    for cmd in tools.COMMANDS:
        assert cmd.name == f"workflow_{cmd.cli_name}"


def test_cli_subparsers_are_derived_from_commands():
    # cli_setup builds exactly one subparser per COMMANDS entry — no second,
    # hand-maintained argparse command list that could drift.
    parser = argparse.ArgumentParser(prog="workflow", add_help=False)
    tools.cli_setup(parser)

    assert _subparser_names(parser) == {cmd.cli_name for cmd in tools.COMMANDS}


def test_dispatch_routes_exactly_the_commands():
    # Dispatch resolves by subcommand name off the SAME COMMANDS source: the
    # routing table covers every command and nothing else (no if/elif drift).
    assert set(tools._COMMANDS_BY_CLI) == {cmd.cli_name for cmd in tools.COMMANDS}
    for cmd in tools.COMMANDS:
        assert tools._COMMANDS_BY_CLI[cmd.cli_name] is cmd


def test_dispatch_unknown_subcommand_returns_flat_error():
    # An unknown subcommand is refused with the flat-error contract, never a
    # KeyError — the table lookup must guard the miss.
    result = tools._dispatch_ns(object(), argparse.Namespace(wf_cmd="nope"))

    assert isinstance(result, dict)
    assert "error" in result
    assert "nope" in result["error"]


def test_usage_hint_lists_every_command():
    # The `<start|status|...>` hint (CLI args_hint + slash usage) is derived from
    # COMMANDS, so it can't omit a newly added command.
    hint = tools.command_names_hint()

    for cmd in tools.COMMANDS:
        assert cmd.cli_name in hint
