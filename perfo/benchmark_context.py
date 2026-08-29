#!/usr/bin/env python3
"""Small benchmark for context.py's LLM context assembly.

Run locally with:

    uv run --python 3.12 --extra dev python perfo/benchmark_context.py [DIR]

Parses DIR (defaults to this repo's own src/code_explorer), ingests into a
fresh KuzuBackend, picks the most-called function as the seed (same pattern
as perfo/index_with_lattice.py and perfo/benchmark_backends.py), times
ContextAssembler.assemble_context(), and prints the rendered markdown so the
actual output quality can be inspected, not just a timing number.
"""

import sys
import time
from pathlib import Path

from rich.console import Console

from code_explorer.analyzer.base_analyzer import CodeAnalyzer
from code_explorer.analyzer.call_resolver import CallResolver
from code_explorer.context import ContextAssembler
from code_explorer.graph.backends.kuzu_backend import KuzuBackend
from code_explorer.graph.graph import DependencyGraph

console = Console()
REPO_ROOT = Path(__file__).parent.parent


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "src" / "code_explorer"
    db_path = REPO_ROOT / "perfo" / "bench_context.db"

    console.print(f"[cyan]Parsing[/cyan] {target} ...")
    results = CodeAnalyzer().analyze_directory(target)
    resolved_calls = CallResolver(results).resolve_all_calls()

    graph = DependencyGraph(db_path=db_path, project_root=target, backend=KuzuBackend(db_path))
    graph.backend.clear_all()
    graph.ingest_results(results, resolved_calls=resolved_calls)

    # Pick the most-called function as the seed, but only among (file, name)
    # pairs that resolve to exactly one Function node. get_callers/get_callees
    # (graph/queries.py) match Function by (file, name) only, not the unique
    # id -- when two distinct functions share a name in the same file (e.g.
    # same-named methods on different classes), that query conflates them,
    # producing garbled/duplicated results. This is a real, pre-existing bug
    # in the query layer (flagged separately), not something to silently
    # demo here -- so the benchmark picks an unambiguous seed instead.
    rows = graph.backend.query(
        "MATCH (callee:Function) "
        "WITH callee.file AS file, callee.name AS name, COUNT(callee) AS n_defs "
        "WHERE n_defs = 1 "
        "MATCH (caller:Function)-[:CALLS]->(callee2:Function {file: file, name: name}) "
        "RETURN file, name, COUNT(caller) AS n "
        "ORDER BY n DESC LIMIT 1"
    )
    if not rows:
        console.print("[yellow]No unambiguous CALLS edges found -- nothing to benchmark.[/yellow]")
        graph.backend.close()
        return
    seed = rows[0]

    t0 = time.perf_counter()
    ctx = ContextAssembler(graph).assemble_context(seed["file"], seed["name"], max_nodes=20)
    elapsed = (time.perf_counter() - t0) * 1000

    console.print(
        f"[cyan]assemble_context[/cyan] for {seed['name']} ({seed['file']}): "
        f"{elapsed:.1f}ms -- {1 + len(ctx.callers) + len(ctx.callees)} node(s), "
        f"{ctx.callers_truncated + ctx.callees_truncated} truncated"
    )
    console.print()
    console.print(ctx.to_markdown())

    graph.backend.close()


if __name__ == "__main__":
    main()
