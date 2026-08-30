#!/usr/bin/env python3
"""Compare Cypher aggregation vs. LatticeDB's imperative edge API for
get_statistics()'s "most called functions" -- a GLOBAL aggregation across
every CALLS edge, a different query shape from benchmark_call_edges.py's
single-seed-node lookup, so it needed its own fix. See
docs/explanation/latticedb-migration.md's Performance Findings.

Run locally with:

    uv run --python 3.12 --extra dev python perfo/benchmark_most_called.py [DIR]

The gap only shows up at real scale -- on gemseo (2,107 files, 338,128
resolved calls) this measured 23.9s (Cypher) vs 1.25s (imperative), ~19x.
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

console = Console()
REPO_ROOT = Path(__file__).parent.parent


def _clean(db_path: Path) -> None:
    for stale in db_path.parent.glob(db_path.name + "*"):
        stale.unlink(missing_ok=True)


def _old_cypher_most_called(backend, limit: int):
    rows = backend.query(
        """
        MATCH (caller:Function)-[:CALLS]->(callee:Function)
        RETURN callee.name AS name, callee.file AS file, COUNT(caller) AS call_count
        ORDER BY call_count DESC
        LIMIT $limit
        """,
        {"limit": limit},
    )
    return [(r["name"], r["file"], r["call_count"]) for r in rows]


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "src" / "code_explorer"

    console.print(f"[cyan]Parsing[/cyan] {target} ...")
    results = CodeAnalyzer().analyze_directory(target)
    resolved_calls = CallResolver(results).resolve_all_calls()

    db_path = REPO_ROOT / "perfo" / "bench_most_called.lattice"
    _clean(db_path)
    graph = DependencyGraph(
        db_path=db_path, project_root=target, backend=LatticeBackend(db_path)
    )
    graph.ingest_results(results, resolved_calls=resolved_calls, assume_new=True)

    t0 = time.perf_counter()
    old_result = _old_cypher_most_called(graph.backend, limit=20)
    t_cypher = time.perf_counter() - t0

    t0 = time.perf_counter()
    new_result = graph.backend.get_most_called_functions(limit=20)
    t_imperative = time.perf_counter() - t0

    assert len(old_result) == len(new_result), "result count mismatch -- something's wrong"
    assert old_result[0][2] == new_result[0][2], "top call_count mismatch -- something's wrong"

    table = Table(title="get_most_called_functions: Cypher aggregation vs. imperative API")
    table.add_column("Approach")
    table.add_column("Time", justify="right")
    table.add_row("Cypher MATCH + ORDER BY (old)", f"{t_cypher * 1000:.1f}ms")
    table.add_row("Imperative API (current)", f"{t_imperative * 1000:.1f}ms")
    if t_imperative > 0:
        table.add_row("Speedup", f"{t_cypher / t_imperative:.1f}x")
    console.print(table)
    console.print(f"\nTop function both found: {new_result[0][0]} ({new_result[0][2]} callers) -- same result, different cost.")

    graph.backend.close()
    _clean(db_path)


if __name__ == "__main__":
    main()
