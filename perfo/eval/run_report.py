"""Run the benchmark tiers and render a publishable report.

Three properties make a benchmark worth re-running, and all three are about
plumbing rather than measurement:

1. **Every run is appended, never overwritten.** results/history.jsonl is
   committed, so a regression is visible as a delta against the previous run
   rather than as a number nobody remembers the old value of.
2. **Every run records what produced it** -- git sha, dirty flag, host, CPU
   count, date. A number without its provenance cannot be argued with later.
3. **The report is generated, never edited.** Hand-maintained tables drift
   from the code that produced them; this one is regenerated from the JSONL
   every time, so it cannot.

Usage:
    python perfo/eval/run_report.py                  # all corpora, all tiers
    python perfo/eval/run_report.py --tier t0        # just the scale gate
    python perfo/eval/run_report.py --render-only    # re-render from history
"""

import argparse
import json
import os
import platform
import re
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
HISTORY = HERE / "results" / "history.jsonl"
REPORT_MD = HERE / "results" / "report.md"

# Corpora are addressed by name so the report's rows are stable across runs
# even when a corpus is skipped (missing checkout, or --only).
CORPORA = {
    "gemseo": Path("/home/pedot/Developpments/gemseo"),
    "django": REPO / ".benchmarks" / "django",
    "home-assistant": REPO / ".benchmarks" / "home-assistant",
}


def _sh(*args: str, cwd: Path = REPO) -> str:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True).stdout.strip()


def provenance() -> dict:
    dirty = bool(_sh("git", "status", "--porcelain"))
    return {
        "utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sha": _sh("git", "rev-parse", "--short", "HEAD"),
        "dirty": dirty,
        "host": socket.gethostname(),
        "cpus": os.cpu_count(),
        "python": platform.python_version(),
        "platform": platform.platform(),
    }


def run_t0(corpus: Path, backend: str) -> dict | None:
    """Scale gate. Shells out so the measured path is the real CLI."""
    out = subprocess.run(
        [sys.executable, str(HERE / "t0_scale.py"), str(corpus), "--backend", backend],
        capture_output=True, text=True, cwd=REPO,
    )
    txt = out.stdout
    m_build = re.search(r"cold build\s+([\d.]+)s\s+peak RSS\s+([\d.]+) GB\s+index\s+([\d.]+) MB", txt)
    m_files = re.search(r"\(([\d,]+) \.py files", txt)
    m_inc = re.search(r"re-index 1 file\s*([\d.]+)s", txt)
    if not m_build:
        print(f"  t0 {corpus.name}: FAILED\n{out.stdout[-500:]}{out.stderr[-500:]}")
        return None
    searches = [int(x) for x in re.findall(r"search (\d+)ms", txt)]
    return {
        "corpus": corpus.name,
        "py_files": int(m_files.group(1).replace(",", "")) if m_files else None,
        "backend": backend,
        "cold_build_s": float(m_build.group(1)),
        "peak_rss_gb": float(m_build.group(2)),
        "index_mb": float(m_build.group(3)),
        "incremental_s": float(m_inc.group(1)) if m_inc else None,
        "search_ms_max": max(searches) if searches else None,
        "search_ms_median": sorted(searches)[len(searches) // 2] if searches else None,
    }


def _fmt_delta(cur, prev, unit="", lower_is_better=True) -> str:
    """Render `value (+12%)`, marking a regression. Silent when there is no
    prior run -- a first measurement has nothing to regress against."""
    if cur is None:
        return "--"
    base = f"{cur:g}{unit}"
    if prev in (None, 0):
        return base
    pct = (cur - prev) / prev * 100
    if abs(pct) < 5:  # noise floor; wall-clock on a laptop is not tighter
        return base
    worse = (pct > 0) if lower_is_better else (pct < 0)
    return f"{base} ({'+' if pct > 0 else ''}{pct:.0f}% {'⚠' if worse else '✓'})"


def render(history: list[dict]) -> str:
    if not history:
        return "# Benchmark report\n\nNo runs recorded yet.\n"
    cur = history[-1]
    prev = history[-2] if len(history) > 1 else {}
    prev_t0 = {r["corpus"]: r for r in prev.get("t0", [])}
    p = cur["provenance"]

    L = ["# Benchmark report", ""]
    L.append(f"Generated from `perfo/eval/results/history.jsonl` -- run {len(history)}, "
             f"{p['utc']}, commit `{p['sha']}`{' **(dirty tree)**' if p['dirty'] else ''}.")
    L.append("")
    L.append(f"`{p['platform']}`, {p['cpus']} CPUs, Python {p['python']}.")
    L.append("")
    L.append("Percentages compare against the previous recorded run; changes under "
             "5% are suppressed as noise. ⚠ marks a regression.")
    L.append("")

    if cur.get("t0"):
        L += ["## T0 -- scale gate", "",
              "Does the indexer survive a large corpus? Measured through the real "
              "CLI, so process startup and index open are included.", "",
              "| corpus | .py files | cold build | peak RSS | index | search (median/max) | re-index 1 file |",
              "|---|---:|---:|---:|---:|---:|---:|"]
        for r in cur["t0"]:
            q = prev_t0.get(r["corpus"], {})
            L.append(
                f"| {r['corpus']} | {r['py_files']:,} "
                f"| {_fmt_delta(r['cold_build_s'], q.get('cold_build_s'), 's')} "
                f"| {_fmt_delta(r['peak_rss_gb'], q.get('peak_rss_gb'), ' GB')} "
                f"| {_fmt_delta(r['index_mb'], q.get('index_mb'), ' MB')} "
                f"| {r['search_ms_median']}/{r['search_ms_max']} ms "
                f"| {_fmt_delta(r['incremental_s'], q.get('incremental_s'), 's')} |"
            )
        L.append("")

    if cur.get("t1"):
        L += ["## T1 -- seed accuracy", "",
              "Can the search find the code a real commit changed? Queries are commit "
              "subject lines; answers are the functions that commit touched "
              "(`build_queryset.py`). Recall@1 matters most: the context bundle is "
              "seeded from the top hit alone.", "",
              "| corpus | queries | mode | R@1 | R@5 | R@10 | MRR |",
              "|---|---:|---|---:|---:|---:|---:|"]
        for r in cur["t1"]:
            for row in r["rows"]:
                tag = row["mode"] + ("+demote" if row.get("rerank") else "")
                L.append(f"| {r['corpus']} | {row['n']} | {tag} | {row['recall@1']:.3f} "
                         f"| {row['recall@5']:.3f} | {row['recall@10']:.3f} | {row['mrr']:.3f} |")
        L.append("")

    L += ["## Reproducing", "", "```bash", "python perfo/eval/run_report.py", "```", ""]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", default="t0", help="comma-separated: t0,t1")
    ap.add_argument("--backend", default="sqlite")
    ap.add_argument("--only", help="comma-separated corpus names")
    ap.add_argument("--render-only", action="store_true")
    args = ap.parse_args()

    history = [json.loads(l) for l in HISTORY.read_text().splitlines() if l.strip()] \
        if HISTORY.exists() else []

    if not args.render_only:
        tiers = {t.strip() for t in args.tier.split(",")}
        names = args.only.split(",") if args.only else list(CORPORA)
        run = {"provenance": provenance(), "t0": [], "t1": []}
        t_start = time.perf_counter()
        for name in names:
            corpus = CORPORA.get(name)
            if not corpus or not corpus.is_dir():
                print(f"  skip {name}: not checked out")
                continue
            if "t0" in tiers:
                print(f"  t0 {name} ...", flush=True)
                if (r := run_t0(corpus, args.backend)):
                    run["t0"].append(r)
        run["wall_s"] = round(time.perf_counter() - t_start, 1)
        HISTORY.parent.mkdir(parents=True, exist_ok=True)
        with HISTORY.open("a") as fh:
            fh.write(json.dumps(run) + "\n")
        history.append(run)
        print(f"  recorded run {len(history)} ({run['wall_s']}s)")

    REPORT_MD.write_text(render(history))
    print(f"  wrote {REPORT_MD.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
