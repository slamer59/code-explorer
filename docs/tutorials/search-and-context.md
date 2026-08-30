# Searching Code and Getting an LLM-Ready Context Bundle

This tutorial walks through `code-explorer search` *(experimental)*: finding
code by keyword, typo, or meaning, and getting back a ready-to-use bundle of
source code instead of just a list of file names.

## What You'll Learn

By the end of this tutorial, you'll be able to:
- Search a codebase by keyword (BM25) and get a context bundle for the top hit
- Recover from a typo'd query with fuzzy search
- Jump straight to a known function with the exact-match shortcut
- Search by meaning, not keywords, with semantic (vector) search

## Prerequisites

- A Python project to search (this tutorial uses Code Explorer's own source,
  same as the [Getting Started](getting-started.md) tutorial)
- For the semantic search step only: a local [Ollama](https://ollama.com)
  server with the `nomic-embed-text` model pulled

## Before you start: this is a separate index from `analyze`

If you've done the [Getting Started](getting-started.md) tutorial, you've
already built a KuzuDB database with `code-explorer analyze`. `search` does
**not** use that database — it builds its own **LatticeDB** index instead
(the only backend with full-text/semantic search built in). The first
`search` on a directory indexes it automatically; nothing needs to run first.

## Step 1: Your First Search

```bash
code-explorer search "resolve call" src
```

The first run indexes the directory (you'll see `Analyzing files...` and
`Writing nodes`/`Writing edges` progress bars), then runs the search:

```
Search results for 'resolve call'
┏━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━┓
┃ Type  ┃ Name         ┃ File                             ┃ Score ┃
┡━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━┩
│ Class │ FunctionCall │ code_explorer/analyzer/models.py │ 3.456 │
│ Class │ ContextNode  │ code_explorer/context.py         │ 3.118 │
└───────┴──────────────┴──────────────────────────────────┴───────┘
```

**What just happened?** This is BM25 lexical search — the default mode. It
ranks matches by relevance to the words in your query, over a compact index
(symbol name, signature, docstring — not the whole file, see
[Source of Truth & Search Representations](../explanation/source-of-truth-and-search-representations.md)
if you're curious why).

Run it again on the same directory — no re-indexing this time, since the
index already exists:

```bash
code-explorer search "walking a syntax tree recursively" src
```

## Step 2: The Context Bundle

By default, `search` doesn't just list hits — it also assembles a bundle of
source code for the top **Function** hit (Class hits have no call graph to
expand, so they're skipped for this part):

```
Seed:
    analyzer/tree_sitter_adapter.py::walk_tree

Direct callers:
    ...

Direct callees:
    ...

---

### analyzer/tree_sitter_adapter.py::walk_tree (seed)
```python
def walk_tree(tree):
    ...
```
```

**What just happened?** The seed function's source, plus its direct callers
and callees (source attached, capped at 20 nodes total) — everything you'd
need to hand an LLM to answer "what does this do and what touches it,"
without a separate round of grepping and reading files. Pass `--no-context`
if you only want the ranked hit list.

## Step 3: Recovering from a Typo

```bash
code-explorer search "resolv_cal" src --fuzzy
```

BM25 (Step 1) would find nothing for a misspelled query like this — `--fuzzy`
tolerates the typo and still finds `resolve_call`-shaped matches.

## Step 4: Jumping Straight to a Known Function

If your query looks like `file.py:function_name` (the same format
`code-explorer impact` uses), `search` skips ranking entirely and resolves it
directly:

```bash
code-explorer search "src/code_explorer/context.py:assemble_context" .
```

```
Exact match: src/code_explorer/context.py::assemble_context

Context:
### src/code_explorer/context.py::assemble_context (seed)
```python
def assemble_context(
    self, file: str, function: str, max_nodes: int = 20
) -> CodeContext:
    ...
```
```

**What just happened?** No BM25 involved — `get_function()` resolved the
target directly. This is the fast path for "I already know exactly what I
want," same as `impact`/`trace`'s target format.

## Step 5: Searching by Meaning, Not Keywords

Semantic search finds conceptually related code even when there's no shared
vocabulary at all. It needs a local embedding model first:

```bash
ollama pull nomic-embed-text
```

Then:

```bash
code-explorer search "walking a syntax tree recursively" src/code_explorer/analyzer --semantic
```

```
Search results for 'walking a syntax tree recursively'
┏━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┓
┃ Type     ┃ Name                 ┃ File                ┃ Distance (lower=closer) ┃
┡━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━┩
│ Function │ walk_tree            │ analyzer/extractor… │                0.292 │
│ Function │ walk_tree            │ analyzer/tree_sitt… │                0.306 │
│ Function │ walk                 │ analyzer/tree_sitt… │                0.342 │
└──────────┴──────────────────────┴─────────────────────┴──────────────────────┘
```

**What just happened?** `walk_tree`/`walk` don't share the words "walking,"
"syntax," or "recursively" with the query in any exact sense — the ranking
comes from meaning, not keyword overlap. Note the column: **lower is
better** for `--semantic` (it's a distance), the opposite direction from
BM25's score in Step 1 — don't compare the two numbers directly.

This uses a **separate index file** from Steps 1-4 (vector dimensions are
fixed when a LatticeDB index is created, so semantic and non-semantic search
can't share one file) — the first `--semantic` run on a directory always
indexes and embeds from scratch, even if you already ran plain `search`
there.

## What's Next?

- [CLI Commands Reference](../reference/cli-commands.md#search---find-code-by-keyword-or-meaning-experimental) —
  full flag reference (`--limit`, `--reindex`, etc.)
- [LatticeDB Migration](../explanation/latticedb-migration.md) — the design
  behind this feature and what's not built yet (hybrid retrieval, confidence
  scoring)
- [Getting Started](getting-started.md) — if you haven't yet, `analyze` +
  `impact`/`trace`/`stats`/`visualize` cover the KuzuDB side (exact
  structural queries, not search)

## Troubleshooting

**`--semantic` fails or times out?**
- Confirm Ollama is running and the model is pulled: `ollama pull nomic-embed-text`

**Results look stale after editing code?**
- There's no incremental update yet — re-run with `--reindex` to force a
  fresh index

**"No results" for a query that should obviously match something?**
- Try `--fuzzy` (typos) or `--semantic` (no shared keywords) — the message
  after an empty BM25 result suggests both

**A search hit is a Class and there's no context bundle?**
- Context assembly is Function-only today (Classes have no call graph to
  expand) — `search` tells you this rather than erroring
