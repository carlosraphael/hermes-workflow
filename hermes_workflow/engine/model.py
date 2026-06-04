from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class Param:
    name: str
    type: str
    required: bool = False
    default: object = None


@dataclass(frozen=True)
class Role:
    name: str
    lane: str  # "profile" | "codex"


@dataclass(frozen=True)
class ExpandSpec:
    over_stage: str
    over_key: str
    as_var: str


@dataclass(frozen=True)
class ExpandOut:
    key: str
    item: dict          # field_name -> type string
    max: int = 50


@dataclass(frozen=True)
class Stage:
    id: str
    role: str | None = None
    title: str = ""
    body: str = ""
    needs: tuple = ()
    expand: ExpandSpec | None = None
    expand_out: ExpandOut | None = None
    gate: str | None = None          # "human" or None
    workspace: str = "scratch"       # scratch | dir:<p> | worktree:<p>
    verify_raw: object = None        # raw `verify:` block, captured so Task 8 can REJECT it (0.2.x)


@dataclass(frozen=True)
class Template:
    name: str
    version: str
    description: str
    params: dict           # name -> Param
    roles: dict            # name -> Role
    stages: tuple          # tuple[Stage]

    def stage(self, sid: str) -> Stage:
        for s in self.stages:
            if s.id == sid:
                return s
        raise KeyError(sid)
