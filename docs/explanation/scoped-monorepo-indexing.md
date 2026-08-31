# Scoped Indexing for Monorepos

> Status: **not implemented**. This is a saved design for later — nothing in the
> codebase currently reflects this document.

## The gap, stated plainly

`analyze`/`search`/`ingest_incremental` all discover files by walking a directory tree
and excluding by pattern (`settings.default_exclude_patterns`, plus `analyze`'s
`--exclude`/`--include`) -- see `discover_python_files()` in
`analyzer/base_analyzer.py`. That's an *exclude-list*, not an *include-list*: you can
say "everything except `.venv`", but not "only `services/billing/` and
`libs/shared_auth/`".

On a genuinely large monorepo (the kind `--exclude`/`--include` already imply exist),
that matters in two concrete ways:

- **Cost.** Every `analyze`/`search --reindex` walks and parses the *entire* tree, even
  if you only work in one service directory. `ingest_incremental`'s hash-scan is cheap
  per unchanged file, but it still stats every `.py` file under `target` on every run --
  on a monorepo with tens of thousands of files across dozens of unrelated services,
  that's real wasted work for someone who only ever touches one of them.
- **Relevance.** BM25/vector search results, `impact`/`trace`, and `stats` all currently
  answer over the *whole* indexed tree. If you're working on `services/billing/`, a
  search hit from `services/unrelated_thing/` with a coincidentally similar name is
  noise, not signal -- especially for the LLM-context-assembly use case this tool is
  built around (see `latticedb-migration.md`, Section 18): a scoped result set is a
  *better* context bundle, not just a faster one.

## Proposed design

Add an explicit include-scope, applied on top of (not instead of) the existing
exclude-pattern logic:

- A new `--only PATTERN` option on `analyze` and `search` (repeatable, like
  `--exclude`), accepting directory paths or glob patterns relative to `PATH`
  (e.g. `--only services/billing --only libs/shared_auth`). When given, file discovery
  restricts to files under any of these paths *before* exclude patterns are applied,
  instead of walking all of `PATH`.
- `discover_python_files()` (`analyzer/base_analyzer.py`) gains an `only_patterns:
  Optional[List[str]]` parameter: when set, the git-ls-files fast path filters its
  output to lines starting with one of the given prefixes (cheap -- no extra
  filesystem calls), and the `os.walk` fallback path prunes any directory that isn't
  under (or an ancestor of) one of the scope paths, mirroring how exclude patterns
  already prune `dirnames` in-place.
- `DependencyGraph.ingest_incremental()` takes the same `only_patterns`, threaded
  through to its own `discover_python_files()` call, so incremental re-indexing also
  only hashes files inside the configured scope.
- A `--only` given on `search`/`analyze` must be **stable across runs against the same
  index** -- changing the scope on an existing `.code-explorer` index without
  `--reindex` would leave nodes for now-out-of-scope files lingering (harmless for
  correctness, since they're just not re-hashed, but stale). Document this rather than
  silently reconciling it: if you narrow or widen `--only`, pass `--reindex` once.

## What this does *not* fix, worth stating up front

CALLS edges are resolved by function name across the **whole currently-ingested graph**
(see `analyzer/call_resolver.py` and `ingest_incremental`'s CALLS-edge limitation,
documented in `latticedb-migration.md`'s Phase 3 row) -- if you scope indexing to
`services/billing/` only, a call from billing code into a function that actually lives
in an unindexed `libs/shared_auth/` simply won't resolve to anything (no edge created,
not a wrong one). That's the correct behavior for a genuinely partial index, but it
means `impact`/`trace` results are only as complete as the scope you chose -- scoping
too narrowly silently under-reports impact across service boundaries. This should be
called out plainly in `--only`'s `--help` text, not just this doc.

## Deliberately not designed here

- **No automatic scope detection** (e.g. "infer scope from the nearest `pyproject.toml`
  or `.git` submodule boundary"). `--only` is explicit; inferring it adds a layer of
  surprising behavior for a use case (someone consciously working on one part of a
  monorepo) where explicit is more predictable than clever.
- **No persistent per-repo scope config** (e.g. a `.code-explorer/scope.toml` so you
  don't have to repeat `--only` every invocation). A reasonable follow-up once `--only`
  itself is used enough to know whether that's actually the friction point -- premature
  to build both at once.
- **Not a new file discovery mechanism.** This reuses `discover_python_files()` exactly
  as introduced for "Speed up source file discovery" (see the commit of that name) --
  `--only` is a filter applied within it, not a parallel code path.
