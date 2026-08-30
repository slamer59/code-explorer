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


def test_get_statistics_counts_match_across_backends(backend):
    queries = QueryOperations(backend, Path("."), HELPER_METHODS, schema_version="v2")

    stats = queries.get_statistics()

    assert stats["total_functions"] == 2
    assert stats["edge_stats"]["CALLS"] == 1
    assert stats["most_called_functions"] == [
        {"name": "callee", "file": "foo.py", "call_count": 1}
    ]
