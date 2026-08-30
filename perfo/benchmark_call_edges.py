#!/usr/bin/env python3
"""Compare Cypher MATCH vs. LatticeDB's imperative edge API for the exact
query get_callers()/get_callees() need: "who calls/is called by this
function." This is the discovery behind
docs/explanation/latticedb-migration.md's Performance Findings section --
run this yourself to see it, don't just take the doc's word for it.

Run locally with:

    uv run --python 3.12 --extra dev python perfo/benchmark_call_edges.py [DIR]

On a small DIR the two approaches look similar. The gap is a real
per-Cypher-query planner cost (see the doc for why: MATCH (a)-[:TYPE]->(b)
compiles to Expand<-LabelScan(label), scanning every node with that label
before expanding edges) that only shows up at real scale -- try it against
a large external repo (e.g. clone a big Python monorepo) to see the actual
gap this session found (15.3s -> 0.12ms on a 338K-edge graph).
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


def _old_cypher_call_edges(backend, function_canonical_id: str):
    """The pre-fix approach: two Cypher MATCH queries, one per direction."""
    callers = backend.query(
        "MATCH (caller:Function)-[c:CALLS]->(callee:Function {id: $id}) "
        "RETURN caller.file AS file, caller.name AS name, c.call_line AS call_line",
        {"id": function_canonical_id},
    )
    callees = backend.query(
        "MATCH (caller:Function {id: $id})-[c:CALLS]->(callee:Function) "
        "RETURN callee.file AS file, callee.name AS name, c.call_line AS call_line",
        {"id": function_canonical_id},
    )
    return callers, callees


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "src" / "code_explorer"

    console.print(f"[cyan]Parsing[/cyan] {target} ...")
    results = CodeAnalyzer().analyze_directory(target)
    resolved_calls = CallResolver(results).resolve_all_calls()

    db_path = REPO_ROOT / "perfo" / "bench_call_edges.lattice"
    _clean(db_path)
    graph = DependencyGraph(
        db_path=db_path, project_root=target, backend=LatticeBackend(db_path)
    )
    graph.ingest_results(results, resolved_calls=resolved_calls, assume_new=True)

    # Most-called function, unambiguous (file, name) -- same pattern as the
    # other perfo scripts.
    rows = graph.backend.query(
        "MATCH (callee:Function) "
        "WITH callee.file AS file, callee.name AS name, COUNT(callee) AS n_defs "
        "WHERE n_defs = 1 "
        "MATCH (caller:Function)-[:CALLS]->(callee2:Function {file: file, name: name}) "
        "RETURN callee2.id AS id, name, COUNT(caller) AS n "
        "ORDER BY n DESC LIMIT 1"
    )
    if not rows:
        console.print("[yellow]No unambiguous seed found -- nothing to benchmark.[/yellow]")
        graph.backend.close()
        return
    seed_id, seed_name, n_callers = rows[0]["id"], rows[0]["name"], rows[0]["n"]
    console.print(f"Seed: {seed_name} ({n_callers} callers)\n")

    t0 = time.perf_counter()
    old_callers, old_callees = _old_cypher_call_edges(graph.backend, seed_id)
    t_cypher = time.perf_counter() - t0

    t0 = time.perf_counter()
    new_callers, new_callees = graph.backend.get_call_edges_with_lines(seed_id)
    t_imperative = time.perf_counter() - t0

    assert len(old_callers) == len(new_callers), "result count mismatch -- something's wrong"
    assert len(old_callees) == len(new_callees), "result count mismatch -- something's wrong"

    table = Table(title="get_call_edges: Cypher MATCH vs. imperative get_incoming/outgoing_edges")
    table.add_column("Approach")
    table.add_column("Time", justify="right")
    table.add_row("Cypher MATCH (old)", f"{t_cypher * 1000:.2f}ms")
    table.add_row("Imperative API (current)", f"{t_imperative * 1000:.2f}ms")
    if t_imperative > 0:
        table.add_row("Speedup", f"{t_cypher / t_imperative:.1f}x")
    console.print(table)
    console.print(f"\nBoth found {len(new_callers)} callers, {len(new_callees)} callees -- same result, different cost.")

    graph.backend.close()
    _clean(db_path)


if __name__ == "__main__":
    main()
