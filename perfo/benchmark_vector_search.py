#!/usr/bin/env python3
"""Small benchmark for CodeGraphBackend.search_vector() (semantic search) on
real code, backed by a local Ollama server.

Run locally with:

    uv run --python 3.12 --extra dev python perfo/benchmark_vector_search.py

Requires Ollama running locally with nomic-embed-text pulled
(see src/code_explorer/embeddings.py). Indexes a small subset of this
repo's own source (context.py + impact.py, not the whole tree -- embedding
is one Ollama HTTP call per node, kept small so this runs quickly), then
runs a few conceptual queries phrased to share no keywords with the code,
and prints embedding time, search latency, and top results -- proving
semantic ranking actually distinguishes related from unrelated code, not
just that the API call succeeds.
"""

import shutil
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
    "how do we get a new access credential after it expires",
    "walking a syntax tree recursively",
    "cap the number of results to a fixed budget",
]


def main() -> None:
    target = REPO_ROOT / "src" / "code_explorer"
    files = [target / "context.py", target / "impact.py"]

    db_path = REPO_ROOT / "perfo" / "vector_bench.lattice"
    for stale in db_path.parent.glob(db_path.name + "*"):
        stale.unlink(missing_ok=True)

    console.print(f"[cyan]Parsing[/cyan] {[f.name for f in files]} ...")
    results = [CodeAnalyzer().analyze_file(f) for f in files]

    graph = DependencyGraph(
        db_path=db_path,
        project_root=target,
        backend=LatticeBackend(db_path, enable_vectors=True, vector_dimensions=768),
    )
    stats = graph.ingest_results(results)
    console.print(f"Indexed {stats['total_nodes']:,} nodes, {stats['total_edges']:,} edges.")

    console.print("[cyan]Generating embeddings via local Ollama[/cyan] ...")
    t0 = time.perf_counter()
    n = graph.backend.build_vector_index()
    embed_time = time.perf_counter() - t0
    console.print(
        f"Embedded {n} nodes in {embed_time:.2f}s "
        f"({embed_time / n * 1000:.0f}ms/node)\n" if n else "No nodes embedded.\n"
    )

    table = Table(title="Semantic search_vector() latency + top results (no shared keywords)")
    table.add_column("Query")
    table.add_column("ms", justify="right")
    table.add_column("Top 2 results (name -- distance)")
    for q in QUERIES:
        t0 = time.perf_counter()
        hits = graph.backend.search_vector(q, limit=2)
        elapsed = (time.perf_counter() - t0) * 1000
        top = "\n".join(f"{h.name} -- {h.score:.3f}" for h in hits) if hits else "[dim]no match[/dim]"
        table.add_row(q, f"{elapsed:.1f}", top)
    console.print(table)

    graph.backend.close()


if __name__ == "__main__":
    main()
