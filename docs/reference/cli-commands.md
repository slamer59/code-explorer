# CLI Commands Reference

Complete reference for all Code Explorer commands with tested examples.

## Quick Start

```bash
# 1. Analyze your codebase
code-explorer analyze ./src --exclude tests --exclude .venv

# 2. View statistics
code-explorer stats

# 3. Find who calls a function
code-explorer impact src/module.py:function_name
```

---

## `analyze` - Build Dependency Graph

Analyze Python codebase and extract functions, classes, variables, and their relationships.

**Synopsis:**
```bash
code-explorer analyze PATH [OPTIONS]
```

**Common Usage:**
```bash
# Basic analysis with exclusions
code-explorer analyze ./src --exclude tests --exclude .venv

# Force full refresh (clears database)
code-explorer analyze ./src --refresh

# Maximum parallelism (16 workers)
code-explorer analyze ./src --workers 16
```

**Options:**
- `PATH` (required): Directory containing Python code
- `--exclude PATTERN`: Exclude patterns (repeatable)
- `--workers N`: Parallel workers (default: 4)
- `--db-path PATH`: Database location (default: `.code-explorer/graph.db`)
- `--refresh`: Force full re-analysis

**Output Example:**
```
Analysis complete!
┏━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━┓
┃ Metric                 ┃ Count ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━┩
│ Total files analyzed   │   156 │
│ Files processed        │    12 │
│ Total functions        │   842 │
│ Total variables        │   234 │
└────────────────────────┴───────┘

╭──────────── ⏱ Performance Metrics ─────────────╮
│  Total analysis time: 3.45s                    │
│                                                │
│  Breakdown:                                    │
│    • File analysis: 1.20s                      │
│    • Node insertion: 0.85s                     │
│    • Edge insertion: 0.12s                     │
│    • Call resolution: 0.98s                    │
│    • Call edge insertion: 0.30s                │
╰────────────────────────────────────────────────╯
```

**Default Exclusions:**
`.venv`, `venv`, `__pycache__`, `.pytest_cache`, `htmlcov`, `dist`, `build`, `.git`

---

## `stats` - Codebase Statistics

Show overview statistics and most-called functions.

**Synopsis:**
```bash
code-explorer stats [OPTIONS]
```

**Common Usage:**
```bash
# Basic statistics (uses .code-explorer/graph.db in current directory)
code-explorer stats

# Show top 20 most-called functions
code-explorer stats --top 20

# Custom database path
code-explorer stats --db-path ./src/.code-explorer/graph.db
```

**Options:**
- `--db-path PATH`: Database location (default: `./.code-explorer/graph.db`)
- `--top N`: Number of top functions (default: 10)

**Output Example:**
```
┏━━━━━━━━━━━━━━━━━━━┳━━━━━━━┓
┃ Metric            ┃ Count ┃
┡━━━━━━━━━━━━━━━━━━━╇━━━━━━━┩
│ Files             │   156 │
│ Functions         │   842 │
│ Variables         │   234 │
│ Function calls    │  2631 │
└───────────────────┴───────┘

Top 10 Most-Called Functions:
┏━━━━┳━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━┳━━━━━━━┓
┃ #  ┃ Function        ┃ File           ┃ Calls ┃
┡━━━━╇━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━╇━━━━━━━┩
│ 1  │ validate_input  │ utils/core.py  │   127 │
│ 2  │ log_event       │ logging.py     │    89 │
└────┴─────────────────┴────────────────┴───────┘
```

---

## `impact` - Function Impact Analysis

Find who calls a function (upstream) or what a function calls (downstream).

**Synopsis:**
```bash
code-explorer impact TARGET [OPTIONS]
```

**Common Usage:**
```bash
# Find who calls this function (upstream impact)
code-explorer impact src/module.py:process_data

# Find what this function calls (downstream impact)
code-explorer impact src/module.py:process_data --downstream

# Limit search depth to 2 levels
code-explorer impact src/api.py:endpoint --max-depth 2
```

**Options:**
- `TARGET` (required): Format `file.py:function_name`
- `--downstream`: Show downstream (what function calls)
- `--max-depth N`: Maximum traversal depth (default: 5)
- `--db-path PATH`: Database location

**Output Example:**
```
Upstream impact for 'process_data':
┏━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━┓
┃ Function         ┃ File          ┃ Line  ┃ Depth ┃
┡━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━┩
│ handle_request   │ api/views.py  │   45  │   1   │
│ batch_process    │ workers.py    │  123  │   1   │
│ main_loop        │ main.py       │   89  │   2   │
└──────────────────┴───────────────┴───────┴───────┘
```

---

## `trace` - Variable Data Flow

Trace how a variable flows through the codebase.

**Synopsis:**
```bash
code-explorer trace TARGET --variable NAME [OPTIONS]
```

**Common Usage:**
```bash
# Trace variable usage from specific line
code-explorer trace src/module.py:42 --variable user_input

# Trace with custom database
code-explorer trace utils.py:15 --variable result --db-path /tmp/analysis.db
```

**Options:**
- `TARGET` (required): Format `file.py:line_number`
- `--variable NAME` (required): Variable name to trace
- `--db-path PATH`: Database location

---

## `visualize` - Generate Mermaid Diagram

Create visual dependency graph as Mermaid diagram.

**Synopsis:**
```bash
code-explorer visualize TARGET [OPTIONS]
```

**Common Usage:**
```bash
# Visualize entire module
code-explorer visualize src/module.py

# Focus on specific function with custom output
code-explorer visualize src/module.py --function process_data --output deps.md

# Control traversal depth
code-explorer visualize utils.py --function helper --max-depth 2
```

**Options:**
- `TARGET` (required): File to visualize (e.g., `module.py`)
- `--function NAME`: Specific function to highlight
- `--output PATH`: Output file (default: `graph.md`)
- `--max-depth N`: Traversal depth (default: 3, function-only)
- `--db-path PATH`: Database location

**View Output:**
- GitHub: Renders automatically
- VS Code: Install Mermaid extension
- Web: https://mermaid.live

---

## Troubleshooting

### "Could not set lock" Error
```bash
# Fix: Close other processes using the database
pkill code-explorer
rm .code-explorer/graph.db-lock  # If needed
```

### Database Not Found
```bash
# Run analyze first
code-explorer analyze ./src

# Or specify correct path
code-explorer stats --db-path ./src/.code-explorer/graph.db
```

### No Files Found
Check that `.venv`, `tests` are in exclude list:
```bash
code-explorer analyze ./src --exclude .venv --exclude tests
```

---

## Performance Tips

1. **Use exclusions**: `--exclude .venv --exclude tests` (faster analysis)
2. **Increase workers**: `--workers 16` on multi-core systems
3. **Limit depth**: `--max-depth 3` for faster impact queries
4. **Incremental updates**: Skip `--refresh` to only re-analyze changed files

---

## Files

- `.code-explorer/graph.db` - Default database location (KuzuDB format)
- `graph.md` - Default visualization output

## Exit Codes

- `0` - Success
- `1` - Error (missing database, invalid arguments, analysis failure)
