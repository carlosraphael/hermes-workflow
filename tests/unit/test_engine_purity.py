"""Meta-test pinning the 'engine purity' invariant.

engine/*.py must import only the standard library, PyYAML (`yaml`), and
intra-package `hermes_workflow.*` modules — never the board, Hermes, or any other
third party. This keeps the engine's dependency floor at PyYAML (the load-bearing
supply-chain guarantee). AST-based so comments/strings can't trip it.
"""
import ast
import pathlib
import sys

import hermes_workflow

_ENGINE = pathlib.Path(hermes_workflow.__file__).resolve().parent / "engine"
_ALLOWED_THIRD_PARTY = {"yaml"}


def _top(name):
    return (name or "").split(".")[0]


def _imported_top_modules(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield _top(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                continue  # relative intra-package import
            yield _top(node.module)


def test_engine_imports_only_stdlib_pyyaml_intrapackage():
    assert _ENGINE.is_dir(), f"engine dir not found: {_ENGINE}"
    offenders = []
    for path in sorted(_ENGINE.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for mod in _imported_top_modules(tree):
            if not mod or mod == "hermes_workflow":
                continue
            if mod in sys.stdlib_module_names or mod in _ALLOWED_THIRD_PARTY:
                continue
            offenders.append(f"{path.name}: imports {mod!r}")
    assert not offenders, (
        "engine/ may import only stdlib + PyYAML + intra-package; found:\n"
        + "\n".join(offenders)
    )
