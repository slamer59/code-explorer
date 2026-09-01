"""Tests for DependencyGraph.ingest_incremental (Phase 3, incremental
re-indexing -- see docs/explanation/latticedb-migration.md).

Kept small (4 tests): re-running on an unchanged directory skips
everything, modifying one file only reprocesses that file, deleting a
file cleans it up, and the parallel parse path produces the same graph
as the sequential one.
"""

from pathlib import Path

from code_explorer.graph.backends.lattice_backend import LatticeBackend
from code_explorer.graph.graph import DependencyGraph
from code_explorer.graph import graph as graph_module


def _graph(temp_dir: Path) -> DependencyGraph:
    return DependencyGraph(
        db_path=temp_dir / "graph.lattice",
        project_root=temp_dir,
        backend=LatticeBackend(temp_dir / "graph.lattice"),
    )


def test_incremental_ingest_skips_unchanged_files(temp_dir):
    (temp_dir / "a.py").write_text("def foo():\n    pass\n")
    (temp_dir / "b.py").write_text("def bar():\n    pass\n")

    graph = _graph(temp_dir)
    first = graph.ingest_incremental(temp_dir)
    assert first["unchanged"] == 0
    assert first["reprocessed"] == 2
    assert first["deleted"] == 0
    assert len(first["changed_node_ids"]) == 2, "both functions should be reported as changed"

    second = graph.ingest_incremental(temp_dir)
    assert second["unchanged"] == 2
    assert second["reprocessed"] == 0
    assert second["deleted"] == 0
    assert second["changed_node_ids"] == []

    rows = graph.backend.query("MATCH (f:Function) RETURN f.name AS name")
    assert {r["name"] for r in rows} == {"foo", "bar"}


def test_incremental_ingest_reprocesses_only_changed_file(temp_dir):
    (temp_dir / "a.py").write_text("def foo():\n    pass\n")
    (temp_dir / "b.py").write_text("def bar():\n    pass\n")

    graph = _graph(temp_dir)
    graph.ingest_incremental(temp_dir)

    (temp_dir / "a.py").write_text("def foo_renamed():\n    pass\n")
    stats = graph.ingest_incremental(temp_dir)

    assert stats["unchanged"] == 1
    assert stats["reprocessed"] == 1
    assert stats["deleted"] == 0
    assert len(stats["changed_node_ids"]) == 1
    rows = graph.backend.query("MATCH (f:Function) RETURN f.name AS name")
    names = {r["name"] for r in rows}
    assert names == {"foo_renamed", "bar"}, "old name should be gone, new name present"


def test_incremental_ingest_cleans_up_deleted_file(temp_dir):
    (temp_dir / "a.py").write_text("def foo():\n    pass\n")
    (temp_dir / "b.py").write_text("def bar():\n    pass\n")

    graph = _graph(temp_dir)
    graph.ingest_incremental(temp_dir)

    (temp_dir / "b.py").unlink()
    stats = graph.ingest_incremental(temp_dir)

    assert stats["unchanged"] == 1
    assert stats["reprocessed"] == 0
    assert stats["deleted"] == 1
    assert stats["changed_node_ids"] == []
    rows = graph.backend.query("MATCH (f:Function) RETURN f.name AS name")
    assert {r["name"] for r in rows} == {"foo"}
    file_rows = graph.backend.query("MATCH (f:File) RETURN f.path AS path")
    assert {r["path"] for r in file_rows} == {"a.py"}


def test_incremental_ingest_parallel_parse_matches_sequential(temp_dir, monkeypatch):
    """The process-pool parse path must produce the same graph as the
    in-process one -- it changes HOW files are parsed, not WHAT comes out.

    _PARALLEL_PARSE_THRESHOLD is 64 in production (measured, see graph.py);
    forced to 0 here so a handful of files exercises the pool without the
    test having to write 64 modules.
    """
    for index in range(6):
        (temp_dir / f"m{index}.py").write_text(
            f"def fn_{index}():\n    return {index}\n"
        )

    sequential = _graph(temp_dir)
    monkeypatch.setattr(graph_module, "_PARALLEL_PARSE_THRESHOLD", 10**9)
    seq_stats = sequential.ingest_incremental(temp_dir)
    seq_functions = {
        (r["file"], r["name"])
        for r in sequential.backend.query(
            "MATCH (f:Function) RETURN f.file AS file, f.name AS name"
        )
    }
    sequential.backend.close()

    for stale in temp_dir.glob("graph.lattice*"):
        stale.unlink()

    parallel = _graph(temp_dir)
    monkeypatch.setattr(graph_module, "_PARALLEL_PARSE_THRESHOLD", 0)
    par_stats = parallel.ingest_incremental(temp_dir)
    par_functions = {
        (r["file"], r["name"])
        for r in parallel.backend.query(
            "MATCH (f:Function) RETURN f.file AS file, f.name AS name"
        )
    }

    assert par_stats["reprocessed"] == seq_stats["reprocessed"] == 6
    assert len(par_stats["changed_node_ids"]) == len(seq_stats["changed_node_ids"])
    assert par_functions == seq_functions
