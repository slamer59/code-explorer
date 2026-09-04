"""Tests for CodeGraphBackend.search_text() (BM25/fuzzy lexical search).

Goes through the full DependencyGraph/ingest_results pipeline (unlike
tests/test_lattice_search_capabilities.py, which seeds nodes directly) to
prove search_text works on data that actually came from the analyzer. Kept
small: this proves the wiring works, not exhaustive search-quality coverage.
"""

import pytest

from code_explorer.analyzer.base_analyzer import CodeAnalyzer
from code_explorer.graph.backends.kuzu_backend import KuzuBackend
from code_explorer.graph.backends.lattice_backend import LatticeBackend
from code_explorer.graph.graph import DependencyGraph


@pytest.mark.xfail(
    reason=(
        "LatticeDB 0.15.0 FTS bug, not ours: a multi-word query returns [] "
        "whenever any term appears in more than one document. Verified on this "
        "fixture -- 'two' alone returns [method_two, public_function], 'add "
        "numbers' returns [public_function], but 'two numbers' / 'add two' / "
        "'add two numbers' all return []. The same corpus and queries through "
        "SqliteBackend (FTS5) return public_function for every one of them. "
        "Upstream's most recent commit before 0.15.0 touched exactly this path "
        "('perf(query): seek the rarer of two ANDed full-text predicates'). "
        "Kept as a failing test rather than deleted: it documents a live "
        "defect in the primary use case, and should start passing on a fixed "
        "release."
    ),
    strict=True,
)
def test_search_text_finds_ingested_function_by_docstring(sample_python_file, temp_dir):
    result = CodeAnalyzer().analyze_file(sample_python_file)
    graph = DependencyGraph(
        db_path=temp_dir / "graph.lattice",
        project_root=temp_dir,
        backend=LatticeBackend(temp_dir / "graph.lattice"),
    )
    graph.ingest_results([result])

    results = graph.backend.search_text("add two numbers", limit=5)

    assert results, "expected at least one BM25 match"
    assert results[0].name == "public_function"
    assert results[0].node_type == "Function"


def test_search_text_fuzzy_tolerates_typo(sample_python_file, temp_dir):
    result = CodeAnalyzer().analyze_file(sample_python_file)
    graph = DependencyGraph(
        db_path=temp_dir / "graph.lattice",
        project_root=temp_dir,
        backend=LatticeBackend(temp_dir / "graph.lattice"),
    )
    graph.ingest_results([result])

    # "numbrs" (typo for "numbers", from the docstring "Add two numbers.")
    exact = graph.backend.search_text("numbrs", node_types=["Function"], limit=5)
    fuzzy = graph.backend.search_text("numbrs", node_types=["Function"], limit=5, fuzzy=True)

    assert exact == [], "typo shouldn't match exact BM25"
    assert any(r.name == "public_function" for r in fuzzy)


def test_kuzu_backend_search_text_raises_not_implemented(temp_dir):
    backend = KuzuBackend(temp_dir / "graph.db")
    backend.open()
    backend.initialize_schema()
    try:
        with pytest.raises(NotImplementedError):
            backend.search_text("anything")
    finally:
        backend.close()
