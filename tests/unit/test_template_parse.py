import pytest
from hermes_workflow.engine.template import parse_template, TemplateError

YAML = """
name: demo
version: 0.1.0
params:
  repo: { type: string, required: true }
roles:
  scout: { lane: profile }
  fixer: { lane: codex }
stages:
  - id: scan
    role: scout
    title: "Scan ${params.repo}"
    body: "find things"
    workspace: "dir:${params.repo}"
    expand_out: { key: items, max: 50, item: { id: string } }
  - id: fix
    role: fixer
    needs: [scan]
    expand: { over: scan.items, as: it }
    title: "Fix ${it.id}"
    workspace: "worktree:${params.repo}"
  - id: approve
    needs: [fix]
    gate: human
"""


def test_parse_basic_template():
    t = parse_template(YAML)
    assert t.name == "demo" and t.version == "0.1.0"
    assert t.params["repo"].required is True
    assert t.roles["fixer"].lane == "codex"
    fix = t.stage("fix")
    assert fix.expand.over_stage == "scan" and fix.expand.over_key == "items" and fix.expand.as_var == "it"
    assert t.stage("scan").expand_out.max == 50
    assert t.stage("approve").gate == "human"


def test_parser_captures_raw_verify_for_later_rejection():
    y = YAML + "    verify: { command: 'pytest', retry: 1 }\n"
    assert parse_template(y).stage("approve").verify_raw == {"command": "pytest", "retry": 1}
    assert parse_template(YAML).stage("scan").verify_raw is None



def test_malformed_yaml_raises_template_error():
    with pytest.raises(TemplateError):
        parse_template("name: t\nstages: [unclosed\n")


def test_expand_over_without_dot_raises_template_error():
    y = """
name: t
version: 0.1.0
stages:
  - { id: s1, role: a, title: x }
  - { id: s2, role: a, needs: [s1], expand: { over: s1, as: it }, title: y }
"""
    with pytest.raises(TemplateError, match="expand.over"):
        parse_template(y)
