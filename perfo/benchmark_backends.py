#!/usr/bin/env python3
"""Compare KuzuBackend vs LatticeBackend: accuracy AND speed, same data.

Run locally with:

    uv run --python 3.12 --extra dev python perfo/benchmark_backends.py [DIR]

DIR defaults to this repo's own src/code_explorer. Both backends are fed the
exact same parsed FileAnalysis results (via DependencyGraph.ingest_results,
graph/ingest.py) so the comparison is apples-to-apples, per the migration
spec's own benchmark rule (docs/explanation/latticedb-migration.md, Section 21):
never compare different graphs.

Measures, per backend:
  - Ingest time and rate (nodes+edges/sec)
  - Single-hop query latency (get_callers, repeated)
  - Impact traversal latency at increasing depth (1/2/4/8)

Then checks ACCURACY: same seed function, both backends must produce the
same set of callers/callees and the same transitive impact set (as sets,
since ordering/duplicate-callsite order isn't guaranteed identical).
"""

import shutil
import sys
import time
from pathlib import Path
from typing import List, Tuple

from rich.console import Console
from rich.table import Table

from code_explorer.analyzer.base_analyzer import CodeAnalyzer
from code_explorer.analyzer.call_resolver import CallResolver
from code_explorer.graph.backends.kuzu_backend import KuzuBackend
from code_explorer.graph.backends.lattice_backend import LatticeBackend
from code_explorer.graph.graph import DependencyGraph
from code_explorer.impact import ImpactAnalyzer

console = Console()
REPO_ROOT = Path(__file__).parent.parent


def build_graph(backend_name: str, backend, target: Path, results, resolved_calls):
    db_path = REPO_ROOT / "perfo" / f"bench_{backend_name}.db"
    shutil.rmtree(db_path, ignore_errors=True)
    graph = DependencyGraph(db_path=db_path, project_root=target, backend=backend)
    t0 = time.perf_counter()
    stats = graph.ingest_results(results, resolved_calls=resolved_calls)
    ingest_time = time.perf_counter() - t0
    return graph, stats, ingest_time


def pick_seed(graph: DependencyGraph) -> Tuple[str, str]:
    """Pick the most-called function as the benchmark seed, for both backends."""
    rows = graph.backend.query(
        "MATCH (caller:Function)-[:CALLS]->(callee:Function) "
        "RETURN callee.file AS file, callee.name AS name, COUNT(caller) AS n "
        "ORDER BY n DESC LIMIT 1"
    )
    if not rows:
        raise SystemExit("No CALLS edges found -- nothing to benchmark.")
    return rows[0]["file"], rows[0]["name"]


def bench_single_hop(graph: DependencyGraph, seed_file: str, seed_name: str, n: int = 100) -> float:
    t0 = time.perf_counter()
    for _ in range(n):
        graph.get_callers(seed_file, seed_name)
    return (time.perf_counter() - t0) / n * 1000  # ms/query


def bench_impact_depths(graph: DependencyGraph, seed_file: str, seed_name: str) -> List[Tuple[int, float, int]]:
    analyzer = ImpactAnalyzer(graph)
    out = []
    for depth in (1, 2, 4, 8):
        t0 = time.perf_counter()
        result = analyzer.analyze_function_impact(
            seed_file, seed_name, direction="upstream", max_depth=depth
        )
        elapsed = (time.perf_counter() - t0) * 1000  # ms
        out.append((depth, elapsed, len(result)))
    return out


def check_accuracy(kuzu_graph, lattice_graph, seed_file: str, seed_name: str) -> bool:
    k_callers = set(kuzu_graph.get_callers(seed_file, seed_name))
    l_callers = set(lattice_graph.get_callers(seed_file, seed_name))
    callers_match = k_callers == l_callers

    k_impact = {(r.function_name, r.file_path, r.depth) for r in ImpactAnalyzer(kuzu_graph).analyze_function_impact(seed_file, seed_name, direction="upstream", max_depth=5)}
    l_impact = {(r.function_name, r.file_path, r.depth) for r in ImpactAnalyzer(lattice_graph).analyze_function_impact(seed_file, seed_name, direction="upstream", max_depth=5)}
    impact_match = k_impact == l_impact

    console.print(f"\n[bold]Accuracy check[/bold] (seed: {seed_name} in {seed_file})")
    console.print(f"  get_callers match:        {'[green]YES[/green]' if callers_match else '[red]NO[/red]'} (Kuzu={len(k_callers)}, Lattice={len(l_callers)})")
    console.print(f"  impact (depth<=5) match:   {'[green]YES[/green]' if impact_match else '[red]NO[/red]'} (Kuzu={len(k_impact)}, Lattice={len(l_impact)})")
    if not callers_match:
        console.print(f"    Kuzu only: {k_callers - l_callers}")
        console.print(f"    Lattice only: {l_callers - k_callers}")
    if not impact_match:
        console.print(f"    Kuzu only: {k_impact - l_impact}")
        console.print(f"    Lattice only: {l_impact - k_impact}")
    return callers_match and impact_match


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "src" / "code_explorer"

    console.print(f"[cyan]Parsing[/cyan] {target} ...")
    results = CodeAnalyzer().analyze_directory(target)
    resolved_calls = CallResolver(results).resolve_all_calls()
    console.print(f"Parsed {len(results)} files, {len(resolved_calls)} resolved calls.\n")

    kuzu_graph, kuzu_stats, kuzu_ingest_time = build_graph(
        "kuzu", KuzuBackend(REPO_ROOT / "perfo" / "bench_kuzu.db"), target, results, resolved_calls
    )
    lattice_graph, lattice_stats, lattice_ingest_time = build_graph(
        "lattice", LatticeBackend(REPO_ROOT / "perfo" / "bench_lattice.db"), target, results, resolved_calls
    )

    seed_file, seed_name = pick_seed(kuzu_graph)

    accurate = check_accuracy(kuzu_graph, lattice_graph, seed_file, seed_name)

    kuzu_single_hop = bench_single_hop(kuzu_graph, seed_file, seed_name)
    lattice_single_hop = bench_single_hop(lattice_graph, seed_file, seed_name)

    kuzu_impact = bench_impact_depths(kuzu_graph, seed_file, seed_name)
    lattice_impact = bench_impact_depths(lattice_graph, seed_file, seed_name)

    table = Table(title="Ingest")
    table.add_column("Backend")
    table.add_column("Nodes", justify="right")
    table.add_column("Edges", justify="right")
    table.add_column("Time", justify="right")
    table.add_column("Rows/sec", justify="right")
    for name, stats, t in (("Kuzu", kuzu_stats, kuzu_ingest_time), ("Lattice", lattice_stats, lattice_ingest_time)):
        rate = (stats["total_nodes"] + stats["total_edges"]) / t if t > 0 else 0
        table.add_row(name, f"{stats['total_nodes']:,}", f"{stats['total_edges']:,}", f"{t:.2f}s", f"{rate:,.0f}")
    console.print()
    console.print(table)

    table2 = Table(title="Single-hop query latency (get_callers, avg of 100 calls)")
    table2.add_column("Backend")
    table2.add_column("ms/query", justify="right")
    table2.add_row("Kuzu", f"{kuzu_single_hop:.3f}")
    table2.add_row("Lattice", f"{lattice_single_hop:.3f}")
    console.print()
    console.print(table2)

    table3 = Table(title=f"Impact traversal latency (seed: {seed_name})")
    table3.add_column("Depth", justify="right")
    table3.add_column("Kuzu ms", justify="right")
    table3.add_column("Kuzu results", justify="right")
    table3.add_column("Lattice ms", justify="right")
    table3.add_column("Lattice results", justify="right")
    for (d, kt, kn), (_, lt, ln) in zip(kuzu_impact, lattice_impact):
        table3.add_row(str(d), f"{kt:.1f}", str(kn), f"{lt:.1f}", str(ln))
    console.print()
    console.print(table3)

    console.print(f"\n[bold]Overall accuracy: {'PASS' if accurate else 'FAIL'}[/bold]")

    kuzu_graph.backend.close()
    lattice_graph.backend.close()


if __name__ == "__main__":
    main()
