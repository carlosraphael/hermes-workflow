# tests/integration/test_plugin_loads.py
import importlib


def test_register_is_importable_and_crashfree():
    mod = importlib.import_module("hermes_workflow")
    assert hasattr(mod, "register")

    class FakeCtx:  # no-op recording ctx; register must not raise
        class log:
            @staticmethod
            def info(*a, **k): pass

        def register_tool(self, *a, **k): pass
        def register_hook(self, *a, **k): pass
        def register_cli_command(self, *a, **k): pass
        def register_command(self, *a, **k): pass
        def register_skill(self, *a, **k): pass

    mod.register(FakeCtx())  # must not raise
