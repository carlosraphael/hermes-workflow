# hermes_workflow/sweep.py
"""Reverse-topological (leaves-first) ordering for hazard-free teardown.

abandon archives children strictly before parents so Hermes' recompute_ready
(run after each archive) never transiently promotes an interior real-assignee
stage to `ready` (Spike 5). A post-order DFS appends a node only after all its
children, so leaves come first and a parent always follows its children.
"""
from __future__ import annotations


def reverse_topo_order(card_ids, children_of) -> list:
    """Return card_ids leaves-first (every child strictly before its parents).

    children_of(cid) -> iterable of this card's child card ids (within the run).
    The property holds regardless of the iteration order of card_ids.
    """
    order, seen = [], set()

    def visit(cid):
        if cid in seen:
            return
        seen.add(cid)
        for child in children_of(cid):
            visit(child)
        order.append(cid)

    for cid in card_ids:
        visit(cid)
    return order
