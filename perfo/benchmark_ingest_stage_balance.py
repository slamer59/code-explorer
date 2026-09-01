#!/usr/bin/env python3
"""Which stage is the ingestion bottleneck: parsing, or graph writing?

Run locally with:

    uv run --python 3.12 --extra dev python perfo/benchmark_ingest_stage_balance.py [DIR]

The streaming pipeline overlaps CPU-bound parsing (worker processes) with the
single-writer graph commit loop (main thread). Whichever side is slower sets
wall-clock; the other one idles. That matters for tuning decisions:

- If the CONSUMER STARVES (main thread blocked waiting for the next parsed
  file), the pipeline is parser-bound. Tuning write batch size -- what
  AdaptiveBatchController does -- optimizes a stage that already has slack,
  and larger batches only raise peak RAM and delay the first commit.
- If the WRITER DOMINATES (main thread busy committing while workers queue up
  behind the bounded window), the pipeline is write-bound and batch-size
  tuning is the right lever.

This measures the split directly by wrapping the analysis iterator and timing
how long each `next()` blocks (starvation) versus how long each batch commit
takes (write work).
"""

import sys
import time
from pathlib import Path
from typing import Iterator, List

from rich.console import Console
from rich.table import Table

from code_explorer.analyzer.base_analyzer import CodeAnalyzer
from code_explorer.analyzer.models import FileAnalysis
from code_explorer.graph.backends.lattice_backend import LatticeBackend
from code_explorer.graph.graph import DependencyGraph
from code_explorer.settings import settings

console = Console()


def timed_stream(analyses: Iterator[FileAnalysis], wait_times: List[float]) -> Iterator[FileAnalysis]:
    """Yield analyses, recording how long the consumer blocked for each one.

    A large total here means worker processes could not keep the consumer fed
    -- i.e. parsing, not writing, is the constraint.
    """
    iterator = iter(analyses)
    while True:
        started = time.perf_counter()
        try:
            analysis = next(iterator)
        except StopIteration:
            return
        wait_times.append(time.perf_counter() - started)
        yield analysis


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    db_path = Path("perfo/bench_stage_balance.lattice")
    for stale in db_path.parent.glob(db_path.name + "*"):
        stale.unlink(missing_ok=True)

    console.print(f"[cyan]Indexing[/cyan] {target} (workers={settings.analysis_workers}) ...")

    backend = LatticeBackend(db_path)
    # Matches the CLI's from-scratch build path (the db is wiped just above):
    # BM25 indexes are built once after ingestion, not maintained per write.
    graph = DependencyGraph(
        db_path=db_path, project_root=target, backend=backend, defer_fts_indexes=True
    )

    wait_times: List[float] = []
    commit_times: List[float] = []

    def on_batch_committed(stats: dict) -> None:
        commit_times.append(stats["last_batch_write_ms"] / 1000.0)

    # The finalize pass (draining PENDING_CALL_STREAM and re-resolving) runs
    # after the last batch and is invisible to on_batch_committed -- time it
    # separately, since on a call-heavy repo it can rival the batch phase.
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
        timed_stream(analyses, wait_times),
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

    starvation = sum(wait_times)
    committing = sum(commit_times)
    finalizing = (
        finalize_span["end"] - finalize_span["start"]
        if finalize_span["start"] is not None
        else 0.0
    )

    table = Table(title=f"Ingestion stage balance -- {target.name}")
    table.add_column("Measure", justify="left")
    table.add_column("Value", justify="right")
    table.add_row("Files", f"{stats['files']:,}")
    table.add_row("Nodes", f"{stats['total_nodes']:,}")
    table.add_row("Edges", f"{stats['total_edges']:,}")
    table.add_row("Calls resolved", f"{stats['calls_resolved']:,}")
    table.add_row("Calls unresolved", f"{stats['calls_unresolved']:,}")
    table.add_row("Batches", f"{stats['batches']:,}")
    table.add_row("Selected batch size", f"{stats['selected_batch_size']:,}")
    table.add_row("", "")
    table.add_row("Wall clock", f"{wall:.1f}s")
    table.add_row("Consumer starved (waiting on parse)", f"{starvation:.1f}s  ({starvation / wall * 100:.0f}%)")
    table.add_row("Committing batches (write work)", f"{committing:.1f}s  ({committing / wall * 100:.0f}%)")
    table.add_row("Finalize pass (pending-call drain)", f"{finalizing:.1f}s  ({finalizing / wall * 100:.0f}%)")
    console.print(table)

    if stats["calls_unresolved"] > stats["calls_resolved"]:
        console.print(
            f"[yellow]Note:[/yellow] {stats['calls_unresolved']:,} calls left "
            f"unresolved vs {stats['calls_resolved']:,} resolved. Some of that is "
            "correct (stdlib/third-party targets have no node to point at), but a "
            "high ratio also inflates the finalize pass, which re-examines every "
            "pending reference. See perfo/benchmark_call_resolution_quality.py."
        )

    if starvation > committing * 2:
        console.print(
            "[yellow]Parser-bound.[/yellow] The writer spends most of its time "
            "waiting for parsed files. Write batch-size tuning optimizes a stage "
            "that already has slack -- add parser workers (or reduce per-file "
            "parse cost) to move wall-clock."
        )
    elif committing > starvation * 2:
        console.print(
            "[yellow]Write-bound.[/yellow] Workers can outrun the writer, so "
            "batch-size/commit tuning is the correct lever."
        )
    else:
        console.print(
            "[green]Balanced.[/green] Neither stage dominates; the overlap is "
            "doing its job."
        )


if __name__ == "__main__":
    main()
