"""Reads source code from disk by path + line range.

Companion to docs/explanation/source-of-truth-and-search-representations.md:
the filesystem is the authoritative source of truth for what code says, so
context assembly reads it directly (via start_line/end_line already stored
on Function/Class nodes) instead of relying on a stored graph property that
can go stale or duplicate storage across a large repo.
"""

from pathlib import Path
from typing import Protocol


class SourceProvider(Protocol):
    """Reads file contents or a line range from some source of truth."""

    def get_file(self, path: str) -> str:
        ...

    def get_range(self, path: str, start_line: int, end_line: int) -> str:
        ...


class FilesystemSourceProvider:
    """Reads source directly from the working tree under `root`."""

    def __init__(self, root: Path):
        self.root = root

    def get_file(self, path: str) -> str:
        try:
            return (self.root / path).read_text()
        except OSError as e:
            raise FileNotFoundError(
                f"Could not read {path!r} under {self.root} -- has the file "
                f"moved or been deleted since indexing? {e}"
            ) from e

    def get_range(self, path: str, start_line: int, end_line: int) -> str:
        text = self.get_file(path)
        lines = text.splitlines()
        if start_line < 1 or end_line > len(lines) or start_line > end_line:
            raise ValueError(
                f"Line range {start_line}-{end_line} is out of bounds for "
                f"{path!r} ({len(lines)} lines) -- the file may have changed "
                f"since indexing; try re-indexing (--reindex)."
            )
        return "\n".join(lines[start_line - 1 : end_line])
