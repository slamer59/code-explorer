"""Turn a mined query set into ranx Qrels.

Ground truth is a commit: the query is its subject line, the relevant
documents are the files it touched. Every relevant file gets relevance 1 --
a commit gives no ordering among the files it changed, and inventing a
graded scale here would be inventing data.

Two qrels are produced from the same query set:

- **file** -- doc_id is the repo-relative path. Comparable across every
  tool, because every tool knows which file a result came from.
- **symbol** -- doc_id is "path::symbol". Only tools that name symbols can
  score against it, so it is reported separately and never mixed into a
  cross-tool table.

Each can be narrowed to a `subset`, and that is not cosmetic. A commit that
changes behaviour changes its tests, so roughly half of every answer set is
test files -- 56% on django, 50% on home-assistant. Scoring against all of
them cannot adjudicate anything about how a tool *should* treat tests,
because the ground truth already assumed the answer. Splitting the qrels is
what makes the question askable:

- **all**  -- every file the commit touched (the original behaviour).
- **code** -- only the non-test files. "Where is this implemented?"
- **test** -- only the test files. "What covers this?"

A tool is then judged on the question it was actually asked.
"""

from __future__ import annotations

import json
from pathlib import Path


def load_cases(path: Path) -> tuple[str, list[dict]]:
    path = Path(path)
    data = json.loads(path.read_text())
    return data.get("repo", path.stem), data["cases"]


def query_id(case: dict, index: int) -> str:
    """Stable id: the commit sha when there is one, else the position.

    Stable ids are what let two runs recorded weeks apart be compared, and
    what let a per-query regression be traced back to the commit it came
    from.
    """
    return case.get("sha") or f"q{index:04d}"


#: Copied from hybrid_search._TEST_PATH_MARKERS. Duplicated rather than
#: imported, because bench/ must not import the tool it grades -- but it has
#: to match exactly, or the split measures a different rule than the pipeline
#: applies. The unanchored "tests/" catches a repo-relative "tests/foo.py".
_TEST_PATH_MARKERS = ("/tests/", "/test/", "tests/", "test/")


def is_test_path(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or any(marker in path for marker in _TEST_PATH_MARKERS)
    )


def build(
    cases: list[dict], level: str = "file", subset: str = "all"
) -> dict[str, dict[str, int]]:
    if subset not in ("all", "code", "test"):
        raise ValueError(f"unknown subset {subset!r}")
    qrels: dict[str, dict[str, int]] = {}
    for i, case in enumerate(cases):
        relevant: dict[str, int] = {}
        for answer in case["answers"]:
            if subset != "all":
                wanted_test = subset == "test"
                if is_test_path(answer["file"]) != wanted_test:
                    continue
            if level == "file":
                relevant[answer["file"]] = 1
            else:
                for symbol in answer["symbols"]:
                    relevant[f"{answer['file']}::{symbol}"] = 1
        if relevant:
            qrels[query_id(case, i)] = relevant
    return qrels
