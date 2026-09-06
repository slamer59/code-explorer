"""Run tools x queries, and write TREC-style run files.

The runner never scores anything. It produces runs; `report.py` scores them
with ranx. Keeping the two apart is what makes a run file re-scorable later
under a metric nobody had thought of when it was recorded.
"""

from __future__ import annotations

import json
import os
import platform
import socket
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import click

from . import config
from .adapters import build
from .qrels import load_cases, query_id


def provenance(corpus: Path) -> dict:
    """What produced these numbers. A number without it cannot be argued with."""

    def sh(*args: str, cwd: Path) -> str:
        try:
            out = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
        except OSError:
            return ""
        return out.stdout.strip()

    repo = config.ROOT.parent
    return {
        "utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tool_sha": sh("git", "rev-parse", "--short", "HEAD", cwd=repo),
        "tool_dirty": bool(sh("git", "status", "--porcelain", cwd=repo)),
        "corpus_sha": sh("git", "rev-parse", "--short", "HEAD", cwd=corpus),
        "host": socket.gethostname(),
        "cpus": os.cpu_count(),
        "python": platform.python_version(),
        "platform": platform.platform(),
    }


def _delivered(result) -> dict[str, float]:
    """Everything one call puts in front of the model, in the order printed.

    Scoring `seed` and `bundle` as separate runs measures two halves of one
    output and credits the tool for neither: a tool that returns a ranked
    list *and* an assembled context is judged on each in isolation, when the
    caller receives both from a single invocation. The ranked list comes
    first because that is the order the output is printed in; files only
    expansion reached follow it.
    """
    merged = {h.doc_id: h.score for h in result.seed}
    floor = min(merged.values(), default=1.0)
    for i, hit in enumerate(result.bundle, start=1):
        # Strictly below every seed hit, but ordered among themselves.
        merged.setdefault(hit.doc_id, floor - i * 1e-3)
    return merged


def _run_file(corpus: str, tool: str, kind: str) -> Path:
    path = config.RUNS / corpus / f"{tool}.{kind}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def execute(tool: str, corpus_name: str, k: int, limit: int | None, do_index: bool) -> dict:
    corpus = config.corpus_path(corpus_name)
    if not corpus.exists():
        raise SystemExit(f"corpus {corpus_name!r} is not checked out at {corpus}")
    queryset = config.queryset_path(corpus_name)
    if not queryset.exists():
        raise SystemExit(
            f"no queryset at {queryset}; build one with `python -m bench.queryset`"
        )

    repo, cases = load_cases(queryset)
    if limit:
        cases = cases[:limit]

    adapter = build(tool, corpus, **config.tool_options(tool))
    index_ms = None
    if do_index:
        started = time.perf_counter()
        adapter.index()
        index_ms = (time.perf_counter() - started) * 1000

    seed_run: dict[str, dict[str, float]] = {}
    bundle_run: dict[str, dict[str, float]] = {}
    delivered_run: dict[str, dict[str, float]] = {}
    per_query: list[dict] = []

    with click.progressbar(cases, label=f"{tool} x {corpus_name}") as bar:
        for i, case in enumerate(bar):
            qid = query_id(case, i)
            result = adapter.query(case["query"], k)
            # ranx wants {doc_id: score}; scores must be descending in rank
            # order, which every adapter guarantees via dedupe().
            if result.seed:
                seed_run[qid] = {h.doc_id: h.score for h in result.seed}
            if result.bundle:
                bundle_run[qid] = {h.doc_id: h.score for h in result.bundle}
            delivered = _delivered(result)
            if delivered:
                delivered_run[qid] = delivered
            per_query.append({
                "qid": qid,
                "query": case["query"],
                "n_relevant": len(case["answers"]),
                "n_seed": len(result.seed),
                "n_bundle": len(result.bundle),
                "tokens": result.tokens,
                "wall_ms": round(result.wall_ms, 1),
                "mode": result.mode,
                "error": result.error,
            })

    meta = {
        "tool": tool,
        "corpus": corpus_name,
        "repo": repo,
        "k": k,
        "n_queries": len(cases),
        "expands": adapter.expands,
        "embedding": adapter.embedding(),
        "index_ms": None if index_ms is None else round(index_ms, 1),
        "provenance": provenance(corpus),
        "per_query": per_query,
    }

    for kind, run in (("delivered", delivered_run), ("seed", seed_run),
                      ("bundle", bundle_run)):
        _run_file(corpus_name, tool, kind).write_text(
            json.dumps({**meta, "kind": kind, "run": run}, indent=1)
        )

    config.HISTORY.parent.mkdir(parents=True, exist_ok=True)
    with config.HISTORY.open("a") as fh:
        fh.write(json.dumps({k_: v for k_, v in meta.items() if k_ != "per_query"}) + "\n")
    return meta


@click.command()
@click.option("--corpus", "corpora", multiple=True, help="Corpus name; repeatable.")
@click.option("--tools", default="", help="Comma-separated tool names (default: all).")
@click.option("-k", default=10, show_default=True, help="Results requested per query.")
@click.option("--limit", type=int, default=None, help="Only the first N queries (smoke runs).")
@click.option("--index/--no-index", default=False, show_default=True,
              help="Rebuild each tool's index before querying.")
def main(corpora: tuple[str, ...], tools: str, k: int, limit: int | None, index: bool) -> None:
    """Produce run files for every (tool, corpus) pair."""
    corpus_names = list(corpora) or list(config.corpora())
    tool_names = [t.strip() for t in tools.split(",") if t.strip()] or list(config.tools())

    for corpus_name in corpus_names:
        for tool in tool_names:
            meta = execute(tool, corpus_name, k, limit, index)
            errors = sum(1 for q in meta["per_query"] if q["error"])
            click.echo(
                f"  {tool} x {corpus_name}: {meta['n_queries']} queries, "
                f"{errors} errors -> {config.RUNS / corpus_name}"
            )


if __name__ == "__main__":
    main()
