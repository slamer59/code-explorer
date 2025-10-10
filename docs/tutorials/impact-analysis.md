# Understanding Impact Analysis

Learn how to track how code changes propagate through your codebase.

## Learning Objectives

- Understand upstream vs downstream dependencies
- Use impact analysis to plan refactoring
- Identify critical functions
- Trace variable data flow

## The Problem: "Where Can This Bug Go?"

Imagine you need to fix a bug in function `process_data()`. The questions are:

1. **Upstream**: Who calls this function? (Who will be affected by my fix?)
2. **Downstream**: What does this function call? (What dependencies might cause issues?)

Code Explorer answers both questions.

## Upstream Impact: Finding Callers

Let's say you're fixing a bug in the `compute_hash` function in `graph.py`:

```bash
code-explorer impact src/code_explorer/graph.py:DependencyGraph.compute_file_hash
```

Output:

```
┏━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━┓
┃ Function                ┃ File       ┃ Line  ┃ Depth ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━┩
│ analyze                 │ cli.py     │   138 │     1 │
│ file_exists             │ graph.py   │   596 │     1 │
└─────────────────────────┴────────────┴───────┴───────┘
```

**Interpretation**:
- Two functions call `compute_file_hash`
- Both are at depth 1 (direct callers)
- If you change the hash algorithm, test `analyze` and `file_exists`

## Downstream Impact: Finding Dependencies

Now see what `analyze` depends on:

```bash
code-explorer impact src/code_explorer/cli.py:analyze --downstream --max-depth 2
```

Output shows all functions called by `analyze` (depth 1) and functions called by those functions (depth 2):

```
┏━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━┓
┃ Function                ┃ File       ┃ Line  ┃ Depth ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━┩
│ DependencyGraph.__init__│ graph.py   │    45 │     1 │
│ clear_all               │ graph.py   │   676 │     1 │
│ analyze_directory       │ analyzer.py│    89 │     1 │
│ compute_file_hash       │ graph.py   │   694 │     1 │
│ _create_schema          │ graph.py   │    84 │     2 │
│ _check_read_only        │ graph.py   │    72 │     2 │
└─────────────────────────┴────────────┴───────┴───────┘
```

**Interpretation**:
- `analyze` directly calls 4 functions (depth 1)
- Those functions call 2 more (depth 2)
- If any of these break, `analyze` will fail

## Practical Example: Refactoring a Function

Let's walk through refactoring `add_function` in `graph.py`.

### Step 1: Find all callers

```bash
code-explorer impact src/code_explorer/graph.py:DependencyGraph.add_function
```

Result: 1 caller found at `cli.py:155`

### Step 2: Examine the calling code

Open `cli.py:155` and see how `add_function` is used:

```python
graph.add_function(
    name=func.name,
    file=func.file,
    start_line=func.start_line,
    end_line=func.end_line,
    is_public=func.is_public
)
```

### Step 3: Plan changes

Now you know:
- Only one place calls this function
- All 5 parameters are used
- You can safely add optional parameters without breaking anything
- If you change required parameters, only update `cli.py:155`

### Step 4: Make changes and verify

1. Refactor `add_function`
2. Update `cli.py:155`
3. Run tests: `pytest tests/test_graph.py -k add_function`
4. Re-analyze to update graph: `code-explorer analyze ./src --refresh`

## Tracing Variable Data Flow

Track how data flows through variables:

```bash
code-explorer trace src/code_explorer/cli.py:analyze --variable graph
```

This shows everywhere the `graph` variable is used in the `analyze` function.

## Depth Control

Limit how deep to traverse:

```bash
# Only show direct callers (depth 1)
code-explorer impact module.py:function --max-depth 1

# Show entire call chain (depth 10)
code-explorer impact module.py:function --max-depth 10
```

**Performance tip**: Higher depth = slower queries. Start with 3-5 for most cases.

## Real-World Use Cases

### 1. Bug Triage: "How Critical Is This Bug?"

```bash
code-explorer impact src/vulnerable_function.py:process_user_input
```

Many callers at depth 1-2 = critical bug (wide impact)
Few callers at depth 5+ = lower priority (isolated)

### 2. Safe Refactoring: "Can I Delete This Function?"

```bash
code-explorer impact src/old_module.py:legacy_function
```

No results = safe to delete (nothing calls it)

### 3. API Design: "Who Uses This Public API?"

```bash
code-explorer impact src/api.py:public_endpoint --max-depth 3
```

Shows all code paths that eventually call your API.

### 4. Performance Optimization: "What's the Hottest Path?"

```bash
code-explorer stats --top 20
```

The most-called functions are candidates for optimization.

## Next Steps

- [How-To: Find Dependencies](../how-to/find-dependencies.md) - Specific recipes
- [Explanation: Graph Algorithms](../explanation/graph-algorithms.md) - How traversal works
- [Reference: CLI Commands](../reference/cli-commands.md) - Complete command reference
