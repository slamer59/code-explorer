# Change Proposal: add-code-search

## Why

Developers need to find code using natural language queries instead of exact text matching. Current tools (grep, ripgrep) require knowing exact function names, making it hard to explore unfamiliar codebases or find "functions that handle authentication" without knowing implementation details.

## What Changes

- Add semantic search engine that understands code intent using embeddings
- Index function signatures, docstrings, and source code in vector database
- Provide natural language query interface via CLI
- Support queries like "find functions that validate user input" or "authentication logic"
- **BREAKING**: None - additive feature only

## Impact

- **Affected specs**: New capability `code-search`
- **Affected code**:
  - New file: `src/code_explorer/search.py` (semantic search engine)
  - New file: `src/code_explorer/embeddings.py` (vector embeddings generation)
  - Modified: `src/code_explorer/cli.py` (add `search` command)
  - Modified: `src/code_explorer/graph.py` (store function source code for indexing)
  - Modified: `pyproject.toml` (add dependencies: sentence-transformers, faiss-cpu)
- **Database changes**: Function node already has `source_code` field (added in recent changes)
- **Performance**: Indexing adds ~2-3 seconds per 1000 functions (one-time cost)
