# CLI Commands Reference

Complete reference for all Code Explorer commands.

## Global Options

```bash
--version        Show version and exit
--help          Show help message
```

---

## `analyze`

Analyze Python codebase and build dependency graph.

### Synopsis

```bash
code-explorer analyze PATH [OPTIONS]
```

### Arguments

- `PATH` (required): Directory containing Python code to analyze

### Options

- `--exclude PATTERN`: Patterns to exclude (can be specified multiple times)
  - Example: `--exclude tests --exclude .venv`

- `--workers N`: Number of parallel workers (default: 4)
  - Higher values = faster analysis on multi-core systems
  - Set to 1 for sequential processing

- `--db-path PATH`: Path to KuzuDB database
  - Default: `.code-explorer/graph.db` in the analyzed directory

- `--refresh`: Force full re-analysis (clears existing database)
  - Without this flag, only changed files are re-analyzed

### Examples

```bash
# Basic analysis
code-explorer analyze ./src

# Exclude directories
code-explorer analyze . --exclude tests --exclude migrations --exclude .venv

# Custom database location
code-explorer analyze ./src --db-path /tmp/analysis.db

# Force full refresh
code-explorer analyze ./src --refresh

# Sequential processing (no parallelism)
code-explorer analyze ./src --workers 1

# Maximum parallelism
code-explorer analyze ./src --workers 16
```

### Output

Displays:
- Total files analyzed
- Files processed (new or changed)
- Files skipped (unchanged)
- Total functions and variables extracted
- Database location

---

## `impact`

Find impact of changing a function.

### Synopsis

```bash
code-explorer impact TARGET [OPTIONS]
```

### Arguments

- `TARGET` (required): Function to analyze in format `file.py:function_name`

### Options

- `--downstream`: Show downstream impact (what this function calls)
  - Default is upstream (who calls this function)

- `--max-depth N`: Maximum depth for transitive analysis (default: 5)
  - Depth 1 = direct callers/callees only
  - Higher depth = more comprehensive but slower

- `--db-path PATH`: Path to KuzuDB database
  - Default: `.code-explorer/graph.db` in current directory

### Examples

```bash
# Find who calls this function (upstream)
code-explorer impact src/module.py:process_data

# Find what this function calls (downstream)
code-explorer impact src/module.py:process_data --downstream

# Limit search depth
code-explorer impact src/api.py:endpoint --max-depth 3

# Custom database
code-explorer impact module.py:func --db-path /tmp/analysis.db
```

### Output

Table showing:
- Function name
- File path
- Line number where relationship occurs
- Depth (distance from target function)

---

## `trace`

Trace variable data flow through the codebase.

### Synopsis

```bash
code-explorer trace TARGET --variable NAME [OPTIONS]
```

### Arguments

- `TARGET` (required): Location in format `file.py:line_number`
- `--variable NAME` (required): Variable name to trace

### Options

- `--db-path PATH`: Path to KuzuDB database
  - Default: `.code-explorer/graph.db` in current directory

### Examples

```bash
# Trace variable usage
code-explorer trace src/module.py:42 --variable user_input

# Trace with custom database
code-explorer trace utils.py:15 --variable result --db-path /tmp/analysis.db
```

### Output

Table showing:
- File where variable is used
- Function using the variable
- Line number of usage

---

## `stats`

Show statistics about the analyzed codebase.

### Synopsis

```bash
code-explorer stats [OPTIONS]
```

### Options

- `--db-path PATH`: Path to KuzuDB database
  - Default: `.code-explorer/graph.db` in current directory

- `--top N`: Number of top functions to show (default: 10)

### Examples

```bash
# Basic statistics
code-explorer stats

# Show top 20 most-called functions
code-explorer stats --top 20

# Custom database
code-explorer stats --db-path /tmp/analysis.db
```

### Output

Two tables:

**Overview**:
- Total files, functions, variables
- Total edges (relationships)
- Function calls count

**Top Most-Called Functions**:
- Rank, function name, file, call count

---

## `visualize`

Generate Mermaid diagram of dependency graph.

### Synopsis

```bash
code-explorer visualize TARGET [OPTIONS]
```

### Arguments

- `TARGET` (required): File to visualize (e.g., `module.py`)

### Options

- `--function NAME`: Specific function to highlight in the graph
  - Without this, generates module-level visualization

- `--output PATH`: Output file for Mermaid diagram (default: `graph.md`)

- `--max-depth N`: Maximum depth to traverse (default: 3)
  - Only applies when `--function` is specified

- `--db-path PATH`: Path to KuzuDB database
  - Default: `.code-explorer/graph.db` in current directory

### Examples

```bash
# Visualize entire module
code-explorer visualize src/module.py

# Focus on specific function
code-explorer visualize src/module.py --function process_data --output deps.md

# Control depth
code-explorer visualize utils.py --function helper --max-depth 2

# Custom database and output
code-explorer visualize api.py --function endpoint \
  --db-path /tmp/analysis.db \
  --output api-deps.md
```

### Output

Creates a Markdown file with embedded Mermaid diagram. View in:
- GitHub (renders automatically)
- VS Code (with Mermaid extension)
- Mermaid Live Editor (https://mermaid.live)

---

## Exit Codes

- `0`: Success
- `1`: Error (missing database, invalid arguments, analysis failure)

---

## Environment Variables

None currently supported.

---

## Files

- `.code-explorer/graph.db`: Default database location (KuzuDB format)
- `graph.md`: Default visualization output

---

## Notes

### Database Locking

KuzuDB uses file locking. Only one process can write at a time. Multiple readers are allowed.

If you get "Could not set lock" errors:
- Close any open Kuzu Explorer instances
- Ensure no other `code-explorer` processes are running

### Performance Tips

1. **Use exclusions**: `--exclude .venv --exclude tests` speeds up analysis
2. **Increase workers**: `--workers 16` on multi-core systems
3. **Limit depth**: `--max-depth 3` for faster impact queries
4. **Incremental updates**: Don't use `--refresh` unless necessary

### Path Handling

All file paths are stored as absolute paths. When querying, use:
- Absolute paths: `/full/path/to/module.py`
- Relative paths: `src/module.py` (resolved against current directory)
- Just filenames: `module.py` (searches across all files)

---

## See Also

- [Getting Started Tutorial](../tutorials/getting-started.md)
- [Impact Analysis Tutorial](../tutorials/impact-analysis.md)
- [Graph Schema Reference](graph-schema.md)
