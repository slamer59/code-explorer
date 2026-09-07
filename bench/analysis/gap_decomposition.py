"""Where one tool's advantage over another actually comes from.

A recall gap is a summary, not a diagnosis. This splits it into the parts you
can act on: relevant files the winner returned and the loser never did, broken
down by whether they are test files (i.e. suppressed by demote_tests) or
application code.

It produced the two numbers the gap analysis turns on: 83% of zvec-grep's
remaining recall@5 advantage on django is test files we deliberately demote,
and only 13 files across 150 queries were application code.

Usage:
    uv run python analysis/gap_decomposition.py <corpus> <winner> <loser> [k]
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench import config                                        # noqa: E402
from bench.qrels import build, load_cases, query_id             # noqa: E402
from analysis.ground_truth_composition import is_test           # noqa: E402


def ranked(corpus: str, tool: str, kind: str = "delivered") -> dict[str, list[str]]:
    path = config.RUNS / corpus / f"{tool}.{kind}.json"
    run = json.loads(path.read_text())["run"]
    return {q: [d for d, _ in sorted(v.items(), key=lambda x: -x[1])] for q, v in run.items()}


def main() -> int:
    if len(sys.argv) < 4:
        print(__doc__)
        return 2
    corpus, winner, loser = sys.argv[1:4]
    k = int(sys.argv[4]) if len(sys.argv) > 4 else 5

    _, cases = load_cases(config.queryset_path(corpus))
    rel = build(cases, "file")
    qtext = {query_id(c, i): c["query"] for i, c in enumerate(cases)}
    W, L = ranked(corpus, winner), ranked(corpus, loser)

    won = [(q, d) for q, docs in rel.items()
           for d in (set(W.get(q, [])[:k]) & set(docs)) - set(L.get(q, [])[:k])]
    if not won:
        print(f"no files {winner} finds in its top-{k} that {loser} misses")
        return 0

    tests = [(q, d) for q, d in won if is_test(d)]
    print(f"{corpus}: relevant files in {winner}'s top-{k} but not {loser}'s: {len(won)}")
    print(f"  test files (which demote_tests suppresses) : {len(tests):4}  "
          f"({len(tests)/len(won):.0%})")
    print(f"  application code                           : {len(won)-len(tests):4}")

    print(f"\n  examples -- where {loser} ranked the same file:")
    for q, d in tests[:3]:
        pos = L.get(q, []).index(d) + 1 if d in L.get(q, []) else None
        print(f"\n    {qtext.get(q, q)[:64]!r}")
        print(f"      {d}")
        print(f"      {winner}: rank {W[q].index(d)+1}   |   "
              f"{loser}: {'rank ' + str(pos) if pos else 'not returned'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
