"""Demonstrate LatticeDB search capabilities that Kuzu doesn't have.

These are not tests of code-explorer's own search feature (none exists yet --
see docs/explanation/latticedb-migration.md, Phase 4+). They exercise
LatticeBackend/latticedb directly to prove the underlying engine actually
delivers the three retrieval modes the migration spec is betting on: BM25
lexical search, typo-tolerant fuzzy search, and vector similarity search --
all over the same embedded database used for structural graph storage,
which Kuzu cannot do on its own.
"""

import numpy as np
import pytest

from code_explorer.graph.backends.lattice_backend import LatticeBackend
from code_explorer.graph.records import EdgeRecord, NodeRecord


@pytest.fixture
def lattice_backend(temp_dir):
    backend = LatticeBackend(temp_dir / "search.lattice")
    backend.open()
    backend.initialize_schema()
    yield backend
    backend.close()


def _seed_functions(backend: LatticeBackend) -> None:
    backend.upsert_nodes(
        [
            NodeRecord(
                id="fn_refresh",
                type="Function",
                properties={
                    "id": "fn_refresh",
                    "name": "refresh_token",
                    "file": "auth/token.py",
                    "source_code": (
                        "def refresh_token(token):\n"
                        "    \"\"\"Refreshes an OAuth access token.\"\"\"\n"
                        "    return issue_new_token(token)"
                    ),
                },
            ),
            NodeRecord(
                id="fn_render",
                type="Function",
                properties={
                    "id": "fn_render",
                    "name": "render_template",
                    "file": "views/render.py",
                    "source_code": (
                        "def render_template(name, context):\n"
                        "    \"\"\"Renders an HTML template with context.\"\"\"\n"
                        "    return TEMPLATE_ENGINE.render(name, context)"
                    ),
                },
            ),
            NodeRecord(
                id="fn_delete",
                type="Function",
                properties={
                    "id": "fn_delete",
                    "name": "delete_session",
                    "file": "auth/session.py",
                    "source_code": (
                        "def delete_session(session_id):\n"
                        "    \"\"\"Deletes a stored user session.\"\"\"\n"
                        "    return SESSION_STORE.remove(session_id)"
                    ),
                },
            ),
        ]
    )


def test_bm25_search_finds_relevant_function_by_keyword(lattice_backend):
    """BM25 lexical search over source_code should rank the OAuth-token
    function first for a query naming its domain vocabulary, without any
    exact identifier match -- something Kuzu's Cypher-only queries can't do
    (they require an exact/pattern match on a known property value)."""
    _seed_functions(lattice_backend)
    # The Function.source_code FTS index is now created automatically by
    # LatticeBackend.initialize_schema() (see graph/backends/lattice_backend.py's
    # SEARCHABLE_TEXT_FIELDS) -- the fixture above already called it.

    results = lattice_backend.db.fts_search(
        "Function", "source_code", "OAuth access token", limit=5
    )

    assert results, "expected at least one BM25 match"
    with lattice_backend.db.read() as txn:
        top_names = [txn.get_property(r.node_id, "name") for r in results]
    assert top_names[0] == "refresh_token"


def test_fuzzy_search_tolerates_misspelled_symbol_name(lattice_backend):
    """Fuzzy search should still find 'delete_session' when the query has a
    typo ('delet_sesion'), the fallback behavior Strategy C in the migration
    spec calls for -- exact/BM25 lookups would return nothing here."""
    _seed_functions(lattice_backend)
    lattice_backend.db.create_node_fts_index("Function", "name")

    exact_results = lattice_backend.db.fts_search(
        "Function", "name", "delet_sesion", limit=5
    )
    assert exact_results == []

    fuzzy_results = lattice_backend.db.fts_search_fuzzy(
        "Function", "name", "delet_sesion", limit=5, max_distance=2
    )

    assert fuzzy_results, "expected fuzzy search to tolerate the typo"
    with lattice_backend.db.read() as txn:
        top_name = txn.get_property(fuzzy_results[0].node_id, "name")
    assert top_name == "delete_session"


def test_indexing_and_search_share_one_database(lattice_backend):
    """Index a small structural graph (File -CONTAINS_FUNCTION-> Function
    -CALLS-> Function) through the same NodeRecord/EdgeRecord path
    KuzuBackend uses, then run both a structural Cypher traversal and a BM25
    search against that same LatticeBackend instance. This is the actual
    selling point over Kuzu: one embedded database file backs exact graph
    queries *and* lexical/fuzzy/vector search -- Kuzu has no search layer at
    all, so this combination would need a second engine bolted on."""
    lattice_backend.upsert_nodes(
        [
            NodeRecord(
                id="auth/token.py",
                type="File",
                properties={
                    "path": "auth/token.py",
                    "language": "python",
                    "content_hash": "h1",
                },
            )
        ]
    )
    _seed_functions(lattice_backend)
    lattice_backend.upsert_edges(
        [
            EdgeRecord(
                src_id="auth/token.py",
                dst_id="fn_refresh",
                type="CONTAINS_FUNCTION",
                properties={},
            ),
            EdgeRecord(
                src_id="fn_refresh",
                dst_id="fn_delete",
                type="CALLS",
                properties={"call_line": 3},
            ),
        ]
    )

    # Exact structural traversal (what the impact engine relies on).
    callers = lattice_backend.query(
        "MATCH (caller:Function)-[:CALLS]->(callee:Function) "
        "WHERE callee.id = $id RETURN caller.name AS name",
        {"id": "fn_delete"},
    )
    assert callers == [{"name": "refresh_token"}]

    contains = lattice_backend.query(
        "MATCH (f:File)-[:CONTAINS_FUNCTION]->(fn:Function) "
        "WHERE f.path = $path RETURN fn.name AS name",
        {"path": "auth/token.py"},
    )
    assert contains == [{"name": "refresh_token"}]

    # BM25 search over the same indexed data, in the same database file.
    # (Function.source_code FTS index already created by initialize_schema().)
    hits = lattice_backend.db.fts_search(
        "Function", "source_code", "user session", limit=5
    )
    assert hits, "expected the indexed graph data to also be search-hittable"
    with lattice_backend.db.read() as txn:
        assert txn.get_property(hits[0].node_id, "name") == "delete_session"


def test_vector_search_ranks_nearest_embedding(temp_dir):
    """Vector similarity search should rank the nearest embedding highest,
    proving the mechanism the migration spec's Phase 5 (semantic/conceptual
    queries) depends on. Embeddings here are synthetic (hand-placed points),
    not from a real embedding model -- this tests the retrieval mechanism,
    not semantic quality, which is a later-phase concern."""
    backend = LatticeBackend(temp_dir / "vector.lattice")
    # Vector search needs the feature enabled at database-creation time, with
    # a fixed dimensionality -- confirmed via latticedb's Database signature
    # (enable_vector / vector_dimensions kwargs).
    import latticedb

    db = latticedb.Database(
        backend.db_path, create=True, enable_vectors=True, vector_dimensions=4
    )
    db.open()
    try:
        with db.write() as txn:
            near = txn.create_node(
                labels=["Function"], properties={"name": "refresh_token"}
            )
            far = txn.create_node(
                labels=["Function"], properties={"name": "render_template"}
            )
            txn.set_vector(near.id, "embedding", np.array([1, 0, 0, 0], dtype=np.float32))
            txn.set_vector(far.id, "embedding", np.array([0, 0, 0, 1], dtype=np.float32))
            txn.commit()

        results = db.vector_search(
            np.array([0.9, 0.1, 0, 0], dtype=np.float32), k=2
        )

        assert results, "expected at least one vector match"
        with db.read() as txn:
            top_name = txn.get_property(results[0].node_id, "name")
        assert top_name == "refresh_token"
        assert results[0].distance < results[1].distance
    finally:
        db.close()
