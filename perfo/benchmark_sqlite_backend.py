#!/usr/bin/env python3
"""Measure SqliteBackend on a real corpus, against the recorded LatticeDB
baselines, to answer one question: is SQLite viable as a full-capability
backend for this project?

Run locally with:

    uv run --python 3.12 --extra dev python perfo/benchmark_sqlite_backend.py [DIR]

DIR defaults to /home/pedot/Developpments/gemseo, the corpus the LatticeDB
baselines in the table below were measured on.

WHAT IS AND IS NOT LIKE-FOR-LIKE
--------------------------------
Every read-path number here (reopen, BM25, 1-hop, property lookup, context
assembly) IS directly comparable to the LatticeDB baseline: same corpus,
same public API, same machine.

The BUILD number is NOT. LatticeDB's 27.6s is the streaming ingest path
(graph/lattice_streaming.py), which is LatticeDB-specific -- it batches
through LatticeDB's own bulk primitives and does call resolution inline.
SQLite has no equivalent, so it goes through the generic
DependencyGraph.ingest_results path (graph/ingest.py), which is a different
algorithm doing a different amount of work. Read the two build times as
"both are in the same order of magnitude", not as a head-to-head.

Parse + call-resolution time is reported separately and excluded from the
ingest number precisely because it is backend-independent: it is the same
work for both, and folding it in would flatter whichever backend is slower.
"""

import shutil
import statistics
import sys
import time
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from rich.console import Console
from rich.table import Table

from code_explorer.analyzer.base_analyzer import CodeAnalyzer
from code_explorer.analyzer.call_resolver import CallResolver
from code_explorer.context import ContextAssembler
from code_explorer.graph.backends.sqlite_backend import SqliteBackend
from code_explorer.graph.graph import DependencyGraph

console = Console()
REPO_ROOT = Path(__file__).parent.parent
DEFAULT_TARGET = Path("/home/pedot/Developpments/gemseo")

# Recorded LatticeDB numbers for the same corpus on this machine, so the
# table is self-contained. Build time is the streaming path -- see module
# docstring for why it is not a like-for-like comparison.
LATTICE_BASELINE = {
    "nodes": "15,403",
    "edges": "~36,116",
    "build": "27.6 s (streaming path)",
    "size": "256 MB",
    "reopen": "0.03 s",
    "bm25": "1-46 ms",
    "one_hop": "1.1 ms",
    "prop_lookup": "0.9 ms",
    "context": "4.5 ms",
    "cold_full": "75 ms",
}

BM25_QUERIES = [
    "parse",
    "optimization problem",
    "design space",
    "gradient",
    "execute discipline",
    "json grammar",
]


def timed(fn: Callable[[], object], repeat: int = 1) -> Tuple[float, object]:
    """Return (median ms, last result)."""
    samples = []
    out = None
    for _ in range(repeat):
        t0 = time.perf_counter()
        out = fn()
        samples.append((time.perf_counter() - t0) * 1000)
    return statistics.median(samples), out


def db_size_bytes(db_path: Path) -> int:
    """SQLite's on-disk footprint is the main file plus its -wal/-shm
    sidecars; counting only the main file understates a WAL database that
    has not been checkpointed."""
    return sum(p.stat().st_size for p in db_path.parent.glob(db_path.name + "*"))


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:,.0f} {unit}" if unit == "B" else f"{n / 1:.0f} {unit}"
        n /= 1024.0
    return str(n)


def size_mb(n: int) -> str:
    return f"{n / (1024 * 1024):.0f} MB"


def clean(db_path: Path) -> None:
    if db_path.is_dir():
        shutil.rmtree(db_path, ignore_errors=True)
    for p in db_path.parent.glob(db_path.name + "*"):
        p.unlink(missing_ok=True)


def pick_seed(backend: SqliteBackend) -> Optional[Tuple[str, str]]:
    """Most-called function: the same seed choice perfo/benchmark_backends.py
    makes, so the query-latency rows describe a realistically hot node rather
    than a leaf nobody calls."""
    rows = backend.get_most_called_functions(limit=1)
    if not rows:
        return None
    name, file, _ = rows[0]
    return file, name


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_TARGET
    db_path = REPO_ROOT / "perfo" / "bench_sqlite.db"
    clean(db_path)

    py_files = sum(1 for _ in target.rglob("*.py"))
    console.print(f"[cyan]Corpus[/cyan] {target} ({py_files:,} .py files)")

    console.print("[cyan]Parsing[/cyan] ...")
    t0 = time.perf_counter()
    results = CodeAnalyzer().analyze_directory(target)
    parse_time = time.perf_counter() - t0

    t0 = time.perf_counter()
    resolved_calls = CallResolver(results).resolve_all_calls()
    resolve_time = time.perf_counter() - t0
    console.print(
        f"  parsed {len(results):,} files in {parse_time:.1f}s, "
        f"resolved {len(resolved_calls):,} calls in {resolve_time:.1f}s "
        f"[dim](backend-independent, excluded from the build number)[/dim]"
    )

    # -- build ------------------------------------------------------------
    console.print("[cyan]Building[/cyan] SQLite index (generic ingest_results path) ...")
    backend = SqliteBackend(db_path)
    graph = DependencyGraph(db_path=db_path, project_root=target, backend=backend)
    t0 = time.perf_counter()
    stats = graph.ingest_results(results, resolved_calls=resolved_calls, assume_new=True)
    build_time = time.perf_counter() - t0
    backend.optimize()
    optimize_time_note = ""
    backend.close()
    built_size = db_size_bytes(db_path)

    # -- reopen (clean close) ---------------------------------------------
    # The headline metric. Measured on a backend that was closed cleanly, on
    # a database already built -- the exact situation every CLI invocation
    # after the first is in.
    reopen_samples = []
    for _ in range(5):
        b = SqliteBackend(db_path)
        t0 = time.perf_counter()
        b.open()
        # An open() that defers all work until first use would score 0 and
        # mean nothing, so charge it one trivial read: the first real query
        # a CLI run makes.
        b.conn.execute('SELECT COUNT(*) FROM "Function"').fetchone()
        reopen_samples.append((time.perf_counter() - t0) * 1000)
        b.close()
    reopen_ms = statistics.median(reopen_samples)

    # -- read paths -------------------------------------------------------
    backend = SqliteBackend(db_path)
    graph = DependencyGraph(db_path=db_path, project_root=target, backend=backend)

    seed = pick_seed(backend)
    if seed is None:
        console.print("[red]No CALLS edges -- nothing to benchmark.[/red]")
        return
    seed_file, seed_name = seed
    console.print(f"[dim]seed: {seed_name} in {seed_file}[/dim]")

    bm25_rows = []
    for q in BM25_QUERIES:
        ms, hits = timed(lambda q=q: backend.search_text(q, limit=10), repeat=5)
        bm25_rows.append((q, ms, len(hits)))

    fuzzy_ms, fuzzy_hits = timed(
        lambda: backend.search_text("parze", limit=10, fuzzy=True), repeat=5
    )
    exact_typo = backend.search_text("parze", limit=10)

    seed_id = graph.queries._resolve_function_id(seed_file, seed_name)
    one_hop_ms, edges = timed(
        lambda: backend.get_call_edges_with_lines(seed_id), repeat=20
    )
    callers, callees = edges

    prop_ms, prop_rows = timed(
        lambda: backend.query(
            "MATCH (f:Function {file: $file, name: $name}) "
            "RETURN f.id AS id, f.start_line AS start_line",
            {"file": seed_file, "name": seed_name},
        ),
        repeat=20,
    )

    assembler = ContextAssembler(graph)
    ctx_ms, ctx = timed(
        lambda: assembler.assemble_context(seed_file, seed_name), repeat=10
    )

    most_called_ms, _ = timed(lambda: backend.get_most_called_functions(limit=20), repeat=3)
    backend.close()

    # -- cold in-process: open + search + context --------------------------
    # What a single CLI invocation actually costs end to end.
    cold_samples = []
    for _ in range(3):
        t0 = time.perf_counter()
        b = SqliteBackend(db_path)
        g = DependencyGraph(db_path=db_path, project_root=target, backend=b)
        b.search_text("optimization problem", limit=10)
        ContextAssembler(g).assemble_context(seed_file, seed_name)
        cold_samples.append((time.perf_counter() - t0) * 1000)
        b.close()
    cold_ms = statistics.median(cold_samples)

    # -- report -----------------------------------------------------------
    bm25_lo = min(r[1] for r in bm25_rows)
    bm25_hi = max(r[1] for r in bm25_rows)

    t = Table(title="SQLite vs LatticeDB baseline (same corpus, same machine)")
    t.add_column("Metric")
    t.add_column("LatticeDB", justify="right")
    t.add_column("SQLite", justify="right")
    t.add_row("Nodes / Edges", f"{LATTICE_BASELINE['nodes']} / {LATTICE_BASELINE['edges']}",
              f"{stats['total_nodes']:,} / {stats['total_edges']:,}")
    t.add_row("Full build wall", LATTICE_BASELINE["build"],
              f"{build_time:.1f} s (generic path)")
    t.add_row("Database size", LATTICE_BASELINE["size"], size_mb(built_size))
    t.add_row("Reopen (clean close)", LATTICE_BASELINE["reopen"], f"{reopen_ms:.1f} ms")
    t.add_row("BM25 query", LATTICE_BASELINE["bm25"], f"{bm25_lo:.1f}-{bm25_hi:.1f} ms")
    t.add_row("1-hop callers/callees", LATTICE_BASELINE["one_hop"], f"{one_hop_ms:.2f} ms")
    t.add_row("Indexed property lookup", LATTICE_BASELINE["prop_lookup"], f"{prop_ms:.2f} ms")
    t.add_row("Context assembly", LATTICE_BASELINE["context"], f"{ctx_ms:.2f} ms")
    t.add_row("Open + search + context", LATTICE_BASELINE["cold_full"], f"{cold_ms:.1f} ms")
    console.print()
    console.print(t)

    t2 = Table(title="BM25 detail (median of 5)")
    t2.add_column("Query")
    t2.add_column("ms", justify="right")
    t2.add_column("hits", justify="right")
    for q, ms, n in bm25_rows:
        t2.add_row(q, f"{ms:.1f}", str(n))
    t2.add_row(
        "[dim]'parze' exact (typo)[/dim]", "-", f"{len(exact_typo)} [dim](expected 0)[/dim]"
    )
    t2.add_row("'parze' fuzzy", f"{fuzzy_ms:.1f}", str(len(fuzzy_hits)))
    console.print()
    console.print(t2)

    console.print(
        f"\n[dim]seed {seed_name}: {len(callers)} callers, {len(callees)} callees; "
        f"context bundle: {len(ctx.callers)} callers + {len(ctx.callees)} callees; "
        f"get_most_called_functions(20) = {most_called_ms:.0f} ms; "
        f"parse {parse_time:.1f}s + resolve {resolve_time:.1f}s excluded from build.[/dim]"
    )
    if fuzzy_hits:
        console.print(
            f"[dim]fuzzy top hit for 'parze': {fuzzy_hits[0].name} ({fuzzy_hits[0].file})[/dim]"
        )


if __name__ == "__main__":
    main()
