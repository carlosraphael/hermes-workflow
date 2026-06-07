"""Pin that CLI template reads tolerate a UTF-8 BOM (Windows/WSL2-edited files)."""
from hermes_workflow.cli import _read_template


def test_read_template_strips_utf8_bom(tmp_path):
    p = tmp_path / "t.workflow.yaml"
    p.write_bytes(b"\xef\xbb\xbfname: demo\n")   # UTF-8 BOM + content
    text = _read_template(str(p))
    assert not text.startswith("﻿"), "BOM leaked into template text"
    assert text.startswith("name:")


def test_read_template_plain_utf8(tmp_path):
    p = tmp_path / "t.workflow.yaml"
    p.write_text("name: demo\n", encoding="utf-8")
    assert _read_template(str(p)).startswith("name:")
