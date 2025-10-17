"""
KuzuDB COPY FROM bulk loading performance benchmark.

This script tests the performance of bulk loading code-explorer graph data
using KuzuDB's COPY FROM functionality with Parquet files.

**Prerequisites:**
- Parquet files must exist in perfo/data/output/nodes/ and perfo/data/output/edges/
- Run perfo/export_graph.py first to generate test data

**Usage:**
```bash
python perfo/benchmark_bulk_load.py
```

**Steps:**
1. Preprocess files.parquet to remove unsupported timestamp column
2. Create fresh database in perfo/benchmark_bulk.db
3. Create code-explorer schema (File, Function, Class, etc.)
4. Load all node tables using COPY FROM
5. Load all edge tables using COPY FROM
6. Display detailed timing breakdown with Rich tables

**Load order:**
- Nodes first: File, Function, Class, Variable, Import, Decorator, Attribute, Exception
- Edges second: CONTAINS_*, METHOD_OF, INHERITS, HAS_*, CALLS, REFERENCES, ACCESSES, etc.

**Output format:**
```
Loading nodes...
✓ File: 100 rows in 0.04s (2,500 rows/sec)
✓ Function: 3000 rows in 0.15s (20,000 rows/sec)
...

Loading edges...
✓ CALLS: 15000 edges in 0.20s (75,000 edges/sec)
...

Total: 20,000 rows in 1.5s (13,333 rows/sec)
```

**Known Limitations:**
- KuzuDB 0.11.2 COPY FROM doesn't support timestamp[us] from Parquet directly
- Workaround: Preprocess files.parquet to drop the last_modified timestamp column
- Test data may contain duplicate primary keys (handled gracefully with error messages)
"""

import asyncio
import shutil
from pathlib import Path
from typing import Dict, List, Tuple

import kuzu
import pandas as pd
from codetiming import Timer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.box import ROUNDED

# Path configuration
SCRIPT_DIR = Path(__file__).parent
DATA_PATH = SCRIPT_DIR / "data" / "output"
NODES_PATH = DATA_PATH / "nodes"
EDGES_PATH = DATA_PATH / "edges"
DB_PATH = SCRIPT_DIR / "benchmark_bulk.db"
TEMP_DATA_PATH = SCRIPT_DIR / "temp_data"

console = Console()


class BenchmarkResult:
    """Container for benchmark timing results."""

    def __init__(self):
        self.node_times: Dict[str, Tuple[float, int]] = {}
        self.edge_times: Dict[str, Tuple[float, int]] = {}
        self.total_time: float = 0.0

    def add_node_time(self, table_name: str, elapsed: float, row_count: int):
        """Record node table loading time."""
        self.node_times[table_name] = (elapsed, row_count)

    def add_edge_time(self, table_name: str, elapsed: float, row_count: int):
        """Record edge table loading time."""
        self.edge_times[table_name] = (elapsed, row_count)

    def get_total_rows(self) -> int:
        """Calculate total rows loaded."""
        node_rows = sum(count for _, count in self.node_times.values())
        edge_rows = sum(count for _, count in self.edge_times.values())
        return node_rows + edge_rows


def preprocess_files_parquet() -> Path:
    """Preprocess files.parquet to remove timestamp column.

    Returns:
        Path to the preprocessed parquet file
    """
    source = NODES_PATH / "files.parquet"
    dest = TEMP_DATA_PATH / "files.parquet"

    # Create temp directory
    TEMP_DATA_PATH.mkdir(exist_ok=True)

    # Read and drop timestamp column
    df = pd.read_parquet(source)
    df_fixed = df[['path', 'language', 'content_hash']]

    # Save preprocessed file
    df_fixed.to_parquet(dest, index=False)

    return dest


async def create_schema(conn: kuzu.AsyncConnection) -> None:
    """Create KuzuDB schema with all node and edge tables."""
    # Node tables
    # Note: Omitting last_modified field for simplicity in bulk loading benchmark
    # (KuzuDB 0.11.2 has limitations with timestamp[us] from Parquet in COPY FROM)
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

    # Edge tables
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
        CREATE REL TABLE IF NOT EXISTS INHERITS(
            FROM Class TO Class
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
        CREATE REL TABLE IF NOT EXISTS CALLS(
            FROM Function TO Function,
            call_line INT64
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
        CREATE REL TABLE IF NOT EXISTS DECORATED_BY(
            FROM Function TO Decorator,
            position INT64
        )
    """)

    await conn.execute("""
        CREATE REL TABLE IF NOT EXISTS HANDLES_EXCEPTION(
            FROM Function TO Exception,
            line_number INT64,
            context STRING
        )
    """)


async def load_table(
    conn: kuzu.AsyncConnection,
    table_name: str,
    parquet_path: Path,
    column_select: str | None = None,
) -> Tuple[float, int]:
    """Load a single table using COPY FROM and return timing + row count.

    Args:
        conn: KuzuDB async connection
        table_name: Name of the table to load
        parquet_path: Path to the parquet file
        column_select: Optional column selection for LOAD FROM (e.g., "path, language, content_hash")

    Returns:
        Tuple of (elapsed_time, row_count)
    """
    if not parquet_path.exists():
        console.print(f"[yellow]⚠ {parquet_path.name} not found, skipping[/yellow]")
        return 0.0, 0

    # Get row count from parquet before loading
    try:
        import pyarrow.parquet as pq
        table = pq.read_table(parquet_path)
        count = len(table)
    except Exception:
        count = 0

    # Load data
    timer = Timer(logger=None)
    timer.start()

    if column_select:
        # Use LOAD FROM with column selection
        query = f"""
COPY {table_name} FROM (
    LOAD FROM '{parquet_path}'
    RETURN {column_select}
)
"""
        await conn.execute(query)
    else:
        # Direct COPY FROM
        await conn.execute(f"COPY {table_name} FROM '{parquet_path}';")

    elapsed = timer.stop()

    return elapsed, count


async def load_rel_table(
    conn: kuzu.AsyncConnection,
    table_name: str,
    parquet_path: Path,
) -> Tuple[float, int]:
    """Load a single relationship table using COPY FROM and return timing + row count.

    Args:
        conn: KuzuDB async connection
        table_name: Name of the relationship table to load
        parquet_path: Path to the parquet file

    Returns:
        Tuple of (elapsed_time, row_count)
    """
    if not parquet_path.exists():
        console.print(f"[yellow]⚠ {parquet_path.name} not found, skipping[/yellow]")
        return 0.0, 0

    # Load data
    timer = Timer(logger=None)
    timer.start()
    await conn.execute(f"COPY {table_name} FROM '{parquet_path}';")
    elapsed = timer.stop()

    # Count relationships - need to use appropriate node labels for the relationship
    # For now, we'll estimate from the file or skip detailed counting for speed
    # Since COPY FROM doesn't return count, we'll read the parquet file
    try:
        import pyarrow.parquet as pq
        table = pq.read_table(parquet_path)
        count = len(table)
    except Exception:
        count = 0

    return elapsed, count


async def load_nodes(
    conn: kuzu.AsyncConnection,
    results: BenchmarkResult,
    files_parquet_path: Path,
) -> None:
    """Load all node tables in order."""
    console.print("\n[bold cyan]Loading nodes...[/bold cyan]")

    # Map table name to (filename/path, use_direct_path)
    node_mappings = [
        ("File", files_parquet_path, True),  # Use preprocessed file
        ("Function", NODES_PATH / "functions.parquet", False),
        ("Class", NODES_PATH / "classes.parquet", False),
        ("Variable", NODES_PATH / "variables.parquet", False),
        ("Import", NODES_PATH / "imports.parquet", False),
        ("Decorator", NODES_PATH / "decorators.parquet", False),
        ("Attribute", NODES_PATH / "attributes.parquet", False),
        ("Exception", NODES_PATH / "exceptions.parquet", False),
    ]

    for table_name, parquet_path, _ in node_mappings:
        # Always use direct COPY now (no column selection needed)
        try:
            elapsed, count = await load_table(conn, table_name, parquet_path, None)

            if count > 0:
                rate = count / elapsed if elapsed > 0 else 0
                results.add_node_time(table_name, elapsed, count)
                console.print(
                    f"[green]✓[/green] {table_name:12} {count:>6} rows in {elapsed:>6.3f}s "
                    f"({rate:>10,.0f} rows/sec)"
                )
        except Exception as e:
            console.print(f"[red]✗[/red] {table_name:12} Error: {str(e)[:80]}")


async def load_edges(
    conn: kuzu.AsyncConnection,
    results: BenchmarkResult,
) -> None:
    """Load all edge tables in order."""
    console.print("\n[bold cyan]Loading edges...[/bold cyan]")

    edge_mappings = [
        ("CONTAINS_FUNCTION", "contains_function.parquet"),
        ("CONTAINS_CLASS", "contains_class.parquet"),
        ("CONTAINS_VARIABLE", "contains_variable.parquet"),
        ("METHOD_OF", "method_of.parquet"),
        ("INHERITS", "inherits.parquet"),
        ("HAS_IMPORT", "has_import.parquet"),
        ("HAS_ATTRIBUTE", "has_attribute.parquet"),
        ("CALLS", "calls.parquet"),
        ("REFERENCES", "references.parquet"),
        ("ACCESSES", "accesses.parquet"),
        ("DECORATED_BY", "decorated_by.parquet"),
        ("HANDLES_EXCEPTION", "handles_exception.parquet"),
    ]

    for table_name, filename in edge_mappings:
        parquet_path = EDGES_PATH / filename
        try:
            elapsed, count = await load_rel_table(conn, table_name, parquet_path)

            if count > 0:
                rate = count / elapsed if elapsed > 0 else 0
                results.add_edge_time(table_name, elapsed, count)
                console.print(
                    f"[green]✓[/green] {table_name:20} {count:>6} edges in {elapsed:>6.3f}s "
                    f"({rate:>10,.0f} edges/sec)"
                )
        except Exception as e:
            console.print(f"[red]✗[/red] {table_name:20} Error: {str(e)[:80]}")


def display_summary(results: BenchmarkResult) -> None:
    """Display summary table with benchmark results."""
    console.print("\n")

    # Create summary table
    table = Table(
        title="KuzuDB COPY FROM Benchmark Summary",
        box=ROUNDED,
        show_header=True,
        header_style="bold magenta",
    )

    table.add_column("Category", style="cyan", no_wrap=True)
    table.add_column("Tables", justify="right", style="green")
    table.add_column("Total Rows", justify="right", style="yellow")
    table.add_column("Total Time", justify="right", style="blue")
    table.add_column("Avg Rate", justify="right", style="magenta")

    # Node stats
    node_count = len(results.node_times)
    node_rows = sum(count for _, count in results.node_times.values())
    node_time = sum(time for time, _ in results.node_times.values())
    node_rate = node_rows / node_time if node_time > 0 else 0

    table.add_row(
        "Nodes",
        str(node_count),
        f"{node_rows:,}",
        f"{node_time:.3f}s",
        f"{node_rate:,.0f} rows/s",
    )

    # Edge stats
    edge_count = len(results.edge_times)
    edge_rows = sum(count for _, count in results.edge_times.values())
    edge_time = sum(time for time, _ in results.edge_times.values())
    edge_rate = edge_rows / edge_time if edge_time > 0 else 0

    table.add_row(
        "Edges",
        str(edge_count),
        f"{edge_rows:,}",
        f"{edge_time:.3f}s",
        f"{edge_rate:,.0f} edges/s",
    )

    # Total stats
    total_rows = results.get_total_rows()
    total_time = results.total_time
    total_rate = total_rows / total_time if total_time > 0 else 0

    table.add_row(
        "[bold]Total[/bold]",
        f"[bold]{node_count + edge_count}[/bold]",
        f"[bold]{total_rows:,}[/bold]",
        f"[bold]{total_time:.3f}s[/bold]",
        f"[bold]{total_rate:,.0f} rows/s[/bold]",
        style="bold",
    )

    console.print(table)
    console.print()


async def run_benchmark() -> None:
    """Run the complete benchmark."""
    # Display header
    console.print(
        Panel.fit(
            "[bold cyan]KuzuDB COPY FROM Benchmark[/bold cyan]\n"
            f"Database: {DB_PATH}\n"
            f"Data: {DATA_PATH}",
            border_style="cyan",
        )
    )

    # Clean up old database and temp data
    if DB_PATH.exists():
        console.print(f"\n[yellow]Removing existing database: {DB_PATH}[/yellow]")
        if DB_PATH.is_dir():
            shutil.rmtree(DB_PATH, ignore_errors=True)
        else:
            DB_PATH.unlink(missing_ok=True)

    if TEMP_DATA_PATH.exists():
        shutil.rmtree(TEMP_DATA_PATH, ignore_errors=True)

    # Initialize results
    results = BenchmarkResult()

    # Create database and connection
    console.print(f"[cyan]Creating database: {DB_PATH}[/cyan]")
    db = kuzu.Database(str(DB_PATH))
    conn = kuzu.AsyncConnection(db)

    # Start total timer
    total_timer = Timer(logger=None)
    total_timer.start()

    try:
        # Preprocess files.parquet
        console.print("[cyan]Preprocessing files.parquet...[/cyan]")
        preprocess_timer = Timer(logger=None)
        preprocess_timer.start()
        files_parquet_path = preprocess_files_parquet()
        preprocess_time = preprocess_timer.stop()
        console.print(f"[green]✓[/green] Preprocessing complete in {preprocess_time:.3f}s")

        # Create schema
        console.print("[cyan]Creating schema...[/cyan]")
        schema_timer = Timer(logger=None)
        schema_timer.start()
        await create_schema(conn)
        schema_time = schema_timer.stop()
        console.print(f"[green]✓[/green] Schema created in {schema_time:.3f}s")

        # Load nodes
        await load_nodes(conn, results, files_parquet_path)

        # Load edges
        await load_edges(conn, results)

        # Stop total timer
        results.total_time = total_timer.stop()

        # Display summary
        display_summary(results)

        console.print(
            f"[bold green]✓ Benchmark complete![/bold green] "
            f"Database saved to: {DB_PATH}"
        )

    except Exception as e:
        console.print(f"[bold red]Error during benchmark: {e}[/bold red]")
        raise


async def main():
    """Main entry point."""
    # Verify data paths exist
    if not NODES_PATH.exists():
        console.print(
            f"[bold red]Error:[/bold red] Nodes path not found: {NODES_PATH}"
        )
        console.print(
            "Please run the data export script first to generate Parquet files."
        )
        return

    if not EDGES_PATH.exists():
        console.print(
            f"[bold red]Error:[/bold red] Edges path not found: {EDGES_PATH}"
        )
        console.print(
            "Please run the data export script first to generate Parquet files."
        )
        return

    await run_benchmark()


if __name__ == "__main__":
    asyncio.run(main())
