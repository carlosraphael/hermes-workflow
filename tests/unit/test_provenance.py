from hermes_workflow.engine.provenance import (
    Sentinel, embed_sentinel, extract_sentinel, build_root_body, parse_root_body,
    is_version_compatible,
)


def test_sentinel_roundtrip_in_markdown_body():
    s = Sentinel(workflow_root="t_root", stage_id="fix", fan_index=2, attempt=0,
                 template_id="demo", template_version="0.1.0", plugin_version="0.1.0", schema_version="0.1")
    body = embed_sentinel("Do the work.", s)
    assert "Do the work." in body
    assert extract_sentinel(body) == s


def test_root_snapshot_roundtrip():
    body = build_root_body(template_yaml="name: demo\nversion: 0.1.0\n",
                           params={"repo": "/r"}, bindings={"scout": "designer"},
                           plugin_version="0.1.0", schema_version="0.1")
    snap = parse_root_body(body)
    assert snap.params["repo"] == "/r" and snap.bindings["scout"] == "designer"
    assert snap.schema_version == "0.1" and snap.plugin_version == "0.1.0"


def test_version_gate_is_total_and_never_raises():
    snap = parse_root_body(build_root_body("name: d\nversion: 0.1.0\n", {}, {}, "0.1.0", "0.1"))
    assert is_version_compatible(snap, supported={"0.1"}) is True
    assert is_version_compatible(snap, supported={"0.2"}) is False
    # garbage in -> False, never an exception (the gate must fail closed)
    assert is_version_compatible(None, supported={"0.1"}) is False
    assert is_version_compatible(object(), supported={"0.1"}) is False


def test_version_gate_total_on_bad_supported_and_weird_inputs():
    snap = parse_root_body(build_root_body("name: d\nversion: 0.1.0\n", {}, {}, "0.1.0", "0.1"))
    # a malformed `supported` must not raise either
    assert is_version_compatible(snap, supported=None) is False
    assert is_version_compatible("not a snapshot", supported={"0.1"}) is False


def test_extract_sentinel_returns_none_on_missing_or_garbage():
    assert extract_sentinel("a plain body with no sentinel") is None
    assert extract_sentinel("<!--hermes-workflow:sentinel {bad json-->") is None


def test_version_gate_rejects_string_supported_no_false_accept():
    # schema_version "0" must NOT be admitted by a bare-string supported "0.1"
    snap0 = parse_root_body(build_root_body("name: d\nversion: 0.1.0\n", {}, {}, "0.1.0", "0"))
    assert is_version_compatible(snap0, supported="0.1") is False
    # a correct set-typed supported still works
    snap1 = parse_root_body(build_root_body("name: d\nversion: 0.1.0\n", {}, {}, "0.1.0", "0.1"))
    assert is_version_compatible(snap1, supported={"0.1"}) is True
