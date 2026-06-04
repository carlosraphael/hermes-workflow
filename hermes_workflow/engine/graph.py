from __future__ import annotations
from dataclasses import dataclass, field
from hermes_workflow.engine.interpolate import interpolate
from hermes_workflow.engine.model import Template, Stage
from hermes_workflow.lanes.presets import lane_skill

GATE_ASSIGNEE = "_workflow_gate"   # mirrors version.SENTINEL_GATE_ASSIGNEE


@dataclass(frozen=True)
class Identity:
    stage_id: str
    fan_index: int
    attempt: int = 0


@dataclass
class CardSpec:
    identity: Identity
    title: str
    body: str
    assignee: str
    workspace: str
    parent_identities: list      # list[Identity]; NOTE: list (a test asserts == [Identity(...)])
    skills: list = field(default_factory=list)
    gate: bool = False


def _expanded(stage: Stage, completed: dict):
    """The source stage's emitted item list, or None if the source isn't done yet."""
    src = completed.get(stage.expand.over_stage)
    if src is None:
        return None  # source not done -> stage not materializable
    return list(src.get(stage.expand.over_key, []))


def _parents_for(stage: Stage, t: Template, completed: dict) -> list:
    """Parent identities: for each needed stage, every instance that exists/should exist."""
    parents = []
    for dep in stage.needs:
        dep_stage = t.stage(dep)
        if dep_stage.expand:
            items = _expanded(dep_stage, completed)
            if items is None:
                continue
            if items:
                parents += [Identity(dep, i, 0) for i in range(len(items))]
            else:
                # empty fan-out: gate the consumer on the fan-out SOURCE instead
                parents.append(Identity(dep_stage.expand.over_stage, 0, 0))
        else:
            parents.append(Identity(dep, 0, 0))
    return parents


def _materializable(stage: Stage, t: Template, completed: dict) -> bool:
    """A stage is materializable once every fan-out it depends on (incl. its own) has a done source."""
    for dep in stage.needs:
        dep_stage = t.stage(dep)
        if dep_stage.expand and _expanded(dep_stage, completed) is None:
            return False  # waiting on the fan-out source to complete
    if stage.expand and _expanded(stage, completed) is None:
        return False
    return True


def cards_for_run(t: Template, params: dict, bindings: dict, *, completed: dict, existing: set) -> list:
    specs: list = []
    for stage in t.stages:
        if not _materializable(stage, t, completed):
            continue
        instances = _expanded(stage, completed) if stage.expand else [None]
        if instances is None:
            continue
        for idx, item in enumerate(instances):
            ident = Identity(stage.id, idx if stage.expand else 0, 0)
            if ident in existing:
                continue
            evars = {stage.expand.as_var: item} if (stage.expand and item is not None) else {}
            assignee = bindings.get(stage.role, GATE_ASSIGNEE) if stage.role else GATE_ASSIGNEE
            lane = t.roles[stage.role].lane if stage.role else None
            specs.append(CardSpec(
                identity=ident,
                title=interpolate(stage.title, params=params, expand_vars=evars),
                body=interpolate(stage.body, params=params, expand_vars=evars),
                assignee=assignee,
                workspace=interpolate(stage.workspace, params=params, expand_vars={}),
                parent_identities=_parents_for(stage, t, completed),
                skills=([lane_skill(lane)] if lane and lane_skill(lane) else []),
                gate=stage.gate == "human",
            ))
    return specs
