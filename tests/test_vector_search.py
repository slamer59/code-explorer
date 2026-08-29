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


def test_kuzu_backend_search_vector_raises_not_implemented(temp_dir):
    backend = KuzuBackend(temp_dir / "graph.db")
    backend.open()
    backend.initialize_schema()
    try:
        with pytest.raises(NotImplementedError):
            backend.search_vector("anything")
    finally:
        backend.close()
