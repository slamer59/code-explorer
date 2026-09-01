#!/usr/bin/env python3
"""Which rule resolved each call edge?

Run locally with:

    uv run --python 3.12 --extra dev python perfo/benchmark_resolution_methods.py [DIR]

`calls_resolved` alone cannot tell an improvement from a reshuffle. The
resolver has five rules of very different trustworthiness, from following an
actual import statement (`explicit_import`) down to "only one function in the
whole corpus has that name" (`global_unique`). A change can leave the total
flat while moving thousands of edges between them -- in either direction. This
prints the split, so the direction is visible.

Same build path as perfo/benchmark_ingest_stage_balance.py (fresh db, deferred
FTS indexes); it just reports different numbers from the same stats dict.
LatticeDB is single-writer: do not run this alongside another index build.
"""

import sys
import time
from pathlib import Path

from rich.console import Console
from rich.table import Table

from code_explorer.analyzer.base_analyzer import CodeAnalyzer
from code_explorer.graph.backends.lattice_backend import LatticeBackend
from code_explorer.graph.graph import DependencyGraph
from code_explorer.settings import settings

console = Console()

# Ordered best-first: an exact import match is worth far more than a
# name-level guess, and reading the histogram in confidence order is how you
# see whether a change moved work up or down that scale.
METHOD_ORDER = [
    "explicit_import",
    "same_class",
    "direct_base",
    "same_file",
    "package_reexport",
    "global_unique",
]


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    db_path = Path("perfo/bench_resolution_methods.lattice")
    for stale in db_path.parent.glob(db_path.name + "*"):
        stale.unlink(missing_ok=True)

    console.print(
        f"[cyan]Indexing[/cyan] {target} (workers={settings.analysis_workers}) ..."
    )
    backend = LatticeBackend(db_path)
    graph = DependencyGraph(
        db_path=db_path, project_root=target, backend=backend, defer_fts_indexes=True
    )
    analyses = CodeAnalyzer().iter_analyze_directory(
        target, max_workers=settings.analysis_workers
    )

    wall_start = time.perf_counter()
    stats = graph.ingest_analysis_stream(
        analyses,
        batch_size=settings.upsert_batch_size,
        batch_bytes=settings.ingest_batch_bytes,
        assume_new=True,
        adaptive=settings.adaptive_ingest_batching,
        max_batch_size=settings.ingest_batch_max_size,
        calibration_batches=settings.ingest_calibration_batches,
        throughput_tolerance=settings.ingest_throughput_tolerance,
    )
    wall = time.perf_counter() - wall_start

    methods = {
        key[len("resolution_method_") :]: value
        for key, value in stats.items()
        if key.startswith("resolution_method_")
    }
    total = sum(methods.values()) or 1

    table = Table(title=f"Call resolution methods -- {target.name}")
    table.add_column("Method")
    table.add_column("Edges", justify="right")
    table.add_column("Share", justify="right")
    for method in METHOD_ORDER + sorted(set(methods) - set(METHOD_ORDER)):
        count = methods.get(method, 0)
        table.add_row(method, f"{count:,}", f"{count / total * 100:.1f}%")
    table.add_row("", "", "")
    table.add_row("[b]total[/b]", f"{sum(methods.values()):,}", "")
    console.print(table)

    summary = Table(title="Totals")
    summary.add_column("Measure")
    summary.add_column("Value", justify="right")
    for label, key in (
        ("Files", "files"),
        ("Nodes", "total_nodes"),
        ("Edges", "total_edges"),
        ("Calls resolved", "calls_resolved"),
        ("Calls unresolved", "calls_unresolved"),
        ("Calls skipped (unattributable)", "calls_skipped_unattributable"),
        ("External symbols", "external_symbols"),
        ("External call edges", "external_edges"),
    ):
        summary.add_row(label, f"{stats.get(key, 0):,}")
    summary.add_row("Wall clock", f"{wall:.1f}s")
    console.print(summary)


if __name__ == "__main__":
    main()
