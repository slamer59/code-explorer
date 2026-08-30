#!/usr/bin/env python3
"""Compare ContextAssembler's query count/latency before vs. after batching
callers/callees resolution into get_callers_and_callees_with_lines().

Run locally with:

    uv run --python 3.12 --extra dev python perfo/benchmark_context_speed.py [DIR]

"Before" replicates the original N+1 pattern directly (get_callers() +
get_callees(), each re-resolving the function id, then one extra query per
caller/callee just to fetch its line range) -- that code no longer exists
in context.py (it was replaced, not kept as a toggle), so this
reconstructs it here specifically to keep this comparison honest and
reproducible instead of only asserting the improvement in prose.
"""

import sys
import time
from pathlib import Path

from rich.console import Console
from rich.table import Table

from code_explorer.analyzer.base_analyzer import CodeAnalyzer
from code_explorer.analyzer.call_resolver import CallResolver
from code_explorer.context import ContextAssembler
from code_explorer.graph.backends.lattice_backend import LatticeBackend
from code_explorer.graph.graph import DependencyGraph
from code_explorer.source_provider import FilesystemSourceProvider

console = Console()
REPO_ROOT = Path(__file__).parent.parent


def _clean(db_path: Path) -> None:
    for stale in db_path.parent.glob(db_path.name + "*"):
        stale.unlink(missing_ok=True)


def _counting_query(graph):
    """Wrap graph.backend.query to count calls, return the counter list."""
    orig = graph.backend.query
    count = [0]

    def wrapped(*a, **kw):
        count[0] += 1
        return orig(*a, **kw)

    graph.backend.query = wrapped
    return count


def _old_assemble_context(graph, source_provider, file, function, max_nodes=20):
    """Reconstruction of the pre-optimization N+1 pattern: separate
    get_callers()/get_callees() calls (each re-resolving the function id),
    then one query per caller/callee to fetch its line range."""
    rel_file = graph._to_relative_path(file)
    rows = graph.backend.query(
        "MATCH (f:Function {file: $file, name: $name}) "
        "RETURN f.start_line AS start_line, f.end_line AS end_line",
        {"file": rel_file, "name": function},
    )
    if not rows:
        raise ValueError(f"Function not found: {file}::{function}")
    seed_start, seed_end = rows[0]["start_line"], rows[0]["end_line"]
    source_provider.get_range(rel_file, seed_start, seed_end)

    caller_rows = graph.get_callers(file, function)
    callee_rows = graph.get_callees(file, function)

    remaining = max(max_nodes - 1, 0)
    callee_budget = remaining // 2
    caller_budget = remaining - callee_budget

    for row_file, row_name, _line in (caller_rows[:caller_budget] + callee_rows[:callee_budget]):
        r = graph.backend.query(
            "MATCH (f:Function {file: $file, name: $name}) "
            "RETURN f.start_line AS start_line, f.end_line AS end_line",
            {"file": row_file, "name": row_name},
        )
        if r:
            source_provider.get_range(row_file, r[0]["start_line"], r[0]["end_line"])


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "src" / "code_explorer"

    console.print(f"[cyan]Parsing[/cyan] {target} ...")
    results = CodeAnalyzer().analyze_directory(target)
    resolved_calls = CallResolver(results).resolve_all_calls()

    db_path = REPO_ROOT / "perfo" / "bench_context_speed.lattice"
    _clean(db_path)
    graph = DependencyGraph(
        db_path=db_path, project_root=target, backend=LatticeBackend(db_path)
    )
    graph.ingest_results(results, resolved_calls=resolved_calls, assume_new=True)

    # Pick the most-called function as the seed, same pattern as the other
    # perfo scripts, avoiding the (file, name) ambiguity case (see
    # perfo/benchmark_context.py's seed-selection comment for why).
    rows = graph.backend.query(
        "MATCH (callee:Function) "
        "WITH callee.file AS file, callee.name AS name, COUNT(callee) AS n_defs "
        "WHERE n_defs = 1 "
        "MATCH (caller:Function)-[:CALLS]->(callee2:Function {file: file, name: name}) "
        "RETURN file, name, COUNT(caller) AS n "
        "ORDER BY n DESC LIMIT 1"
    )
    if not rows:
        console.print("[yellow]No unambiguous seed found -- nothing to benchmark.[/yellow]")
        return
    seed_file, seed_name = rows[0]["file"], rows[0]["name"]
    console.print(f"Seed: {seed_file}::{seed_name}\n")

    source_provider = FilesystemSourceProvider(target)

    count_old = _counting_query(graph)
    t0 = time.perf_counter()
    _old_assemble_context(graph, source_provider, seed_file, seed_name)
    t_old = time.perf_counter() - t0
    n_queries_old = count_old[0]
    graph.backend.close()

    # Fresh backend connection for the "after" measurement -- LatticeDB is
    # single-writer, so reuse the same closed-then-reopened file rather than
    # holding two connections to it open at once.
    graph2 = DependencyGraph(db_path=db_path, project_root=target, backend=LatticeBackend(db_path))
    count_new = _counting_query(graph2)
    t0 = time.perf_counter()
    ContextAssembler(graph2, source_provider=source_provider).assemble_context(seed_file, seed_name)
    t_new = time.perf_counter() - t0
    n_queries_new = count_new[0]

    table = Table(title="ContextAssembler: before vs. after batching callers/callees")
    table.add_column("Version")
    table.add_column("Cypher queries", justify="right")
    table.add_column("Time", justify="right")
    table.add_row("Before (N+1 pattern, reconstructed)", str(n_queries_old), f"{t_old * 1000:.1f}ms")
    table.add_row("After (get_callers_and_callees_with_lines)", str(n_queries_new), f"{t_new * 1000:.1f}ms")
    if t_new > 0:
        table.add_row("Speedup", "", f"{t_old / t_new:.2f}x")
    console.print(table)

    graph2.backend.close()
    _clean(db_path)


if __name__ == "__main__":
    main()
