"""Latency and index-footprint measurement, delegated to hyperfine.

Warmups, outlier detection, shell-spawn compensation and the statistics are
hyperfine's problem, not ours -- a hand-rolled timing loop gets all four
subtly wrong and reports a mean with no confidence interval. This module
only decides *what* to time and folds the JSON back into the report.

Two things are measured, and they are different kinds of cost:

- **Cold index build**, once per tool. Paid on setup; an agent never feels
  it, so it is reported for completeness rather than as a headline.
- **Warm query latency**, over a fixed set of queries. Paid on every single
  question the agent asks, and includes interpreter startup because the
  user pays that too.
"""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
from pathlib import Path

import click

from . import config
from .adapters import build

#: Fixed and boring on purpose: query *content* must not vary between tools
#: or between runs, or the latency numbers stop being comparable.
LATENCY_QUERIES = [
    "authentication backend",
    "serialize model to json",
    "cache invalidation",
    "migration autodetector",
    "template context processor",
]


def _dir_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def measure(tool: str, corpus_name: str, runs: int) -> dict:
    if shutil.which("hyperfine") is None:
        raise SystemExit(
            "hyperfine is not installed.\n"
            "  sudo dnf install hyperfine   (or: cargo install hyperfine)"
        )
    corpus = config.corpus_path(corpus_name)
    adapter = build(tool, corpus, **config.tool_options(tool))

    commands = []
    for query in LATENCY_QUERIES:
        result = adapter.query(query, 10)  # warm the caches once, unmeasured
        if result.error:
            raise SystemExit(f"{tool}: {result.error}")
        commands.append(shlex.join(adapter.query_argv(query, 10)))

    export = config.RESULTS / "perf" / corpus_name / f"{tool}.json"
    export.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["hyperfine", "--warmup", "2", "--runs", str(runs),
         "--export-json", str(export), *commands],
        cwd=corpus, check=True,
    )
    data = json.loads(export.read_text())
    return {
        "tool": tool,
        "corpus": corpus_name,
        "index_bytes": _dir_bytes(corpus / adapter.index_dir),
        "results": [
            {"command": r["command"], "mean_ms": r["mean"] * 1000,
             "stddev_ms": (r.get("stddev") or 0.0) * 1000}
            for r in data["results"]
        ],
    }


@click.command()
@click.option("--corpus", "corpora", multiple=True)
@click.option("--tools", default="")
@click.option("--runs", default=10, show_default=True)
def main(corpora: tuple[str, ...], tools: str, runs: int) -> None:
    """Time warm queries with hyperfine; write results/perf/<corpus>/<tool>.json."""
    tool_names = [t.strip() for t in tools.split(",") if t.strip()] or list(config.tools())
    for corpus in (list(corpora) or list(config.corpora())):
        for tool in tool_names:
            summary = measure(tool, corpus, runs)
            mean = sum(r["mean_ms"] for r in summary["results"]) / len(summary["results"])
            click.echo(f"  {tool} x {corpus}: {mean:.0f} ms mean, "
                       f"{summary['index_bytes'] / 1e6:.1f} MB index")


if __name__ == "__main__":
    main()
