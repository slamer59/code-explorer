#!/usr/bin/env python3
"""Small benchmark for CodeGraphBackend.search_text() (BM25) on real code.

Run locally with:

    uv run --python 3.12 --extra dev python perfo/benchmark_search.py [DIR]

DIR defaults to this repo's own src/code_explorer. Parses -> ingests into a
fresh LatticeBackend -> runs a handful of representative natural-language-ish
queries and prints each one's latency + top result. Kept small on purpose --
this proves search actually works end to end on real ingested data, it's not
a full search-quality benchmark.
"""

import sys
import time
from pathlib import Path

from rich.console import Console
from rich.table import Table

from code_explorer.analyzer.base_analyzer import CodeAnalyzer
from code_explorer.graph.backends.lattice_backend import LatticeBackend
from code_explorer.graph.graph import DependencyGraph

console = Console()
REPO_ROOT = Path(__file__).parent.parent

QUERIES = [
    "parse file",
    "extract function",
    "resolve call",
    "walk tree",
    "detect language",
]


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "src" / "code_explorer"
    db_path = REPO_ROOT / "perfo" / "search_bench.lattice"
    # LatticeDB's db_path is a single file with sidecar files (e.g. .lattice-wal),
    # not a directory -- shutil.rmtree silently no-ops on a plain file.
    for stale in db_path.parent.glob(db_path.name + "*"):
        stale.unlink(missing_ok=True)

    console.print(f"[cyan]Parsing[/cyan] {target} ...")
    results = CodeAnalyzer().analyze_directory(target)

    graph = DependencyGraph(
        db_path=db_path, project_root=target, backend=LatticeBackend(db_path)
    )
    stats = graph.ingest_results(results)
    console.print(f"Indexed {stats['total_nodes']:,} nodes, {stats['total_edges']:,} edges.\n")

    table = Table(title="BM25 search_text() latency + top result")
    table.add_column("Query")
    table.add_column("ms", justify="right")
    table.add_column("Top result")
    for q in QUERIES:
        t0 = time.perf_counter()
        hits = graph.backend.search_text(q, limit=3)
        elapsed = (time.perf_counter() - t0) * 1000
        top = f"{hits[0].name} ({hits[0].file})" if hits else "[dim]no match[/dim]"
        table.add_row(q, f"{elapsed:.2f}", top)
    console.print(table)

    graph.backend.close()


if __name__ == "__main__":
    main()
