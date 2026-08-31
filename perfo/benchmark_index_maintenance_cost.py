#!/usr/bin/env python3
"""How much of ingestion is index maintenance, not data writing?

Run locally with:

    uv run --python 3.12 --extra dev python perfo/benchmark_index_maintenance_cost.py [DIR]

Profiling a gemseo index build showed `commit` at 53.6% of CPU self-time, and
attributing those samples to their callers showed 64.6% of commit time under
upsert_nodes versus 2.2% under upsert_edges -- roughly a 30x asymmetry. The
structural difference between the two is how many indexes each write maintains:

- Function nodes: property indexes on id, file, name, module, parent_class
  (five), plus the BM25 FTS index on search_text.
- CALLS edges: one property index on call_reference_id.

LatticeDB's docs state every declared index "is maintained on every write that
touches its property", and its README notes a "repeated-term FTS indexing
workload that previously exposed quadratic append behavior" -- code text is
exactly that workload (every search_text repeats path components, `self`, and
common identifiers).

This isolates the cost by building the same corpus three ways: everything on,
FTS index omitted, and the low-selectivity property indexes omitted too. The
graph contents are identical in each case -- only which indexes exist changes.
Search is unusable without the FTS index, so a win here is an argument for
deferring index creation until after bulk load, not for dropping it.
"""

import sys
import time
from pathlib import Path
from typing import Dict, List

from rich.console import Console
from rich.table import Table

from code_explorer.analyzer.base_analyzer import CodeAnalyzer
from code_explorer.graph.backends import lattice_backend as lb
from code_explorer.graph.backends.lattice_backend import LatticeBackend
from code_explorer.graph.graph import DependencyGraph
from code_explorer.settings import settings

console = Console()

# Property indexes LatticeBackend.initialize_schema declares on Function beyond
# its primary key. `parent_class` is the low-selectivity one -- most functions
# are module-level, so the overwhelming majority of values are the empty string,
# and LatticeDB's Property Indexes guide warns that an index over few distinct
# values "only narrows to a third, which a scan would have managed nearly as
# fast" while still costing write work on every insert.
OPTIONAL_FUNCTION_INDEXES = ("name", "module", "parent_class")


def build(target: Path, db_path: Path, *, fts: bool, extra_indexes: bool) -> Dict[str, float]:
    for stale in db_path.parent.glob(db_path.name + "*"):
        stale.unlink(missing_ok=True)

    original_fts = dict(lb.SEARCHABLE_TEXT_FIELDS)
    original_ensure = LatticeBackend._ensure_node_property_index

    if not fts:
        lb.SEARCHABLE_TEXT_FIELDS.clear()

    if not extra_indexes:
        def _skip_optional(self, label: str, prop: str) -> None:
            if label == "Function" and prop in OPTIONAL_FUNCTION_INDEXES:
                return
            original_ensure(self, label, prop)

        LatticeBackend._ensure_node_property_index = _skip_optional

    try:
        backend = LatticeBackend(db_path)
        graph = DependencyGraph(db_path=db_path, project_root=target, backend=backend)

        commit_seconds: List[float] = []

        def on_batch_committed(stats: dict) -> None:
            commit_seconds.append(stats["last_batch_write_ms"] / 1000.0)

        analyses = CodeAnalyzer().iter_analyze_directory(
            target, max_workers=settings.analysis_workers
        )
        started = time.perf_counter()
        stats = graph.ingest_analysis_stream(
            analyses,
            batch_size=settings.upsert_batch_size,
            batch_bytes=settings.ingest_batch_bytes,
            assume_new=True,
            adaptive=False,
            on_batch_committed=on_batch_committed,
        )
        wall = time.perf_counter() - started
        backend.close()
    finally:
        lb.SEARCHABLE_TEXT_FIELDS.clear()
        lb.SEARCHABLE_TEXT_FIELDS.update(original_fts)
        LatticeBackend._ensure_node_property_index = original_ensure

    size_mb = sum(
        f.stat().st_size for f in db_path.parent.glob(db_path.name + "*")
    ) / (1024 * 1024)

    return {
        "wall": wall,
        "commit": sum(commit_seconds),
        "nodes": stats["total_nodes"],
        "edges": stats["total_edges"],
        "size_mb": size_mb,
    }


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    db_path = Path("perfo/bench_index_cost.lattice")

    # Only the FTS index is actually optional. Dropping the name/module/
    # parent_class property indexes raises LatticeUnsupportedError as soon as
    # _resolve_references looks a candidate up: LatticeDB refuses an indexless
    # lookup rather than silently falling back to a scan (documented behaviour,
    # confirmed by trying it). So the low-selectivity `parent_class` index is a
    # write-time cost we cannot simply remove -- it would have to be replaced by
    # a different resolution strategy, not deleted.
    scenarios = [
        ("all indexes (current)", True, True),
        ("no FTS index", False, True),
    ]

    table = Table(title=f"Index maintenance cost -- {target.name}")
    table.add_column("Configuration")
    table.add_column("Wall", justify="right")
    table.add_column("Commit", justify="right")
    table.add_column("DB size", justify="right")
    table.add_column("vs baseline", justify="right")

    baseline = None
    for label, fts, extra in scenarios:
        console.print(f"[cyan]Building[/cyan] {label} ...")
        result = build(target, db_path, fts=fts, extra_indexes=extra)
        if baseline is None:
            baseline = result["wall"]
            delta = "--"
        else:
            delta = f"{baseline / result['wall']:.2f}x faster"
        table.add_row(
            label,
            f"{result['wall']:.1f}s",
            f"{result['commit']:.1f}s",
            f"{result['size_mb']:.0f} MB",
            delta,
        )
        # Print each row as it lands: a later scenario blowing up should not
        # take the earlier measurements with it.
        console.print(
            f"[green]  {label}:[/green] wall {result['wall']:.1f}s, "
            f"commit {result['commit']:.1f}s, {result['size_mb']:.0f} MB, "
            f"{result['nodes']:,} nodes, {result['edges']:,} edges"
        )

    console.print(table)
    console.print(
        "[dim]Identical graph contents in every row -- only index declarations "
        "differ. A large gap means ingestion is dominated by index maintenance, "
        "which argues for building indexes after bulk load rather than "
        "maintaining them per write.[/dim]"
    )


if __name__ == "__main__":
    main()
