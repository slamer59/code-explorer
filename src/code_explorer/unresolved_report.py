"""Summarise the call references ingestion could not resolve.

The finalize pass reports a bare count ("8,291 unresolved"), which tells you
something is missing but not *what*. This turns the leftover
UNRESOLVED_CALL_STREAM records into a short, grouped answer: which targets the
graph has no edge for, and which of them are worth caring about.

Kept out of lattice_backend.py deliberately -- this is reporting, not storage,
and it reads the stream through the backend's public db handle.
"""

from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Tuple

# How many stream records to inspect. The stream is read in pages; on the
# reference corpus a page of 500 costs ~7ms and is flat in offset (measured --
# read_stream is not quadratic), so a full read of a few thousand records is
# well under a second. The cap exists so a pathological repo cannot turn a
# summary line into a visible stall.
_MAX_RECORDS = 20_000
_PAGE = 1_000


def _bucket(
    target_module: str,
    called_name: str,
    project_modules: frozenset,
    qualifier: str = "",
) -> str:
    """Classify one unresolved target.

    HYPOTHESIS: a target whose module resolves to a project package is a
    resolution gap worth fixing, while one that does not is a third-party or
    stdlib call the graph is never going to contain. Measured on the reference
    corpus, that split was ~25% internal / ~75% external among references that
    carried a module at all.

    The no-module case is split further by whether the call had a receiver,
    because "no import resolved" on its own is misleading: on the 2,103-file
    gemseo corpus it covered 7,527 of 7,733 unresolved references (97%), and
    a measurement of that bucket (perfo/benchmark_duck_typing.py) found 87%
    of it to be `obj.method()` on a receiver whose type is unknown -- not a
    missing import at all. Splitting them here is the difference between "the
    import resolver has a 97% hole" (false) and "the resolver is fine, we
    have no receiver types" (true).

    What this can get wrong: it keys off the *presence* of a qualifier, not
    its type, so `self.x.run()` and `numpy.linalg.norm()` both land in the
    receiver bucket. It is a shape hint, not a classification of the target.
    """
    if not target_module:
        if qualifier and qualifier != "self":
            return "method on a receiver of unknown type"
        return "no import resolved"
    root = target_module.split(".")[0]
    if target_module in project_modules or root in project_modules:
        return "project code (resolution gap)"
    return "external library"


def summarize_unresolved(
    backend,
    stream_name: str,
    project_modules: Optional[frozenset] = None,
) -> Tuple[Dict[str, int], "Counter"]:
    """Return (counts per bucket, a Counter of every unresolved target).

    Targets are reported as `module.name` when an import was resolved, and as
    a bare name otherwise -- a bare name is usually a builtin or a method on a
    value whose type we never knew, which is exactly why it did not resolve.
    """
    project_modules = project_modules or frozenset()
    buckets: Counter = Counter()
    targets: Counter = Counter()

    after = 0
    seen = 0
    while seen < _MAX_RECORDS:
        try:
            records = backend.db.read_stream(stream_name, after_sequence=after, limit=_PAGE)
        except Exception:
            # Stream absent (nothing was ever deferred) or unreadable -- a
            # reporting nicety must never break the command that calls it.
            break
        if not records:
            break
        for record in records:
            payload = record.payload
            seen += 1
            module = payload.get("target_module") or ""
            name = payload.get("target_name") or payload.get("called_name") or "?"
            buckets[
                _bucket(module, name, project_modules, payload.get("qualifier") or "")
            ] += 1
            targets[f"{module}.{name}" if module else name] += 1
        after = records[-1].sequence

    return dict(buckets), targets


def project_modules_from_files(relative_paths) -> frozenset:
    """Package names implied by the indexed files, including parent packages."""
    modules = set()
    for relative in relative_paths:
        parts = list(PurePosixPath(relative).parts)
        if not parts:
            continue
        if parts[-1] == "__init__.py":
            parts.pop()
        elif parts[-1].endswith(".py"):
            parts[-1] = parts[-1][:-3]
        prefix: List[str] = []
        for part in parts:
            prefix.append(part)
            modules.add(".".join(prefix))
    return frozenset(modules)


def write_report(
    path: "Path",
    buckets: Dict[str, int],
    targets: "Counter",
    project_modules: frozenset,
) -> int:
    """Write every unresolved target to `path`, most frequent first.

    A file rather than console output: the console gets a few lines, but the
    full list runs to thousands of entries on a real repo and is the thing you
    actually want to grep when asking "why is there no edge for X".
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    total = sum(targets.values())
    lines = [
        "# Unresolved call targets",
        "#",
        "# Each line: <count>  <target>",
        "# A target shown as module.name had its import resolved; a bare name",
        "# did not (a builtin, or a method on a value whose type is unknown).",
        f"# {total:,} unresolved references across {len(targets):,} distinct targets.",
        "#",
    ]
    for bucket, count in sorted(buckets.items(), key=lambda kv: -kv[1]):
        lines.append(f"#   {count:>8,}  {bucket}")
    lines.append("")

    for target, count in targets.most_common():
        lines.append(f"{count:>8,}  {target}")

    path.write_text("\n".join(lines) + "\n")
    return total
