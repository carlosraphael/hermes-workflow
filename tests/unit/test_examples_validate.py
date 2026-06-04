# tests/unit/test_examples_validate.py
import pathlib, pytest
from hermes_workflow.engine.template import parse_template, validate_template

EX = pathlib.Path(__file__).parents[2] / "examples"


@pytest.mark.parametrize("name", ["fix-flaky-tests", "build-hermes-plugin"])
def test_example_validates(name):
    validate_template(parse_template((EX / f"{name}.workflow.yaml").read_text()))
