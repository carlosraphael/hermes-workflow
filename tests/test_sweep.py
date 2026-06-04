# tests/test_sweep.py
"""Pure unit tests for reverse-topological (leaves-first) ordering."""
from hermes_workflow.sweep import reverse_topo_order


def _children_of(edges):
    return lambda cid: edges.get(cid, [])


def test_diamond_orders_every_child_before_its_parents():
    # root -> a; a -> b, a -> c; b -> j, c -> j  (a diamond with a join j).
    edges = {"root": ["a"], "a": ["b", "c"], "b": ["j"], "c": ["j"]}
    order = reverse_topo_order(["root"], _children_of(edges))

    pos = {cid: i for i, cid in enumerate(order)}
    # Every parent->child edge: child strictly before parent.
    for parent, children in edges.items():
        for child in children:
            assert pos[child] < pos[parent]
    # Spot the spec's concrete expectations.
    assert pos["j"] < pos["b"] and pos["j"] < pos["c"]
    assert pos["b"] < pos["a"] and pos["c"] < pos["a"]
    assert pos["a"] < pos["root"]


def test_single_node():
    assert reverse_topo_order(["only"], _children_of({})) == ["only"]


def test_empty_input():
    assert reverse_topo_order([], _children_of({})) == []
