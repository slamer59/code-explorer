"""Tests for bounded, ambiguity-aware call resolution."""

from code_explorer.analyzer.base_analyzer import CodeAnalyzer
from code_explorer.analyzer.call_resolver import CallResolver


def _analyze(*paths):
    analyzer = CodeAnalyzer(search_only=True, retain_full_source=False)
    return [analyzer.analyze_file(path) for path in paths]


def test_ambiguous_cross_file_name_does_not_multiply_edges(temp_dir):
    first = temp_dir / "first.py"
    first.write_text("def helper():\n    pass\n")
    second = temp_dir / "second.py"
    second.write_text("def helper():\n    pass\n")
    caller = temp_dir / "caller.py"
    caller.write_text("def call_helper():\n    helper()\n")

    resolved = CallResolver(_analyze(first, second, caller)).resolve_all_calls()

    assert resolved == []


def test_same_file_definition_wins_when_name_is_globally_ambiguous(temp_dir):
    external = temp_dir / "external.py"
    external.write_text("def helper():\n    pass\n")
    caller = temp_dir / "caller.py"
    caller.write_text("def helper():\n    pass\ndef call_helper():\n    helper()\n")

    resolved = CallResolver(_analyze(external, caller)).resolve_all_calls()

    assert len(resolved) == 1
    assert resolved[0]["caller_function"] == "call_helper"
    assert resolved[0]["callee_file"] == str(caller)


def test_unique_cross_file_definition_is_resolved(temp_dir):
    helper = temp_dir / "helper.py"
    helper.write_text("def uniquely_named_helper():\n    pass\n")
    caller = temp_dir / "caller.py"
    caller.write_text("def call_helper():\n    uniquely_named_helper()\n")

    resolved = CallResolver(_analyze(helper, caller)).resolve_all_calls()

    assert len(resolved) == 1
    assert resolved[0]["callee_file"] == str(helper)
