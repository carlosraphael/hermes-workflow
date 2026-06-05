# tests/unit/test_examples_validate.py
import pathlib
import pytest
from hermes_workflow.engine.template import parse_template, validate_template

EX = pathlib.Path(__file__).parents[2] / "examples"
FIXTURE = (pathlib.Path(__file__).parents[2] / "tests" / "integration"
           / "fixtures" / "fanout-smoke.workflow.yaml")


@pytest.mark.parametrize("path", sorted(EX.glob("*.workflow.yaml")), ids=lambda p: p.name)
def test_example_validates(path):
    validate_template(parse_template(path.read_text()))


def test_fanout_fixture_validates():
    validate_template(parse_template(FIXTURE.read_text()))
