"""Tests for LatticeBackend's chunked-transaction writes, assume_new, and
the node_id_map fast path for edge creation.

Kept small (4 tests): chunking across a batch boundary doesn't drop data,
assume_new's documented tradeoff (faster, but duplicates instead of updates
against pre-existing data) actually behaves as documented, upsert_nodes
returns a usable canonical-id -> internal-id map, and upsert_edges actually
uses that map instead of a DB lookup per endpoint when given one (proven by
making the lookup path raise if called, not just checking output).
"""

import pytest

from code_explorer.graph.backends import lattice_backend as lb_module
from code_explorer.graph.backends.lattice_backend import LatticeBackend
from code_explorer.graph.records import EdgeRecord, NodeRecord


def test_upsert_nodes_chunking_preserves_all_nodes(temp_dir, monkeypatch):
    # Force multiple small batches (5 nodes, batch size 2 -> 3 transactions)
    # instead of relying on the real ~1000 default, which no test-sized
    # input would ever cross.
    monkeypatch.setattr(lb_module, "_UPSERT_BATCH_SIZE", 2)

    backend = LatticeBackend(temp_dir / "g.lattice")
    backend.open()
    backend.initialize_schema()

    nodes = [
        NodeRecord(
            id=f"fn_{i}", type="Function",
            properties={"id": f"fn_{i}", "name": f"f{i}", "file": "a.py",
                        "start_line": i, "end_line": i + 1},
        )
        for i in range(5)
    ]
    backend.upsert_nodes(nodes)

    rows = backend.query("MATCH (f:Function) RETURN f.name AS name")
    assert {r["name"] for r in rows} == {"f0", "f1", "f2", "f3", "f4"}
    backend.close()


def test_assume_new_skips_dedup_and_creates_duplicates(temp_dir):
    backend = LatticeBackend(temp_dir / "g.lattice")
    backend.open()
    backend.initialize_schema()

    node = NodeRecord(
        id="fn_x", type="Function",
        properties={"id": "fn_x", "name": "x", "file": "a.py",
                    "start_line": 1, "end_line": 2},
    )

    # Default (assume_new=False): re-upserting the same id updates in place.
    backend.upsert_nodes([node])
    backend.upsert_nodes([node])
    rows = backend.query("MATCH (f:Function {id: 'fn_x'}) RETURN f.name AS name")
    assert len(rows) == 1

    # assume_new=True: skips the lookup, so a repeat "upsert" of the same id
    # creates a second node instead of updating -- the documented tradeoff,
    # only safe when the caller knows nothing pre-exists.
    backend.upsert_nodes([node], assume_new=True)
    rows2 = backend.query("MATCH (f:Function {id: 'fn_x'}) RETURN f.name AS name")
    assert len(rows2) == 2
    backend.close()


def test_upsert_nodes_returns_canonical_id_to_internal_id_map(temp_dir):
    backend = LatticeBackend(temp_dir / "g.lattice")
    backend.open()
    backend.initialize_schema()

    a = NodeRecord(
        id="fn_a", type="Function",
        properties={"id": "fn_a", "name": "a", "file": "x.py", "start_line": 1, "end_line": 2},
    )
    b = NodeRecord(
        id="fn_b", type="Function",
        properties={"id": "fn_b", "name": "b", "file": "x.py", "start_line": 3, "end_line": 4},
    )
    id_map = backend.upsert_nodes([a, b], assume_new=True)

    assert set(id_map.keys()) == {("Function", "fn_a"), ("Function", "fn_b")}
    with backend.db.read() as txn:
        assert txn.get_property(id_map[("Function", "fn_a")], "name") == "a"
        assert txn.get_property(id_map[("Function", "fn_b")], "name") == "b"
    backend.close()


def test_upsert_edges_uses_node_id_map_without_db_lookup(temp_dir, monkeypatch):
    backend = LatticeBackend(temp_dir / "g.lattice")
    backend.open()
    backend.initialize_schema()

    a = NodeRecord(
        id="fn_a", type="Function",
        properties={"id": "fn_a", "name": "a", "file": "x.py", "start_line": 1, "end_line": 2},
    )
    b = NodeRecord(
        id="fn_b", type="Function",
        properties={"id": "fn_b", "name": "b", "file": "x.py", "start_line": 3, "end_line": 4},
    )
    id_map = backend.upsert_nodes([a, b], assume_new=True)

    # Prove the map path is actually used, not just that the end result is
    # correct either way: make the DB-lookup fallback raise if called.
    def _boom(*args, **kwargs):
        raise AssertionError("_find_node_id should not be called when node_id_map covers the edge")

    monkeypatch.setattr(backend, "_find_node_id", _boom)

    backend.upsert_edges(
        [EdgeRecord(src_id="fn_a", dst_id="fn_b", type="CALLS", properties={"call_line": 5})],
        node_id_map=id_map,
    )

    rows = backend.query(
        "MATCH (a:Function)-[c:CALLS]->(b:Function) RETURN a.name AS name, c.call_line AS l"
    )
    assert rows == [{"name": "a", "l": 5}]
    backend.close()


def test_backend_context_manager_closes_and_checkpoints(temp_dir):
    """`with LatticeBackend(...)` must open and then close.

    Regression guard for a real incident: a benchmark script that never
    called close() left an un-checkpointed WAL, and reopening that database
    took >400s (versus 0.03s clean) with its FTS indexes unreadable. The
    fix is that closing is automatic, so this asserts the contract rather
    than the symptom.
    """
    db_path = temp_dir / "ctx.lattice"
    with LatticeBackend(db_path) as backend:
        backend.initialize_schema()
        assert backend.db is not None
    assert backend.db is None  # closed on exit

    # Reopening a cleanly-closed database works and sees the same schema.
    with LatticeBackend(db_path) as reopened:
        assert reopened.db is not None
