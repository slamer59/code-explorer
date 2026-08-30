# Indexing Markdown Docs for Search Context

> Status: **not implemented**. Design note for future work, saved for later —
> not scoped or scheduled yet. Companion to
> [Searching Code and Getting an LLM-Ready Context Bundle](../tutorials/search-and-context.md)
> and [LatticeDB Migration](latticedb-migration.md).

## The idea

`code-explorer search` today only indexes `Function`/`Class` nodes (see
[Source of Truth & Search Representations](source-of-truth-and-search-representations.md)
for what that indexed text actually contains). A repo's own Markdown docs —
README, `docs/explanation/*.md`, tutorials — often contain the **"why"** behind
code that the code itself doesn't state: design rationale, tradeoffs, "we tried X,
it didn't work because Y." That's exactly the kind of thing missing when a query
asks something conceptual (e.g. "why doesn't context assembly store full source")
and the real answer lives in a doc, not in any function's docstring.

Concretely: a new indexable unit — call it `DocSection` — one node per Markdown
heading + its section text, carrying the same kind of compact `search_text` field
`Function`/`Class` nodes already have (see the doc linked above for why compact,
not the whole file). Indexed through the exact same `SEARCHABLE_TEXT_FIELDS`/BM25/
vector mechanism already built in `graph/backends/lattice_backend.py` — no new
search infrastructure needed, just a new thing to feed into it.

## What this needs, honestly

This is **not** "another language" for the
[Polyglot Analyzer Restructuring](polyglot-analyzer-restructuring.md) plan — Markdown
is a different *content type* (prose/docs), not a programming language, and doesn't
fit that plan's `LanguageAdapter` (which is scoped to functions/classes/calls, not
headings/prose). It's a separate, new extraction path.

- **Grammar is two-stage, not one.** `tree-sitter-markdown` (confirmed on PyPI,
  actively maintained by the `tree-sitter-grammars` org as of this writing) is
  actually *two* grammars used together: a block parser (headings, paragraphs,
  lists, code blocks, tables) and a separate inline parser (emphasis, links, code
  spans). Every language currently in this codebase's design assumes one grammar
  per language — this would be the first two-stage case.
- **Correctness caveat, stated by the grammar itself**: `tree-sitter-markdown`'s own
  documentation says it's "not recommended for use where correctness is important"
  — it's built for editor syntax highlighting, with known inaccuracies on complex
  Markdown. Fine for "index headings and section text for BM25," not something to
  build a correctness-sensitive feature on top of.
- **Indexing granularity is a real decision, not a default.** Per-heading-section
  (not whole-file) is almost certainly right, mirroring the same "compact
  representation beats a raw blob" principle already applied to code's `search_text`
  — but nested headings (an `##` section containing `###` subsections) need a
  concrete rule for where one section's text ends and the next begins.
- **New extraction work, new node type.** A `DocSection` extractor (walking the
  block grammar's heading structure), a new entry in the canonical node model
  (`graph/records.py`/`graph/ingest.py`), and a decision on whether `DocSection`
  gets its own `SEARCHABLE_TEXT_FIELDS` entry alongside `Function`/`Class` or a
  separate one (so results can be filtered/labeled by kind in the CLI's results
  table).

## Where this would touch the existing codebase, when it's picked up

- New `analyzer/languages/markdown/` or similar (not part of the Python
  `LanguageAdapter`, since Markdown isn't "a language" in that plan's sense) — a
  small extractor walking `tree-sitter-markdown`'s block-grammar heading structure.
- `graph/ingest.py` — a `DocSection` conversion path alongside
  `file_analyses_to_records()`'s existing Function/Class handling.
- `graph/backends/lattice_backend.py`'s `SEARCHABLE_TEXT_FIELDS` — add `DocSection`
  (or a new dict entry) so BM25/vector search covers it.
- `cli.py`'s `search` command — the results table already has a `Type` column
  (`Function`/`Class` today); `DocSection` would show up there naturally. Context
  assembly (`ContextAssembler`) is Function-only by design (it expands a call
  graph) — a `DocSection` hit would need its own, simpler "just show the section
  text" path rather than trying to force it through caller/callee expansion.

## Explicitly out of scope for this note

- Not scoped or scheduled — this is a captured idea, not a plan with steps.
- Not extending the Polyglot Analyzer Restructuring plan's `LanguageAdapter` to
  cover this — it's a different kind of content, deliberately kept separate.
- Not deciding the indexing-granularity question above — that needs a real design
  pass when this is picked up, not a default guessed here.
