#!/usr/bin/env python3
"""How good is call resolution -- and is the unresolved remainder legitimate?

Run against an index already built by perfo/benchmark_ingest_stage_balance.py:

    uv run --python 3.12 --extra dev python perfo/benchmark_call_resolution_quality.py [DB_PATH]

The import-aware resolver refuses to guess: a call it cannot pin down is left
in UNRESOLVED_CALL_STREAM rather than linked to every same-named function (the
old CallResolver's behavior, which produced a large spurious fan-out). That is
the right instinct, but it trades one failure mode for another, so the ratio
alone doesn't tell you whether resolution is good.

The question that does: of the calls left unresolved, how many name a function
that actually exists in this graph? Those are potential *missed* edges. Calls
naming something absent (stdlib, third-party, builtins) are correctly
unresolved and should not count against the resolver.

Uses the imperative get_nodes_by_label/get_property API rather than Cypher --
a `MATCH (f:Function) RETURN f.name` label scan is markedly slower here (see
docs/explanation/latticedb-migration.md's performance findings).
"""

import sys
import time
from collections import Counter
from pathlib import Path

from rich.console import Console
from rich.table import Table

from code_explorer.graph.backends.lattice_backend import (
    UNRESOLVED_CALL_STREAM,
    LatticeBackend,
)

console = Console()

SAMPLE_LIMIT = 4000


def main() -> None:
    db_path = Path(sys.argv[1] if len(sys.argv) > 1 else "perfo/bench_stage_balance.lattice")
    if not db_path.exists():
        console.print(
            f"[red]No index at {db_path}[/red] -- run "
            "perfo/benchmark_ingest_stage_balance.py first."
        )
        sys.exit(1)

    backend = LatticeBackend(db_path)
    backend.open()

    t0 = time.perf_counter()
    node_ids = backend.db.get_nodes_by_label("Function")
    known: set[str] = set()
    with backend.db.read() as txn:
        for node_id in node_ids:
            name = txn.get_property(node_id, "name")
            if name:
                known.add(name)
    console.print(
        f"[dim]{len(node_ids):,} Function nodes, {len(known):,} distinct names "
        f"({time.perf_counter() - t0:.1f}s)[/dim]"
    )

    after = 0
    total = missed = external = 0
    statuses: Counter = Counter()
    missed_names: Counter = Counter()

    t1 = time.perf_counter()
    page_times = []
    while total < SAMPLE_LIMIT:
        page_start = time.perf_counter()
        records = backend.db.read_stream(
            UNRESOLVED_CALL_STREAM, after_sequence=after, limit=500
        )
        page_times.append(time.perf_counter() - page_start)
        if not records:
            break
        for record in records:
            payload = record.payload
            total += 1
            statuses[payload.get("status", "unknown")] += 1
            name = payload.get("target_name") or payload.get("called_name")
            if name in known:
                missed += 1
                missed_names[name] += 1
            else:
                external += 1
        after = records[-1].sequence

    table = Table(title="Unresolved call breakdown (sampled)")
    table.add_column("Measure")
    table.add_column("Value", justify="right")
    table.add_row("Sampled unresolved refs", f"{total:,}")
    table.add_row(
        "Names a function in this graph (missed link)",
        f"{missed:,} ({missed / max(total, 1) * 100:.1f}%)",
    )
    table.add_row(
        "Names something absent (external -- correct)",
        f"{external:,} ({external / max(total, 1) * 100:.1f}%)",
    )
    for status, count in statuses.most_common():
        table.add_row(f"  status={status}", f"{count:,}")
    console.print(table)

    if page_times:
        console.print(
            f"[dim]stream paging: {len(page_times)} pages, first "
            f"{page_times[0] * 1000:.0f}ms, last {page_times[-1] * 1000:.0f}ms, "
            f"total {sum(page_times):.1f}s[/dim]"
        )
        # If per-page cost grows with after_sequence, read_stream is rescanning
        # from the head each call -- that makes _finalize_pending quadratic in
        # the number of pending calls, which is the scaling risk at 100k files.
        if len(page_times) >= 4 and page_times[-1] > page_times[0] * 3:
            console.print(
                "[yellow]Warning:[/yellow] per-page read_stream cost grows with "
                "offset -- the finalize drain looks quadratic in pending-call "
                "count, not linear."
            )

    console.print(f"\n[cyan]Top missed targets:[/cyan] {missed_names.most_common(12)}")
    console.print(f"[dim]scan took {time.perf_counter() - t1:.1f}s[/dim]")
    backend.close()


if __name__ == "__main__":
    main()
