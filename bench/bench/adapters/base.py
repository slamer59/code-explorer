"""The contract every tool under test satisfies.

A tool is a subprocess. The harness gives it a corpus path and a query
string; it gives back a ranked list. That is the whole interface, and it is
why adding a third tool costs an adapter file rather than a refactor.

`doc_id` is the corpus-relative POSIX file path. It is the only identifier
every code-search tool can produce: zvec-grep returns text chunks with no
guaranteed symbol identity, code-explorer returns whole symbols. Both know
which file they came from. Scoring at file level is therefore the honest
common denominator -- symbol-level numbers are reported separately, and
only for tools that can produce them.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class Hit:
    """One ranked result, normalised across tools."""

    doc_id: str  # corpus-relative POSIX path
    rank: int  # 1-based, as the tool ordered it
    score: float
    symbol: str | None = None  # None when the tool does not name one


@dataclass
class QueryResult:
    """What one query cost and what it returned.

    `seed` is what search returned. `bundle` is what the tool ultimately puts
    in front of the model -- for a tool with no expansion step the two are
    the same list, which is the correct answer for that tool rather than a
    missing measurement.
    """

    seed: list[Hit] = field(default_factory=list)
    bundle: list[Hit] = field(default_factory=list)
    tokens: int = 0
    wall_ms: float = 0.0
    error: str | None = None
    #: What the tool says it actually did, when it says so. Retrieval mode
    #: often depends on which indexes exist rather than on a default, so it
    #: is recorded per query rather than asserted once in the report.
    mode: str | None = None


class Adapter:
    """Base class. Subclasses implement `index` and `query`."""

    name: str = "unnamed"
    #: True when the tool assembles context beyond the raw hit list, so the
    #: report can say whether a `bundle` column is a real second step or an
    #: echo of the first.
    expands: bool = False
    #: Corpus-relative directory holding this tool's index, for the footprint
    #: column. Declared here so nothing outside the adapter has to know it.
    index_dir: str = "."

    def __init__(self, corpus: Path, name: str | None = None, **options: object) -> None:
        self.corpus = Path(corpus).resolve()
        self.options = options
        # The registry key wins over the class default, so one tool can be
        # entered several times under different configurations and each
        # appears as its own row. Comparing a tool's best setup against
        # another tool's best setup is the point; comparing two defaults
        # measures packaging decisions instead.
        if name:
            self.name = name

    @property
    def query_flags(self) -> list[str]:
        """Extra argv appended to every query, from the registry entry."""
        return [str(f) for f in (self.options.get("query_flags") or [])]

    @property
    def reset(self) -> list[str]:
        """Corpus-relative paths to delete before indexing.

        Configurations of the same tool share one index directory, so a
        capability built by one ("run --semantic once and a vector index
        appears") silently leaks into the next. Declaring what to clear keeps
        each configuration measuring what it claims to measure.
        """
        return [str(path) for path in (self.options.get("reset") or [])]

    def clear(self) -> list[str]:
        """Delete the declared reset paths. Returns what was removed."""
        import shutil

        removed = []
        for relative in self.reset:
            target = (self.corpus / relative).resolve()
            # Refuse to escape the corpus: a stray "../.." in a config file
            # must not delete someone's home directory.
            if not target.is_relative_to(self.corpus) or target == self.corpus:
                raise SystemExit(f"reset path escapes the corpus: {relative}")
            if target.is_dir():
                shutil.rmtree(target)
                removed.append(relative)
            elif target.exists():
                target.unlink()
                removed.append(relative)
        return removed

    @property
    def prepare(self) -> list[list[str]]:
        """Extra flag sets, each run once at index time.

        Some capabilities only exist once something has been built -- a
        vector index, a warmed cache. This is how a configuration says so,
        without the harness knowing what any particular flag means.
        """
        return [[str(f) for f in group] for group in (self.options.get("prepare") or [])]

    # -- subprocess plumbing, shared ------------------------------------

    def run(self, argv: Sequence[str], timeout: float = 600.0) -> tuple[str, str, int, float]:
        """Run argv in the corpus directory; return (stdout, stderr, code, ms)."""
        started = time.perf_counter()
        proc = subprocess.run(
            list(argv),
            cwd=self.corpus,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.stdout, proc.stderr, proc.returncode, (time.perf_counter() - started) * 1000

    def relative(self, path: str) -> str:
        """Normalise a tool-reported path to a corpus-relative POSIX doc_id."""
        candidate = Path(path)
        if candidate.is_absolute():
            try:
                candidate = candidate.relative_to(self.corpus)
            except ValueError:
                pass
        return candidate.as_posix().lstrip("./")

    @staticmethod
    def dedupe(hits: list[Hit]) -> list[Hit]:
        """Collapse repeated files, keeping each file's best rank.

        Tools return several chunks or symbols from one file; at file level
        that is one document retrieved once. Keeping the duplicates would
        inflate a tool's apparent precision and silently shorten its
        effective top-k.
        """
        best: dict[str, Hit] = {}
        for hit in hits:
            if hit.doc_id not in best or hit.rank < best[hit.doc_id].rank:
                best[hit.doc_id] = hit
        ordered = sorted(best.values(), key=lambda h: h.rank)
        return [
            Hit(h.doc_id, i, h.score, h.symbol) for i, h in enumerate(ordered, start=1)
        ]

    # -- to implement ---------------------------------------------------

    def index(self) -> None:
        """Build the tool's index over the corpus. May be a no-op."""
        raise NotImplementedError

    def query_argv(self, query: str, k: int) -> list[str]:
        """The exact command one query runs.

        Public because the latency harness times *this*, rather than
        branching on the tool's name to reconstruct it. A tool that cannot
        express a query as a single argv does not belong in this benchmark.
        """
        raise NotImplementedError

    def query(self, query: str, k: int) -> QueryResult:
        raise NotImplementedError

    def notes(self) -> list[str]:
        """Caveats the report must print next to this tool's numbers.

        Lives with the adapter so adding a tool cannot silently add an
        unstated asymmetry to a comparison table.
        """
        return list(self.options.get("notes") or [])
