"""Tests for analyzer/docstrings.py's extract_docstring.

Kept small (2 tests): the happy path, and a regression test for a real
crash found while indexing a large external codebase (gemseo) --
whitespace-only docstrings (e.g. '""" """') caused an IndexError.
"""

from code_explorer.analyzer.base_analyzer import CodeAnalyzer


def test_extract_docstring_returns_first_line(temp_dir):
    (temp_dir / "a.py").write_text(
        'def foo():\n    """First line.\n\n    More detail.\n    """\n    pass\n'
    )
    result = CodeAnalyzer().analyze_file(temp_dir / "a.py")

    assert result.functions[0].docstring == "First line."


def test_extract_docstring_handles_whitespace_only_docstring(temp_dir):
    # Regression test: '""" """' crashed extract_docstring with an
    # IndexError (docstring.strip().splitlines()[0] on an empty list),
    # found indexing gemseo/src/gemseo/third_party/sompy.py.
    (temp_dir / "a.py").write_text('def foo():\n    """ """\n    pass\n')

    result = CodeAnalyzer().analyze_file(temp_dir / "a.py")

    assert result.functions[0].docstring is None
