from __future__ import annotations
import re
import yaml
from hermes_workflow.engine.model import Param, Role, ExpandSpec, ExpandOut, Stage, Template

_WS_TOKEN = re.compile(r"\$\{([^}]+)\}")


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


def validate_template(t: Template) -> None:
    """Deterministic gatekeeper. Raises TemplateError on the first rule violation."""
    ids = [s.id for s in t.stages]
    dupes = sorted({sid for sid in ids if ids.count(sid) > 1})
    if dupes:
        raise TemplateError(f"duplicate stage id(s): {', '.join(dupes)}")
    id_set = set(ids)
    expand_sources = {s.expand.over_stage for s in t.stages if s.expand}

    for s in t.stages:
        # gate vs role
        if s.gate is not None:
            if s.role is not None:
                raise TemplateError(f"stage {s.id}: a gate stage must not declare a role")
        elif s.role is None:
            raise TemplateError(f"stage {s.id}: non-gate stage needs a role")
        if s.role is not None and s.role not in t.roles:
            raise TemplateError(f"stage {s.id}: unknown role {s.role!r}")

        for dep in s.needs:
            if dep not in id_set:
                raise TemplateError(f"stage {s.id}: needs unknown stage {dep!r}")

        if s.verify_raw is not None:
            raise TemplateError(f"stage {s.id}: verify.command/retry is deferred to 0.2.x")

        if s.expand:
            src = t.stage(s.expand.over_stage) if s.expand.over_stage in id_set else None
            if src is None:
                raise TemplateError(
                    f"stage {s.id}: expand.over references unknown stage {s.expand.over_stage!r}")
            if not src.expand_out or src.expand_out.key != s.expand.over_key:
                raise TemplateError(
                    f"stage {s.id}: expand.over key must match source expand_out.key")
            if s.id in expand_sources:
                raise TemplateError(f"stage {s.id}: nested expand is forbidden in 0.1.0")

        for tok in _WS_TOKEN.findall(s.workspace):
            if not tok.strip().startswith("params."):
                raise TemplateError(
                    f"stage {s.id}: workspace may only use ${{params.*}}, got {tok!r}")
        if s.expand and s.workspace.split(":", 1)[0] == "scratch":
            raise TemplateError(f"stage {s.id}: fan-out stages must not use scratch workspace")

    _check_cycle(t)


def _check_cycle(t: Template) -> None:
    graph = {s.id: set(s.needs) for s in t.stages}
    visiting, done = set(), set()

    def dfs(n):
        if n in done:
            return
        if n in visiting:
            raise TemplateError(f"dependency cycle at stage {n!r}")
        visiting.add(n)
        for m in graph.get(n, ()):
            dfs(m)
        visiting.discard(n)
        done.add(n)

    for n in graph:
        dfs(n)
