"""zvec-grep (`zg`), driven through `zg query`.

`zg` has no JSON output as of 0.2.1, so this parses its agent-markdown,
whose hit header is stable and machine-shaped:

    #1 matchedBy=fts+vector src/gemseo/core/collections/functions.py:127-151
    symbol: function get_dimension scope: Functions

Asymmetries the report must state rather than silently correct for:
`zg` indexes every file type while code-explorer indexes Python only; `zg`
is hybrid FTS+vector by default while code-explorer's default is BM25
alone; `zg` returns chunks where code-explorer returns whole symbols.
"""

from __future__ import annotations

import re

from .base import Adapter, Hit, QueryResult

_HIT = re.compile(r"^#(\d+)\s+matchedBy=(\S+)\s+(.+?):(\d+)-(\d+)\s*$")
_SYMBOL = re.compile(r"^symbol:\s+\S+\s+(\S+)")

# Same len/4 heuristic code-explorer uses for its own budget, so the cost
# column compares two numbers produced the same way.
_CHARS_PER_TOKEN = 4


class ZgAdapter(Adapter):
    name = "zg"
    index_dir = ".zvec-grep"
    #: zg returns hits; it has no second expansion step. Its `bundle` is its
    #: seed list, which is what an agent would actually read.
    expands = False

    def _argv(self, *extra: str) -> list[str]:
        base = list(self.options.get("command") or ["zg"])
        return [*base, *extra]

    def index(self) -> None:
        self.clear()
        embedding = str(self.options.get("embedding") or "local/potion-retrieval-32m")
        stdout, stderr, code, _ = self.run(
            self._argv("index", "--embedding", embedding), timeout=7200
        )
        if code != 0:
            raise RuntimeError(f"index failed ({code}): {stderr[-2000:]}")

    def query_argv(self, query: str, k: int) -> list[str]:
        return self._argv(
            "query", query,
            "--limit", str(k),
            "--mode", str(self.options.get("mode") or "direct"),
            "--preview", "none",
            *self.query_flags,
        )

    def query(self, query: str, k: int) -> QueryResult:
        argv = self.query_argv(query, k)
        try:
            stdout, stderr, code, ms = self.run(argv)
        except Exception as exc:
            return QueryResult(error=f"{type(exc).__name__}: {exc}")
        if code != 0:
            return QueryResult(wall_ms=ms, error=f"exit {code}: {stderr[-500:]}")

        hits = self.dedupe(list(self._parse(stdout)))
        # zg exposes no score, only an explicit rank. 1/rank is
        # rank-preserving, which is all ranx needs to order a run.
        # zg names the route that matched each hit ("fts", "vector",
        # "fts+vector"); the modes actually used across the hit list is the
        # honest description of what ran.
        routes = sorted({m.group(2) for m in map(_HIT.match, map(str.strip, stdout.splitlines())) if m})
        return QueryResult(
            seed=hits,
            bundle=hits,
            tokens=len(stdout) // _CHARS_PER_TOKEN,
            wall_ms=ms,
            mode=",".join(routes) or None,
        )

    def _parse(self, stdout: str):
        lines = stdout.splitlines()
        for i, line in enumerate(lines):
            match = _HIT.match(line.strip())
            if match is None:
                continue
            rank = int(match.group(1))
            symbol = None
            if i + 1 < len(lines):
                sym = _SYMBOL.match(lines[i + 1].strip())
                if sym is not None:
                    symbol = sym.group(1)
            yield Hit(self.relative(match.group(3)), rank, 1.0 / rank, symbol)
