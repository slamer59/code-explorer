#!/usr/bin/env python3
"""Compare LatticeDB index size: compact search_text vs. full source_code.

Run locally with:

    uv run --python 3.12 --extra dev python perfo/benchmark_index_size.py [DIR]

The whole point of docs/explanation/source-of-truth-and-search-representations.md
is a smaller index -- this indexes the same directory twice (once with the
default compact search_text, once with include_source=True, the old
behavior) and reports the resulting file sizes side by side.
"""

import sys
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


def _index(target: Path, db_path: Path, include_source: bool, results, resolved_calls) -> int:
    _clean(db_path)
    graph = DependencyGraph(
        db_path=db_path, project_root=target, backend=LatticeBackend(db_path)
    )
    graph.ingest_results(results, resolved_calls=resolved_calls, include_source=include_source)
    graph.backend.close()
    return db_path.stat().st_size


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "src" / "code_explorer"

    console.print(f"[cyan]Parsing[/cyan] {target} ...")
    results = CodeAnalyzer().analyze_directory(target)
    resolved_calls = CallResolver(results).resolve_all_calls()

    compact_size = _index(
        target, REPO_ROOT / "perfo" / "size_compact.lattice", False, results, resolved_calls
    )
    full_size = _index(
        target, REPO_ROOT / "perfo" / "size_full_source.lattice", True, results, resolved_calls
    )

    table = Table(title=f"LatticeDB index size on {target}")
    table.add_column("Mode")
    table.add_column("Size", justify="right")
    table.add_row("Compact search_text (default)", f"{compact_size / 1024:.1f} KiB")
    table.add_row("Full source_code (include_source=True)", f"{full_size / 1024:.1f} KiB")
    table.add_row("Reduction", f"{(1 - compact_size / full_size) * 100:.0f}%")
    console.print(table)


if __name__ == "__main__":
    main()
