from __future__ import annotations
import json
from dataclasses import dataclass, asdict

_SENTINEL_OPEN = "<!--hermes-workflow:sentinel "
_SENTINEL_CLOSE = "-->"
_SNAPSHOT_OPEN = "<!--hermes-workflow:snapshot "


@dataclass(frozen=True)
class Sentinel:
    workflow_root: str
    stage_id: str
    fan_index: int
    attempt: int
    template_id: str
    template_version: str
    plugin_version: str
    schema_version: str


@dataclass(frozen=True)
class CompiledSnapshot:
    template_yaml: str
    params: dict
    bindings: dict
    plugin_version: str
    schema_version: str


def embed_sentinel(body: str, s: Sentinel) -> str:
    return f"{_SENTINEL_OPEN}{json.dumps(asdict(s))}{_SENTINEL_CLOSE}\n{body}"


def extract_sentinel(body: str) -> Sentinel | None:
    i = body.find(_SENTINEL_OPEN)
    if i < 0:
        return None
    j = body.find(_SENTINEL_CLOSE, i)
    if j < 0:
        return None
    raw = body[i + len(_SENTINEL_OPEN):j].strip()
    try:
        return Sentinel(**json.loads(raw))
    except Exception:
        return None


def build_root_body(template_yaml: str, params: dict, bindings: dict,
                    plugin_version: str, schema_version: str) -> str:
    payload = {"template_yaml": template_yaml, "params": params, "bindings": bindings,
               "plugin_version": plugin_version, "schema_version": schema_version}
    return f"{_SNAPSHOT_OPEN}{json.dumps(payload)}{_SENTINEL_CLOSE}\n# hermes-workflow run\n"


def parse_root_body(body: str) -> CompiledSnapshot:
    i = body.find(_SNAPSHOT_OPEN)
    j = body.find(_SENTINEL_CLOSE, i)
    payload = json.loads(body[i + len(_SNAPSHOT_OPEN):j].strip())
    return CompiledSnapshot(**payload)


def is_version_compatible(snapshot, supported) -> bool:
    """Total: never raises. Returns False for anything it cannot positively confirm.

    (Spike 1: a raising gate fails OPEN at the host, so we must fail CLOSED by
    returning False.) The try/except wraps both ``set(supported)`` and the
    membership test so a bad ``supported`` (e.g. None) yields False, not an error.
    """
    if isinstance(supported, (str, bytes)):
        return False  # a bare string would set()-split per character -> false-accept
    try:
        return getattr(snapshot, "schema_version", None) in set(supported)
    except Exception:
        return False
