"""Prove QueryOperations produces identical results against both backends.

Phase 1 of the LatticeDB migration (see docs/explanation/latticedb-migration.md):
QueryOperations now runs its Cypher through CodeGraphBackend.query() instead
of a raw kuzu.Connection, so it should behave the same whether the backend is
KuzuBackend or LatticeBackend. This is a proof the routing works, not a full
regression suite for every query method.
"""

from pathlib import Path

import pytest

from code_explorer.graph.backends.kuzu_backend import KuzuBackend
from code_explorer.graph.backends.lattice_backend import LatticeBackend
from code_explorer.graph.queries import QueryOperations
from code_explorer.graph.records import EdgeRecord, NodeRecord

HELPER_METHODS = {
    "to_relative_path": lambda f: f,
    "make_variable_id": lambda file, name, line: f"var_{file}_{name}_{line}",
}


def _seed(backend) -> None:
    backend.upsert_nodes(
        [
            NodeRecord(
                id="fn_caller",
                type="Function",
                properties={
                    "id": "fn_caller",
                    "name": "caller",
                    "file": "foo.py",
                    "start_line": 1,
                    "end_line": 5,
                    "is_public": True,
                    "source_code": "",
                },
            ),
            NodeRecord(
                id="fn_callee",
                type="Function",
                properties={
                    "id": "fn_callee",
                    "name": "callee",
                    "file": "foo.py",
                    "start_line": 10,
                    "end_line": 15,
                    "is_public": True,
                    "source_code": "",
                },
            ),
        ]
    )
    backend.upsert_edges(
        [
            EdgeRecord(
                src_id="fn_caller",
                dst_id="fn_callee",
                type="CALLS",
                properties={"call_line": 3},
            )
        ]
    )


@pytest.fixture(params=["kuzu", "lattice"])
def backend(request, temp_dir: Path):
    if request.param == "kuzu":
        b = KuzuBackend(temp_dir / "graph.db")
    else:
        b = LatticeBackend(temp_dir / "graph.lattice")
    b.open()
    b.initialize_schema()
    _seed(b)
    yield b
    b.close()


def test_get_callers_and_callees_match_across_backends(backend):
    queries = QueryOperations(backend, Path("."), HELPER_METHODS, schema_version="v2")

    assert queries.get_callers("foo.py", "callee") == [("foo.py", "caller", 3)]
    assert queries.get_callees("foo.py", "caller") == [("foo.py", "callee", 3)]


def test_get_callers_and_callees_with_lines_matches_separate_calls(backend):
    """The combined method (built to cut context assembly's query count,
    see docs/explanation/latticedb-migration.md's Performance Findings)
    must return the same callers/callees as the two separate calls, plus
    accurate start_line/end_line for each -- not a shortcut that drops
    data or gets the wrong node's line range."""
    queries = QueryOperations(backend, Path("."), HELPER_METHODS, schema_version="v2")

    callers, callees = queries.get_callers_and_callees_with_lines("foo.py", "callee")
    assert callers == [("foo.py", "caller", 3, 1, 5)]  # (file, name, call_line, start_line, end_line)
    assert callees == []

    callers2, callees2 = queries.get_callers_and_callees_with_lines("foo.py", "caller")
    assert callers2 == []
    assert callees2 == [("foo.py", "callee", 3, 10, 15)]


def test_get_call_edges_with_lines_matches_across_backends(backend):
    """The backend-level primitive itself (not QueryOperations) -- each
    backend implements this via whatever is fastest for it (see
    docs/explanation/latticedb-migration.md's Performance Findings:
    LatticeDB's Cypher MATCH on a CALLS-edge traversal measured ~15s on a
    real 338K-edge graph -- LabelScan-based Expand, confirmed via
    LatticeDB's own architecture docs -- vs. ~2ms via its imperative
    get_incoming_edges/get_outgoing_edges + get_property API for the same
    data). Must produce identical results regardless of which primitive a
    backend uses internally."""
    callers, callees = backend.get_call_edges_with_lines("fn_callee")
    assert callers == [("foo.py", "caller", 3, 1, 5)]
    assert callees == []

    callers2, callees2 = backend.get_call_edges_with_lines("fn_caller")
    assert callers2 == []
    assert callees2 == [("foo.py", "callee", 3, 10, 15)]


def test_get_most_called_functions_matches_across_backends(backend):
    """Global aggregation across all CALLS edges -- a different query shape
    from get_call_edges_with_lines (which is scoped to one seed node), so it
    needed its own backend-specific fix. Confirmed via direct measurement on
    gemseo's real 338K-edge graph (see docs/explanation/latticedb-migration.md):
    the old Cypher aggregation (MATCH (caller)-[:CALLS]->(callee) ... ORDER BY
    COUNT(caller) DESC LIMIT 20) measured 23.9s; iterating Function nodes via
    the imperative get_nodes_by_label/get_incoming_edges API measured 1.25s --
    about 19x faster, same category of fix as get_call_edges_with_lines but a
    different implementation since there's no single seed node to start from."""
    backend.upsert_nodes(
        [
            NodeRecord(
                id="fn_caller2",
                type="Function",
                properties={
                    "id": "fn_caller2",
                    "name": "caller2",
                    "file": "foo.py",
                    "start_line": 20,
                    "end_line": 25,
                    "is_public": True,
                    "source_code": "",
                },
            ),
        ]
    )
    backend.upsert_edges(
        [
            EdgeRecord(
                src_id="fn_caller2",
                dst_id="fn_callee",
                type="CALLS",
                properties={"call_line": 21},
            )
        ]
    )
    # Now: fn_callee has 2 callers (fn_caller, fn_caller2); fn_callee itself
    # calls nothing. fn_caller/fn_caller2 have 0 incoming calls.

    result = backend.get_most_called_functions(limit=20)

    assert result[0] == ("callee", "foo.py", 2)
    names = [r[0] for r in result]
    assert names.count("callee") == 1  # no duplicates


def test_get_most_called_functions_sums_across_ambiguous_same_named_nodes(backend):
    """Regression test: a first version of the LatticeDB implementation
    counted per internal node id instead of grouping by (name, file), which
    silently dropped a function from the top-N when two distinct Function
    nodes shared a name+file (found via a real mismatch on this repo's own
    tree_sitter_adapter.py::walk). Two distinct 'dup' functions in the same
    file, each with their own callers, must be combined into one entry with
    the summed count -- matching Cypher's GROUP BY-on-returned-columns
    semantics, not per-node identity."""
    backend.upsert_nodes(
        [
            NodeRecord(
                id="fn_dup1", type="Function",
                properties={"id": "fn_dup1", "name": "dup", "file": "bar.py",
                            "start_line": 1, "end_line": 2, "is_public": True, "source_code": ""},
            ),
            NodeRecord(
                id="fn_dup2", type="Function",
                properties={"id": "fn_dup2", "name": "dup", "file": "bar.py",
                            "start_line": 50, "end_line": 51, "is_public": True, "source_code": ""},
            ),
            NodeRecord(
                id="fn_dup_caller", type="Function",
                properties={"id": "fn_dup_caller", "name": "dup_caller", "file": "bar.py",
                            "start_line": 100, "end_line": 105, "is_public": True, "source_code": ""},
            ),
        ]
    )
    backend.upsert_edges(
        [
            EdgeRecord(src_id="fn_dup_caller", dst_id="fn_dup1", type="CALLS", properties={"call_line": 101}),
            EdgeRecord(src_id="fn_dup_caller", dst_id="fn_dup2", type="CALLS", properties={"call_line": 102}),
        ]
    )
    # fn_dup1 has 1 caller, fn_dup2 has 1 caller -- same (name, file), must
    # combine to count=2, not appear as two separate count=1 entries (or
    # worse, be individually outranked and dropped from a small top-N).

    result = backend.get_most_called_functions(limit=1)

    assert result == [("dup", "bar.py", 2)]


def test_get_statistics_counts_match_across_backends(backend):
    queries = QueryOperations(backend, Path("."), HELPER_METHODS, schema_version="v2")

    stats = queries.get_statistics()

    assert stats["total_functions"] == 2
    assert stats["edge_stats"]["CALLS"] == 1
    assert stats["most_called_functions"] == [
        {"name": "callee", "file": "foo.py", "call_count": 1}
    ]
