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


def test_sentinel_roundtrip_survives_arrow_in_fields():
    # Author-controlled fields containing the literal '-->' terminator must not
    # truncate the embedded payload (D1-01).
    s = Sentinel(workflow_root="root-->x", stage_id="fix-->stage", fan_index=2, attempt=0,
                 template_id="a-->b", template_version="0.1.0 --> dev",
                 plugin_version="0.1.0", schema_version="0.1")
    prose = "author body with A --> B prose."
    body = embed_sentinel(prose, s)
    assert extract_sentinel(body) == s
    assert prose in body


def test_root_snapshot_roundtrip_survives_arrow_in_template_yaml():
    # template_yaml prose and params/bindings values containing '-->' must
    # round-trip exactly without truncation (D1-01).
    template_yaml = 'name: demo\nstages:\n  - id: scan\n    title: "scan A --> B"\n'
    body = build_root_body(template_yaml=template_yaml,
                           params={"note": "x --> y"},
                           bindings={"edge": "a --> b"},
                           plugin_version="0.1.0", schema_version="0.1")
    snap = parse_root_body(body)
    assert snap.template_yaml == template_yaml
    assert snap.params == {"note": "x --> y"}
    assert snap.bindings == {"edge": "a --> b"}
    assert snap.plugin_version == "0.1.0"
    assert snap.schema_version == "0.1"


def test_extract_sentinel_finds_genuine_close_when_author_body_has_arrow():
    # An author body placed AFTER the sentinel that itself contains '-->'
    # must not confuse extraction of the genuine terminator.
    s = Sentinel(workflow_root="t_root", stage_id="fix", fan_index=0, attempt=0,
                 template_id="demo", template_version="0.1.0",
                 plugin_version="0.1.0", schema_version="0.1")
    body = embed_sentinel("see diagram: A --> B --> C in the body.", s)
    assert extract_sentinel(body) == s
