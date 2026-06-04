# tests/test_preflight_eval.py
"""Unit tests for the pure preflight decision function ``_evaluate_probe``.

These are pure-logic (no subprocess, no Hermes): they exercise the decision
over a probe-emitted ``info`` dict for both profile and codex lanes.
"""
from hermes_workflow.preflight import _evaluate_probe


def test_enabled_no_error_non_codex_is_ok():
    info = {"enabled": True, "error": None, "codex_bin": False, "lane_skill": False}
    assert _evaluate_probe(info, is_codex=False) == {"ok": True, "error": None}


def test_enabled_but_error_set_is_not_ok():
    info = {"enabled": True, "error": "boom", "codex_bin": True, "lane_skill": True}
    result = _evaluate_probe(info, is_codex=False)
    assert result["ok"] is False
    assert result["error"] == "boom"


def test_not_enabled_is_not_ok():
    info = {"enabled": False, "error": "not enabled in config", "codex_bin": True, "lane_skill": True}
    result = _evaluate_probe(info, is_codex=False)
    assert result["ok"] is False
    assert result["error"]


def test_codex_missing_binary_is_not_ok():
    info = {"enabled": True, "error": None, "codex_bin": False, "lane_skill": True}
    result = _evaluate_probe(info, is_codex=True)
    assert result["ok"] is False
    assert "codex binary" in result["error"]


def test_codex_missing_lane_skill_is_not_ok():
    info = {"enabled": True, "error": None, "codex_bin": True, "lane_skill": False}
    result = _evaluate_probe(info, is_codex=True)
    assert result["ok"] is False
    assert "lane skill" in result["error"]


def test_codex_fully_ready_is_ok():
    info = {"enabled": True, "error": None, "codex_bin": True, "lane_skill": True}
    assert _evaluate_probe(info, is_codex=True) == {"ok": True, "error": None}
