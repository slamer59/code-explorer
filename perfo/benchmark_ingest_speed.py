#!/usr/bin/env python3
"""Compare LatticeDB ingest speed with and without the two write-side
optimizations added this session: assume_new (skip the existing-node lookup
in upsert_nodes) and node_id_map (resolve edge endpoints from an in-memory
map built during upsert_nodes, instead of a DB lookup per endpoint).

Run locally with:

    uv run --python 3.12 --extra dev python perfo/benchmark_ingest_speed.py [DIR]

node_id_map is the one that actually matters at real scale: on a large
codebase, edges (CALLS) typically outnumber nodes by an order of magnitude
(e.g. gemseo: ~15K nodes, ~338K resolved calls), so per-edge-endpoint lookup
cost dominates total ingest time far more than per-node lookup cost --
confirmed by measurement, not assumed (assume_new alone gave ~1.01x on
gemseo; this benchmark isolates node_id_map's contribution specifically,
since DependencyGraph.ingest_results always builds and uses it now, which
made the old assume_new-only comparison stop showing the difference).
"""

import sys
import time
from pathlib import Path

from rich.console import Console
from rich.table import Table

from code_explorer.analyzer.base_analyzer import CodeAnalyzer
from code_explorer.analyzer.call_resolver import CallResolver
from code_explorer.graph.backends.lattice_backend import LatticeBackend
from code_explorer.graph.graph import DependencyGraph
from code_explorer.graph.ingest import file_analyses_to_records

console = Console()
REPO_ROOT = Path(__file__).parent.parent


def _clean(db_path: Path) -> None:
    for stale in db_path.parent.glob(db_path.name + "*"):
        stale.unlink(missing_ok=True)


def _ingest_with_node_id_map(target: Path, db_path: Path, results, resolved_calls) -> float:
    """The current code path: ingest_results always builds and passes
    node_id_map to upsert_edges."""
    _clean(db_path)
    graph = DependencyGraph(
        db_path=db_path, project_root=target, backend=LatticeBackend(db_path)
    )
    t0 = time.perf_counter()
    graph.ingest_results(results, resolved_calls=resolved_calls, assume_new=True)
    elapsed = time.perf_counter() - t0
    graph.backend.close()
    _clean(db_path)
    return elapsed


def _ingest_without_node_id_map(target: Path, db_path: Path, results, resolved_calls) -> float:
    """Simulates the old behavior (before this session's optimization):
    calls upsert_nodes/upsert_edges directly, withholding node_id_map so
    every edge endpoint falls back to a DB lookup, same as before."""
    _clean(db_path)
    backend = LatticeBackend(db_path)
    graph = DependencyGraph(db_path=db_path, project_root=target, backend=backend)
    nodes, edges = file_analyses_to_records(results, target, resolved_calls)
    t0 = time.perf_counter()
    backend.upsert_nodes(nodes, assume_new=True)
    backend.upsert_edges(edges, node_id_map=None)  # forces the DB-lookup fallback
    elapsed = time.perf_counter() - t0
    backend.close()
    _clean(db_path)
    return elapsed


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "src" / "code_explorer"

    console.print(f"[cyan]Parsing[/cyan] {target} ...")
    results = CodeAnalyzer().analyze_directory(target)
    resolved_calls = CallResolver(results).resolve_all_calls()
    n_nodes = len(results) + sum(len(r.functions) + len(r.classes) for r in results)
    console.print(f"{n_nodes:,} nodes, {len(resolved_calls):,} resolved calls (edges).\n")

    t_without = _ingest_without_node_id_map(
        target, REPO_ROOT / "perfo" / "bench_ingest_nolmap.lattice", results, resolved_calls
    )
    t_with = _ingest_with_node_id_map(
        target, REPO_ROOT / "perfo" / "bench_ingest_lmap.lattice", results, resolved_calls
    )

    table = Table(title="Ingest time: edge endpoints via DB lookup vs. in-memory node_id_map")
    table.add_column("Mode")
    table.add_column("Time", justify="right")
    table.add_row("Without node_id_map (DB lookup per edge endpoint)", f"{t_without:.2f}s")
    table.add_row("With node_id_map (in-memory, this session's fix)", f"{t_with:.2f}s")
    if t_with > 0:
        table.add_row("Speedup", f"{t_without / t_with:.2f}x")
    console.print(table)


if __name__ == "__main__":
    main()
