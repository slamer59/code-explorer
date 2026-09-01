#!/usr/bin/env python3
"""Measure the parse step of DependencyGraph.ingest_incremental --
sequential (one core, one file at a time) vs. a bounded spawn-based
ProcessPoolExecutor -- as a function of how many files changed.

This is the number that picks _PARALLEL_PARSE_THRESHOLD in
graph/graph.py: a process pool costs ~1s of spawn + re-import before it
parses anything, so for a small change set sequential wins outright.

Parse only -- no database is touched, so this can run while another
process holds the LatticeDB single-writer lock. For the end-to-end
incremental numbers (which include hashing every file and the LatticeDB
write) see perfo/benchmark_incremental_ingest.py.

Run locally with:

    uv run --python 3.12 --extra dev python perfo/benchmark_incremental_parse.py [DIR]
"""

import sys
import time
from pathlib import Path

from rich.console import Console
from rich.table import Table

from code_explorer.analyzer.base_analyzer import discover_python_files
from code_explorer.graph import graph as graph_module
from code_explorer.graph.graph import DependencyGraph
from code_explorer.settings import settings

console = Console()
REPO_ROOT = Path(__file__).parent.parent
COUNTS = [1, 2, 4, 8, 16, 32, 64, 80, 100, 128, 200]


def _parse(paths, threshold: int) -> float:
    """Time _parse_changed_files with the threshold forced either way.

    Called unbound with self=None on purpose: _parse_changed_files reads
    nothing off the instance, and this keeps the benchmark from having to
    open a DependencyGraph (and take the single-writer lock) just to time
    a pure-CPU parse.
    """
    original = graph_module._PARALLEL_PARSE_THRESHOLD
    graph_module._PARALLEL_PARSE_THRESHOLD = threshold
    try:
        t0 = time.perf_counter()
        results = DependencyGraph._parse_changed_files(None, paths)
        elapsed = time.perf_counter() - t0
    finally:
        graph_module._PARALLEL_PARSE_THRESHOLD = original
    assert len(results) == len(paths)
    return elapsed


def main() -> None:
    target = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else REPO_ROOT / "src" / "code_explorer"
    )
    py_files = discover_python_files(target, settings.default_exclude_patterns)
    console.print(
        f"[cyan]{len(py_files):,} files[/cyan] in {target}, "
        f"analysis_workers={settings.analysis_workers}"
    )

    table = Table(title="ingest_incremental parse step: sequential vs. parallel")
    table.add_column("Changed files", justify="right")
    table.add_column("Sequential", justify="right")
    table.add_column("Parallel", justify="right")
    table.add_column("Speedup", justify="right")
    table.add_column("Winner")

    for count in COUNTS:
        if count > len(py_files):
            continue
        # Same slice both ways, so the two timings parse identical work.
        paths = py_files[:count]
        t_seq = _parse(paths, threshold=10**9)
        t_par = _parse(paths, threshold=0)
        table.add_row(
            f"{count:,}",
            f"{t_seq:.2f}s",
            f"{t_par:.2f}s",
            f"{t_seq / t_par:.2f}x",
            "parallel" if t_par < t_seq else "[yellow]sequential[/yellow]",
        )
        console.print(f"  n={count}: seq {t_seq:.2f}s / par {t_par:.2f}s")

    console.print(table)


if __name__ == "__main__":
    main()
