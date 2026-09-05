"""T0 -- scale gate: does the indexer survive a corpus 9x gemseo?

Not a score, a gate. If building home-assistant's 18,631 files takes 20
minutes or 8GB, nothing in T1-T4 matters, so this runs first and its
numbers decide whether the rest of the plan is worth writing.

Measures the real CLI, not the library: an agent pays process startup,
index open and Rich rendering too, and those are exactly the costs a
library-level harness hides.

Usage:
    python perfo/eval/t0_scale.py .benchmarks/home-assistant
    python perfo/eval/t0_scale.py .benchmarks/django --backend lattice
"""

import argparse
import json
import re
import resource
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
# Queries chosen to be plausible without knowing the corpus -- the point is
# latency under a warm index, not relevance (that is T1's job).
LATENCY_QUERIES = [
    "config entry setup",
    "async setup platform",
    "device registry",
    "state machine",
    "authenticate user",
]


def _cli(*args: str) -> list[str]:
    return [
        "uv", "run", "--project", str(REPO), "--python", "3.12", "--extra", "dev",
        "code-explorer", *args,
    ]


def _run(cmd: list[str], cwd: Path) -> tuple[float, int, str]:
    """Return (wall_seconds, peak_rss_kb, combined output).

    Peak RSS comes from getrusage(RUSAGE_CHILDREN), which reports the
    high-water mark across all children reaped so far -- so it is read as a
    delta around this call, not an absolute.
    """
    before = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    wall = time.perf_counter() - t0
    after = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    out = proc.stdout + proc.stderr
    if proc.returncode != 0:
        out += f"\n[exit {proc.returncode}]"
    return wall, max(after - before, after if before == 0 else 0), out


def _index_bytes(corpus: Path) -> int:
    d = corpus / ".code-explorer"
    return sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) if d.is_dir() else 0


def _strip_ansi(s: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", s)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus", type=Path)
    ap.add_argument("--backend", default="sqlite")
    ap.add_argument("--json", type=Path, help="append one JSON line of results here")
    args = ap.parse_args()

    corpus = args.corpus.resolve()
    if not corpus.is_dir():
        print(f"no such corpus: {corpus}", file=sys.stderr)
        return 2

    py_files = sum(1 for _ in corpus.rglob("*.py"))
    print(f"corpus  {corpus.name}  ({py_files:,} .py files, backend={args.backend})")

    # Cold build. Remove any existing index so this is genuinely from scratch.
    shutil.rmtree(corpus / ".code-explorer", ignore_errors=True)
    build_s, build_rss, build_out = _run(
        _cli("search", "config entry", ".", "--backend", args.backend,
             "--no-context", "--limit", "1"),
        cwd=corpus,
    )
    idx_mb = _index_bytes(corpus) / 1e6
    print(f"  cold build     {build_s:8.1f}s   peak RSS {build_rss / 1e6:6.2f} GB   index {idx_mb:8.1f} MB")
    for line in _strip_ansi(build_out).splitlines():
        if line.startswith(("Done ", "Library boundary", "Error", "Traceback")):
            print(f"    | {line[:110]}")

    # Warm queries against the built index.
    lat = []
    for q in LATENCY_QUERIES:
        s, _, out = _run(
            _cli("search", q, ".", "--backend", args.backend, "--no-context", "--limit", "5"),
            cwd=corpus,
        )
        m = re.search(r"Search took (\d+)ms", _strip_ansi(out))
        lat.append({"query": q, "wall_s": round(s, 3),
                    "search_ms": int(m.group(1)) if m else None})
        print(f"  query {q!r:34.34}  wall {s:6.2f}s   search {lat[-1]['search_ms']}ms")

    # Incremental: touch one file, re-run. This is the cost an agent pays on
    # every invocation after the first, so it matters more than the cold build.
    victim = next(corpus.rglob("*.py"))
    victim.touch()
    inc_s, _, _ = _run(
        _cli("search", "config entry", ".", "--backend", args.backend,
             "--no-context", "--limit", "1"),
        cwd=corpus,
    )
    print(f"  re-index 1 file{inc_s:8.1f}s")

    result = {
        "corpus": corpus.name, "py_files": py_files, "backend": args.backend,
        "cold_build_s": round(build_s, 1), "peak_rss_gb": round(build_rss / 1e6, 2),
        "index_mb": round(idx_mb, 1), "incremental_s": round(inc_s, 1),
        "queries": lat,
    }
    if args.json:
        with args.json.open("a") as fh:
            fh.write(json.dumps(result) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
