# Add Dependency Analysis

## Why
Code Explorer currently has no functional capabilities. This change adds the core dependency analysis feature that combines Python's built-in `ast` module with `astroid` (semantic analysis) and KuzuDB (graph storage) to enable developers to quickly determine which files and lines are impacted when they change code. This addresses the critical need for fast, fine-grained impact analysis in Python codebases.

The approach prioritizes simplicity and maintainability by using only well-established, actively maintained tools rather than experimental or archived libraries.

## What Changes
- Add `ast` module integration (Python stdlib) for basic AST parsing and call graph extraction
- Add `astroid` integration for semantic analysis, name resolution, and type inference
- Add KuzuDB integration for storing dependency graphs with fine-grained node and edge types
- Implement code analyzer that extracts functions, classes, variables, and their relationships from Python files
- Create graph schema with nodes (File, Function, Variable) and edges (CONTAINS, CALLS, DEFINES, USES)
- Build impact analysis query system to answer:
  - "How does changing this function affect upstream/downstream code?"
  - "Where can this bug come from or go to?"
- Add parallel processing for analyzing multiple files concurrently
- Implement content hashing for incremental updates (only re-analyze changed files)
- Create CLI interface for analyzing codebases and querying dependencies
- Add visualization support for dependency graphs using Mermaid diagrams with impact highlighting

## Impact
- **Affected specs**: New capability `dependency-analysis`
- **Affected code**:
  - `src/code_explorer/__init__.py` - Add CLI entry point
  - New files:
    - `src/code_explorer/analyzer.py` - Code analysis using ast + astroid
    - `src/code_explorer/graph.py` - KuzuDB graph operations
    - `src/code_explorer/impact.py` - Impact analysis queries
    - `src/code_explorer/cli.py` - Command-line interface
    - `src/code_explorer/visualizer.py` - Graph visualization with Mermaid
- **Dependencies**: Add `astroid`, `kuzu`, `click` (CLI), `rich` (terminal UI)
- **Performance**: Initial analysis will take seconds to minutes depending on codebase size; queries should be sub-second
