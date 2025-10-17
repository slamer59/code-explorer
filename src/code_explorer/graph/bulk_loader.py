"""
Production-ready bulk loader for KuzuDB using COPY FROM.

This module provides high-performance bulk loading of graph data from Parquet files
into KuzuDB using the native COPY FROM functionality. It's significantly faster than
row-by-row insertion for large datasets.

**Key Features:**
- Async-first design with AsyncConnection for optimal performance
- Detailed timing and row count tracking per table
- Graceful handling of missing files
- Proper load ordering (nodes before edges)
- File preprocessing for timestamp column issues

**Usage:**

Async (recommended):
```python
import asyncio
from pathlib import Path
from code_explorer.graph.bulk_loader import load_from_parquet

async def main():
    stats = await load_from_parquet(
        conn=async_conn,
        parquet_dir=Path("data/parquet"),
    )
    print(f"Loaded {stats['total_nodes']} nodes and {stats['total_edges']} edges")

asyncio.run(main())
```

Sync (convenience wrapper):
```python
from pathlib import Path
from code_explorer.graph.bulk_loader import load_from_parquet_sync

stats = load_from_parquet_sync(
    db_path=Path("graph.db"),
    parquet_dir=Path("data/parquet"),
)
```

**Directory Structure:**
```
parquet_dir/
├── nodes/
│   ├── files.parquet
│   ├── functions.parquet
│   ├── classes.parquet
│   └── ...
└── edges/
    ├── contains_function.parquet
    ├── calls.parquet
    └── ...
```

**Return Statistics:**
```python
{
    'total_nodes': 1500,
    'total_edges': 3200,
    'total_time': 2.45,
    'node_times': {
        'File': (0.04, 100),
        'Function': (0.12, 850),
        ...
    },
    'edge_times': {
        'CONTAINS_FUNCTION': (0.08, 850),
        'CALLS': (0.15, 1200),
        ...
    },
    'errors': []
}
```
"""

import asyncio
import logging
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import kuzu
import pandas as pd
import pyarrow.parquet as pq
from codetiming import Timer

logger = logging.getLogger(__name__)


def preprocess_files_parquet(source: Path, dest: Path) -> None:
    """Preprocess files.parquet to remove timestamp column.

    KuzuDB 0.11.2 COPY FROM doesn't support timestamp[us] from Parquet directly.
    This function removes the unsupported last_modified column.

    Args:
        source: Path to original files.parquet
        dest: Path to save preprocessed file

    Raises:
        FileNotFoundError: If source file doesn't exist
        ValueError: If required columns are missing
    """
    if not source.exists():
        raise FileNotFoundError(f"Source file not found: {source}")

    logger.info(f"Preprocessing {source} -> {dest}")

    # Read and validate columns
    df = pd.read_parquet(source)
    required_cols = ["path", "language", "content_hash"]

    missing_cols = set(required_cols) - set(df.columns)
    if missing_cols:
        raise ValueError(f"Missing required columns in files.parquet: {missing_cols}")

    # Keep only required columns
    df_fixed = df[required_cols]

    # Save preprocessed file
    dest.parent.mkdir(parents=True, exist_ok=True)
    df_fixed.to_parquet(dest, index=False)

    logger.info(f"Preprocessed {len(df_fixed)} file records")


async def create_schema(conn: kuzu.AsyncConnection) -> None:
    """Create KuzuDB schema with all node and edge tables.

    This creates the exact schema used by code-explorer, matching the
    benchmark implementation. The schema omits the last_modified field
    from File table to avoid timestamp compatibility issues.

    Args:
        conn: KuzuDB async connection
    """
    logger.info("Creating schema...")

    # Node tables - 8 tables
    await conn.execute("""
        CREATE NODE TABLE IF NOT EXISTS File(
            path STRING,
            language STRING,
            content_hash STRING,
            PRIMARY KEY(path)
        )
    """)

    await conn.execute("""
        CREATE NODE TABLE IF NOT EXISTS Function(
            id STRING,
            name STRING,
            file STRING,
            start_line INT64,
            end_line INT64,
            is_public BOOLEAN,
            source_code STRING,
            PRIMARY KEY(id)
        )
    """)

    await conn.execute("""
        CREATE NODE TABLE IF NOT EXISTS Class(
            id STRING,
            name STRING,
            file STRING,
            start_line INT64,
            end_line INT64,
            bases STRING,
            is_public BOOLEAN,
            source_code STRING,
            PRIMARY KEY(id)
        )
    """)

    await conn.execute("""
        CREATE NODE TABLE IF NOT EXISTS Variable(
            id STRING,
            name STRING,
            file STRING,
            definition_line INT64,
            scope STRING,
            PRIMARY KEY(id)
        )
    """)

    await conn.execute("""
        CREATE NODE TABLE IF NOT EXISTS Import(
            id STRING,
            imported_name STRING,
            import_type STRING,
            alias STRING,
            line_number INT64,
            is_relative BOOLEAN,
            file STRING,
            PRIMARY KEY(id)
        )
    """)

    await conn.execute("""
        CREATE NODE TABLE IF NOT EXISTS Decorator(
            id STRING,
            name STRING,
            file STRING,
            line_number INT64,
            arguments STRING,
            PRIMARY KEY(id)
        )
    """)

    await conn.execute("""
        CREATE NODE TABLE IF NOT EXISTS Attribute(
            id STRING,
            name STRING,
            class_name STRING,
            file STRING,
            definition_line INT64,
            type_hint STRING,
            is_class_attribute BOOLEAN,
            PRIMARY KEY(id)
        )
    """)

    await conn.execute("""
        CREATE NODE TABLE IF NOT EXISTS Exception(
            id STRING,
            name STRING,
            file STRING,
            line_number INT64,
            PRIMARY KEY(id)
        )
    """)

    # Edge tables - 12 tables (including CALLS and INHERITS)
    await conn.execute("""
        CREATE REL TABLE IF NOT EXISTS CONTAINS_FUNCTION(
            FROM File TO Function
        )
    """)

    await conn.execute("""
        CREATE REL TABLE IF NOT EXISTS CONTAINS_CLASS(
            FROM File TO Class
        )
    """)

    await conn.execute("""
        CREATE REL TABLE IF NOT EXISTS CONTAINS_VARIABLE(
            FROM File TO Variable
        )
    """)

    await conn.execute("""
        CREATE REL TABLE IF NOT EXISTS METHOD_OF(
            FROM Function TO Class
        )
    """)

    await conn.execute("""
        CREATE REL TABLE IF NOT EXISTS HAS_IMPORT(
            FROM File TO Import
        )
    """)

    await conn.execute("""
        CREATE REL TABLE IF NOT EXISTS HAS_ATTRIBUTE(
            FROM Class TO Attribute
        )
    """)

    await conn.execute("""
        CREATE REL TABLE IF NOT EXISTS DECORATED_BY(
            FROM Function TO Decorator,
            position INT64
        )
    """)

    await conn.execute("""
        CREATE REL TABLE IF NOT EXISTS REFERENCES(
            FROM Function TO Variable,
            line_number INT64,
            context STRING
        )
    """)

    await conn.execute("""
        CREATE REL TABLE IF NOT EXISTS ACCESSES(
            FROM Function TO Attribute,
            line_number INT64,
            access_type STRING
        )
    """)

    await conn.execute("""
        CREATE REL TABLE IF NOT EXISTS HANDLES_EXCEPTION(
            FROM Function TO Exception,
            line_number INT64,
            context STRING
        )
    """)

    await conn.execute("""
        CREATE REL TABLE IF NOT EXISTS CALLS(
            FROM Function TO Function,
            call_line INT64
        )
    """)

    await conn.execute("""
        CREATE REL TABLE IF NOT EXISTS INHERITS(
            FROM Class TO Class
        )
    """)

    logger.info("Schema created successfully")


async def load_table(
    conn: kuzu.AsyncConnection,
    table_name: str,
    parquet_path: Path,
) -> Tuple[float, int]:
    """Load a single node table using COPY FROM.

    Args:
        conn: KuzuDB async connection
        table_name: Name of the table to load
        parquet_path: Path to the parquet file

    Returns:
        Tuple of (elapsed_time_seconds, row_count)
        Returns (0.0, 0) if file doesn't exist
    """
    if not parquet_path.exists():
        logger.warning(f"Parquet file not found, skipping: {parquet_path.name}")
        return 0.0, 0

    # Get row count from parquet before loading
    try:
        table = pq.read_table(parquet_path)
        count = len(table)
    except Exception as e:
        logger.error(f"Failed to read parquet metadata for {parquet_path.name}: {e}")
        return 0.0, 0

    # Load data with timing
    timer = Timer(logger=None)
    timer.start()

    try:
        await conn.execute(f"COPY {table_name} FROM '{parquet_path}';")
        elapsed = timer.stop()
        logger.info(f"Loaded {table_name}: {count} rows in {elapsed:.3f}s")
        return elapsed, count
    except Exception as e:
        elapsed = timer.stop()
        logger.error(f"Failed to load {table_name}: {str(e)[:200]}")
        raise


async def load_rel_table(
    conn: kuzu.AsyncConnection,
    table_name: str,
    parquet_path: Path,
) -> Tuple[float, int]:
    """Load a single relationship table using COPY FROM.

    Args:
        conn: KuzuDB async connection
        table_name: Name of the relationship table to load
        parquet_path: Path to the parquet file

    Returns:
        Tuple of (elapsed_time_seconds, edge_count)
        Returns (0.0, 0) if file doesn't exist
    """
    if not parquet_path.exists():
        logger.warning(f"Parquet file not found, skipping: {parquet_path.name}")
        return 0.0, 0

    # Get edge count from parquet
    try:
        table = pq.read_table(parquet_path)
        count = len(table)
    except Exception as e:
        logger.error(f"Failed to read parquet metadata for {parquet_path.name}: {e}")
        return 0.0, 0

    # Load data with timing
    timer = Timer(logger=None)
    timer.start()

    try:
        await conn.execute(f"COPY {table_name} FROM '{parquet_path}';")
        elapsed = timer.stop()
        logger.info(f"Loaded {table_name}: {count} edges in {elapsed:.3f}s")
        return elapsed, count
    except Exception as e:
        elapsed = timer.stop()
        logger.error(f"Failed to load {table_name}: {str(e)[:200]}")
        raise


async def load_from_parquet(
    conn: kuzu.AsyncConnection,
    parquet_dir: Path,
) -> dict:
    """Load graph from Parquet files using COPY FROM.

    This is the main entry point for bulk loading. It loads all nodes first,
    then all edges, tracking detailed statistics for each table.

    **Load Order:**
    1. Nodes: File, Function, Class, Variable, Import, Decorator, Attribute, Exception
    2. Edges: CONTAINS_*, METHOD_OF, HAS_*, DECORATED_BY, REFERENCES, ACCESSES, HANDLES_EXCEPTION, CALLS, INHERITS

    Args:
        conn: KuzuDB async connection
        parquet_dir: Directory containing nodes/ and edges/ subdirectories

    Returns:
        Dictionary with detailed statistics:
        {
            'total_nodes': int,
            'total_edges': int,
            'total_time': float,
            'node_times': Dict[str, Tuple[float, int]],  # table_name -> (time, count)
            'edge_times': Dict[str, Tuple[float, int]],  # table_name -> (time, count)
            'errors': List[str]
        }

    Raises:
        FileNotFoundError: If parquet_dir doesn't exist
        ValueError: If nodes/ or edges/ subdirectories don't exist
    """
    if not parquet_dir.exists():
        raise FileNotFoundError(f"Parquet directory not found: {parquet_dir}")

    nodes_path = parquet_dir / "nodes"
    edges_path = parquet_dir / "edges"

    if not nodes_path.exists():
        raise ValueError(f"Nodes directory not found: {nodes_path}")
    if not edges_path.exists():
        raise ValueError(f"Edges directory not found: {edges_path}")

    logger.info(f"Starting bulk load from {parquet_dir}")

    # Initialize result tracking
    node_times: Dict[str, Tuple[float, int]] = {}
    edge_times: Dict[str, Tuple[float, int]] = {}
    errors: List[str] = []

    total_timer = Timer(logger=None)
    total_timer.start()

    # Preprocess files.parquet (handle timestamp column)
    temp_dir = parquet_dir / "temp"
    try:
        files_source = nodes_path / "files.parquet"
        files_dest = temp_dir / "files.parquet"

        if files_source.exists():
            try:
                preprocess_files_parquet(files_source, files_dest)
            except Exception as e:
                error_msg = f"Failed to preprocess files.parquet: {e}"
                logger.error(error_msg)
                errors.append(error_msg)
                files_dest = files_source  # Fallback to original
        else:
            logger.warning("files.parquet not found, skipping file preprocessing")
            files_dest = files_source
    except Exception as e:
        error_msg = f"Preprocessing error: {e}"
        logger.error(error_msg)
        errors.append(error_msg)
        files_dest = nodes_path / "files.parquet"

    # Load nodes in order (must come before edges)
    logger.info("Loading nodes...")

    node_mappings = [
        ("File", files_dest),
        ("Function", nodes_path / "functions.parquet"),
        ("Class", nodes_path / "classes.parquet"),
        ("Variable", nodes_path / "variables.parquet"),
        ("Import", nodes_path / "imports.parquet"),
        ("Decorator", nodes_path / "decorators.parquet"),
        ("Attribute", nodes_path / "attributes.parquet"),
        ("Exception", nodes_path / "exceptions.parquet"),
    ]

    for table_name, parquet_path in node_mappings:
        try:
            elapsed, count = await load_table(conn, table_name, parquet_path)
            if count > 0:
                node_times[table_name] = (elapsed, count)
        except Exception as e:
            error_msg = f"Failed to load {table_name}: {str(e)[:200]}"
            logger.error(error_msg)
            errors.append(error_msg)

    # Load edges in order (must come after nodes)
    logger.info("Loading edges...")

    edge_mappings = [
        ("CONTAINS_FUNCTION", "contains_function.parquet"),
        ("CONTAINS_CLASS", "contains_class.parquet"),
        ("CONTAINS_VARIABLE", "contains_variable.parquet"),
        ("METHOD_OF", "method_of.parquet"),
        ("HAS_IMPORT", "has_import.parquet"),
        ("HAS_ATTRIBUTE", "has_attribute.parquet"),
        ("DECORATED_BY", "decorated_by.parquet"),
        ("REFERENCES", "references.parquet"),
        ("ACCESSES", "accesses.parquet"),
        ("HANDLES_EXCEPTION", "handles_exception.parquet"),
        ("CALLS", "calls.parquet"),
        ("INHERITS", "inherits.parquet"),
    ]

    for table_name, filename in edge_mappings:
        parquet_path = edges_path / filename
        try:
            elapsed, count = await load_rel_table(conn, table_name, parquet_path)
            if count > 0:
                edge_times[table_name] = (elapsed, count)
        except Exception as e:
            error_msg = f"Failed to load {table_name}: {str(e)[:200]}"
            logger.error(error_msg)
            errors.append(error_msg)

    total_time = total_timer.stop()

    # Cleanup temp directory
    if temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)

    # Calculate totals
    total_nodes = sum(count for _, count in node_times.values())
    total_edges = sum(count for _, count in edge_times.values())

    logger.info(
        f"Bulk load complete: {total_nodes} nodes, {total_edges} edges in {total_time:.3f}s"
    )

    return {
        "total_nodes": total_nodes,
        "total_edges": total_edges,
        "total_time": total_time,
        "node_times": node_times,
        "edge_times": edge_times,
        "errors": errors,
    }


def load_from_parquet_sync(
    db_path: Path,
    parquet_dir: Path,
    create_new: bool = True,
) -> dict:
    """Synchronous wrapper for bulk loading from Parquet.

    This is a convenience function that creates a new database,
    creates the schema, and loads all data. For more control,
    use the async version directly.

    Args:
        db_path: Path to KuzuDB database (will be created if needed)
        parquet_dir: Directory containing nodes/ and edges/ subdirectories
        create_new: If True, removes existing database first (default: True)

    Returns:
        Dictionary with detailed statistics (same as load_from_parquet)

    Raises:
        FileNotFoundError: If parquet_dir doesn't exist
        ValueError: If nodes/ or edges/ subdirectories don't exist
    """
    logger.info(f"Sync bulk load: {db_path} from {parquet_dir}")

    # Remove existing database if requested
    if create_new and db_path.exists():
        logger.info(f"Removing existing database: {db_path}")
        if db_path.is_dir():
            shutil.rmtree(db_path, ignore_errors=True)
        else:
            db_path.unlink(missing_ok=True)

    # Create database and connection
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = kuzu.Database(str(db_path))
    conn = kuzu.AsyncConnection(db)

    # Run async operations
    async def _load():
        # Create schema
        await create_schema(conn)

        # Load data
        return await load_from_parquet(conn, parquet_dir)

    return asyncio.run(_load())
