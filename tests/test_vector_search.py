"""Tests for CodeGraphBackend.search_vector() (semantic search via local Ollama).

Requires a local Ollama server running with the nomic-embed-text model
pulled (see src/code_explorer/embeddings.py) -- not mocked, tests against
the real local service, matching this session's established pattern for
LatticeDB-backed tests. Kept small: proves the wiring and that semantic
ranking actually works, not exhaustive search-quality coverage.
"""

import pytest

from code_explorer.analyzer.base_analyzer import CodeAnalyzer
from code_explorer.graph.backends.kuzu_backend import KuzuBackend
from code_explorer.graph.backends.lattice_backend import LatticeBackend
from code_explorer.graph.graph import DependencyGraph


def test_search_vector_ranks_semantically_related_function_first(temp_dir):
    """A conceptual query with no shared keywords should still rank the
    semantically related function above an unrelated one -- the actual
    point of vector search vs BM25."""
    file_path = temp_dir / "auth_and_math.py"
    file_path.write_text(
        "def refresh_token(token):\n"
        "    '''Refreshes an OAuth access token by calling the auth server.'''\n"
        "    return issue_new_token(token)\n"
        "\n"
        "\n"
        "def add(a, b):\n"
        "    '''Adds two numbers together.'''\n"
        "    return a + b\n"
    )
    result = CodeAnalyzer().analyze_file(file_path)

    graph = DependencyGraph(
        db_path=temp_dir / "graph.lattice",
        project_root=temp_dir,
        backend=LatticeBackend(
            temp_dir / "graph.lattice", enable_vectors=True, vector_dimensions=768
        ),
    )
    graph.ingest_results([result])
    graph.backend.build_vector_index()

    results = graph.backend.search_vector(
        "how do we get a new access credential after it expires", limit=2
    )

    assert results, "expected at least one vector match"
    assert results[0].name == "refresh_token"
    assert results[0].score < results[1].score  # lower distance = closer


def test_build_vector_index_node_ids_embeds_only_those_nodes(temp_dir):
    """node_ids scoping (used for incremental re-indexing) must embed only
    the given nodes, not silently fall back to the full graph scan."""
    from code_explorer.graph.records import NodeRecord

    backend = LatticeBackend(
        temp_dir / "graph.lattice", enable_vectors=True, vector_dimensions=768
    )
    backend.open()
    backend.initialize_schema()

    alpha = NodeRecord(
        id="fn_alpha", type="Function",
        properties={
            "id": "fn_alpha", "name": "alpha", "file": "a.py",
            "start_line": 1, "end_line": 2,
            "search_text": "alpha refreshes an oauth access token",
        },
    )
    beta = NodeRecord(
        id="fn_beta", type="Function",
        properties={
            "id": "fn_beta", "name": "beta", "file": "a.py",
            "start_line": 3, "end_line": 4,
            "search_text": "beta adds two numbers together",
        },
    )
    id_map = backend.upsert_nodes([alpha, beta], assume_new=True)
    alpha_id = id_map[("Function", "fn_alpha")]

    n = backend.build_vector_index(node_ids=[alpha_id])
    assert n == 1

    results = backend.search_vector("token refresh", node_types=["Function"], limit=10)
    names = {r.name for r in results}
    assert "alpha" in names
    assert "beta" not in names, "beta was not in node_ids and must not have been embedded"


def test_build_vector_index_batches_embed_calls(temp_dir, monkeypatch):
    """Prove build_vector_index makes one embed_texts call per batch, not
    one call per node -- not just that the end result is correct either
    way (see this session's established pattern in test_lattice_batching.py)."""
    from code_explorer.graph import backends
    from code_explorer.graph.records import NodeRecord

    backend = LatticeBackend(
        temp_dir / "graph.lattice", enable_vectors=True, vector_dimensions=768
    )
    backend.open()
    backend.initialize_schema()

    nodes = [
        NodeRecord(
            id=f"fn_{i}", type="Function",
            properties={
                "id": f"fn_{i}", "name": f"f{i}", "file": "a.py",
                "start_line": i, "end_line": i + 1,
                "search_text": f"function f{i} does something",
            },
        )
        for i in range(5)
    ]
    backend.upsert_nodes(nodes, assume_new=True)

    calls = []
    real_embed_texts = backends.lattice_backend.embed_texts

    def _spy(texts, **kwargs):
        calls.append(list(texts))
        return real_embed_texts(texts, **kwargs)

    monkeypatch.setattr(backends.lattice_backend, "embed_texts", _spy)

    n = backend.build_vector_index()

    assert n == 5
    assert len(calls) == 1, "expected a single batched call, not 5 per-node calls"
    assert len(calls[0]) == 5


def test_kuzu_backend_search_vector_raises_not_implemented(temp_dir):
    backend = KuzuBackend(temp_dir / "graph.db")
    backend.open()
    backend.initialize_schema()
    try:
        with pytest.raises(NotImplementedError):
            backend.search_vector("anything")
    finally:
        backend.close()
