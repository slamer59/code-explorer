"""Small tests for the search command's exact-target detection heuristic.

Part of the minimal "try exact match, fall back to BM25" hybrid-retrieval
step (docs/explanation/latticedb-migration.md, Implementation Status
ranking item #5) -- not a full query classifier, just a cheap shape check.
"""

from code_explorer.cli import _looks_like_exact_target


def test_detects_file_colon_function_shape():
    assert _looks_like_exact_target("file.py:func_name") == ("file.py", "func_name")
    assert _looks_like_exact_target("auth/token.py:refresh_token") == (
        "auth/token.py",
        "refresh_token",
    )


def test_rejects_ordinary_search_phrases():
    assert _looks_like_exact_target("where do we resolve calls") is None
    assert _looks_like_exact_target("topic: detail") is None  # space after colon
    assert _looks_like_exact_target("a : b") is None  # space around colon
    assert _looks_like_exact_target("file.py:not a valid identifier") is None
