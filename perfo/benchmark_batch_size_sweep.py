#!/usr/bin/env python3
"""Does commit cost scale with batch SIZE or with batch COUNT?

Run locally with:

    uv run --python 3.12 --extra dev python perfo/benchmark_batch_size_sweep.py [DIR]

Why this exists
---------------
perfo/benchmark_ingest_stage_balance.py showed the run is write-bound:
committing is ~50% of wall clock, and py-spy attributes 64.6% of commit
self-time to upsert_nodes against 2.2% to upsert_edges. The obvious lever is
"commit in bigger transactions", but that only helps if commit cost is
per-transaction (LatticeDB fsyncs the log on every commit) rather than
per-item (index maintenance, which is paid per row however the rows are
grouped). Those two models predict opposite curves, so measure instead of
arguing.

The confound this script is careful about
-----------------------------------------
There are TWO batch knobs, and until now both were fed by the SAME setting:

- ``upsert_batch_size`` sets the streaming ingest batch target -- how many
  operations the producer accumulates before the writer commits a batch.
- ``_UPSERT_BATCH_SIZE`` in lattice_backend.py chunks each of those batches
  into db.write() transactions.

So raising the ingest target from 1,000 to 8,000 did NOT produce one 8,000-row
transaction; upsert_nodes re-split it into 1,000-row transactions anyway. That
is a large part of why AdaptiveBatchController's choice has so little leverage
on commit time. ``ingest_write_chunk_size`` now separates the two, and this
sweep varies each axis independently:

    --axis ingest  vary the ingest batch target, hold the write chunk fixed
    --axis write   vary the write transaction chunk, hold the ingest target fixed
    --axis both    vary both together (the pre-existing coupled behaviour)

Each configuration runs in a fresh subprocess, because _UPSERT_BATCH_SIZE is
read from Settings at import time. Repeats default to 2 -- this corpus has real
run-to-run variance (baselines have ranged 27.9-33.0s), so a 5% gap is noise.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from statistics import median
from typing import Iterator, List

from rich.console import Console
from rich.table import Table

console = Console()

DEFAULT_SIZES = (500, 1000, 2000, 4000, 8000, 16000)


def _run_one(target: Path) -> dict:
    """One from-scratch build, honouring whatever env the parent set."""
    # Imported here so the module-level constants in lattice_backend pick up
    # the env vars this subprocess was launched with.
    from code_explorer.analyzer.base_analyzer import CodeAnalyzer
    from code_explorer.analyzer.models import FileAnalysis
    from code_explorer.graph.backends.lattice_backend import LatticeBackend
    from code_explorer.graph.graph import DependencyGraph
    from code_explorer.settings import settings

    db_path = Path(os.environ.get("SWEEP_DB", "perfo/bench_batch_sweep.lattice"))
    for stale in db_path.parent.glob(db_path.name + "*"):
        stale.unlink(missing_ok=True)

    backend = LatticeBackend(db_path)
    graph = DependencyGraph(
        db_path=db_path, project_root=target, backend=backend, defer_fts_indexes=True
    )

    wait_times: List[float] = []
    commit_times: List[float] = []

    def timed_stream(analyses: Iterator[FileAnalysis]) -> Iterator[FileAnalysis]:
        iterator = iter(analyses)
        while True:
            started = time.perf_counter()
            try:
                analysis = next(iterator)
            except StopIteration:
                return
            wait_times.append(time.perf_counter() - started)
            yield analysis

    def on_batch_committed(stats: dict) -> None:
        commit_times.append(stats["last_batch_write_ms"] / 1000.0)

    finalize_span = {"start": None, "end": None}

    def on_finalize_progress(_stats: dict) -> None:
        now = time.perf_counter()
        if finalize_span["start"] is None:
            finalize_span["start"] = now
        finalize_span["end"] = now

    analyses = CodeAnalyzer().iter_analyze_directory(
        target, max_workers=settings.analysis_workers
    )

    wall_start = time.perf_counter()
    stats = graph.ingest_analysis_stream(
        timed_stream(analyses),
        batch_size=settings.upsert_batch_size,
        batch_bytes=settings.ingest_batch_bytes,
        assume_new=True,
        adaptive=settings.adaptive_ingest_batching,
        max_batch_size=settings.ingest_batch_max_size,
        calibration_batches=settings.ingest_calibration_batches,
        throughput_tolerance=settings.ingest_throughput_tolerance,
        on_batch_committed=on_batch_committed,
        on_finalize_progress=on_finalize_progress,
    )
    wall = time.perf_counter() - wall_start

    return {
        "wall": wall,
        "committing": sum(commit_times),
        "starved": sum(wait_times),
        "finalizing": (
            finalize_span["end"] - finalize_span["start"]
            if finalize_span["start"] is not None
            else 0.0
        ),
        "batches": stats["batches"],
        "nodes": stats["total_nodes"],
        "edges": stats["total_edges"],
        "calls_resolved": stats["calls_resolved"],
    }


def _spawn(target: Path, *, ingest: int, write: int, db: Path) -> dict:
    env = dict(os.environ)
    env["CODE_EXPLORER_UPSERT_BATCH_SIZE"] = str(ingest)
    env["CODE_EXPLORER_INGEST_WRITE_CHUNK_SIZE"] = str(write)
    # The sweep pins sizes explicitly; the adaptive controller would override
    # them and make every row measure whatever it happened to pick.
    env["CODE_EXPLORER_ADAPTIVE_INGEST_BATCHING"] = "false"
    env["SWEEP_DB"] = str(db)
    proc = subprocess.run(
        [sys.executable, __file__, str(target), "--child"],
        env=env,
        capture_output=True,
        text=True,
    )
    for line in proc.stdout.splitlines():
        if line.startswith("SWEEP_JSON "):
            return json.loads(line[len("SWEEP_JSON ") :])
    raise RuntimeError(
        f"child run failed (rc={proc.returncode})\n"
        f"{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("target", nargs="?", default=".")
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--axis", choices=("ingest", "write", "both"), default="both")
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--sizes", type=int, nargs="+", default=list(DEFAULT_SIZES))
    parser.add_argument(
        "--fixed",
        type=int,
        default=1000,
        help="value held constant on the axis not being swept",
    )
    args = parser.parse_args()
    target = Path(args.target).resolve()

    if args.child:
        print("SWEEP_JSON " + json.dumps(_run_one(target)))
        return

    db = Path("perfo/bench_batch_sweep.lattice")
    rows = []
    for size in args.sizes:
        if args.axis == "ingest":
            ingest, write = size, args.fixed
        elif args.axis == "write":
            ingest, write = args.fixed, size
        else:
            ingest = write = size
        runs = []
        for repeat in range(args.repeats):
            console.print(
                f"[cyan]run[/cyan] axis={args.axis} size={size:,} "
                f"(ingest={ingest:,} write={write:,}) "
                f"repeat={repeat + 1}/{args.repeats}"
            )
            runs.append(_spawn(target, ingest=ingest, write=write, db=db))
        rows.append((size, ingest, write, runs))

    table = Table(title=f"Batch-size sweep ({args.axis}) -- {target.name}")
    table.add_column("Size", justify="right")
    table.add_column("Wall (each)", justify="right")
    table.add_column("Wall med", justify="right")
    table.add_column("Commit (each)", justify="right")
    table.add_column("Commit med", justify="right")
    table.add_column("Batches", justify="right")
    table.add_column("Nodes/Edges/Calls", justify="right")
    for size, _ingest, _write, runs in rows:
        walls = [r["wall"] for r in runs]
        commits = [r["committing"] for r in runs]
        first = runs[0]
        table.add_row(
            f"{size:,}",
            " / ".join(f"{w:.1f}" for w in walls),
            f"{median(walls):.1f}s",
            " / ".join(f"{c:.1f}" for c in commits),
            f"{median(commits):.1f}s",
            f"{first['batches']:,}",
            f"{first['nodes']:,}/{first['edges']:,}/{first['calls_resolved']:,}",
        )
    console.print(table)

    invariants = {
        (r["nodes"], r["edges"], r["calls_resolved"])
        for _s, _i, _w, rs in rows
        for r in rs
    }
    if len(invariants) == 1:
        console.print(
            f"[green]Invariants stable across every run:[/green] {invariants.pop()}"
        )
    else:
        console.print(f"[red]Invariants DIFFER across runs:[/red] {invariants}")

    print("SWEEP_RESULT " + json.dumps(rows))


if __name__ == "__main__":
    main()
