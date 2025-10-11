# Code Explorer

Python code dependency analyzer with persistent graph storage using KuzuDB.

## Overview

Code Explorer analyzes Python codebases to build a persistent dependency graph. It tracks functions, classes, variables, and their relationships (calls, imports, inheritance), enabling impact analysis and code navigation.

---

## Tutorial

### Getting Started

**Installation**

```bash
pip install -e .
```

**First Analysis**

```bash
# Analyze your codebase
code-explorer analyze ./src

# View statistics
code-explorer stats
```

You'll see output like:
```
Total files analyzed: 6
Total classes: 15
Total functions: 62
Total variables: 236
```

**Finding Impact**

```bash
# Find who calls a function (upstream dependencies)
code-explorer impact src/module.py:my_function

# Find what a function calls (downstream dependencies)
code-explorer impact src/module.py:my_function --downstream
```

**Incremental Updates**

```bash
# Second run - only analyzes changed files
code-explorer analyze ./src

# Force full re-analysis
code-explorer analyze ./src --refresh
```

**Visual Exploration**

```bash
# Start KuzuDB Explorer web UI
docker compose up -d

# Open http://localhost:8000
# Run Cypher queries to explore the graph
```

---

## How-To Guides

### How to Control Source Code Storage

By default, full source code is stored for functions and classes:

```bash
# Don't store source code (smaller database)
code-explorer analyze ./src --no-source

# Store only first 10 lines (preview mode)
code-explorer analyze ./src --source-lines 10
```

### How to Reset the Database

```bash
# Delete the database directory
rm -rf .code-explorer/

# Re-analyze from scratch
code-explorer analyze ./src --refresh
```

### How to Use Read-Only Mode

```bash
# The KuzuDB Explorer runs in read-only mode by default
docker compose up -d
```

Read-only mode prevents accidental schema changes while allowing all queries.

### How to Customize Database Location

```bash
# Specify custom database path
code-explorer analyze ./src --db-path /path/to/custom/db
```

### How to Trace Variable Usage

```bash
# Find where a variable is used
code-explorer trace src/module.py:function_name --variable my_var
```

### How to Generate Dependency Diagrams

```bash
# Create Mermaid diagram
code-explorer visualize src/module.py:function_name --output graph.md

# Limit depth to 2 levels
code-explorer visualize src/module.py:function_name --max-depth 2
```

### How to Find Most Connected Functions

```bash
# Show top 10 most-called functions
code-explorer stats --top 10
```

---

## Reference

### Commands

**`code-explorer analyze <path>`**
- Analyzes Python files and builds dependency graph
- Options:
  - `--refresh` - Force full re-analysis (ignore cache)
  - `--db-path <path>` - Custom database location
  - `--no-source` - Don't store function/class source code
  - `--source-lines <N>` - Store only first N lines of source

**`code-explorer stats`**
- Shows graph statistics (files, classes, functions, variables)
- Options:
  - `--top <N>` - Show top N most-connected functions

**`code-explorer impact <file:function>`**
- Finds function dependencies
- Options:
  - `--downstream` - Show what function calls (default: upstream/callers)
  - `--max-depth <N>` - Limit traversal depth (default: 5)

**`code-explorer trace <file:function>`**
- Traces variable data flow
- Options:
  - `--variable <name>` - Variable name to trace

**`code-explorer visualize <file:function>`**
- Generates Mermaid dependency diagram
- Options:
  - `--output <file>` - Output file path (.md)
  - `--max-depth <N>` - Limit diagram depth

### Database Schema

**Node Types:**
- `File` - Python source files
  - `path` (STRING) - Relative file path
  - `content_hash` (STRING) - SHA-256 hash
  - `last_modified` (INT64) - Timestamp

- `Function` - Functions and methods
  - `id` (STRING) - Hash-based ID (fn_*)
  - `name` (STRING) - Function name
  - `file` (STRING) - Relative file path
  - `start_line`, `end_line` (INT64)
  - `is_public` (BOOLEAN)
  - `source_code` (STRING, optional)

- `Class` - Class definitions
  - `id` (STRING) - Hash-based ID (cls_*)
  - `name` (STRING) - Class name
  - `file` (STRING) - Relative file path
  - `start_line`, `end_line` (INT64)
  - `bases` (STRING) - JSON array of base classes
  - `is_public` (BOOLEAN)
  - `source_code` (STRING, optional)

- `Variable` - Variable definitions
  - `id` (STRING) - Hash-based ID (var_*)
  - `name` (STRING)
  - `file` (STRING)
  - `line` (INT64)
  - `scope` (STRING)

**Edge Types:**
- `CONTAINS` - File contains Function/Class/Variable
- `CALLS` - Function calls Function
- `USES` - Function uses Variable
- `DEFINES` - Function defines Variable
- `IMPORTS` - File imports File
- `INHERITS` - Class inherits from Class
- `METHOD_OF` - Function is method of Class

### Database Location

Default: `./.code-explorer/graph.db` (relative to current directory)

The database persists between runs, enabling incremental analysis.

### ID Generation

Node IDs are 12-character SHA-256 hashes:
- Functions: `fn_` + hash(relative_path::name::line)
- Classes: `cls_` + hash(relative_path::name::line)
- Variables: `var_` + hash(relative_path::name::line)

This ensures stable, portable IDs across environments.

---

## Explanation

### Why Persistent Graph Storage?

Traditional code analysis tools re-parse the entire codebase on every run. Code Explorer uses KuzuDB to persist the dependency graph, enabling:
- **Incremental updates** - Only re-analyze changed files (10-100x faster for large codebases)
- **Complex queries** - Cypher-like graph queries for sophisticated analysis
- **Interactive exploration** - Web UI for visual graph navigation

### How Incremental Updates Work

1. Each file has a SHA-256 content hash stored in the database
2. On re-analysis, Code Explorer compares current file hash with stored hash
3. Unchanged files are skipped entirely
4. Changed files have their old nodes/edges deleted and are re-analyzed
5. New files are added to the graph

This makes the second and subsequent runs dramatically faster.

### AST vs Astroid

Code Explorer uses both:
- **ast** (stdlib) - Fast parsing, extracts structure (functions, classes, calls)
- **astroid** (library) - Semantic analysis, name resolution, type inference

This combination provides accurate dependency tracking without requiring code execution.

### Graph Database Benefits

KuzuDB (embedded graph database) provides:
- **Cypher query language** - Powerful graph traversal
- **ACID transactions** - Reliable persistence
- **Embedded** - No separate server needed
- **Fast** - Optimized for graph queries

Perfect for modeling code dependencies as a natural graph structure.

### Limitations

- **Dynamic imports** - `importlib` or `__import__()` not tracked
- **Dynamic calls** - `getattr()` or `eval()` not resolved
- **Type inference** - Limited to static analysis
- **Monkey patching** - Runtime modifications not detected

Code Explorer analyzes static code structure. Runtime behavior requires different tools.

---

## Requirements

- Python 3.13+
- Dependencies: click, rich, astroid, kuzu
- Docker (optional, for KuzuDB Explorer web UI)
