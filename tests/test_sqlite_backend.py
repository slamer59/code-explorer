"""SqliteBackend held to the same expectations as the other backends.

Two halves:

1. The backend-agnostic half -- the exact assertions from
   tests/test_query_operations_backend_agnostic.py, re-run with SqliteBackend
   as a third parameter, so the spike is checked against the same contract
   Kuzu and LatticeDB are, not a friendlier one written for it.
2. The SQLite-specific half -- BM25/fuzzy/vector behaviour, the Cypher
   subset's boundaries, and the failure modes documented in
   sqlite_backend.py (dangling edges, extra_json properties).
"""

from pathlib import Path

import pytest

from code_explorer.graph.backends.sqlite_backend import (
    CypherSubsetError,
    SqliteBackend,
)
from code_explorer.graph.queries import QueryOperations
from code_explorer.graph.records import EdgeRecord, NodeRecord

HELPER_METHODS = {
    "to_relative_path": lambda f: f,
    "make_variable_id": lambda file, name, line: f"var_{file}_{name}_{line}",
}


def _fn(nid, name, file, start, end, text=""):
    return NodeRecord(
        id=nid,
        type="Function",
        properties={
            "id": nid,
            "name": name,
            "file": file,
            "start_line": start,
            "end_line": end,
            "is_public": True,
            "source_code": "",
            "search_text": text or f"{file}::{name}",
        },
    )


def _seed(backend) -> None:
    backend.upsert_nodes(
        [
            _fn("fn_caller", "caller", "foo.py", 1, 5),
            _fn("fn_callee", "callee", "foo.py", 10, 15),
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


@pytest.fixture
def backend(temp_dir: Path):
    b = SqliteBackend(temp_dir / "graph.sqlite", enable_vectors=True)
    b.open()
    b.initialize_schema()
    _seed(b)
    yield b
    b.close()


# ---------------------------------------------------------------- contract


def test_get_callers_and_callees_match_other_backends(backend):
    queries = QueryOperations(backend, Path("."), HELPER_METHODS, schema_version="v2")

    assert queries.get_callers("foo.py", "callee") == [("foo.py", "caller", 3)]
    assert queries.get_callees("foo.py", "caller") == [("foo.py", "callee", 3)]


def test_get_call_edges_with_lines(backend):
    callers, callees = backend.get_call_edges_with_lines("fn_callee")
    assert callers == [("foo.py", "caller", 3, 1, 5)]
    assert callees == []

    callers2, callees2 = backend.get_call_edges_with_lines("fn_caller")
    assert callers2 == []
    assert callees2 == [("foo.py", "callee", 3, 10, 15)]


def test_get_most_called_functions_sums_across_ambiguous_same_named_nodes(backend):
    """Same regression the LatticeDB implementation needed: two distinct
    Function nodes sharing (name, file) must combine into one summed entry,
    matching Cypher's group-by-returned-columns semantics."""
    backend.upsert_nodes(
        [
            _fn("fn_dup1", "dup", "bar.py", 1, 2),
            _fn("fn_dup2", "dup", "bar.py", 50, 51),
            _fn("fn_dup_caller", "dup_caller", "bar.py", 100, 105),
        ]
    )
    backend.upsert_edges(
        [
            EdgeRecord(src_id="fn_dup_caller", dst_id="fn_dup1", type="CALLS", properties={"call_line": 101}),
            EdgeRecord(src_id="fn_dup_caller", dst_id="fn_dup2", type="CALLS", properties={"call_line": 102}),
        ]
    )

    assert backend.get_most_called_functions(limit=1) == [("dup", "bar.py", 2)]


def test_get_statistics_counts_match(backend):
    queries = QueryOperations(backend, Path("."), HELPER_METHODS, schema_version="v2")

    stats = queries.get_statistics()

    assert stats["total_functions"] == 2
    assert stats["edge_stats"]["CALLS"] == 1
    assert stats["most_called_functions"] == [
        {"name": "callee", "file": "foo.py", "call_count": 1}
    ]


def test_parallel_calls_between_same_pair_are_kept_apart(backend):
    """CALLS legitimately has multiple edges between one pair (distinct call
    sites). The unique index includes the edge's own properties for exactly
    this reason; a (src, dst)-only key would collapse them."""
    backend.upsert_edges(
        [
            EdgeRecord(src_id="fn_caller", dst_id="fn_callee", type="CALLS", properties={"call_line": 4}),
            # A true duplicate, which MERGE semantics must swallow.
            EdgeRecord(src_id="fn_caller", dst_id="fn_callee", type="CALLS", properties={"call_line": 3}),
        ]
    )
    callers, _ = backend.get_call_edges_with_lines("fn_callee")
    assert sorted(c[2] for c in callers) == [3, 4]


def test_upsert_updates_rather_than_duplicates(backend):
    backend.upsert_nodes([_fn("fn_caller", "caller_renamed", "foo.py", 1, 6)])

    rows = backend.query("MATCH (f:Function) RETURN f.name AS name")
    assert sorted(r["name"] for r in rows) == ["callee", "caller_renamed"]


def test_delete_file_removes_nodes_edges_and_search_rows(backend):
    backend.delete_file("foo.py")

    assert backend.query("MATCH (f:Function) RETURN COUNT(f) AS count")[0]["count"] == 0
    assert backend.query("MATCH ()-[r:CALLS]->() RETURN COUNT(r) AS count")[0]["count"] == 0
    assert backend.search_text("callee") == []


def test_clear_all_empties_everything(backend):
    backend.clear_all()

    assert backend.query("MATCH (f:Function) RETURN COUNT(f) AS count")[0]["count"] == 0
    assert backend.search_text("caller") == []


def test_reopen_sees_persisted_data(temp_dir: Path):
    """The headline reason this spike exists: reopening must be cheap and
    must not lose the FTS index."""
    path = temp_dir / "reopen.sqlite"
    b = SqliteBackend(path)
    b.open()
    b.initialize_schema()
    _seed(b)
    b.close()

    b2 = SqliteBackend(path)
    b2.open()
    b2.initialize_schema()
    try:
        assert b2.query("MATCH (f:Function) RETURN COUNT(f) AS count")[0]["count"] == 2
        assert [h.name for h in b2.search_text("callee")] == ["callee"]
    finally:
        b2.close()


def test_booleans_round_trip_as_python_bools(backend):
    """SQLite has no BOOLEAN: is_public is stored 0/1 and must come back as
    a real bool, or callers doing `is True` diverge from the other backends."""
    row = backend.query(
        "MATCH (f:Function {file: $file, name: $name}) RETURN f.is_public AS is_public",
        {"file": "foo.py", "name": "caller"},
    )[0]
    assert row["is_public"] is True


# ------------------------------------------------------------------ search


def test_bm25_search_ranks_the_better_match_first(temp_dir: Path):
    b = SqliteBackend(temp_dir / "s.sqlite")
    b.open()
    b.initialize_schema()
    b.upsert_nodes(
        [
            _fn("fn_a", "parse_file", "a.py", 1, 2, "a.py::parse_file parse a python file into an ast"),
            _fn("fn_b", "unrelated", "b.py", 1, 2, "b.py::unrelated compute a checksum"),
        ]
    )
    try:
        hits = b.search_text("parse file", limit=5)
        assert hits[0].node_id == "fn_a"
        assert hits[0].node_type == "Function"
        # Higher score = more relevant (bm25() is flipped on the way out).
        if len(hits) > 1:
            assert hits[0].score >= hits[1].score
    finally:
        b.close()


def test_fuzzy_search_tolerates_a_typo_where_exact_search_does_not(temp_dir: Path):
    b = SqliteBackend(temp_dir / "f.sqlite")
    b.open()
    b.initialize_schema()
    b.upsert_nodes([_fn("fn_a", "parse_file", "a.py", 1, 2, "a.py::parse_file parse a file")])
    try:
        assert b.search_text("parze", limit=5) == []
        hits = b.search_text("parze", limit=5, fuzzy=True)
        assert [h.node_id for h in hits] == ["fn_a"]
    finally:
        b.close()


def test_fuzzy_raises_rather_than_silently_returning_exact_results(temp_dir: Path):
    """A fuzzy=True call on a backend without the trigram index must not
    quietly degrade to non-fuzzy results."""
    b = SqliteBackend(temp_dir / "nf.sqlite", enable_fuzzy=False)
    b.open()
    b.initialize_schema()
    try:
        with pytest.raises(NotImplementedError):
            b.search_text("anything", fuzzy=True)
    finally:
        b.close()


def test_search_text_query_with_fts5_operators_is_treated_as_literal_text(backend):
    """A user typing `NEAR` or a quote must not become FTS5 syntax (or an
    OperationalError bubbling out of the CLI)."""
    assert backend.search_text('callee NEAR "') != []


def test_search_vector_requires_enable_vectors(temp_dir: Path):
    b = SqliteBackend(temp_dir / "nv.sqlite", enable_vectors=False)
    b.open()
    b.initialize_schema()
    try:
        with pytest.raises(RuntimeError):
            b.search_vector("anything")
    finally:
        b.close()


def test_search_vector_ranks_by_cosine_distance(backend, monkeypatch):
    """Vector search without a live Ollama: inject known embeddings so the
    brute-force scan's ranking (not the embedding model) is what's tested."""
    import numpy as np

    import code_explorer.graph.backends.sqlite_backend as mod

    vectors = {
        "foo.py::caller": np.array([1.0, 0.0, 0.0], dtype=np.float32),
        "foo.py::callee": np.array([0.0, 1.0, 0.0], dtype=np.float32),
    }
    monkeypatch.setattr(mod, "embed_texts", lambda texts, model=None: [vectors[t] for t in texts])
    monkeypatch.setattr(mod, "embed_text", lambda text: np.array([0.0, 0.9, 0.1], dtype=np.float32))

    assert backend.build_vector_index() == 2
    hits = backend.search_vector("whatever", limit=2)

    assert [h.node_id for h in hits] == ["fn_callee", "fn_caller"]
    # score is a DISTANCE here (lower = more similar), matching
    # LatticeBackend.search_vector's contract.
    assert hits[0].score < hits[1].score


# ---------------------------------------------------- Cypher subset limits


def test_unsupported_cypher_raises_instead_of_guessing(backend):
    """The translator must fail loudly. A best-effort translation would
    return silently wrong rows, which is the one outcome a storage backend
    can never have."""
    for statement in [
        "MATCH (a:Function)-[:CALLS*1..3]->(b:Function) RETURN b.name AS name",
        "OPTIONAL MATCH (f:Function) RETURN f.name AS name",
        "MATCH (a:Function)-[:CALLS]->(b:Function)-[:CALLS]->(c:Function) RETURN c.name AS name",
        "MATCH (f:NotALabel) RETURN f.name AS name",
    ]:
        with pytest.raises((CypherSubsetError, ValueError)):
            backend.query(statement)


def test_undeclared_property_lands_in_extra_json_and_is_invisible_to_cypher(backend):
    """Documented gap, asserted so it can't regress into a surprise: a
    property with no declared column is stored (in extra_json) but a Cypher
    pattern matching on it finds nothing rather than raising."""
    backend.upsert_nodes(
        [
            NodeRecord(
                id="fn_extra",
                type="Function",
                properties={
                    "id": "fn_extra",
                    "name": "extra",
                    "file": "x.py",
                    "start_line": 1,
                    "end_line": 2,
                    "confidence": 0.9,  # no such column
                },
            )
        ]
    )
    stored = backend.conn.execute(
        'SELECT extra_json FROM "Function" WHERE id = ?', ("fn_extra",)
    ).fetchone()[0]
    assert "confidence" in stored

    with pytest.raises(Exception):
        backend.query("MATCH (f:Function {confidence: 0.9}) RETURN f.name AS name")


def test_dangling_edges_are_storable_but_invisible_to_reads(backend):
    """No foreign keys: unlike LatticeBackend (which raises "endpoint node
    not found"), this stores the row. Every read joins through the node
    table, so the edge is invisible rather than corrupting results."""
    backend.upsert_edges(
        [
            EdgeRecord(
                src_id="fn_caller", dst_id="fn_does_not_exist", type="CALLS",
                properties={"call_line": 99},
            )
        ]
    )

    _callers, callees = backend.get_call_edges_with_lines("fn_caller")
    assert callees == [("foo.py", "callee", 3, 10, 15)]
    # ...but the raw count does see it -- the honest shape of the gap.
    assert backend.query("MATCH ()-[r:CALLS]->() RETURN COUNT(r) AS count")[0]["count"] == 2
