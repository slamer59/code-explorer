"""Tests for context.py's collect-then-rank expansion.

Four, and only four: the three properties the design actually rests on --
that collection is NOT pruned per level, that the budget degrades instead
of truncating, and that the hub cap blocks expansion *through* a node
without hiding the node -- plus a guard on the one value duplicated
between cli.py and context.py.
"""

from code_explorer.analyzer.base_analyzer import CodeAnalyzer
from code_explorer.analyzer.call_resolver import CallResolver
from code_explorer.cli import _DEFAULT_DEPTH, _DEFAULT_TOKEN_BUDGET
from code_explorer.context import (
    DEFAULT_DEPTH,
    DEFAULT_TOKEN_BUDGET,
    ContextAssembler,
)
from code_explorer.graph.backends.kuzu_backend import KuzuBackend
from code_explorer.graph.graph import DependencyGraph


def _ingest(temp_dir, name, source):
    path = temp_dir / name
    path.write_text(source, encoding="utf-8")
    result = CodeAnalyzer().analyze_file(path)
    graph = DependencyGraph(
        db_path=temp_dir / "graph.db",
        project_root=temp_dir,
        backend=KuzuBackend(temp_dir / "graph.db"),
    )
    graph.ingest_results([result], resolved_calls=CallResolver([result]).resolve_all_calls())
    return graph


def _body(n: int) -> str:
    """A body long enough that abridging it actually saves tokens."""
    return "".join(f"    x{i} = {i} * 12345  # padding to make this body big\n"
                   for i in range(n))


CHAIN = (
    f'''def d():
    """Leaf of the chain."""
{_body(20)}    return 4


def c():
    """Middle of the chain."""
{_body(20)}    return d()


def b():
    """Dull node -- the only path to c and d."""
{_body(20)}    return c()


def a():
    """Seed."""
    return b()
'''
)


def test_expand_reaches_past_the_first_hop_with_true_distances(temp_dir):
    graph = _ingest(temp_dir, "chain.py", CHAIN)

    ctx = ContextAssembler(graph).expand("chain.py", "a", depth=3)

    # The whole point of collecting before ranking: c and d are only
    # reachable *through* b, which carries no relevance signal of its own.
    reached = {n.name: n.distance for n in ctx.callees}
    assert reached == {"b": 1, "c": 2, "d": 3}
    assert all(n.source_code for n in ctx.callees)


def test_budget_degrades_to_signatures_instead_of_cutting_source(temp_dir):
    graph = _ingest(temp_dir, "chain.py", CHAIN)

    # ~90 tokens of body per node: enough for one, not for three.
    ctx = ContextAssembler(graph).expand("chain.py", "a", depth=3, token_budget=150)

    abridged = [n for n in ctx.callees if n.abridged]
    assert abridged, "budget should have forced at least one node to a signature"
    for node in abridged:
        assert node.source_code.startswith("def ")
        assert "body omitted (token budget)" in node.source_code
        # Degraded, not cut mid-function: no partial statement survives.
        assert "x19 = 19" not in node.source_code


HUB = (
    "def leaf_one():\n    return 1\n\n\n"
    "def leaf_two():\n    return 2\n\n\n"
    "def leaf_three():\n    return 3\n\n\n"
    "def hub():\n    return leaf_one() + leaf_two() + leaf_three()\n\n\n"
    "def seed():\n    return hub()\n"
)


def test_hub_cap_blocks_expansion_through_a_node_but_not_the_node(temp_dir):
    graph = _ingest(temp_dir, "hub.py", HUB)
    assembler = ContextAssembler(graph)

    wide = assembler.expand("hub.py", "seed", depth=2, hub_degree=100)
    assert {n.name for n in wide.callees} == {"hub", "leaf_one", "leaf_two", "leaf_three"}

    capped = assembler.expand("hub.py", "seed", depth=2, hub_degree=2)
    # hub itself is still a result -- being popular is not a reason to hide
    # it -- but its three callees no longer ride in behind it.
    assert {n.name for n in capped.callees} == {"hub"}


def test_cli_defaults_match_the_engine():
    # cli.py restates these two rather than importing context at module
    # scope (measured +260ms per invocation). Drift would silently change
    # what --help promises.
    assert (_DEFAULT_DEPTH, _DEFAULT_TOKEN_BUDGET) == (
        DEFAULT_DEPTH,
        DEFAULT_TOKEN_BUDGET,
    )
