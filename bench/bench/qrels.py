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


def build(cases: list[dict], level: str = "file") -> dict[str, dict[str, int]]:
    qrels: dict[str, dict[str, int]] = {}
    for i, case in enumerate(cases):
        relevant: dict[str, int] = {}
        for answer in case["answers"]:
            if level == "file":
                relevant[answer["file"]] = 1
            else:
                for symbol in answer["symbols"]:
                    relevant[f"{answer['file']}::{symbol}"] = 1
        if relevant:
            qrels[query_id(case, i)] = relevant
    return qrels
