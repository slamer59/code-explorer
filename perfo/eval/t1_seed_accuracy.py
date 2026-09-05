"""T1 -- seed accuracy: can BM25 find the code the commit actually changed?

Step 1 of the product's two-step model is "the LLM guesses a plausible name,
BM25 finds it". This measures whether that step works, on queries nobody
wrote to make it look good (see build_queryset.py).

Metric is recall@k over *symbols*, not files: a hit means one of the
functions the commit touched appears in the top k results. Recall@1 is the
number that matters most, because the context bundle is seeded from the top
hit alone -- a correct answer at rank 4 still bundles the wrong
neighbourhood.

Results are also reported as MRR, which distinguishes "rank 2" from "rank 9"
where recall@5 cannot.

Runs in-process against the backend rather than through the CLI: T0 already
established that ~0.45s of every CLI invocation is interpreter startup, and
paying it 200x per mode would make the sweep take an hour to measure
something it does not vary.

Usage:
    python perfo/eval/t1_seed_accuracy.py perfo/eval/queryset-django.json \
        .benchmarks/django --modes bm25,fuzzy
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from code_explorer.hybrid_search import demote_tests  # noqa: E402

KS = (1, 5, 10)


def _load_backend(corpus: Path, backend: str):
    from code_explorer.graph import DependencyGraph

    if backend == "sqlite":
        from code_explorer.graph.backends.sqlite_backend import SqliteBackend
        be = SqliteBackend(str(corpus / ".code-explorer" / "graph.sqlite"))
    else:
        from code_explorer.graph.backends.lattice_backend import LatticeBackend
        be = LatticeBackend(str(corpus / ".code-explorer" / "graph.lattice"))
    be.open()
    return DependencyGraph(backend=be), be


def _hit_rank(hits, answers: set[str]) -> int | None:
    """1-based rank of the first result naming a symbol the commit touched.

    Matches on symbol name only, not file: a commit that renames or moves a
    function still counts as found, and requiring the file to match too
    would penalise retrieval for the corpus being a different revision than
    the commit (the clone is HEAD, the commit is history).
    """
    for i, h in enumerate(hits, start=1):
        if h.name in answers:
            return i
    return None


def evaluate(cases, graph, mode: str, fetch: int, rerank: bool) -> dict:
    ranks: list[int | None] = []
    t0 = time.perf_counter()
    for case in cases:
        answers = {s for a in case["answers"] for s in a["symbols"]}
        try:
            if mode == "fuzzy":
                hits = graph.backend.search_text(case["query"], limit=fetch, fuzzy=True)
            else:
                hits = graph.backend.search_text(case["query"], limit=fetch)
        except Exception:
            hits = []
        if rerank:
            hits = demote_tests(hits)
        ranks.append(_hit_rank(hits, answers))
    elapsed = time.perf_counter() - t0

    n = len(ranks)
    found = [r for r in ranks if r is not None]
    return {
        "mode": mode, "rerank": rerank, "n": n,
        **{f"recall@{k}": round(sum(1 for r in found if r <= k) / n, 3) for k in KS},
        "mrr": round(sum(1 / r for r in found) / n, 3),
        "unfound": n - len(found),
        "ms_per_query": round(elapsed / n * 1000, 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("queryset", type=Path)
    ap.add_argument("corpus", type=Path)
    ap.add_argument("--backend", default="sqlite")
    ap.add_argument("--modes", default="bm25,fuzzy")
    ap.add_argument("--fetch", type=int, default=max(KS),
                    help="results pulled per query; must be >= max k")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()

    data = json.loads(args.queryset.read_text())
    cases = data["cases"]
    graph, be = _load_backend(args.corpus.resolve(), args.backend)
    print(f"{data['repo']}: {len(cases)} queries, backend={args.backend}")

    rows = []
    try:
        for mode in args.modes.split(","):
            for rerank in (False, True):
                r = evaluate(cases, graph, mode.strip(), args.fetch, rerank)
                rows.append(r)
                tag = f"{r['mode']}{'+demote' if rerank else ''}"
                print(f"  {tag:16.16}  R@1 {r['recall@1']:.3f}  R@5 {r['recall@5']:.3f}"
                      f"  R@10 {r['recall@10']:.3f}  MRR {r['mrr']:.3f}"
                      f"  miss {r['unfound']:3d}  {r['ms_per_query']:6.1f}ms/q")
    finally:
        be.close()

    if args.json:
        args.json.write_text(json.dumps({"repo": data["repo"], "rows": rows}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
