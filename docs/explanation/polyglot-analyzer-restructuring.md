# Restructuring the Analyzer for Polyglot Readiness

> Status: **not implemented**. This is a saved design/plan for later — Python is the
> only language implemented today, and this document describes how to restructure the
> analyzer so a second language can be added later without touching shared code.
> Nothing in the codebase currently reflects this document.

## Context

The tree-sitter based parser/extractor pipeline (`src/code_explorer/analyzer/`) is
currently Python-only, with no seam for adding another language later: file discovery
is a hardcoded `*.py` glob, the parser module hardcodes `tree_sitter_python`, and every
extractor hardcodes Python's tree-sitter node-type strings inline. The tree-sitter
library itself (`tree-sitter` on PyPI, plus per-language grammar packages like
`tree_sitter_python`) is the real [tree-sitter](https://github.com/tree-sitter/tree-sitter)
project originally created by Max Brunsfeld at GitHub — the same incremental parser
GitHub uses for syntax highlighting and code navigation — so grammars for most major
languages already exist and are actively maintained in that ecosystem.

The goal here is **not** to add another language now — only to restructure Python's
existing implementation so it has "the good structure": adding a second language later
should be a matter of adding a new package and registering it, not touching shared
code. This is a pure internal reorganization: same CLI behavior, same `FileAnalysis`
output shape (plus one new `language` field), same graph/ingestion downstream.

## Current state (as of this analysis)

- **`analyzer/parser.py`**: hardcodes `import tree_sitter_python`; `get_python_parser()`
  uses a single global `_parser_cache: Parser | None` (not keyed by language);
  `parse_python_file()`/`parse_file()` call it unconditionally, no language parameter
  anywhere. `get_parser_type()` always returns the literal `"tree_sitter"` (vestigial).
  `extract_source_text()`/`get_node_text()`/`parse_and_extract()` are genuinely generic
  byte-offset utilities with no Python-specific logic.
- **`analyzer/tree_sitter_adapter.py`**: `TreeSitterAdapter`, `TreeSitterWalker`,
  `NodeWrapper`, `wrap_node()`, `walk_tree()`, `detect_parser_type()` are all
  language-agnostic and reusable as-is. `is_function_node()`, `is_call_node()`,
  `get_node_name()` hardcode Python's literal node-type strings
  (`"function_definition"`, `"call"`) and are **live** — `BaseExtractor` delegates to
  them. `get_tree_sitter_language()` and `parse_with_tree_sitter()` are dead code (no
  callers found; use a deprecated tree-sitter API / the old `tree_sitter_languages`
  bundle API that isn't used anywhere else in the codebase) — should be deleted rather
  than moved (verify no callers first). `TREE_SITTER_NODE_TYPES` is also unreferenced
  dead scaffolding — delete.
- **`analyzer/base_analyzer.py`** (`CodeAnalyzer`): `analyze_directory()` hardcodes
  `root_path.rglob("*.py")` (line 328); `analyze_file()` calls `parse_python_file()`
  unconditionally; `_run_extractions()` runs one fixed, hardcoded set of extractor
  instances built in `__init__` regardless of file type; `_extract_module_info()` is
  Python-package-specific (`__init__.py` walking) — this stays Python-only logic, just
  relocated.
- **`analyzer/extractors/*.py`**: every extractor (`functions.py`, `classes.py`,
  `imports.py`, `variables.py`, `decorators.py`, `attributes.py`, `exceptions.py`)
  hardcodes Python tree-sitter node-type string literals inline (e.g.
  `node.type == "function_definition"`, `"class_definition"`, `"import_statement"`,
  field names like `"superclasses"`). `extractors/base.py` (`BaseExtractor`) is itself
  generic (delegates to the adapter layer), but calls the Python-specific helpers above.
  All extractors import `get_parser_type` from `analyzer/parser.py`.
- **`analyzer/models.py`**: `FileAnalysis` and the per-construct dataclasses are already
  language-agnostic in shape; no schema blocker. No `language` field exists yet on
  `FileAnalysis` — needs to be added.
- **`graph/ingest.py:70`**: hardcodes `"language": "python"` when building `File`
  `NodeRecord`s — the one place downstream that needs the real detected language.
  `node_operations.py`'s `add_file()` already takes `language` as a parameter (no
  change needed there).
- **`graph/schema.py`**: `File.language` is already a free-form `STRING` column, not an
  enum — no schema change needed.
- **No call sites outside `analyzer/`** import `analyzer.parser` or
  `analyzer.extractors` directly (confirmed via repo-wide grep) — every importer is
  internal to the analyzer package itself (`base_analyzer.py` and the extractors
  importing each other / `get_parser_type`). This move is self-contained; no compat
  shim needed anywhere (this repo's convention favors direct updates over
  backward-compat shims for internal reorgs — see `graph.py`→`graph/`, which predates
  this analysis, not a pattern to add to deliberately).
- **`tree-sitter-languages` dependency** is already declared in `pyproject.toml` and
  bundles many prebuilt grammars, but is only referenced by the dead code above — not
  actually wired into the live path. Not needed for this restructuring (Python-only),
  but confirms grammars for a future second language are already available without new
  installs.

## Target structure

```
src/code_explorer/analyzer/
    languages/
        __init__.py          # LANGUAGE_REGISTRY dict + register_language() + detect_language(path)
        base.py               # LanguageAdapter dataclass (the extension point)
        python/
            __init__.py        # builds PYTHON_ADAPTER, calls register_language(PYTHON_ADAPTER)
            parser.py           # moved from analyzer/parser.py: get_python_parser(), parse_python_file()
            node_helpers.py     # moved from tree_sitter_adapter.py: is_function_node(), is_call_node(), get_node_name()
            extractors/         # moved from analyzer/extractors/*.py, unchanged internals
                base.py           # BaseExtractor (generic contract; imports node_helpers from ..node_helpers)
                functions.py
                classes.py
                imports.py
                variables.py
                decorators.py
                attributes.py
                exceptions.py
                __init__.py
    parser.py                 # kept: only the generic byte-offset utilities
                               # (extract_source_text, get_node_text, parse_and_extract)
    tree_sitter_adapter.py     # kept: only the generic adapter classes
                               # (TreeSitterAdapter, TreeSitterWalker, NodeWrapper, wrap_node, walk_tree)
    base_analyzer.py           # CodeAnalyzer: registry-driven file discovery + dispatch
    models.py                  # + `language: str` field on FileAnalysis
```

`LanguageAdapter` (new, `analyzer/languages/base.py`):

```python
@dataclass(frozen=True)
class LanguageAdapter:
    name: str                                   # "python"
    extensions: Tuple[str, ...]                 # (".py",)
    get_parser: Callable[[], Parser]             # returns a ready tree-sitter Parser
    extractor_classes: Tuple[Type[BaseExtractor], ...]
    extract_module_info: Optional[Callable] = None   # Python's __init__.py-walking hook; None if a language has no equivalent
```

## Implementation steps

### Step 1 — Add the registry + `LanguageAdapter`

New `analyzer/languages/base.py` (dataclass above) and `analyzer/languages/__init__.py`:

```python
LANGUAGE_REGISTRY: Dict[str, LanguageAdapter] = {}

def register_language(adapter: LanguageAdapter) -> None:
    LANGUAGE_REGISTRY[adapter.name] = adapter

def detect_language(path: Path) -> Optional[str]:
    for name, adapter in LANGUAGE_REGISTRY.items():
        if path.suffix in adapter.extensions:
            return name
    return None
```

### Step 2 — Split `tree_sitter_adapter.py`

Delete the dead code (`get_tree_sitter_language`, `parse_with_tree_sitter`,
`TREE_SITTER_NODE_TYPES`) after confirming no callers (repeat the grep as a final
check before deleting — don't trust an earlier finding blindly). Move
`is_function_node()`, `is_call_node()`, `get_node_name()` to new
`analyzer/languages/python/node_helpers.py` unchanged. Leave `TreeSitterAdapter`,
`TreeSitterWalker`, `NodeWrapper`, `wrap_node()`, `walk_tree()`, `detect_parser_type()`
in place in `tree_sitter_adapter.py` — they're already generic.

### Step 3 — Split `parser.py`

Move `get_python_parser()` and `parse_python_file()` to
`analyzer/languages/python/parser.py`. Leave `extract_source_text()`, `get_node_text()`,
`parse_and_extract()`, and `get_parser_type()` in `analyzer/parser.py` (generic,
still used by every extractor via `get_parser_type`).

### Step 4 — Move extractors

Move `analyzer/extractors/*.py` to `analyzer/languages/python/extractors/*.py`
unchanged except import paths: `BaseExtractor`'s `is_function_node`/`is_call_node`/
`get_node_name` methods now import from sibling `..node_helpers` instead of
`code_explorer.analyzer.tree_sitter_adapter`; each extractor's
`from code_explorer.analyzer.parser import get_parser_type` stays pointed at the
now-slimmer `analyzer/parser.py` (unchanged, still there).

### Step 5 — Build `PYTHON_ADAPTER` and register it

`analyzer/languages/python/__init__.py` imports the moved parser + extractor classes,
builds a `PYTHON_ADAPTER = LanguageAdapter(name="python", extensions=(".py",), ...)`,
and calls `register_language(PYTHON_ADAPTER)`. `analyzer/base_analyzer.py` imports
`analyzer.languages.python` (for its registration side effect) alongside
`analyzer.languages` (for the registry/dispatch functions).

### Step 6 — Make `CodeAnalyzer` registry-driven

In `base_analyzer.py`:
- `analyze_directory()`: replace the hardcoded `root_path.rglob("*.py")` with a loop
  over `{ext for a in LANGUAGE_REGISTRY.values() for ext in a.extensions}` (currently
  just `.py` — behavior is identical today, but no longer hardcoded).
- `analyze_file()`: call `detect_language(file_path)`, look up the `LanguageAdapter`,
  use `adapter.get_parser()` instead of the direct `parse_python_file` import, and set
  `FileAnalysis.language = adapter.name`. If no adapter matches, skip the file (this
  can't happen today since only `.py` is discovered, but makes the dispatch honest).
- `_run_extractions()` / `__init__`: build extractor instances from
  `adapter.extractor_classes` instead of the hardcoded fixed list.
- `_extract_module_info()` stays exactly as-is (Python-specific), just called only when
  `adapter.extract_module_info` is set (wire the existing method in as `PYTHON_ADAPTER`'s
  `extract_module_info` hook rather than an unconditional call).

### Step 7 — Add `language` to `FileAnalysis` and fix `ingest.py`

Add `language: str` to `FileAnalysis` in `analyzer/models.py` (small additive change).
In `graph/ingest.py:70`, replace the hardcoded `"language": "python"` with
`result.language`.

### Step 8 — Verification

- No test suite exercises the analyzer directly today (only
  `tests/test_generic_ingestion.py`, `tests/test_lattice_search_capabilities.py`,
  `tests/test_query_operations_backend_agnostic.py` exist, none touch
  `analyzer/parser.py`/`extractors/` imports). Run
  `uv run --python 3.12 --extra dev pytest tests/ -q` — must stay green (behavior-
  preserving refactor, not exercised by import path changes but confirms nothing
  else broke).
- Re-run `perfo/index_with_lattice.py` against this repo's own `src/code_explorer` — it
  exercises the full `CodeAnalyzer.analyze_directory` → `CallResolver` →
  `ingest_results` → `ImpactAnalyzer` pipeline end-to-end. Compare node/edge counts and
  the impact-trace output against a pre-refactor run — should match exactly, since this
  is a pure reorganization.
- Add one small test asserting `FileAnalysis.language == "python"` after analyzing a
  fixture file (using existing `tests/conftest.py` fixtures), and one test asserting
  `detect_language(Path("x.py")) == "python"` / `detect_language(Path("x.rs")) is None`
  — keep this small (2 tests), not a full suite.

## Explicitly out of scope

- Registering or implementing any language other than Python (no `.js`/`.go`/`.rs`
  adapters, no `tree-sitter-languages` wiring).
- Renaming `BaseExtractor` or redesigning the extraction contract itself — it's already
  generic enough to serve as the shared interface; only its Python-specific delegate
  helpers move.
- Fixing the `imports.py`/`exceptions.py` Python-idiosyncrasies (relative-import dot
  counting, exception raise/catch) to be more "generic" — they stay exactly as they are,
  just relocated. Generalizing them is meaningless without a second language to validate
  against.
- Wiring `tree-sitter-languages` grammars for other languages.
