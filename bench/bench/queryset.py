"""Turn a repository's git history into a labeled retrieval query set.

Hand-writing queries does not scale, and it is biased: I would write
queries for code I already know is indexed well. A merged commit is a free
labeled example instead -- its subject line is the query a developer would
have asked, and the functions it touched are the answer set. Thousands of
them per repo, no manual labeling, and it moves to any repo unchanged.

Selection is deliberately narrow. A commit qualifies only if it touches
2-8 distinct Python functions across >=2 files: single-function commits are
findable by grep and prove nothing, and 50-function refactors have no
coherent "answer". What is left is exactly the case the product claims --
evidence spans files, the entry point is not known in advance.

The subject line is used verbatim as the query, with conventional-commit
noise ("fix:", "[core]") and issue refs ("(#1234)") stripped. It is
deliberately NOT cleaned further: an agent's guess is messy prose too, and
polishing the query into something BM25 likes would be marking our own
homework.

Usage:
    python -m bench.queryset ../.benchmarks/home-assistant \
        --out querysets/home-assistant.json --limit 200
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# "fix(core): ..." / "[core] ..." / trailing "(#1234)" -- vocabulary of the
# commit convention, not of the codebase, so it can only mislead retrieval.
_PREFIX = re.compile(r"^(?:\w+(?:\([^)]*\))?!?:\s*|\[[^\]]+\]\s*)+")
_ISSUE_REF = re.compile(r"\s*\(#\d+\)\s*$")
# Django's convention: "Fixed #37293 -- Renamed ...". The ticket id and the
# verb in front of it are metadata about the *process*, not the code, and
# leaving them in hands BM25 five tokens of pure noise on every query.
_TICKET_LEAD = re.compile(r"^(?:\w+\s+)?#\d+\s*--\s*")
# Hunk headers: git puts the enclosing symbol after the second @@.
_HUNK = re.compile(r"^@@ .* @@\s*(.*)$")
_DEFLINE = re.compile(r"^\s*(?:async\s+)?(?:def|class)\s+(\w+)")

MERGE_NOISE = ("Merge pull request", "Merge branch", "Bump ", "Update dependencies")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=False,
    ).stdout


def _clean_subject(subject: str) -> str:
    s = _ISSUE_REF.sub("", subject)
    s = _TICKET_LEAD.sub("", s)
    s = _PREFIX.sub("", s).strip()
    return s


def _touched_symbols(repo: Path, sha: str) -> dict[str, set[str]]:
    """Map file -> set of function/class names the commit touched.

    Read from `git show -U0`'s hunk headers, which name the enclosing
    definition, plus any def/class line the diff adds outright. Both are
    approximations -- a hunk header names the *enclosing* symbol, which for
    a decorator or a class-body edit is the class rather than the method.
    That is acceptable: it errs toward a coarser answer set, which makes the
    benchmark harder on us, not easier.
    """
    diff = _git(repo, "show", "-U0", "--format=", sha)
    out: dict[str, set[str]] = {}
    current: str | None = None
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:]
            current = path if path.endswith(".py") else None
            continue
        if current is None:
            continue
        if (m := _HUNK.match(line)) and (d := _DEFLINE.match(m.group(1))):
            out.setdefault(current, set()).add(d.group(1))
        elif line.startswith("+") and (d := _DEFLINE.match(line[1:])):
            out.setdefault(current, set()).add(d.group(1))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=200, help="query set size")
    ap.add_argument("--scan", type=int, default=4000, help="commits to consider")
    ap.add_argument("--min-symbols", type=int, default=2)
    ap.add_argument("--max-symbols", type=int, default=8)
    args = ap.parse_args()

    repo = args.repo.resolve()
    log = _git(repo, "log", f"-{args.scan}", "--no-merges", "--format=%H\x1f%s")
    if not log.strip():
        print(f"no history in {repo} (shallow clone with depth 1?)", file=sys.stderr)
        return 2

    cases, skipped = [], {"noise": 0, "one_file": 0, "symbol_count": 0, "short_query": 0}
    for line in log.splitlines():
        if len(cases) >= args.limit:
            break
        sha, _, subject = line.partition("\x1f")
        if any(subject.startswith(n) for n in MERGE_NOISE):
            skipped["noise"] += 1
            continue
        query = _clean_subject(subject)
        if len(query.split()) < 3:
            skipped["short_query"] += 1
            continue
        touched = _touched_symbols(repo, sha)
        if len(touched) < 2:
            skipped["one_file"] += 1
            continue
        total = sum(len(v) for v in touched.values())
        if not (args.min_symbols <= total <= args.max_symbols):
            skipped["symbol_count"] += 1
            continue
        cases.append({
            "sha": sha, "query": query,
            "answers": [{"file": f, "symbols": sorted(s)} for f, s in sorted(touched.items())],
            "n_symbols": total, "n_files": len(touched),
        })

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(
        {"repo": repo.name, "scanned": len(log.splitlines()), "cases": cases}, indent=1
    ))
    print(f"{repo.name}: {len(cases)} cases -> {args.out}")
    print(f"  skipped: {skipped}")
    if cases:
        print(f"  example: {cases[0]['query']!r}")
        print(f"           {cases[0]['n_symbols']} symbols across {cases[0]['n_files']} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
