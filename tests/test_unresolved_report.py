"""Tests for the unresolved-call report.

Small on purpose: the bucketing rule is the part with a judgement call in
it, and writing the file is the part a user actually consumes.
"""

from collections import Counter

from code_explorer.unresolved_report import (
    project_modules_from_files,
    write_report,
)


def test_project_modules_includes_parent_packages():
    modules = project_modules_from_files(
        ["pkg/sub/mod.py", "pkg/__init__.py", "other/thing.py"]
    )
    assert "pkg" in modules
    assert "pkg.sub" in modules
    assert "pkg.sub.mod" in modules
    assert "other.thing" in modules


def test_write_report_lists_targets_most_frequent_first(temp_dir):
    path = temp_dir / ".code-explorer" / "unresolved-calls.txt"
    targets = Counter({"numpy.array": 42, "print": 7, "pkg.mod.Thing": 3})
    buckets = {"external library": 42, "no import resolved": 7, "project code (resolution gap)": 3}

    total = write_report(path, buckets, targets, frozenset({"pkg"}))

    assert total == 52
    body = path.read_text()
    # Most frequent first, so the worst offender is what you see at the top.
    first_entry = [l for l in body.splitlines() if l and not l.startswith("#")][0]
    assert "numpy.array" in first_entry
    assert "print" in body and "pkg.mod.Thing" in body
    assert "external library" in body  # bucket summary is in the header
