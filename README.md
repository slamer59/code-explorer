# Code Explorer - Python Dependency Analysis Tool

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)

**Code Explorer** is a powerful Python code analyzer and dependency analysis tool with persistent graph storage using KuzuDB. Designed for developers who need to understand complex codebases, track dependencies, and perform impact analysis efficiently.

## Overview

Code Explorer is the best Python code analyzer for understanding large codebases. It builds a persistent dependency graph by analyzing Python files to track functions, classes, variables, and their relationships (calls, imports, inheritance). This free Python code analyzer enables sophisticated impact analysis and code navigation through graph-based queries.

**Key Capabilities:**
- 🔍 **Dependency Tracking** - Map all function calls, imports, and class relationships
- 📊 **Impact Analysis** - Identify code affected by changes before refactoring
- 🗺️ **Code Visualization** - Generate Mermaid diagrams of dependencies
- ⚡ **Fast Queries** - Sub-second graph database queries
- 💾 **Incremental Updates** - Only re-analyze changed files (10-100x faster)
- 🎯 **AST-Based** - Accurate static code analysis without execution

---

## Why Choose Code Explorer?

### Best Python Code Analyzer for Large Projects

Code Explorer excels at analyzing complex Python codebases where understanding dependencies is critical:

✅ **Enterprise-Grade Performance** - Analyze 10,000+ file codebases in minutes
✅ **Graph Database Backend** - KuzuDB provides lightning-fast relationship queries
✅ **Comprehensive Analysis** - Functions, classes, imports, decorators, variables, exceptions
✅ **Persistent Storage** - Results saved to disk for instant reuse
✅ **Command-Line First** - Perfect for CI/CD integration and automation

### Python Code Analyzer Comparison

| Feature | Code Explorer | pylint/flake8 | IDE Navigation |
|---------|---------------|---------------|----------------|
| Relationship Analysis | ✅ Graph-based | ❌ Syntax only | ⚠️ Single file |
| Impact Analysis | ✅ Multi-level | ❌ None | ⚠️ Limited |
| Visualization | ✅ Diagrams | ❌ Text only | ❌ None |
| Persistent Storage | ✅ Database | ❌ None | ❌ None |
| CI/CD Integration | ✅ CLI-first | ⚠️ Limited | ❌ Not designed |

---

## Tutorial - Getting Started with Dependency Analysis

### Installation

The best free Python code analyzer is just a pip install away:

```bash
# Install from source
pip install -e .

# Or install from PyPI (when published)
pip install code-explorer
```

**Requirements:**
- Python 3.8 or higher
- Dependencies: click, rich, astroid, kuzu, pandas

### Python Code Analyzer Tutorial - First Analysis

**Step 1: Analyze Your Codebase**

```bash
# Analyze current directory
code-explorer analyze .

# Analyze specific directory
code-explorer analyze ./src

# Include normally excluded directories
code-explorer analyze . --include .venv
```

**Example Output:**
```
Analyzing codebase at: /path/to/project
Database location: .code-explorer/graph.db
Excluding: __pycache__, .pytest_cache, dist, build, .git

✓ 234 files analyzed
✓ 1,523 functions inserted
✓ 287 classes inserted
✓ 892 variables inserted
✓ 2,145 import relationships
✓ 8,734 function call edges

Total analysis time: 12.3s
```

**Step 2: View Codebase Statistics**

```bash
code-explorer stats
```

Output shows:
- Total files, classes, functions, variables
- Most-called functions (complexity hotspots)
- Import statistics
- Decorator usage
- Exception handling patterns

**Step 3: Find Impact of Changes**

Before refactoring any function, use this dependency analysis guide:

```bash
# Find who calls this function (upstream dependencies)
code-explorer impact src/module.py:my_function

# Find what this function calls (downstream dependencies)
code-explorer impact src/module.py:my_function --downstream

# Limit search depth for focused analysis
code-explorer impact src/module.py:my_function --max-depth 3
```

**Step 4: Trace Variable Data Flow**

Debug issues by tracking variable usage:

```bash
# Find where a variable is used across functions
code-explorer trace src/module.py:42 --variable user_input

# Track data flow through the application
code-explorer trace src/processor.py:15 --variable result
```

**Step 5: Visualize Dependencies**

Generate beautiful dependency graphs:

```bash
# Create Mermaid diagram for a module
code-explorer visualize src/module.py --output graph.md

# Focus on specific function with depth limit
code-explorer visualize src/utils.py --function calculate --max-depth 2

# View in GitHub, VS Code, or any Mermaid-compatible viewer
```

### Incremental Analysis for Fast Updates

Second and subsequent runs are dramatically faster:

```bash
# Only analyzes changed files (10-100x faster)
code-explorer analyze ./src

# Force complete re-analysis when needed
code-explorer analyze ./src --refresh
```

**How it works:**
1. File content hashes are stored in the database
2. Unchanged files are automatically skipped
3. Only modified files are re-analyzed
4. Perfect for development workflow and CI/CD

---

## How-To Guides

### How to Analyze Large Codebases

For projects with 10,000+ files or including virtual environments:

```bash
# Use chunked processing for memory efficiency
code-explorer analyze . --include .venv --chunk-size 25

# Increase parallel workers for faster processing
code-explorer analyze . --workers 16

# For very low RAM systems
code-explorer analyze . --chunk-size 10
```

### How to Control Source Code Storage

Manage database size by controlling source code storage:

```bash
# Store full source code (default, larger database)
code-explorer analyze ./src

# Don't store source code (smaller database, faster)
code-explorer analyze ./src --no-source

# Store only first 10 lines (preview mode)
code-explorer analyze ./src --source-lines 10
```

### How to Reset the Database

Start fresh analysis from scratch:

```bash
# Delete the database directory
rm -rf .code-explorer/

# Or use refresh flag
code-explorer analyze ./src --refresh
```

### How to Customize Database Location

Use custom database paths for multiple projects or specific locations:

```bash
# Specify custom database path
code-explorer analyze ./src --db-path /path/to/custom/db

# All subsequent commands must use the same path
code-explorer stats --db-path /path/to/custom/db
code-explorer impact src/module.py:func --db-path /path/to/custom/db
```

### How to Use Read-Only Mode

Prevent accidental modifications:

```bash
# The KuzuDB Explorer runs in read-only mode by default
docker compose up -d

# Open http://localhost:8000
# Run Cypher queries safely without risking data corruption
```

### How to Find Most Complex Functions

Identify code that needs refactoring:

```bash
# Show top 20 most-called functions
code-explorer stats --top 20

# These are complexity hotspots - refactoring candidates
```

### How to Integrate with CI/CD

Add dependency analysis to your continuous integration:

```bash
#!/bin/bash
# .github/workflows/analyze.sh

# Analyze codebase
code-explorer analyze . --refresh

# Generate complexity report
code-explorer stats --top 50 > complexity-report.txt

# Fail build if critical functions are too complex
# (add custom logic based on your thresholds)
```

### How to Debug with Variable Tracing

Track down data flow issues:

```bash
# Start at the error line
code-explorer trace src/app.py:error_line --variable suspicious_var

# Follow the trail backwards to find the source
code-explorer trace src/input.py:45 --variable user_data
```

---

## Reference

### Complete Command Reference

#### `code-explorer analyze <path>`

Analyzes Python files and builds the dependency graph.

**Options:**
- `--exclude PATTERN` - Exclude files/directories (can specify multiple times)
- `--include PATTERN` - Override default exclusions (e.g., `--include .venv`)
- `--workers N` - Number of parallel workers (default: 4)
- `--db-path PATH` - Custom database location (default: `.code-explorer/graph.db`)
- `--refresh` - Force complete re-analysis (ignore cache)
- `--chunk-size N` - Files per chunk for edge insertion (default: 25, lower = less RAM)
- `--no-source` - Don't store function/class source code
- `--source-lines N` - Store only first N lines of source

**Examples:**
```bash
# Basic analysis
code-explorer analyze ./src

# Complex project with multiple exclusions
code-explorer analyze . --exclude tests --exclude docs --workers 8

# Analyze everything including virtual environment
code-explorer analyze . --include .venv --include venv

# Low memory system
code-explorer analyze . --chunk-size 10
```

#### `code-explorer stats`

Shows comprehensive graph statistics.

**Options:**
- `--top N` - Show top N most-connected functions (default: 10)
- `--db-path PATH` - Custom database location

**Examples:**
```bash
# Basic statistics
code-explorer stats

# Show top 25 most-called functions
code-explorer stats --top 25
```

#### `code-explorer impact <file:function>`

Finds function dependencies and impact analysis.

**Options:**
- `--downstream` - Show what function calls (default: upstream/callers)
- `--max-depth N` - Limit traversal depth (default: 5)
- `--db-path PATH` - Custom database location

**Examples:**
```bash
# Find who calls this function
code-explorer impact services/auth.py:validate_user

# Find what this function calls
code-explorer impact utils/helpers.py:process_data --downstream

# Shallow search for immediate dependencies
code-explorer impact main.py:run --max-depth 2
```

#### `code-explorer trace <file:line> --variable <name>`

Traces variable data flow through the codebase.

**Options:**
- `--variable NAME` - Variable name to trace (required)
- `--db-path PATH` - Custom database location

**Examples:**
```bash
# Trace user input flow
code-explorer trace app.py:45 --variable user_data

# Track result variable through functions
code-explorer trace processor.py:120 --variable result
```

#### `code-explorer visualize <file:function>`

Generates Mermaid dependency diagrams.

**Options:**
- `--function NAME` - Highlight specific function
- `--output PATH` - Output file path (default: graph.md)
- `--max-depth N` - Limit diagram depth (default: 3)
- `--db-path PATH` - Custom database location

**Examples:**
```bash
# Visualize entire module
code-explorer visualize services/auth.py --output auth_graph.md

# Focus on specific function with depth control
code-explorer visualize utils.py --function calculate --max-depth 2
```

### Database Schema

**Node Types:**
- **File** - Python source files
  - `path` (STRING) - Relative file path
  - `content_hash` (STRING) - SHA-256 hash for change detection
  - `last_modified` (TIMESTAMP) - Last modification time

- **Function** - Functions and methods
  - `id` (STRING) - Hash-based ID (fn_*)
  - `name` (STRING) - Function name
  - `file` (STRING) - Relative file path
  - `start_line`, `end_line` (INT64) - Location in source
  - `is_public` (BOOLEAN) - Public/private visibility
  - `source_code` (STRING, optional) - Function source code

- **Class** - Class definitions
  - `id` (STRING) - Hash-based ID (cls_*)
  - `name` (STRING) - Class name
  - `file` (STRING) - Relative file path
  - `start_line`, `end_line` (INT64) - Location in source
  - `bases` (STRING) - JSON array of base classes
  - `is_public` (BOOLEAN) - Public/private visibility
  - `source_code` (STRING, optional) - Class source code

- **Variable** - Variable definitions
  - `id` (STRING) - Hash-based ID (var_*)
  - `name` (STRING) - Variable name
  - `file` (STRING) - Relative file path
  - `definition_line` (INT64) - Where defined
  - `scope` (STRING) - module, class, or function

- **Import** - Import statements
  - `id` (STRING) - Hash-based ID (imp_*)
  - `imported_name` (STRING) - What was imported
  - `import_type` (STRING) - import or from-import
  - `alias` (STRING) - Import alias if any
  - `line_number` (INT64) - Location in source

- **Decorator** - Decorator applications
  - `id` (STRING) - Hash-based ID (dec_*)
  - `name` (STRING) - Decorator name
  - `file` (STRING) - Relative file path
  - `line_number` (INT64) - Location in source
  - `arguments` (JSON) - Decorator arguments

**Edge Types:**
- `CONTAINS_FUNCTION` - File contains Function
- `CONTAINS_CLASS` - File contains Class
- `CONTAINS_VARIABLE` - File contains Variable
- `CALLS` - Function calls Function
- `METHOD_OF` - Function is method of Class
- `INHERITS` - Class inherits from Class
- `HAS_IMPORT` - File has Import
- `USES` - Function uses Variable
- `HAS_ATTRIBUTE` - Class has Attribute
- `DECORATED_BY` - Function/Class decorated by Decorator

### Environment Variables

**`CODE_EXPLORER_DEBUG`**

Enable detailed debug logging:
```bash
# Show verbose logging for troubleshooting
CODE_EXPLORER_DEBUG=1 code-explorer analyze .
```

---

## Explanation

### Why Persistent Graph Storage?

Traditional Python code analyzer tools re-parse the entire codebase on every run. Code Explorer uses KuzuDB for persistent graph storage, providing:

**Incremental Updates** - Only re-analyze changed files (10-100x faster for large codebases)
**Complex Queries** - Cypher-like graph queries for sophisticated dependency analysis
**Interactive Exploration** - Web UI for visual graph navigation
**ACID Transactions** - Reliable, consistent persistence

### How Incremental Updates Work

The dependency analysis tool intelligently tracks changes:

1. Each file has a SHA-256 content hash stored in the database
2. On re-analysis, current file hash is compared with stored hash
3. Unchanged files are skipped entirely (zero parsing overhead)
4. Changed files have their old nodes/edges deleted and are re-analyzed
5. New files are added to the graph seamlessly

This makes the second and subsequent runs dramatically faster, perfect for development workflow.

### AST vs Astroid for Code Analysis

Code Explorer uses both for comprehensive Python code analysis:

**ast (Python stdlib)**
- Fast parsing and structure extraction
- Functions, classes, imports, calls
- Reliable and stable

**astroid (third-party)**
- Semantic analysis and name resolution
- Type inference capabilities
- Better cross-file understanding

This combination provides accurate dependency tracking without requiring code execution.

### Graph Database Benefits

KuzuDB (embedded graph database) provides:

**Cypher Query Language** - Powerful graph traversal for complex analysis
**ACID Transactions** - Reliable data persistence
**Embedded Architecture** - No separate server needed
**High Performance** - Optimized for relationship queries
**Perfect Fit** - Code dependencies are naturally a graph structure

### Python Static Analysis Limitations

Code Explorer analyzes static code structure. Be aware of limitations:

❌ **Dynamic imports** - `importlib` or `__import__()` not tracked
❌ **Dynamic calls** - `getattr()` or `eval()` not resolved
❌ **Type inference** - Limited to static analysis capabilities
❌ **Monkey patching** - Runtime modifications not detected
❌ **Generated code** - Metaprogramming not fully analyzed

For runtime behavior analysis, complement Code Explorer with profiling tools.

### Best Python Code Analyzer Practices

**1. Run analysis regularly** - Integrate into your development workflow
**2. Use exclusions wisely** - Skip test files and vendor code
**3. Check impact before refactoring** - Always run impact analysis first
**4. Visualize complex areas** - Use diagrams for complicated dependencies
**5. Monitor statistics** - Track code complexity over time
**6. Leverage incremental updates** - Fast re-analysis in development
**7. Integrate with CI/CD** - Automated dependency tracking

---

## Real-World Use Cases

### Use Case 1: Refactoring Legacy Code

```bash
# Step 1: Find all usages before making changes
code-explorer impact old_module.py:legacy_function --max-depth 10

# Step 2: Visualize the impact scope
code-explorer visualize old_module.py --function legacy_function

# Step 3: Make changes confidently knowing the full impact
# Step 4: Re-analyze to verify changes
code-explorer analyze . --refresh
```

### Use Case 2: Onboarding New Developers

```bash
# New team member can quickly understand codebase structure
code-explorer stats
code-explorer visualize main.py --function main --max-depth 5

# Explore specific areas of interest
code-explorer impact services/core.py:main_handler
```

### Use Case 3: Bug Investigation

```bash
# Trace where problematic data originates
code-explorer trace app.py:error_line --variable suspicious_input

# Find all functions that touch this problematic code
code-explorer impact utils.py:buggy_function --downstream
```

### Use Case 4: CI/CD Integration

```bash
# In your CI pipeline
code-explorer analyze . --refresh
code-explorer stats --top 100 > complexity-report.txt

# Fail build if complexity threshold exceeded
# Track dependency metrics over time
```

---

## Python Dependency Analysis Guide - Advanced Topics

### Analyzing Very Large Codebases

For enterprise-scale projects:

```bash
# Maximum parallelization
code-explorer analyze . --workers 32 --chunk-size 15

# Analyze incrementally by directory
code-explorer analyze ./src --db-path ./analysis/db
code-explorer analyze ./lib --db-path ./analysis/db
code-explorer analyze ./tests --db-path ./analysis/db
```

### Memory Optimization Strategies

Control memory usage for large analyses:

```bash
# Reduce chunk size (uses less RAM but slower)
code-explorer analyze . --chunk-size 10

# Disable source code storage (smaller database)
code-explorer analyze . --no-source

# Process in stages
code-explorer analyze ./src  # First pass
code-explorer analyze ./lib  # Second pass
```

### Graph Query Examples

Using the web UI for advanced queries:

```cypher
// Find most complex functions (high fan-in)
MATCH (caller:Function)-[:CALLS]->(callee:Function)
RETURN callee.name, COUNT(caller) as call_count
ORDER BY call_count DESC
LIMIT 20;

// Find circular dependencies
MATCH path = (f:Function)-[:CALLS*]->(f)
RETURN path;

// Find orphaned functions (never called)
MATCH (f:Function)
WHERE NOT (:Function)-[:CALLS]->(f)
RETURN f.name, f.file;
```

---

## Requirements

- Python 3.8 or higher
- Dependencies: click, rich, astroid, kuzu, pandas
- Docker (optional, for KuzuDB Explorer web UI)
- 4GB+ RAM recommended for large codebases
- Disk space: ~100MB per 1000 files analyzed (with source code)

---

## Contributing

Contributions welcome! This free Python code analyzer benefits from community input:

1. **Report Bugs** - Open GitHub issues with details
2. **Suggest Features** - Share ideas for improvements
3. **Submit Pull Requests** - Fork, branch, code, test, submit
4. **Improve Documentation** - Help others understand the tool
5. **Share Use Cases** - Tell us how you use Code Explorer

---

## License

MIT License - Free for personal and commercial use.

---

## Get Started Today

Experience the best Python code analyzer for dependency analysis:

```bash
# Install
pip install -e .

# Analyze your first project
cd /path/to/your/python/project
code-explorer analyze .

# Explore the results
code-explorer stats
code-explorer impact main.py:main
code-explorer visualize main.py --output deps.md
```

Start understanding your Python codebase better with this powerful dependency analysis tool!

---

**Keywords**: python code analyzer, dependency analysis tool, code graph database, python static analysis, codebase visualization, impact analysis, dependency tracker, code relationship mapping, python code exploration, software architecture analysis, best python code analyzer, free python code analyzer, python code analyzer tutorial, dependency analysis guide, code analyzer comparison
