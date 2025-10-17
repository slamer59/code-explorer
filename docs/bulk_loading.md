# Bulk Loading with KuzuDB COPY FROM

This document describes how to use the production-ready bulk loader for high-performance graph data loading.

## Overview

The bulk loader uses KuzuDB's native `COPY FROM` functionality to load Parquet files directly into the graph database. This approach is **23x faster** and uses **99% less memory** compared to row-by-row insertion.

**Performance Characteristics:**
- Loading 10,000+ nodes in < 1 second
- Parallel file processing with async/await
- Minimal memory footprint (streaming from Parquet)
- Detailed timing and statistics tracking

## Quick Start

### Async API (Recommended)

```python
import asyncio
from pathlib import Path
import kuzu
from code_explorer.graph.bulk_loader import create_schema, load_from_parquet

async def main():
    # Create database and connection
    db = kuzu.Database("graph.db")
    conn = kuzu.AsyncConnection(db)

    # Create schema
    await create_schema(conn)

    # Load data
    stats = await load_from_parquet(
        conn=conn,
        parquet_dir=Path("data/parquet"),
    )

    # Print statistics
    print(f"Loaded {stats['total_nodes']} nodes in {stats['total_time']:.2f}s")
    print(f"Loaded {stats['total_edges']} edges")

    for table, (time, count) in stats['node_times'].items():
        rate = count / time if time > 0 else 0
        print(f"  {table}: {count} rows in {time:.3f}s ({rate:,.0f} rows/sec)")

asyncio.run(main())
```

### Sync API (Convenience Wrapper)

```python
from pathlib import Path
from code_explorer.graph.bulk_loader import load_from_parquet_sync

# Create new database and load data in one call
stats = load_from_parquet_sync(
    db_path=Path("graph.db"),
    parquet_dir=Path("data/parquet"),
    create_new=True  # Removes existing DB first
)

print(f"Loaded {stats['total_nodes']} nodes and {stats['total_edges']} edges")
```

### Integration with DependencyGraph

```python
from pathlib import Path
from code_explorer.graph.graph import DependencyGraph

# Using the DependencyGraph facade
graph = DependencyGraph(db_path=Path("graph.db"))

stats = graph.load_from_parquet(Path("data/parquet"))

print(f"Graph loaded: {stats['total_nodes']} nodes, {stats['total_edges']} edges")
```

## Directory Structure

The bulk loader expects Parquet files organized in this structure:

```
parquet_dir/
├── nodes/
│   ├── files.parquet          # File nodes
│   ├── functions.parquet      # Function nodes
│   ├── classes.parquet        # Class nodes
│   ├── variables.parquet      # Variable nodes
│   ├── imports.parquet        # Import nodes
│   ├── decorators.parquet     # Decorator nodes
│   ├── attributes.parquet     # Attribute nodes
│   └── exceptions.parquet     # Exception nodes
└── edges/
    ├── contains_function.parquet   # File -> Function
    ├── contains_class.parquet      # File -> Class
    ├── contains_variable.parquet   # File -> Variable
    ├── method_of.parquet           # Function -> Class
    ├── has_import.parquet          # File -> Import
    ├── has_attribute.parquet       # Class -> Attribute
    ├── decorated_by.parquet        # Function -> Decorator
    ├── references.parquet          # Function -> Variable
    ├── accesses.parquet            # Function -> Attribute
    └── handles_exception.parquet   # Function -> Exception
```

## Load Order

The bulk loader follows a strict load order to ensure referential integrity:

**1. Nodes (must be loaded before edges):**
1. File
2. Function
3. Class
4. Variable
5. Import
6. Decorator
7. Attribute
8. Exception

**2. Edges (must be loaded after nodes):**
1. CONTAINS_FUNCTION
2. CONTAINS_CLASS
3. CONTAINS_VARIABLE
4. METHOD_OF
5. HAS_IMPORT
6. HAS_ATTRIBUTE
7. DECORATED_BY
8. REFERENCES
9. ACCESSES
10. HANDLES_EXCEPTION

## Schema

The bulk loader creates tables matching the code-explorer schema:

### Node Tables

```sql
-- File nodes
CREATE NODE TABLE File(
    path STRING PRIMARY KEY,
    language STRING,
    content_hash STRING
)

-- Function nodes
CREATE NODE TABLE Function(
    id STRING PRIMARY KEY,
    name STRING,
    file STRING,
    start_line INT64,
    end_line INT64,
    is_public BOOLEAN,
    source_code STRING
)

-- Class nodes
CREATE NODE TABLE Class(
    id STRING PRIMARY KEY,
    name STRING,
    file STRING,
    start_line INT64,
    end_line INT64,
    bases STRING,
    is_public BOOLEAN,
    source_code STRING
)

-- Additional node tables: Variable, Import, Decorator, Attribute, Exception
```

### Edge Tables

```sql
-- File contains Function
CREATE REL TABLE CONTAINS_FUNCTION(FROM File TO Function)

-- Function decorated by Decorator
CREATE REL TABLE DECORATED_BY(
    FROM Function TO Decorator,
    position INT64
)

-- Function references Variable
CREATE REL TABLE REFERENCES(
    FROM Function TO Variable,
    line_number INT64,
    context STRING
)

-- Additional edge tables: see schema above
```

## File Preprocessing

The `files.parquet` may contain a timestamp column that KuzuDB 0.11.2 doesn't support in COPY FROM. The bulk loader automatically preprocesses this file:

```python
from code_explorer.graph.bulk_loader import preprocess_files_parquet

# Removes unsupported timestamp column
preprocess_files_parquet(
    source=Path("nodes/files.parquet"),
    dest=Path("temp/files.parquet")
)
```

This keeps only the required columns: `path`, `language`, `content_hash`.

## Error Handling

The bulk loader handles errors gracefully:

**Missing Files:**
- Logs warning and continues
- Returns statistics with 0 counts for missing tables

**Schema Errors:**
- Raises exception immediately
- Database remains in consistent state

**Load Errors:**
- Logs error with details
- Continues with remaining tables
- Returns all errors in `stats['errors']` list

```python
stats = await load_from_parquet(conn, parquet_dir)

if stats['errors']:
    print("Errors occurred during loading:")
    for error in stats['errors']:
        print(f"  - {error}")
```

## Statistics

The loader returns detailed statistics:

```python
{
    'total_nodes': 15234,           # Total nodes loaded
    'total_edges': 32451,           # Total edges loaded
    'total_time': 2.45,             # Total time in seconds
    'node_times': {                 # Per-table timing
        'File': (0.04, 100),        # (time_seconds, row_count)
        'Function': (0.15, 8500),
        'Class': (0.08, 1200),
        ...
    },
    'edge_times': {                 # Per-relationship timing
        'CONTAINS_FUNCTION': (0.12, 8500),
        'CALLS': (0.35, 15000),
        ...
    },
    'errors': []                    # List of error messages
}
```

## Performance Tips

### 1. Use Async API

The async API is faster for multiple files:

```python
# GOOD: Async (parallel I/O)
stats = await load_from_parquet(async_conn, parquet_dir)

# SLOWER: Sync wrapper (sequential)
stats = load_from_parquet_sync(db_path, parquet_dir)
```

### 2. Pre-generate Parquet Files

Generate Parquet files once, load many times:

```python
# Export once
from code_explorer.analyzer.export_parquet import export_to_parquet
export_to_parquet(analysis_results, output_dir, project_root)

# Load many times (development, testing, etc.)
graph.load_from_parquet(output_dir)
```

### 3. Use SSD Storage

Parquet I/O benefits from fast storage:
- Use SSD for both Parquet files and database
- Keep Parquet files and DB on same drive to avoid network latency

### 4. Batch Export

Process all files at once for Parquet export:

```python
# GOOD: Export all files together
all_results = [analyze(f) for f in files]
export_to_parquet(all_results, output_dir)

# BAD: Export one file at a time
for f in files:
    result = analyze(f)
    export_to_parquet([result], output_dir)  # Overwrites each time!
```

## Logging

The bulk loader uses Python's logging module:

```python
import logging

# Enable detailed logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Load with logging
stats = await load_from_parquet(conn, parquet_dir)
```

**Log Levels:**
- `INFO`: Load progress, row counts, timing
- `WARNING`: Missing files, skipped tables
- `ERROR`: Load failures, schema errors

## Comparison with Batch Operations

| Metric | Bulk Loader (COPY FROM) | Old Batch Operations |
|--------|------------------------|---------------------|
| **Speed** | 23x faster | Baseline |
| **Memory** | 99% less | High (pandas DataFrames) |
| **Disk I/O** | Streaming | In-memory buffering |
| **API** | Async-first | Sync only |
| **Error Handling** | Granular per-table | All-or-nothing |
| **Preprocessing** | Automatic | Manual |

## Troubleshooting

### Missing Parquet Files

**Issue:** Warnings about missing files

**Solution:** This is normal if not all node/edge types are used. The loader skips missing files gracefully.

### Timestamp Column Error

**Issue:** Error loading `files.parquet` with timestamp column

**Solution:** Automatic - the loader preprocesses the file to remove timestamps.

### Referential Integrity Errors

**Issue:** "Node not found" errors when loading edges

**Solution:** Ensure nodes are loaded before edges. The bulk loader handles this automatically.

### Out of Memory

**Issue:** Running out of memory during load

**Solution:** The bulk loader uses streaming and should never run OOM. If this happens, check:
1. Is preprocessing running? (creates temp files)
2. Is the database on a full disk?
3. Are other processes consuming memory?

## API Reference

### `load_from_parquet(conn, parquet_dir)`

Async function to load all graph data from Parquet files.

**Parameters:**
- `conn` (kuzu.AsyncConnection): KuzuDB async connection
- `parquet_dir` (Path): Directory containing nodes/ and edges/ subdirectories

**Returns:**
- `dict`: Statistics dictionary with timing and counts

**Raises:**
- `FileNotFoundError`: If parquet_dir doesn't exist
- `ValueError`: If nodes/ or edges/ subdirectories missing

### `load_from_parquet_sync(db_path, parquet_dir, create_new=True)`

Sync wrapper that creates database and loads data.

**Parameters:**
- `db_path` (Path): Path to KuzuDB database
- `parquet_dir` (Path): Directory containing Parquet files
- `create_new` (bool): Remove existing database first (default: True)

**Returns:**
- `dict`: Statistics dictionary

### `create_schema(conn)`

Async function to create all node and edge tables.

**Parameters:**
- `conn` (kuzu.AsyncConnection): KuzuDB async connection

### `preprocess_files_parquet(source, dest)`

Remove timestamp column from files.parquet.

**Parameters:**
- `source` (Path): Original files.parquet
- `dest` (Path): Preprocessed output path

**Raises:**
- `FileNotFoundError`: If source doesn't exist
- `ValueError`: If required columns missing

## Examples

### Complete Workflow

```python
import asyncio
from pathlib import Path
from code_explorer.analyzer.codebase import analyze_codebase
from code_explorer.analyzer.export_parquet import export_to_parquet
from code_explorer.graph.bulk_loader import load_from_parquet_sync

# 1. Analyze codebase
results = analyze_codebase(
    root_dir=Path("src"),
    output_dir=Path(".code-explorer")
)

# 2. Export to Parquet
export_to_parquet(
    results=results,
    output_dir=Path(".code-explorer/parquet"),
    project_root=Path(".")
)

# 3. Bulk load into database
stats = load_from_parquet_sync(
    db_path=Path(".code-explorer/graph.db"),
    parquet_dir=Path(".code-explorer/parquet"),
    create_new=True
)

# 4. Use the graph
from code_explorer.graph.graph import DependencyGraph
graph = DependencyGraph(db_path=Path(".code-explorer/graph.db"))
functions = graph.get_all_functions_in_file("src/main.py")
```

### Performance Monitoring

```python
import asyncio
from pathlib import Path
import kuzu
from code_explorer.graph.bulk_loader import create_schema, load_from_parquet

async def monitor_load():
    db = kuzu.Database("graph.db")
    conn = kuzu.AsyncConnection(db)

    await create_schema(conn)

    stats = await load_from_parquet(conn, Path("data/parquet"))

    # Analyze performance
    total_items = stats['total_nodes'] + stats['total_edges']
    throughput = total_items / stats['total_time']

    print(f"\n=== Performance Report ===")
    print(f"Total items: {total_items:,}")
    print(f"Total time: {stats['total_time']:.2f}s")
    print(f"Throughput: {throughput:,.0f} items/sec")

    print(f"\n=== Node Loading ===")
    for table, (time, count) in stats['node_times'].items():
        rate = count / time if time > 0 else 0
        print(f"{table:15} {count:>8,} rows  {time:>6.3f}s  {rate:>12,.0f} rows/sec")

    print(f"\n=== Edge Loading ===")
    for table, (time, count) in stats['edge_times'].items():
        rate = count / time if time > 0 else 0
        print(f"{table:20} {count:>8,} edges {time:>6.3f}s  {rate:>12,.0f} edges/sec")

asyncio.run(monitor_load())
```

## See Also

- [perfo/benchmark_bulk_load.py](../perfo/benchmark_bulk_load.py) - Original benchmark implementation
- [src/code_explorer/analyzer/export_parquet.py](../src/code_explorer/analyzer/export_parquet.py) - Parquet export
- [KuzuDB Documentation](https://kuzudb.com/docs/) - Official KuzuDB docs
