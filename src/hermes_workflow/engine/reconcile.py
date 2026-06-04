from __future__ import annotations
from dataclasses import dataclass

_STATUS_RANK = {"done": 5, "running": 4, "ready": 3, "todo": 2, "blocked": 1, "archived": 0}


@dataclass(frozen=True)
class CardRow:
    card_id: str
    status: str
    latest_run_id: int | None = None
    created_at: float = 0.0


def pick_winner(rows: list[CardRow]) -> CardRow:
    """Deterministic winner among duplicates sharing one sentinel identity.
    A 'done' duplicate wins unconditionally (status rank); tiebreak by
    latest_run_id -> created_at -> min(card_id). Falls back to status rank
    when none is 'done'.
    """
    if not rows:
        raise ValueError("pick_winner: no rows")
    # Sort key for min(): negate the higher-is-better fields (status rank, run_id,
    # created_at) so the largest wins; card_id stays plain so the smallest (min) wins.
    return min(rows, key=lambda r: (
        -_STATUS_RANK.get(r.status, 0),
        -(r.latest_run_id if r.latest_run_id is not None else -1),
        -r.created_at,
        r.card_id,
    ))
