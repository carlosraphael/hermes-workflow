# src/hermes_workflow/schemas.py
"""JSON-schema literals for the six orchestrator-facing workflow tools.

One ``WORKFLOW_*_SCHEMA`` per tool, referenced from the ``COMMANDS`` descriptor
table in :mod:`hermes_workflow.cli`. Board- and engine-free: the tool surface's
wire contract lives here in one place, so adding a tool is a schema dict plus a
single ``Command`` entry.
"""

WORKFLOW_START_SCHEMA = {
    "name": "workflow_start",
    "description": "Validate a workflow template + bindings, pre-flight every bound "
                   "profile, then seed the run (root blackboard + dynamic-free prefix).",
    "parameters": {
        "type": "object",
        "properties": {
            "template_text": {"type": "string", "description": "The workflow template YAML."},
            "params": {"type": "object", "description": "Template parameter values."},
            "bindings": {"type": "object", "description": "Role -> profile bindings."},
            "board": {"type": "string", "description": "Kanban board name (optional)."},
        },
        "required": ["template_text", "params", "bindings"],
    },
}

WORKFLOW_STATUS_SCHEMA = {
    "name": "workflow_status",
    "description": "Read-only run summary: per-stage rollup plus blocked / "
                   "awaiting-approval / review-required cards.",
    "parameters": {
        "type": "object",
        "properties": {
            "root_id": {"type": "string", "description": "The workflow root card id."},
            "board": {"type": "string", "description": "Kanban board name (optional)."},
        },
        "required": ["root_id"],
    },
}

WORKFLOW_VALIDATE_SCHEMA = {
    "name": "workflow_validate",
    "description": "Deterministic template gatekeeper (read-only): parse + validate "
                   "a template and report the first failure.",
    "parameters": {
        "type": "object",
        "properties": {
            "template_text": {"type": "string", "description": "The workflow template YAML."},
        },
        "required": ["template_text"],
    },
}

WORKFLOW_RECONCILE_SCHEMA = {
    "name": "workflow_reconcile",
    "description": "Re-run the engine graph from durable inputs: create-missing, "
                   "re-link to joins, dedup duplicates, and diagnose stalls.",
    "parameters": {
        "type": "object",
        "properties": {
            "root_id": {"type": "string", "description": "The workflow root card id."},
            "board": {"type": "string", "description": "Kanban board name (optional)."},
        },
        "required": ["root_id"],
    },
}

WORKFLOW_APPROVE_SCHEMA = {
    "name": "workflow_approve",
    "description": "Complete a human gate card so its downstream stages promote natively.",
    "parameters": {
        "type": "object",
        "properties": {
            "gate_card": {"type": "string", "description": "The human-gate card id to approve."},
            "board": {"type": "string", "description": "Kanban board name (optional)."},
        },
        "required": ["gate_card"],
    },
}

WORKFLOW_ABANDON_SCHEMA = {
    "name": "workflow_abandon",
    "description": "Hazard-free teardown: reclaim running workers, then archive the "
                   "whole run leaves-first.",
    "parameters": {
        "type": "object",
        "properties": {
            "root_id": {"type": "string", "description": "The workflow root card id."},
            "board": {"type": "string", "description": "Kanban board name (optional)."},
        },
        "required": ["root_id"],
    },
}
