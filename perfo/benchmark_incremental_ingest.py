#!/usr/bin/env python3
"""Measure incremental re-index speed (Phase 3) vs. a full rebuild, and
confirm accuracy: touching one file and re-indexing incrementally must
produce the same Function/Class/File node set as a full rebuild.

Run locally with:

    uv run --python 3.12 --extra dev python perfo/benchmark_incremental_ingest.py [DIR]
"""

import sys
import time
from pathlib import Path

from rich.console import Console
from rich.table import Table

from code_explorer.analyzer.base_analyzer import CodeAnalyzer, discover_python_files
from code_explorer.analyzer.call_resolver import CallResolver
from code_explorer.graph.backends.lattice_backend import LatticeBackend
from code_explorer.graph.graph import DependencyGraph
from code_explorer.settings import settings

console = Console()
REPO_ROOT = Path(__file__).parent.parent
# Change-set sizes to time. Spans DependencyGraph._PARALLEL_PARSE_THRESHOLD
# (64) so the sequential and the pooled parse paths are both exercised.
CHANGE_COUNTS = [1, 10, 50, 200]


def _clean(db_path: Path) -> None:
    for stale in db_path.parent.glob(db_path.name + "*"):
        stale.unlink(missing_ok=True)


def _full_rebuild(target: Path, db_path: Path) -> float:
    _clean(db_path)
    results = CodeAnalyzer().analyze_directory(target)
    resolved_calls = CallResolver(results).resolve_all_calls()
    graph = DependencyGraph(
        db_path=db_path, project_root=target, backend=LatticeBackend(db_path)
    )
    t0 = time.perf_counter()
    graph.ingest_results(results, resolved_calls=resolved_calls, assume_new=True)
    elapsed = time.perf_counter() - t0
    graph.backend.close()
    return elapsed


def _function_set(db_path: Path, target: Path) -> set:
    graph = DependencyGraph(
        db_path=db_path, project_root=target, backend=LatticeBackend(db_path, read_only=True)
    )
    rows = graph.backend.query(
        "MATCH (f:Function) RETURN f.file AS file, f.name AS name, f.start_line AS l"
    )
    graph.backend.close()
    return {(r["file"], r["name"], r["l"]) for r in rows}


def _timed_incremental(target: Path, db_path: Path, files: list) -> tuple:
    """Touch `files`, time one ingest_incremental, then restore both the
    files and the index so the next measurement starts from the same
    baseline. Originals are written back byte-for-byte in a finally block --
    this benchmark is pointed at real checkouts.
    """
    originals = {f: f.read_text() for f in files}
    for f in files:
        f.write_text(originals[f] + "\n# bench-touch\n")
    try:
        graph = DependencyGraph(
            db_path=db_path, project_root=target, backend=LatticeBackend(db_path)
        )
        t0 = time.perf_counter()
        stats = graph.ingest_incremental(target)
        elapsed = time.perf_counter() - t0
        graph.backend.close()
    finally:
        for f, text in originals.items():
            f.write_text(text)
        # Resync the index with the restored files, so repeated runs (and the
        # next change count) start clean.
        graph = DependencyGraph(
            db_path=db_path, project_root=target, backend=LatticeBackend(db_path)
        )
        graph.ingest_incremental(target)
        graph.backend.close()
    return stats, elapsed


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "src" / "code_explorer"
    db_path = REPO_ROOT / "perfo" / "bench_incremental.lattice"

    console.print(f"[cyan]Full-indexing[/cyan] {target} ...")
    t_full = _full_rebuild(target, db_path)

    # No-op incremental pass: nothing on disk changed.
    graph = DependencyGraph(
        db_path=db_path, project_root=target, backend=LatticeBackend(db_path)
    )
    t0 = time.perf_counter()
    noop_stats = graph.ingest_incremental(target)
    t_noop = time.perf_counter() - t0
    graph.backend.close()

    # Touch N files (append a harmless comment) and re-run incrementally.
    # Multi-file change sets are where the parallel parse step in
    # ingest_incremental actually pays -- a 1-file change is dominated by
    # hashing every OTHER file, not by parsing the one that changed.
    # Same discovery ingest_incremental uses -- touching a file it excludes
    # would silently measure a no-op pass.
    py_files = sorted(discover_python_files(target, settings.default_exclude_patterns))
    change_counts = [n for n in CHANGE_COUNTS if n <= len(py_files)]
    change_timings = []
    for count in change_counts:
        stats, elapsed = _timed_incremental(target, db_path, py_files[:count])
        change_timings.append((count, elapsed, stats))
        console.print(f"  {count} file(s) changed: {elapsed:.2f}s")
    t_one_change = change_timings[0][1]
    one_change_stats = change_timings[0][2]

    incremental_functions = _function_set(db_path, target)

    rebuild_db_path = REPO_ROOT / "perfo" / "bench_incremental_rebuild.lattice"
    _full_rebuild(target, rebuild_db_path)
    rebuilt_functions = _function_set(rebuild_db_path, target)

    accuracy_ok = incremental_functions == rebuilt_functions

    table = Table(title="Incremental re-index (Phase 3) vs. full rebuild")
    table.add_column("Scenario")
    table.add_column("Time", justify="right")
    table.add_column("Detail")
    table.add_row("Full rebuild", f"{t_full:.2f}s", f"{len(py_files):,} files")
    table.add_row(
        "Incremental, no changes",
        f"{t_noop:.2f}s",
        f"unchanged={noop_stats['unchanged']}, reprocessed={noop_stats['reprocessed']}",
    )
    for count, elapsed, stats in change_timings:
        table.add_row(
            f"Incremental, {count} file(s) changed",
            f"{elapsed:.2f}s",
            f"unchanged={stats['unchanged']}, reprocessed={stats['reprocessed']}",
        )
    if t_one_change > 0:
        table.add_row("Speedup (1 file changed vs. full rebuild)", f"{t_full / t_one_change:.2f}x", "")
    console.print(table)

    accuracy_msg = (
        "[green]MATCH[/green]" if accuracy_ok else "[red]MISMATCH[/red]"
    )
    console.print(
        f"\nAccuracy check (incremental vs. full-rebuild Function set): {accuracy_msg} "
        f"({len(incremental_functions):,} functions)"
    )
    if not accuracy_ok:
        only_incremental = incremental_functions - rebuilt_functions
        only_rebuild = rebuilt_functions - incremental_functions
        console.print(f"  only in incremental: {len(only_incremental)}")
        console.print(f"  only in full rebuild: {len(only_rebuild)}")

    _clean(db_path)
    _clean(rebuild_db_path)


if __name__ == "__main__":
    main()
