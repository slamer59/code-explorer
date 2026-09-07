"""What the ground truth is actually made of, and what demotion suppresses.

Produced the numbers quoted in settings.test_demotion_factor and in
docs/explanation/gap-analysis-vs-zvec.md. They are the reason the default was
*not* changed: a query set mined from commits counts a commit's tests as
correct answers, because a commit that changes behaviour changes its tests.
Measuring test demotion against that is circular, and this script is how you
check whether a given corpus has that property before trusting a result.

Usage:
    uv run python analysis/ground_truth_composition.py [corpus]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench import config                      # noqa: E402
from bench.qrels import build, load_cases     # noqa: E402


#: Copied verbatim from hybrid_search._TEST_PATH_MARKERS / _is_test_file.
#: Duplicated rather than imported because bench/ must not import the tool it
#: grades -- but it has to match exactly, or this measures a different rule
#: than the one the pipeline applies. Note the unanchored "tests/" marker:
#: it catches a repo-relative "tests/foo.py", which a leading-slash-only
#: check would miss.
_TEST_PATH_MARKERS = ("/tests/", "/test/", "tests/", "test/")


def is_test(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or any(marker in path for marker in _TEST_PATH_MARKERS)
    )


def main() -> int:
    corpus = sys.argv[1] if len(sys.argv) > 1 else "django"
    _, cases = load_cases(config.queryset_path(corpus))
    rel = build(cases, "file")

    slots = [d for docs in rel.values() for d in docs]
    tests = [d for d in slots if is_test(d)]
    py = [d for d in slots if d.endswith(".py")]
    with_test = sum(1 for docs in rel.values() if any(is_test(d) for d in docs))

    print(f"{corpus}: {len(rel)} queries, {len(slots)} relevant-file slots\n")
    print(f"  Python                    {len(py):5}  ({len(py)/len(slots):.0%})")
    print(f"  test files                {len(tests):5}  ({len(tests)/len(slots):.0%})"
          "   <- demoted by demote_tests")
    print(f"  queries with >=1 test     {with_test:5}  ({with_test/len(rel):.0%})")
    print()
    if len(tests) / len(slots) > 0.25:
        print("  WARNING: test files are a large share of the ground truth, so this")
        print("  corpus cannot adjudicate test demotion -- the metric and the")
        print("  decision share an assumption. See gap-analysis-vs-zvec.md.")
    if len(py) == len(slots):
        print("  NOTE: ground truth is 100% Python, so indexing other file types")
        print("  cannot help or hurt any tool here.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
