# Code Explorer

Python code dependency analyzer with persistent graph storage.

## Features

- **AST + Astroid Analysis**: Deep function-level code analysis
- **KuzuDB Storage**: Persistent graph database with incremental updates
- **Impact Analysis**: Find upstream (callers) and downstream (callees) dependencies
- **Variable Tracing**: Track data flow through variable usage
- **Visualization**: Generate Mermaid diagrams of dependencies
- **CLI**: 5 commands for analyzing and exploring your codebase

## Installation

```bash
# Install dependencies
pip install -e .
```

## Usage

### Analyze a codebase

```bash
# First run - analyzes all files
code-explorer analyze ./src

# Second run - only re-analyzes changed files (incremental)
code-explorer analyze ./src

# Force full re-analysis
code-explorer analyze ./src --refresh

# Custom database location
code-explorer analyze ./src --db-path /path/to/db
```

### Find impact of changes

```bash
# Find who calls this function (upstream)
code-explorer impact src/module.py:function_name

# Find what this function calls (downstream)
code-explorer impact src/module.py:function_name --downstream

# Limit depth
code-explorer impact src/module.py:function_name --max-depth 3
```

### Trace variable usage

```bash
code-explorer trace src/module.py:function_name --variable var_name
```

### Show statistics

```bash
code-explorer stats

# Show top 10 most connected functions
code-explorer stats --top 10
```

### Generate visualizations

```bash
# Create Mermaid diagram
code-explorer visualize src/module.py:function_name --output graph.md

# Control depth
code-explorer visualize src/module.py:function_name --max-depth 2
```

## View Database with Kuzu Explorer

Run the Kuzu Explorer web UI to visually explore the dependency graph:

```bash
# First, ensure database directory has correct permissions
chmod 777 .code-explorer/
chmod 666 .code-explorer/graph.db

# Start Kuzu Explorer with your user ID
UID=$(id -u) GID=$(id -g) docker-compose up -d

# Open browser to http://localhost:8000
# The database at .code-explorer/graph.db will be mounted automatically

# Stop when done
docker-compose down
```

### Kuzu Explorer Options

The `docker-compose.yml` can be customized with environment variables:

- `MODE=READ_ONLY` - Launch in read-only mode (no schema changes)
- `KUZU_BUFFER_POOL_SIZE=1073741824` - Set buffer pool size (bytes)
- `KUZU_IN_MEMORY=true` - Run in-memory mode (changes not persisted)
- `KUZU_WASM=true` - Run in WebAssembly mode (browser-only)

Example with read-only mode:

```yaml
environment:
  - KUZU_FILE=graph.db
  - MODE=READ_ONLY
```

## How it Works

1. **Parsing**: Uses Python's `ast` module to parse source code
2. **Semantic Analysis**: Uses `astroid` for name resolution and type inference
3. **Graph Storage**: Stores dependencies in KuzuDB with nodes (File, Function, Variable) and edges (CALLS, USES, CONTAINS, DEFINES, IMPORTS)
4. **Incremental Updates**: SHA-256 content hashing skips unchanged files on subsequent runs
5. **Querying**: Cypher-like queries traverse the dependency graph

## Database Schema

**Nodes:**
- `File`: Python source files with path, content hash, last modified timestamp
- `Function`: Function definitions with name, file, line range, visibility
- `Variable`: Variable definitions/assignments

**Edges:**
- `CONTAINS`: File � Function/Variable
- `CALLS`: Function � Function
- `USES`: Function � Variable
- `DEFINES`: Function � Variable
- `IMPORTS`: File � File

## Database Location

Default: `.code-explorer/graph.db`

The database persists between runs, enabling fast incremental analysis.

## Requirements

- Python 3.13+
- Dependencies: click, rich, astroid, kuzu
- Docker (optional, for Kuzu Explorer)
