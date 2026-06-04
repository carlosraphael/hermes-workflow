from hermes_workflow.veto import evaluate_completion_gate


def test_expand_out_shape_blocks_on_wrong_shape():
    d = evaluate_completion_gate(stage_kind="expand_source",
        expand_out={"key": "flaky", "max": 50, "item": {"test_id": "string", "file": "string"}},
        metadata={"flaky": [{"test_id": "T1"}]}, workspace_dir=None, schema_ok=True)
    assert d and d["action"] == "block" and "file" in d["message"]


def test_expand_out_over_max_blocks():
    d = evaluate_completion_gate(stage_kind="expand_source",
        expand_out={"key": "k", "max": 2, "item": {"id": "string"}},
        metadata={"k": [{"id": "1"}, {"id": "2"}, {"id": "3"}]}, workspace_dir=None, schema_ok=True)
    assert d["action"] == "block" and "max" in d["message"]


def test_valid_shape_passes():
    assert evaluate_completion_gate(stage_kind="expand_source",
        expand_out={"key": "k", "max": 50, "item": {"id": "string"}},
        metadata={"k": [{"id": "1"}]}, workspace_dir=None, schema_ok=True) is None


def test_non_list_items_block():
    d = evaluate_completion_gate(stage_kind="expand_source",
        expand_out={"key": "k", "max": 50, "item": {"id": "string"}},
        metadata={"k": "not-a-list"}, workspace_dir=None, schema_ok=True)
    assert d["action"] == "block" and "list" in d["message"]


def test_schema_mismatch_blocks():
    assert evaluate_completion_gate(stage_kind="plain", expand_out=None, metadata={},
        workspace_dir=None, schema_ok=False)["action"] == "block"


def test_internal_error_fails_closed():
    # metadata that breaks iteration must still produce a block, never an exception
    d = evaluate_completion_gate(stage_kind="expand_source",
        expand_out={"key": "k", "max": 1, "item": {"id": "string"}},
        metadata=12345, workspace_dir=None, schema_ok=True)
    assert d["action"] == "block"


def test_plain_stage_passes():
    assert evaluate_completion_gate(stage_kind="plain", expand_out=None, metadata={},
        workspace_dir=None, schema_ok=True) is None
