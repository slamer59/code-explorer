# Getting Started with Code Explorer

This tutorial will guide you through your first dependency analysis session.

## What You'll Learn

By the end of this tutorial, you'll be able to:
- Analyze a Python codebase
- Query function dependencies
- Understand impact of changes
- Visualize dependency graphs

## Prerequisites

- Python 3.13 or higher
- A Python project to analyze (or use the included examples)

## Step 1: Installation

Install Code Explorer in your project:

```bash
pip install -e .
```

Verify the installation:

```bash
code-explorer --version
```

You should see: `code-explorer, version 0.1.0`

## Step 2: Your First Analysis

Let's analyze the Code Explorer codebase itself:

```bash
code-explorer analyze ./src
```

You'll see output like:

```
Analyzing codebase at: /path/to/code-explorer/src
Database location: /path/to/code-explorer/.code-explorer/graph.db

Building dependency graph...
Processing results... ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100%

Analysis complete!
┏━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━┓
┃ Metric                   ┃ Count ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━┩
│ Total files analyzed     │     5 │
│ Files processed          │     5 │
│ Total functions          │    47 │
│ Total variables          │    89 │
└──────────────────────────┴───────┘

Graph persisted to: /path/to/code-explorer/.code-explorer/graph.db
```

**What just happened?**
- Code Explorer scanned all `.py` files in `./src`
- Extracted functions, variables, and their relationships using AST + Astroid
- Stored everything in a KuzuDB graph database at `.code-explorer/graph.db`
- The database persists to disk for fast subsequent queries

## Step 3: Understanding Dependencies

Now let's find out who calls a specific function:

```bash
code-explorer impact src/code_explorer/graph.py:DependencyGraph.add_function
```

Output shows all functions that depend on `add_function`:

```
Analyzing impact of: src/code_explorer/graph.py::DependencyGraph.add_function
Direction: Upstream
Max depth: 5

┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━┓
┃ Function                          ┃ File               ┃ Line  ┃ Depth ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━┩
│ analyze                           │ cli.py             │   155 │     1 │
└───────────────────────────────────┴────────────────────┴───────┴───────┘

Found 1 impacted functions
```

**What does this mean?**
- If you change `add_function`, you need to check the `analyze` function in `cli.py` (line 155)
- This is called **upstream impact** (who calls me?)

Now try **downstream impact** (what do I call?):

```bash
code-explorer impact src/code_explorer/cli.py:analyze --downstream
```

## Step 4: Incremental Updates

Modify a file, then run analyze again:

```bash
# Make a small change to any Python file
echo "# Comment added" >> src/code_explorer/__init__.py

# Re-analyze
code-explorer analyze ./src
```

Output shows:

```
Analysis complete!
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━┓
┃ Metric                       ┃ Count ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━┩
│ Total files analyzed         │     5 │
│ Files processed              │     1 │
│ Files skipped (unchanged)    │     4 │
│ Total functions              │    47 │
│ Total variables              │    89 │
└──────────────────────────────┴───────┘
```

**Notice**: Only 1 file was processed! Code Explorer uses content hashing to skip unchanged files.

## Step 5: View Statistics

Get an overview of your codebase:

```bash
code-explorer stats
```

```
Codebase Statistics

                 Overview
┏━━━━━━━━━━━━━━━━━━━━┳━━━━━━━┓
┃ Metric             ┃ Count ┃
┡━━━━━━━━━━━━━━━━━━━━╇━━━━━━━┩
│ Total files        │     5 │
│ Total functions    │    47 │
│ Total variables    │    89 │
│ Total edges        │    73 │
│ Function calls     │    73 │
└────────────────────┴───────┘

        Top 10 Most-Called Functions
┏━━━━━━━━┳━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━┓
┃ Rank   ┃ Function          ┃ File         ┃ Calls ┃
┡━━━━━━━━╇━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━┩
│      1 │ add_function      │ graph.py     │     8 │
│      2 │ add_call          │ graph.py     │     6 │
│      3 │ console.print     │ cli.py       │     5 │
└────────┴───────────────────┴──────────────┴───────┘
```

## Step 6: Visualize Dependencies

Generate a Mermaid diagram:

```bash
code-explorer visualize src/code_explorer/graph.py \
  --function DependencyGraph.add_function \
  --output graph.md
```

Open `graph.md` in GitHub, VS Code, or any Mermaid viewer to see the dependency graph.

## What's Next?

Now that you've completed your first analysis, explore:

- [Impact Analysis Tutorial](impact-analysis.md) - Deep dive into change propagation
- [How-To: Find Dependencies](../how-to/find-dependencies.md) - Practical recipes
- [Explanation: Architecture](../explanation/architecture.md) - Understand how it works

## Troubleshooting

**Database not found?**
- Run `code-explorer analyze ./src` first to create the database

**Permission denied with Kuzu Explorer?**
- See [How-To: Use Kuzu Explorer](../how-to/use-kuzu-explorer.md) for Docker setup

**Slow analysis?**
- Use `--workers 8` for faster parallel processing
- Exclude test directories: `--exclude tests --exclude .venv`
