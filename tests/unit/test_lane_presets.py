# tests/unit/test_lane_presets.py
from hermes_workflow.lanes.presets import lane_skill, KNOWN_LANES


def test_codex_lane_uses_bundled_skill_name():
    assert lane_skill("codex") == "kanban-codex-lane"   # bundled; NOT re-shipped
    assert "codex" in KNOWN_LANES and "claude-code" not in KNOWN_LANES   # claude-code is 0.2.x
    assert lane_skill("profile") is None
