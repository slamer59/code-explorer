# Architecture

This document explains how Code Explorer works internally.

## Overview

Code Explorer is built on three core components:

```
┌─────────────────┐
│  Python Source  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐      ┌──────────────────┐
│  AST + Astroid  │────▶ │  KuzuDB Graph    │
│  Code Analyzer  │      │  Persistent DB   │
└─────────────────┘      └────────┬─────────┘
                                  │
                                  ▼
                         ┌────────────────────┐
                         │  Query Engines     │
                         │  (Impact, Stats)   │
                         └────────────────────┘
```

## Component 1: Code Analyzer (AST + Astroid)

### Why Two Parsers?

**AST (Built-in)**: Fast, reliable structure extraction
- Parses Python syntax into Abstract Syntax Tree
- Identifies functions, classes, imports, assignments
- Extracts line numbers and visibility

**Astroid (Semantic Analysis)**: Understands meaning
- Resolves names across modules
- Infers types and call targets
- Handles dynamic Python features
- Powers Pylint (well-maintained, battle-tested)

### Analysis Pipeline

```python
# 1. Parse with AST
tree = ast.parse(source_code)

# 2. Extract structure
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef):
        # Found a function!

# 3. Enhance with Astroid
module = astroid.parse(source_code, file_path)
for func in module.body:
    # Resolve what functions this calls
```

### What Gets Extracted

**Functions**:
- Name, file, line range (start/end)
- Visibility (public vs private based on `_` prefix)
- Call sites (which functions this calls)

**Variables**:
- Name, file, definition line
- Scope (module-level vs function-level)
- Usage sites (where it's read/written)

**Imports**:
- Module being imported
- Import type (absolute, relative, from-import)
- Line number

## Component 2: KuzuDB Graph Database

### Why KuzuDB?

Traditional approaches store dependencies in:
- **JSON/pickle**: No querying, load everything into memory
- **SQLite**: Awkward for graph queries (recursive joins)
- **NetworkX**: In-memory only, doesn't persist

**KuzuDB solves these problems**:
- Property graph database (native graph support)
- Persists to disk (survives restarts)
- Cypher-like query language (natural for graphs)
- Embedded (no separate server needed)
- Fast: Built in C++, optimized for graph traversal

### Graph Schema

```cypher
// Node Tables
CREATE NODE TABLE File(
    path STRING PRIMARY KEY,
    language STRING,
    last_modified TIMESTAMP,
    content_hash STRING  // SHA-256 for change detection
)

CREATE NODE TABLE Function(
    id STRING PRIMARY KEY,  // "file::function_name"
    name STRING,
    file STRING,
    start_line INT64,
    end_line INT64,
    is_public BOOLEAN
)

CREATE NODE TABLE Variable(
    id STRING PRIMARY KEY,  // "file::var_name::line"
    name STRING,
    file STRING,
    definition_line INT64,
    scope STRING  // "module" or "function:func_name"
)

// Edge Tables
CREATE REL TABLE CALLS(FROM Function TO Function, call_line INT64)
CREATE REL TABLE USES(FROM Function TO Variable, usage_line INT64)
CREATE REL TABLE CONTAINS(FROM File TO Function)
CREATE REL TABLE DEFINES(FROM Function TO Variable)
CREATE REL TABLE IMPORTS(FROM File TO File, line_number INT64, is_direct BOOLEAN)
```

### Why This Schema?

**Composite IDs**: `file::function_name` ensures uniqueness even with same-named functions in different files

**Separate edge types**: Different relationships (CALLS vs USES) enable targeted queries

**Line numbers on edges**: Track *where* calls/usages happen for precise navigation

## Component 3: Incremental Updates

### The Problem

Analyzing a large codebase takes time. Re-analyzing everything on each change is wasteful.

### The Solution: Content Hashing

```python
# 1. Compute hash of file contents
content_hash = sha256(file.read()).hexdigest()

# 2. Check if file exists with same hash
if graph.file_exists(file_path, content_hash):
    # Skip analysis - file unchanged
    continue

# 3. If changed, delete old data
graph.delete_file_data(file_path)

# 4. Re-analyze only this file
result = analyzer.analyze_file(file_path)
graph.add_file(file_path, "python", content_hash)
# ... add functions, variables, edges
```

### Performance Impact

Example: 100-file project

**First run**: 5 seconds (analyze all files)
**Second run (no changes)**: 0.5 seconds (hash checks only)
**Second run (10 files changed)**: 1.2 seconds (re-analyze 10 files)

**Speedup**: 4-10x faster for typical edit sessions

## Component 4: Query Engines

### Impact Analysis

Traverses the graph using breadth-first search (BFS):

```python
def analyze_upstream_impact(function, max_depth=5):
    """Find all functions that call this function."""
    queue = [(function, 0)]  # (node, depth)
    visited = set()

    while queue:
        current, depth = queue.pop(0)
        if depth >= max_depth:
            continue

        # Query: MATCH (caller)-[:CALLS]->(current)
        callers = graph.get_callers(current.file, current.name)

        for caller in callers:
            if caller not in visited:
                visited.add(caller)
                queue.append((caller, depth + 1))

    return visited
```

**Why BFS?**
- Guarantees shortest path first
- Natural "ripple effect" visualization (depth = impact distance)
- Can limit depth for performance

### Statistics

Uses KuzuDB aggregation:

```cypher
// Most-called functions
MATCH (caller:Function)-[:CALLS]->(callee:Function)
RETURN callee.name, callee.file, COUNT(*) as call_count
ORDER BY call_count DESC
LIMIT 20
```

**Why in database?**
- No need to load all data into Python
- Database can use indexes and optimizations
- Handles large codebases efficiently

## Data Flow: End-to-End

User runs: `code-explorer analyze ./src`

1. **CLI** (`cli.py`): Parse arguments, initialize graph
2. **Analyzer** (`analyzer.py`):
   - Find all `.py` files
   - Compute hashes, check for changes
   - Parse changed files with AST + Astroid
   - Extract functions, variables, calls
3. **Graph** (`graph.py`):
   - Delete old data for changed files
   - Insert new nodes (File, Function, Variable)
   - Insert new edges (CALLS, USES, CONTAINS)
   - Persist to `.code-explorer/graph.db`
4. **CLI**: Display summary statistics

User runs: `code-explorer impact module.py:func`

1. **CLI**: Parse target, load graph
2. **Impact** (`impact.py`): Run BFS from target function
3. **Graph**: Execute Cypher queries for each level
4. **CLI**: Format results as Rich table

## Design Decisions

### Why not just use grep/ripgrep?

Text search can't understand:
- "Which function calls this?" (requires call graph)
- "What's the impact depth?" (requires traversal)
- "Who uses this variable?" (requires scope analysis)

### Why not use LSP (Language Server Protocol)?

LSP is for editor features (go-to-definition, autocomplete). It:
- Doesn't persist data between sessions
- Doesn't build cross-file dependency graphs
- Doesn't analyze impact across the entire codebase

### Why not use traditional static analysis (mypy, pyright)?

Type checkers focus on correctness, not dependencies. They:
- Don't expose call graphs as queryable data
- Don't support impact analysis queries
- Don't track variable data flow for bug tracing

Code Explorer complements these tools.

## Performance Characteristics

**Analysis**: O(n) in number of files × average file size
- Parallelizable across files
- Bottleneck: AST parsing (unavoidable)

**Storage**: O(f + v + e) where f=functions, v=variables, e=edges
- Typical: 1MB per 10,000 lines of code

**Queries**: O(d × b) where d=depth, b=average branching factor
- Indexed by KuzuDB for fast lookups
- Typical query: < 100ms for depth 5

## Next Steps

- [Design Decisions](design-decisions.md) - Why AST + Astroid + KuzuDB?
- [Incremental Updates](incremental-updates.md) - Deep dive into change detection
- [Graph Algorithms](graph-algorithms.md) - BFS, DFS, and traversal strategies
