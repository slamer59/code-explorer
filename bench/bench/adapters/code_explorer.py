"""code-explorer, driven through `search --json`.

Uses the installed CLI, not the package: the benchmark measures what a user
gets, including the interpreter startup and index-open costs that an
in-process harness would hide.
"""

from __future__ import annotations

import json

from .base import Adapter, Hit, QueryResult


class CodeExplorerAdapter(Adapter):
    name = "code-explorer"
    expands = True
    index_dir = ".code-explorer"

    def embedding(self) -> str | None:
        # Only meaningful once --semantic has built a vector index; the
        # model is not selectable from the CLI, it is whatever the local
        # Ollama server is serving.
        return "ollama/nomic-embed-text" if self.prepare else None

    def _argv(self, *extra: str) -> list[str]:
        base = list(self.options.get("command") or ["code-explorer"])
        return [*base, "search", *extra]

    def index(self) -> None:
        self.clear()
        # code-explorer builds its index on first search; --reindex forces it
        # so the timed queries below never pay for the build.
        # query_flags go to the index runs too: some of them (--search-text)
        # change what gets *written*, not how it is queried, and applying them
        # only at query time would silently measure the default index.
        runs = [["--reindex", "--no-context", *self.query_flags],
                *(["--no-context", *self.query_flags, *g] for g in self.prepare)]
        for extra in runs:
            stdout, stderr, code, _ = self.run(
                self._argv(*extra, "--json", "_bench_warmup_", str(self.corpus)),
                timeout=7200,
            )
            if code != 0:
                raise RuntimeError(f"index step {extra} failed ({code}): {stderr[-2000:]}")

    def query_argv(self, query: str, k: int) -> list[str]:
        return self._argv(query, str(self.corpus), "--json", "--limit", str(k),
                          *self.query_flags)

    def query(self, query: str, k: int) -> QueryResult:
        argv = self.query_argv(query, k)
        try:
            stdout, stderr, code, ms = self.run(argv)
        except Exception as exc:  # timeout, missing binary
            return QueryResult(error=f"{type(exc).__name__}: {exc}")
        if code != 0:
            return QueryResult(wall_ms=ms, error=f"exit {code}: {stderr[-500:]}")
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as exc:
            return QueryResult(wall_ms=ms, error=f"unparseable stdout: {exc}")

        seed = self.dedupe([
            Hit(self.relative(h["file"]), h["rank"], float(h["score"]), h.get("name"))
            for h in payload.get("hits", [])
        ])

        # The bundle is the seed's file plus every file expansion reached,
        # ordered by hop distance. Ranking the seed first is not a thumb on
        # the scale: it is what the assembled markdown puts first, and what
        # the model reads first.
        bundle_rows: list[tuple[int, str, str | None]] = []
        seed_node = payload.get("seed")
        if seed_node:
            bundle_rows.append((0, self.relative(seed_node["file"]), seed_node.get("name")))
        for node in payload.get("context_nodes") or []:
            bundle_rows.append(
                (int(node.get("distance", 1)), self.relative(node["file"]), node.get("name"))
            )
        bundle_rows.sort(key=lambda row: row[0])
        bundle = self.dedupe([
            Hit(doc, i, 1.0 / i, symbol)
            for i, (_, doc, symbol) in enumerate(bundle_rows, start=1)
        ])

        return QueryResult(
            seed=seed,
            bundle=bundle,
            tokens=int(payload.get("context_tokens") or 0),
            wall_ms=ms,
            # The retrieval mode is not a property of the tool, it is a
            # property of what was built: `search` fuses a vector index when
            # one exists and runs BM25 alone when it does not. Recording what
            # the tool reports turns "which mode was this?" from a claim in
            # prose into a measurement in the run file.
            mode=payload.get("mode"),
        )
