#!/usr/bin/env python3
"""Measure how far a seed actually reaches, to set context.py's hub cap.

The question this answers: is hub explosion real on a real corpus? A
function with in-degree in the hundreds (every module calls log()) connects
everything to everything and carries no relevance signal, so
ContextAssembler.collect() skips expanding *through* such nodes -- but the
threshold is only defensible if the fan-out curve says so. This script
prints reachable-set size at depth 1/2/3, with and without a cap, over a
sample of seeds, plus wall time per collect.

Run against an index `search` already built (this does NOT build one):

    uv run --python 3.12 --extra dev python perfo/benchmark_fanout.py \\
        /path/to/repo --backend sqlite [--seeds 40] [--depth 3]

Seeds are sampled deterministically across the whole in-degree range (not
just the most-called functions): a hub-heavy sample would make the cap look
free, and a leaf-heavy one would make it look useless.
"""

import argparse
import random
import statistics
import time
from pathlib import Path

from rich.console import Console
from rich.table import Table

from code_explorer.context import ContextAssembler
from code_explorer.graph.graph import DependencyGraph

console = Console()


def _open(target: Path, backend_name: str) -> DependencyGraph:
    if backend_name == "sqlite":
        from code_explorer.graph.backends.sqlite_backend import SqliteBackend

        db_path = target / ".code-explorer" / "graph.sqlite"
        backend = SqliteBackend(db_path)
    else:
        from code_explorer.graph.backends.lattice_backend import LatticeBackend

        db_path = target / ".code-explorer" / "graph.lattice"
        backend = LatticeBackend(db_path)
    if not db_path.exists():
        raise SystemExit(f"No index at {db_path} -- run `code-explorer search` first.")
    return DependencyGraph(db_path=db_path, project_root=target, backend=backend)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    ap.add_argument("--backend", default="sqlite", choices=["sqlite", "lattice"])
    ap.add_argument("--seeds", type=int, default=40)
    ap.add_argument("--depth", type=int, default=3)
    ap.add_argument(
        "--caps",
        default="0,20,60,150",
        help="hub degree caps to compare; 0 means no cap",
    )
    args = ap.parse_args()

    target = args.path.resolve()
    graph = _open(target, args.backend)
    assembler = ContextAssembler(graph)

    rows = graph.backend.query(
        "MATCH (f:Function) RETURN f.id AS id, f.name AS name, f.file AS file"
    )
    console.print(f"[cyan]{len(rows):,}[/cyan] Function nodes in {target}")
    rng = random.Random(1234)
    seeds = rng.sample(rows, min(args.seeds, len(rows)))

    caps = [int(c) for c in args.caps.split(",")]
    table = Table(title=f"Reachable-set size over {len(seeds)} seeds")
    table.add_column("hub cap")
    table.add_column("depth")
    table.add_column("median", justify="right")
    table.add_column("p90", justify="right")
    table.add_column("max", justify="right")
    table.add_column("mean ms", justify="right")

    for cap in caps:
        for depth in range(1, args.depth + 1):
            sizes = []
            elapsed = []
            for seed in seeds:
                t0 = time.perf_counter()
                reached = assembler.collect(
                    seed["id"], "Function", depth=depth, hub_degree=cap
                )
                elapsed.append((time.perf_counter() - t0) * 1000)
                sizes.append(len(reached))
            sizes.sort()
            p90 = sizes[min(int(len(sizes) * 0.9), len(sizes) - 1)]
            table.add_row(
                "none" if cap == 0 else str(cap),
                str(depth),
                f"{statistics.median(sizes):.0f}",
                str(p90),
                str(max(sizes)),
                f"{statistics.mean(elapsed):.0f}",
            )
    console.print(table)
    graph.backend.close()


if __name__ == "__main__":
    main()
