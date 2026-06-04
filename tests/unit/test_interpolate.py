import pytest
from hermes_workflow.engine.interpolate import interpolate, InterpolationError


def test_params_only():
    assert interpolate("Scan ${params.repo}", params={"repo": "/r"}, expand_vars={}) == "Scan /r"


def test_expand_var():
    assert interpolate("Fix ${it.id}", params={}, expand_vars={"it": {"id": "x.py"}}) == "Fix x.py"


def test_unknown_reference_raises():
    with pytest.raises(InterpolationError):
        interpolate("${params.missing}", params={}, expand_vars={})


def test_unknown_namespace_raises():
    with pytest.raises(InterpolationError):
        interpolate("${env.HOME}", params={}, expand_vars={})
