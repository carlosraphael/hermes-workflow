# tests/integration/test_plugin_loads.py
import importlib


def test_register_is_importable_and_crashfree():
    mod = importlib.import_module("hermes_workflow")
    assert hasattr(mod, "register")

    class FakeCtx:  # minimal stand-in; register must not require more in 0.1.0 skeleton
        class log:
            @staticmethod
            def info(*a, **k): pass

    mod.register(FakeCtx())  # must not raise
