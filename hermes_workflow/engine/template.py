from __future__ import annotations
import yaml
from hermes_workflow.engine.model import Param, Role, ExpandSpec, ExpandOut, Stage, Template


class TemplateError(ValueError):
    pass


def parse_template(text: str) -> Template:
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise TemplateError(f"invalid YAML: {e}") from e
    if not isinstance(raw, dict):
        raise TemplateError("template must be a YAML mapping")
    params = {n: Param(n, p.get("type", "string"), bool(p.get("required", False)), p.get("default"))
              for n, p in (raw.get("params") or {}).items()}
    roles = {n: Role(n, r.get("lane", "profile")) for n, r in (raw.get("roles") or {}).items()}
    stages = []
    for s in raw.get("stages") or []:
        exp = s.get("expand")
        expand = None
        if exp:
            over = exp["over"]
            if "." not in over:
                raise TemplateError(f"stage {s.get('id')!r}: expand.over must be '<stage>.<key>', got {over!r}")
            st, key = over.split(".", 1)   # "<stage>.<key>"
            expand = ExpandSpec(st, key, exp["as"])
        eo = s.get("expand_out")
        expand_out = ExpandOut(eo["key"], eo.get("item", {}), int(eo.get("max", 50))) if eo else None
        stages.append(Stage(
            id=s["id"], role=s.get("role"), title=s.get("title", ""), body=s.get("body", ""),
            needs=tuple(s.get("needs", [])), expand=expand, expand_out=expand_out,
            gate=s.get("gate"), workspace=s.get("workspace", "scratch"),
            verify_raw=s.get("verify"),
        ))
    return Template(raw["name"], str(raw["version"]), raw.get("description", ""),
                    params, roles, tuple(stages))
