# Add KuzuDB Persistent Storage

## Why
The current implementation uses an in-memory DependencyGraph that doesn't persist between runs. This means users must re-analyze their entire codebase every time they run a query, which is slow and inefficient for large projects.

Adding KuzuDB persistent storage will enable:
- Graph data persists to disk in `.code-explorer/graph.db`
- Incremental updates: only re-analyze changed files
- Fast queries without re-parsing code
- Support for large codebases (100K+ nodes)

## What Changes
- Replace in-memory graph with KuzuDB backend in `graph.py`
- Create KuzuDB schema with proper node and edge tables
- Implement save/load functionality for graph persistence
- Add incremental update logic using content hashes
- Update CLI to use persistent graph by default
- Add `--refresh` flag to force full re-analysis

## Impact
- **Affected specs**: Modifies existing `dependency-analysis` capability
- **Affected code**:
  - `src/code_explorer/graph.py` - Replace in-memory with KuzuDB
  - `src/code_explorer/cli.py` - Add persistence flags
  - `src/code_explorer/analyzer.py` - Update to check for existing files
- **Dependencies**: Already has `kuzu>=0.0.1`, ensure proper version
- **Breaking changes**: None (backwards compatible with in-memory mode for testing)
- **Performance**: First analysis same speed, subsequent queries instant (no re-parsing)
