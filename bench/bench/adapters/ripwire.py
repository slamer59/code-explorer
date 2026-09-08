"""ripwire (github.com/redhat-et/ripwire), driven through `ripwire --for=TASK --json`.

`--for` is the tool's own recommended natural-language lens; `--query` is
documented as "raw BM25 ranking (debug); use --for" instead, so that is what
this adapter drives. The JSON dialect never carries expanded bodies (its
`bundle` key is always "sigs" for `--json`, per the tool's own --help text),
so there is no second expansion step to record -- `bundle` repeats `seed`,
the same shape as zg.

`--top-k` is documented as inert for `--for` and, worse, prints a warning
line to stdout ahead of the JSON, which breaks the parse -- so it is never
passed here. `--for` has its own internal payload budget (~7.5KB of
signatures) and returns however many ranked symbols fit that budget; this
adapter truncates to `k` client-side after decoding.

ripwire exposes no separate index-build step: each query cold-parses the
corpus, guarded by a warm-by-default per-root cache in the OS tmpdir (outside
the corpus, so there is nothing for `reset` to clear between configurations).
The recorded `wall_ms` is therefore the tool's true steady-state per-query
cost, not an artifact of a missing `prepare` phase.
"""

from __future__ import annotations

import json

from .base import Adapter, Hit, QueryResult


class RipwireAdapter(Adapter):
    name = "ripwire"
    #: --json never serves bodies/hops (bundle="sigs" always), so there is no
    #: real second step -- bundle is seed, same as zg.
    expands = False
    index_dir = "."

    def _argv(self, *extra: str) -> list[str]:
        base = list(self.options.get("command") or ["ripwire"])
        return [*base, ".", *extra]

    def index(self) -> None:
        # No index artifact lives in the corpus to build or clear; the first
        # query pays the cold-parse cost the same way every later one would
        # if the tmpdir cache were absent, so nothing needs pre-warming here.
        pass

    def query_argv(self, query: str, k: int) -> list[str]:
        return self._argv(f"--for={query}", "--json", *self.query_flags)

    def query(self, query: str, k: int) -> QueryResult:
        argv = self.query_argv(query, k)
        try:
            stdout, stderr, code, ms = self.run(argv)
        except Exception as exc:
            return QueryResult(error=f"{type(exc).__name__}: {exc}")
        if code != 0:
            return QueryResult(wall_ms=ms, error=f"exit {code}: {stderr[-500:]}")
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as exc:
            return QueryResult(wall_ms=ms, error=f"unparseable stdout: {exc}")

        ranked = sorted(payload.get("sigs") or [], key=lambda s: s.get("r", 0))
        hits = self.dedupe([
            Hit(self.relative(s["p"]), s["r"], 1.0 / s["r"], s.get("n"))
            for s in ranked
            if s.get("p") is not None
        ])[:k]
        hits = [Hit(h.doc_id, i, h.score, h.symbol) for i, h in enumerate(hits, start=1)]

        return QueryResult(
            seed=hits,
            bundle=hits,
            tokens=int(payload.get("est_tokens") or 0),
            wall_ms=ms,
            mode=payload.get("route"),
        )
