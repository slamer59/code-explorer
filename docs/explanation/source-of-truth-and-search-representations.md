# Source of Truth: Stop Storing Full Source in LatticeDB

> Status: **implemented**. `src/code_explorer/source_provider.py` (the
> `SourceProvider` protocol), `src/code_explorer/graph/ingest.py` (the derived
> `search_text` field), and `src/code_explorer/context.py` (`ContextAssembler`
> reading source via `SourceProvider` instead of a stored property) all exist
> and are in use by `code-explorer search`. See "Measured result" below for
> real numbers. Companion to [LatticeDB Migration](latticedb-migration.md) and
> its [Implementation Status](latticedb-migration.md#1a-implementation-status)
> section.

## The gap, stated plainly

Today, `Function`/`Class` nodes store their **entire `source_code`** as a graph
property, and that same stored copy is used for three different, unrelated
purposes:

1. **BM25 indexing** — `LatticeBackend.SEARCHABLE_TEXT_FIELDS` (`graph/backends/lattice_backend.py`)
   creates a full-text index directly over `source_code`.
2. **Vector embeddings** — `build_vector_index()` embeds the same `source_code`
   property.
3. **Context assembly** — `ContextAssembler._get_source()` (`src/code_explorer/context.py`)
   reads the same stored `source_code` to build the LLM context bundle.

This works at the scale tested so far (this repo's own ~450 nodes) but does
not scale to a large monorepo, for three concrete, compounding reasons:

- **Storage/RAM cost multiplies with repo size.** Every function's full body
  is duplicated into the graph database, indexed for FTS, and (once vector
  search is used) embedded — three copies of information that already exists
  on disk, once, in the working tree. At monorepo scale (tens or hundreds of
  thousands of functions) this is a real, compounding cost, not a rounding
  error — and this session already measured LatticeDB's per-query cost
  scaling with graph size (see the migration doc's benchmark findings), so
  a bloated graph makes an already-real performance gap worse, not better.
- **BM25 relevance is diluted by syntax noise.** Indexing full source code
  means keywords, punctuation-adjacent identifiers, and boilerplate compete
  with the actual meaningful vocabulary (names, docstrings) for BM25 term
  weight. A compact representation is not just smaller — it's a *better*
  search signal, not a lesser one.
- **The stored copy goes stale.** `source_code` is captured once at ingest
  time. If the file changes without a re-index (and there is no incremental
  re-index yet — see the migration doc's Phase 3 status), the stored copy
  silently diverges from the actual file. Context assembly then hands an
  LLM code that no longer matches what's on disk, with no signal that this
  happened.

None of this is hypothetical or speculative — it's a direct consequence of
the current design, verifiable by reading `graph/ingest.py`,
`graph/backends/lattice_backend.py`, and `src/code_explorer/context.py` as
they stand today.

## The fix: LatticeDB is a code *index*, not a source *warehouse*

The filesystem (or Git) is already the authoritative, always-current source
of truth for what the code actually says. LatticeDB's job should be to say
**where** a symbol lives and **why** it matters (graph relationships, search
relevance) — not to hold a second copy of **what** it says.

```text
                  ┌──────────────────────┐
                  │   Git / Filesystem   │
                  │                      │
                  │ FULL SOURCE          │
                  └──────────┬───────────┘
                             │
                    path + line ranges
                             │
                             ▼
┌──────────────────────────────────────────────────┐
│                   LATTICEDB                      │
│                                                  │
│  File / Module / Class / Function / Test nodes  │
│  Graph relationships (CALLS, CONTAINS, ...)     │
│                                                  │
│  search_text ──────────────► BM25                │
│  embedding_text ───────────► HNSW               │
│  metadata / hashes / locations                   │
└───────────────────────┬──────────────────────────┘
                        │
                 hybrid retrieval
                        │
                        ▼
                 impact analysis
                        │
                        ▼
                  ranked nodes
                        │
                        ▼
                 SourceProvider
                        │
                        ▼
                   source slices
                        │
                        ▼
                       LLM
```

### 1. `search_text`: a compact, derived indexing artifact

Not part of the canonical `NodeRecord`/`EdgeRecord` model (`graph/records.py`)
— an *indexing-time* derivation, so the BM25 representation can be iterated
on without another graph migration. Minimal version (deliberately not
over-built — see "What this is not," below):

```text
search_text =
    qualified-ish name (file::function_name)
    + signature-ish (name + params, if cheaply available)
    + docstring (first line is enough to start)
```

Example, for `refresh_token(token: str) -> AccessToken` in `auth/token.py`:

```text
auth/token.py::refresh_token
refresh_token(token)
Refreshes an expired OAuth access token.
```

Tiny compared to the function's full body, but carries the actual useful
vocabulary (`refresh`, `token`, `OAuth`, `expired`, `access`) without syntax
noise.

**No new extractor needed to get the docstring.** `source_code` is already
available *in memory* in `FileAnalysis` during `graph/ingest.py`'s
conversion step, before it's ever written anywhere. A cheap, non-AST
heuristic (first triple-quoted string immediately following the `def`/`class`
line) can pull a docstring out of that in-memory text — then the full text is
simply never written into the `NodeRecord`. This avoids touching the
extractor layer at all (which `docs/explanation/polyglot-analyzer-restructuring.md`
already scoped separately and deliberately left alone).

### 2. `embedding_text`: start as the same representation as `search_text`

The richer version of this idea (BM25 gets terse identifier-heavy text,
embeddings get a fuller natural-language description) is good in principle —
but building two derivation paths before there's evidence the shared one is
insufficient is exactly the kind of premature complexity this codebase has
been deliberately avoiding all along (see the "always add tests but not too
much" / minimal-ranking framing in the migration doc). Start with one shared
`search_text` feeding both BM25 and the embedding call; only split them if a
concrete quality problem is observed with real queries.

### 3. `SourceProvider`: the actual source of truth

```python
class SourceProvider(Protocol):
    def get_file(self, path: str) -> str: ...
    def get_range(self, path: str, start_line: int, end_line: int) -> str: ...
```

Implementations: `FilesystemSourceProvider` (read the file directly — the
obvious default, and all that's needed initially) and, later if useful,
`GitSourceProvider` (read a specific commit's blob, for analyzing a
historical revision rather than the working tree).

`ContextAssembler` stops reading a stored `source_code` property and instead
calls `SourceProvider.get_range(file, start_line, end_line)` using the
`start_line`/`end_line` already stored on every `Function`/`Class` node
today (no new fields needed there). This also means context assembly always
reflects the *current* file content, not a stale ingest-time snapshot —
strictly better, not just smaller.

**A residual staleness note, for honesty**: if a file changes after indexing
but before a query, `start_line`/`end_line` could point at the wrong lines
until the next re-index. This is not a *new* problem this design
introduces — the graph structure itself is already stale in that scenario
(no incremental re-index exists yet, migration doc Phase 3), so line-range
drift is a symptom of that same known, already-documented gap, not an
additional one.

## Measured result

Run `perfo/benchmark_index_size.py` yourself to reproduce:

```
uv run --python 3.12 --extra dev python perfo/benchmark_index_size.py [DIR]
```

On this repo's own `src/code_explorer` (44 files, ~450 nodes), indexing with the
default compact `search_text` instead of full `source_code`
(`include_source=True`) produced:

| Mode | Index size |
|---|---|
| Compact `search_text` (default) | 8,068 KiB |
| Full `source_code` (`include_source=True`) | 10,164 KiB |
| Reduction | 21% |

A real reduction, but more modest than the gap's framing above might suggest —
FTS/vector index structures themselves are a meaningful share of file size
independent of the indexed property's text length, so shrinking the property
doesn't shrink the file 1:1. The staleness and BM25-relevance-dilution
arguments for this design stand independent of the size number.

## What this is not

- Not a call to add docstring extraction as a first-class extractor feature
  (that's `polyglot-analyzer-restructuring.md`'s territory if/when it
  happens) — the in-memory heuristic above is a deliberately cheap stopgap.
- Not a call to generate LLM-written summaries during indexing — too
  expensive to run per-function at monorepo scale; AST-derived metadata
  (name, signature, decorators) is the fallback when no docstring exists,
  not an LLM call.
- Not a call to split `search_text`/`embedding_text` into two
  representations now — start shared, split only with evidence.
- Not scoped or scheduled — this is a documented gap and a recommended
  direction, not a plan with steps to execute yet.

## Where this touches the existing codebase, when it's picked up

- `graph/ingest.py` — stop putting full `source_code` into Function/Class
  `NodeRecord.properties`; derive and store `search_text` instead.
- `graph/backends/lattice_backend.py` — `SEARCHABLE_TEXT_FIELDS` indexes
  `search_text` instead of `source_code`; `build_vector_index()` embeds the
  same field.
- `src/code_explorer/context.py` — `ContextAssembler` gains a
  `SourceProvider` dependency and reads source via `get_range()` instead of
  a stored property.
- `graph/schema.py` (Kuzu) — the `Function`/`Class` DDL's `source_code`
  column would need to change too, if/when `KuzuBackend` ever needs to stay
  in parity with this (search is currently LatticeDB-only, so this is a
  lower-priority side effect, not a blocker).
