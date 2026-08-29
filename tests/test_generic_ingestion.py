"""Tests for the generic (non-Kuzu) FileAnalysis ingestion path.

Covers graph/ingest.py + DependencyGraph.ingest_results, which let `analyze`
populate backends without a Parquet/COPY-FROM bulk loader (e.g. LatticeDB).
Kept small: this is a Phase-1 path, not the primary Kuzu ingestion path,
which already has its own coverage via the existing analyzer/CLI usage.
"""

from pathlib import Path

from code_explorer.analyzer.base_analyzer import CodeAnalyzer
from code_explorer.graph.backends.lattice_backend import LatticeBackend
from code_explorer.graph.graph import DependencyGraph
from code_explorer.graph.ingest import file_analyses_to_records


def test_file_analyses_to_records_covers_files_functions_classes(
    sample_python_file, temp_dir
):
    result = CodeAnalyzer().analyze_file(sample_python_file)

    nodes, edges = file_analyses_to_records([result], project_root=temp_dir)

    node_types = {n.type for n in nodes}
    assert node_types == {"File", "Function", "Class"}
    function_names = {n.properties["name"] for n in nodes if n.type == "Function"}
    assert {"public_function", "_private_function", "caller_function"} <= function_names
    assert any(n.type == "Class" and n.properties["name"] == "SampleClass" for n in nodes)

    edge_types = {e.type for e in edges}
    assert edge_types == {"CONTAINS_FUNCTION", "CONTAINS_CLASS"}


def test_ingest_results_populates_lattice_backend_and_is_queryable(
    sample_python_file, temp_dir
):
    result = CodeAnalyzer().analyze_file(sample_python_file)

    backend = LatticeBackend(temp_dir / "graph.lattice")
    graph = DependencyGraph(
        db_path=temp_dir / "graph.lattice", project_root=temp_dir, backend=backend
    )

    stats = graph.ingest_results([result])

    assert stats["total_nodes"] > 0
    assert stats["total_edges"] > 0

    rows = graph.backend.query(
        "MATCH (f:File)-[:CONTAINS_FUNCTION]->(fn:Function) "
        "WHERE fn.name = $name RETURN fn.name AS name",
        {"name": "public_function"},
    )
    assert rows == [{"name": "public_function"}]
