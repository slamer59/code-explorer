#!/usr/bin/env python3
"""Index a real directory into LatticeDB and prove it worked.

Run locally with:

    uv run --python 3.12 --extra dev python perfo/index_with_lattice.py [DIR]

DIR defaults to this repo's own src/code_explorer, so it works out of the
box with no setup. Parses -> resolves calls -> ingests into a fresh
LatticeBackend (via DependencyGraph.ingest_results, see
graph/ingest.py) -> reports timing/counts -> runs a couple of real
get_callers/impact queries against the indexed data to prove it's not just
inserted, it's actually queryable.
"""

import shutil
import sys
import time
from pathlib import Path

from rich.console import Console
from rich.table import Table

from code_explorer.analyzer.base_analyzer import CodeAnalyzer
from code_explorer.analyzer.call_resolver import CallResolver
from code_explorer.graph.backends.lattice_backend import LatticeBackend
from code_explorer.graph.graph import DependencyGraph
from code_explorer.impact import ImpactAnalyzer

console = Console()

REPO_ROOT = Path(__file__).parent.parent


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "src" / "code_explorer"
    db_path = REPO_ROOT / "perfo" / "lattice_index.lattice"
    shutil.rmtree(db_path, ignore_errors=True)

    console.print(f"[cyan]Parsing[/cyan] {target} ...")
    t0 = time.perf_counter()
    results = CodeAnalyzer().analyze_directory(target)
    parse_time = time.perf_counter() - t0

    t0 = time.perf_counter()
    resolved_calls = CallResolver(results).resolve_all_calls()
    resolve_time = time.perf_counter() - t0

    console.print(f"[cyan]Indexing into LatticeDB[/cyan] ({db_path}) ...")
    graph = DependencyGraph(
        db_path=db_path, project_root=target, backend=LatticeBackend(db_path)
    )
    t0 = time.perf_counter()
    stats = graph.ingest_results(results, resolved_calls=resolved_calls)
    ingest_time = time.perf_counter() - t0

    table = Table(title="LatticeDB Indexing Results")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Files parsed", str(len(results)))
    table.add_row("Parse time", f"{parse_time:.2f}s")
    table.add_row("Call resolution time", f"{resolve_time:.2f}s")
    table.add_row("Nodes indexed", f"{stats['total_nodes']:,}")
    table.add_row("Edges indexed", f"{stats['total_edges']:,}")
    table.add_row("Ingest time", f"{ingest_time:.2f}s")
    if ingest_time > 0:
        rate = (stats["total_nodes"] + stats["total_edges"]) / ingest_time
        table.add_row("Ingest rate", f"{rate:,.0f} rows/sec")
    console.print(table)

    # Prove it's actually queryable, not just inserted: find whichever
    # indexed function has the most callers and trace its impact.
    rows = graph.backend.query(
        "MATCH (caller:Function)-[:CALLS]->(callee:Function) "
        "RETURN callee.file AS file, callee.name AS name, COUNT(caller) AS n "
        "ORDER BY n DESC LIMIT 1"
    )
    if not rows:
        console.print("[yellow]No CALLS edges found -- nothing to trace.[/yellow]")
        graph.backend.close()
        return

    seed = rows[0]
    console.print(
        f"\n[cyan]Most-called function:[/cyan] {seed['name']} "
        f"({seed['file']}) -- {seed['n']} direct caller(s)"
    )

    t0 = time.perf_counter()
    impact = ImpactAnalyzer(graph)
    result = impact.analyze_function_impact(
        seed["file"], seed["name"], direction="upstream", max_depth=5
    )
    query_time = time.perf_counter() - t0

    console.print(f"[cyan]Impact query time:[/cyan] {query_time * 1000:.1f}ms")
    console.print(f"[cyan]Transitive upstream impact:[/cyan] {len(result)} function(s)")
    for r in result[:10]:
        console.print(f"  depth {r.depth}: {r.function_name} ({r.file_path})")

    graph.backend.close()


if __name__ == "__main__":
    main()
