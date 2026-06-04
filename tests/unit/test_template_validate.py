import pytest
from hermes_workflow.engine.template import parse_template, validate_template, TemplateError


def _v(yaml_text):
    validate_template(parse_template(yaml_text))


BASE = """
name: t
version: 0.1.0
params: { repo: { type: string, required: true } }
roles: { a: { lane: profile } }
stages:
  - { id: s1, role: a, title: x, workspace: "dir:${params.repo}" }
"""


def test_valid_template_passes():
    _v(BASE)


def test_unknown_role_rejected():
    y = BASE.replace("role: a", "role: ghost")
    with pytest.raises(TemplateError, match="role"):
        _v(y)


def test_verify_command_rejected_as_0_2_x():
    y = BASE + "    verify: { command: 'pytest', retry: 1 }\n"
    with pytest.raises(TemplateError, match="0.2.x|verify"):
        _v(y)


def test_nested_expand_rejected():
    y = """
name: t
version: 0.1.0
params: {}
roles: { a: { lane: profile } }
stages:
  - { id: s1, role: a, title: x, workspace: "dir:/tmp", expand_out: { key: k, item: {id: string} } }
  - { id: s2, role: a, title: y, needs: [s1], expand: { over: s1.k, as: it },
      workspace: "dir:/tmp", expand_out: { key: k2, item: {id: string} } }
  - { id: s3, role: a, title: z, needs: [s2], expand: { over: s2.k2, as: jt }, workspace: "dir:/tmp" }
"""
    with pytest.raises(TemplateError, match="nested"):
        _v(y)


def test_expand_vars_forbidden_in_workspace():
    y = """
name: t
version: 0.1.0
params: {}
roles: { a: { lane: profile } }
stages:
  - { id: s1, role: a, title: x, workspace: "dir:/tmp", expand_out: { key: k, item: {id: string} } }
  - { id: s2, role: a, title: y, needs: [s1], expand: { over: s1.k, as: it },
      workspace: "worktree:${it.id}" }
"""
    with pytest.raises(TemplateError, match="workspace"):
        _v(y)


def test_cycle_rejected():
    y = """
name: t
version: 0.1.0
params: {}
roles: { a: { lane: profile } }
stages:
  - { id: s1, role: a, title: x, needs: [s2] }
  - { id: s2, role: a, title: y, needs: [s1] }
"""
    with pytest.raises(TemplateError, match="cycle"):
        _v(y)


def test_gate_stage_with_role_rejected():
    y = """
name: t
version: 0.1.0
params: {}
roles: { a: { lane: profile } }
stages:
  - { id: g1, gate: human, role: a }
"""
    with pytest.raises(TemplateError, match="gate"):
        _v(y)


def test_fanout_stage_on_scratch_rejected():
    y = """
name: t
version: 0.1.0
params: {}
roles: { a: { lane: profile } }
stages:
  - { id: s1, role: a, title: x, workspace: "dir:/tmp", expand_out: { key: k, item: {id: string} } }
  - { id: s2, role: a, title: y, needs: [s1], expand: { over: s1.k, as: it }, workspace: "scratch" }
"""
    with pytest.raises(TemplateError, match="scratch"):
        _v(y)


def test_duplicate_stage_id_rejected():
    y = """
name: t
version: 0.1.0
params: {}
roles: { a: { lane: profile } }
stages:
  - { id: s1, role: a, title: x }
  - { id: s1, role: a, title: y }
"""
    with pytest.raises(TemplateError, match="duplicate"):
        _v(y)


def test_unknown_needs_rejected():
    y = """
name: t
version: 0.1.0
params: {}
roles: { a: { lane: profile } }
stages:
  - { id: s1, role: a, title: x, needs: [ghost] }
"""
    with pytest.raises(TemplateError, match="unknown stage|needs"):
        _v(y)
