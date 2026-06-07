# src/hermes_workflow/cli.py
"""Registration surfaces: the single COMMANDS descriptor table + CLI/slash dispatch.

``COMMANDS`` is the single source of truth for the workflow command set. One
frozen ``Command`` per tool drives tool registration (``__init__.py``), the
``hermes workflow <cmd>`` subparser, and ``/workflow`` slash dispatch — all
*derived* from this one table, so adding a tool is one descriptor entry plus its
schema in :mod:`hermes_workflow.schemas` (see AGENTS.md "Adding a tool or hook").
"""
import argparse
import json
import pathlib
import shlex
from collections.abc import Callable
from dataclasses import dataclass

from hermes_workflow.schemas import (
    WORKFLOW_ABANDON_SCHEMA,
    WORKFLOW_APPROVE_SCHEMA,
    WORKFLOW_RECONCILE_SCHEMA,
    WORKFLOW_START_SCHEMA,
    WORKFLOW_STATUS_SCHEMA,
    WORKFLOW_VALIDATE_SCHEMA,
)
from hermes_workflow.tools import (
    workflow_abandon,
    workflow_approve,
    workflow_reconcile,
    workflow_start,
    workflow_status,
    workflow_validate,
)


@dataclass(frozen=True)
class Command:
    """One workflow command — the single source for every surface it appears on.

    A descriptor drives tool registration (``name``/``schema``/``fn``), the
    ``hermes workflow <cmd>`` subparser (``positional`` + ``cli_args``), and
    CLI/slash dispatch (``bind`` maps a parsed argparse namespace to ``fn``'s
    keyword args — the one place ``--template`` is read off disk and
    ``--params``/``--bindings`` JSON is decoded). Add a tool by adding ONE entry
    to ``COMMANDS``; nothing else enumerates the command set.

    ``name`` is the tool name (``workflow_start``); the runtime CLI/slash
    subcommand is the same name without the ``workflow_`` prefix (``start``,
    per the CONTEXT.md naming taxonomy).
    """
    name: str
    fn: Callable
    schema: dict
    bind: Callable                 # (argparse.Namespace) -> kwargs dict for fn
    positional: tuple = ()         # positional argparse arg names, e.g. ("root_id",)
    cli_args: tuple = ()           # ((flag, argparse_kwargs), ...) optional flags

    @property
    def cli_name(self) -> str:
        return self.name.removeprefix("workflow_")


COMMANDS = (
    Command(
        "workflow_start", workflow_start, WORKFLOW_START_SCHEMA,
        bind=lambda ns: {
            "template_text": _read_template(ns.template),
            "params": json.loads(ns.params),
            "bindings": json.loads(ns.bindings),
            "board": ns.board,
        },
        cli_args=(("--template", {"required": True}), ("--params", {"default": "{}"}),
                  ("--bindings", {"required": True}), ("--board", {})),
    ),
    Command(
        "workflow_status", workflow_status, WORKFLOW_STATUS_SCHEMA,
        bind=lambda ns: {"root_id": ns.root_id, "board": ns.board},
        positional=("root_id",), cli_args=(("--board", {}),),
    ),
    Command(
        "workflow_validate", workflow_validate, WORKFLOW_VALIDATE_SCHEMA,
        bind=lambda ns: {"template_text": _read_template(ns.template)},
        cli_args=(("--template", {"required": True}),),
    ),
    Command(
        "workflow_reconcile", workflow_reconcile, WORKFLOW_RECONCILE_SCHEMA,
        bind=lambda ns: {"root_id": ns.root_id, "board": ns.board},
        positional=("root_id",), cli_args=(("--board", {}),),
    ),
    Command(
        "workflow_approve", workflow_approve, WORKFLOW_APPROVE_SCHEMA,
        bind=lambda ns: {"gate_card": ns.gate_card, "board": ns.board},
        positional=("gate_card",), cli_args=(("--board", {}),),
    ),
    Command(
        "workflow_abandon", workflow_abandon, WORKFLOW_ABANDON_SCHEMA,
        bind=lambda ns: {"root_id": ns.root_id, "board": ns.board},
        positional=("root_id",), cli_args=(("--board", {}),),
    ),
)


def make_tool_handler(ctx, fn):
    """Adapt a keyword workflow function to the registry's handler contract.

    The registry calls handler(args: dict, **kwargs) and expects a JSON string
    that never raises. We unpack args as keywords into fn(ctx, **args), serialize
    its dict result, and convert any exception into a {"error": ...} envelope.
    """
    def handler(args, **kwargs):
        try:
            return json.dumps(fn(ctx, **(args or {})))
        except Exception as e:
            return json.dumps({"error": f"{fn.__name__} failed: {e}"})
    return handler


def cli_setup(parser):
    """Add `hermes workflow <subcommand>` sub-subparsers (also reused by the slash parser).

    Every subparser is built from a ``COMMANDS`` descriptor — there is no second,
    hand-maintained argparse command list, so adding a tool needs only a descriptor.
    """
    sub = parser.add_subparsers(dest="wf_cmd", required=True)
    for cmd in COMMANDS:
        p = sub.add_parser(cmd.cli_name)
        for name in cmd.positional:
            p.add_argument(name)
        for flag, kwargs in cmd.cli_args:
            p.add_argument(flag, **kwargs)


def _read_template(path):
    # utf-8-sig transparently strips a BOM (Windows/WSL2 GUI editors) and reads
    # plain UTF-8 unchanged. Templates are the only on-disk read (CLI path).
    return pathlib.Path(path).read_text(encoding="utf-8-sig")


_COMMANDS_BY_CLI = {cmd.cli_name: cmd for cmd in COMMANDS}


def command_names_hint() -> str:
    """`<start|status|...>` usage hint derived from COMMANDS (no second list)."""
    return "<" + "|".join(cmd.cli_name for cmd in COMMANDS) + ">"


def _dispatch_ns(ctx, ns):
    """Run a parsed `workflow ...` namespace; returns the tool's dict result.

    Table lookup over ``COMMANDS`` (replacing the old per-command if/elif chain):
    the descriptor's ``bind`` maps the namespace to the tool's keyword args.
    """
    cmd = _COMMANDS_BY_CLI.get(getattr(ns, "wf_cmd", None))
    if cmd is None:
        return {"error": f"unknown workflow subcommand: {getattr(ns, 'wf_cmd', None)!r}"}
    return cmd.fn(ctx, **cmd.bind(ns))


def cli_dispatch(ctx, args):
    """`hermes workflow ...` terminal handler (args already parsed by Hermes)."""
    try:
        result = _dispatch_ns(ctx, args)
    except Exception as e:
        result = {"error": f"workflow {getattr(args, 'wf_cmd', '?')} failed: {e}"}
    print(json.dumps(result, indent=2))
    return result


def slash_dispatch(ctx, raw_args):
    """`/workflow ...` in-session slash handler. Returns a JSON string (or usage)."""
    parser = argparse.ArgumentParser(prog="workflow", add_help=False)
    cli_setup(parser)
    try:
        ns = parser.parse_args(shlex.split(raw_args or ""))
    except SystemExit:
        return f"usage: /workflow {command_names_hint()} [args]"
    # The interactive slash surface honors the plugin's flat {"error": ...} contract:
    # a missing --template path or malformed --params/--bindings JSON becomes a clean
    # error rather than a raw exception bubbling into the session.
    try:
        result = _dispatch_ns(ctx, ns)
    except Exception as e:
        result = {"error": f"workflow {ns.wf_cmd} failed: {e}"}
    return json.dumps(result, indent=2)
