"""Tests for FilesystemSourceProvider (source_provider.py).

Kept small (2 cases, matching this repo's established convention): the
happy-path line-range read, and that a missing file raises clearly rather
than silently returning empty content -- silent empty source would be worse
than an error for a feature whose whole point is giving an LLM real context
(see context.py's ContextAssembler, which relies on this failing loudly).
"""

import pytest

from code_explorer.source_provider import FilesystemSourceProvider


def test_get_range_returns_correct_line_slice(temp_dir):
    (temp_dir / "a.py").write_text("line1\nline2\nline3\nline4\nline5\n")
    provider = FilesystemSourceProvider(temp_dir)

    assert provider.get_range("a.py", 2, 4) == "line2\nline3\nline4"


def test_get_range_raises_for_missing_file(temp_dir):
    provider = FilesystemSourceProvider(temp_dir)

    with pytest.raises(FileNotFoundError):
        provider.get_range("does_not_exist.py", 1, 2)
