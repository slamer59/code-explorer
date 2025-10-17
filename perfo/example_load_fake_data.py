"""
Example script demonstrating how to load fake generated data into KuzuDB.

This shows how to:
1. Create a KuzuDB database
2. Create the code-explorer schema
3. Load generated Parquet files using COPY FROM
4. Verify the loaded data

Usage:
    python perfo/example_load_fake_data.py
"""

import shutil
from pathlib import Path

import kuzu
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def main():
    """Load fake data into KuzuDB and display statistics."""
    # Configuration
    data_dir = Path("perfo/data/output")
    db_path = Path("perfo/test_fake_db")

    # Clean up existing database
    if db_path.exists():
        console.print(f"[yellow]Removing existing database at {db_path}[/yellow]")
        shutil.rmtree(db_path)

    # Create database
    console.print()
    console.print(Panel(
        "[bold cyan]Loading Fake Data into KuzuDB[/bold cyan]",
        border_style="cyan"
    ))
    console.print()

    console.print("[cyan]Creating database...[/cyan]")
    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)

    # Create schema
    console.print("[cyan]Creating schema...[/cyan]")

    # Node tables
    conn.execute("""
        CREATE NODE TABLE File(
            path STRING,
            language STRING,
            last_modified TIMESTAMP,
            content_hash STRING,
            PRIMARY KEY(path)
        )
    """)

    conn.execute("""
        CREATE NODE TABLE Function(
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

    conn.execute("""
        CREATE NODE TABLE Class(
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

    conn.execute("""
        CREATE NODE TABLE Variable(
            id STRING,
            name STRING,
            file STRING,
            definition_line INT64,
            scope STRING,
            PRIMARY KEY(id)
        )
    """)

    conn.execute("""
        CREATE NODE TABLE Import(
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

    conn.execute("""
        CREATE NODE TABLE Decorator(
            id STRING,
            name STRING,
            file STRING,
            line_number INT64,
            arguments STRING,
            PRIMARY KEY(id)
        )
    """)

    conn.execute("""
        CREATE NODE TABLE Attribute(
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

    conn.execute("""
        CREATE NODE TABLE Exception(
            id STRING,
            name STRING,
            file STRING,
            line_number INT64,
            PRIMARY KEY(id)
        )
    """)

    # Edge tables
    conn.execute("""
        CREATE REL TABLE CALLS(
            FROM Function TO Function,
            call_line INT64
        )
    """)

    conn.execute("""
        CREATE REL TABLE CONTAINS_FUNCTION(FROM File TO Function)
    """)

    conn.execute("""
        CREATE REL TABLE CONTAINS_CLASS(FROM File TO Class)
    """)

    conn.execute("""
        CREATE REL TABLE CONTAINS_VARIABLE(FROM File TO Variable)
    """)

    conn.execute("""
        CREATE REL TABLE METHOD_OF(FROM Function TO Class)
    """)

    conn.execute("""
        CREATE REL TABLE INHERITS(FROM Class TO Class)
    """)

    conn.execute("""
        CREATE REL TABLE HAS_IMPORT(FROM File TO Import)
    """)

    conn.execute("""
        CREATE REL TABLE DECORATED_BY(
            FROM Function TO Decorator,
            position INT64
        )
    """)

    conn.execute("""
        CREATE REL TABLE HAS_ATTRIBUTE(FROM Class TO Attribute)
    """)

    conn.execute("""
        CREATE REL TABLE REFERENCES(
            FROM Function TO Variable,
            line_number INT64,
            context STRING
        )
    """)

    conn.execute("""
        CREATE REL TABLE ACCESSES(
            FROM Function TO Attribute,
            line_number INT64,
            access_type STRING
        )
    """)

    conn.execute("""
        CREATE REL TABLE HANDLES_EXCEPTION(
            FROM Function TO Exception,
            line_number INT64,
            context STRING
        )
    """)

    console.print("[green]✓ Schema created[/green]")
    console.print()

    # Load nodes
    console.print("[cyan]Loading nodes...[/cyan]")

    nodes = [
        ("File", "files.parquet"),
        ("Function", "functions.parquet"),
        ("Class", "classes.parquet"),
        ("Variable", "variables.parquet"),
        ("Import", "imports.parquet"),
        ("Decorator", "decorators.parquet"),
        ("Attribute", "attributes.parquet"),
        ("Exception", "exceptions.parquet"),
    ]

    node_counts = {}
    for table, filename in nodes:
        parquet_path = data_dir / "nodes" / filename
        try:
            conn.execute(f"COPY {table} FROM '{parquet_path}'")
            result = conn.execute(f"MATCH (n:{table}) RETURN COUNT(*) as count")
            count = result.get_next()[0]
            node_counts[table] = count
            console.print(f"  ✓ Loaded {table}: {count:,} nodes")
        except Exception as e:
            console.print(f"  [red]✗ Error loading {table}: {e}[/red]")
            # Continue with other tables
            node_counts[table] = 0

    console.print()

    # Load edges
    console.print("[cyan]Loading edges...[/cyan]")

    edges = [
        ("CALLS", "calls.parquet"),
        ("CONTAINS_FUNCTION", "contains_function.parquet"),
        ("CONTAINS_CLASS", "contains_class.parquet"),
        ("CONTAINS_VARIABLE", "contains_variable.parquet"),
        ("METHOD_OF", "method_of.parquet"),
        ("INHERITS", "inherits.parquet"),
        ("HAS_IMPORT", "has_import.parquet"),
        ("DECORATED_BY", "decorated_by.parquet"),
        ("HAS_ATTRIBUTE", "has_attribute.parquet"),
        ("REFERENCES", "references.parquet"),
        ("ACCESSES", "accesses.parquet"),
        ("HANDLES_EXCEPTION", "handles_exception.parquet"),
    ]

    edge_counts = {}
    for table, filename in edges:
        parquet_path = data_dir / "edges" / filename
        conn.execute(f"COPY {table} FROM '{parquet_path}'")
        result = conn.execute(f"MATCH ()-[r:{table}]->() RETURN COUNT(*) as count")
        count = result.get_next()[0]
        edge_counts[table] = count
        console.print(f"  ✓ Loaded {table}: {count:,} edges")

    console.print()

    # Display summary
    table = Table(title="Database Summary", show_header=True, header_style="bold magenta")
    table.add_column("Type", style="cyan", width=30)
    table.add_column("Count", style="yellow", justify="right")

    # Node counts
    for node_type, count in node_counts.items():
        table.add_row(f"Node: {node_type}", f"{count:,}")

    table.add_row("", "", end_section=True)

    # Edge counts
    for edge_type, count in edge_counts.items():
        table.add_row(f"Edge: {edge_type}", f"{count:,}")

    table.add_row("", "", end_section=True)

    # Totals
    total_nodes = sum(node_counts.values())
    total_edges = sum(edge_counts.values())
    table.add_row("Total Nodes", f"{total_nodes:,}", style="bold")
    table.add_row("Total Edges", f"{total_edges:,}", style="bold")

    console.print(table)
    console.print()

    # Example queries
    console.print(Panel(
        "[bold cyan]Example Queries[/bold cyan]",
        border_style="cyan"
    ))
    console.print()

    # Query 1: Most called functions
    console.print("[cyan]Top 5 most called functions:[/cyan]")
    result = conn.execute("""
        MATCH (f:Function)<-[c:CALLS]-()
        RETURN f.name, COUNT(*) as call_count
        ORDER BY call_count DESC
        LIMIT 5
    """)
    while result.has_next():
        row = result.get_next()
        console.print(f"  • {row[0]}: {row[1]} calls")
    console.print()

    # Query 2: Classes with most methods
    console.print("[cyan]Top 5 classes with most methods:[/cyan]")
    result = conn.execute("""
        MATCH (c:Class)<-[m:METHOD_OF]-(f:Function)
        RETURN c.name, COUNT(*) as method_count
        ORDER BY method_count DESC
        LIMIT 5
    """)
    while result.has_next():
        row = result.get_next()
        console.print(f"  • {row[0]}: {row[1]} methods")
    console.print()

    # Query 3: Files with most functions
    console.print("[cyan]Top 5 files with most functions:[/cyan]")
    result = conn.execute("""
        MATCH (f:File)-[c:CONTAINS_FUNCTION]->(func:Function)
        RETURN f.path, COUNT(*) as func_count
        ORDER BY func_count DESC
        LIMIT 5
    """)
    while result.has_next():
        row = result.get_next()
        console.print(f"  • {row[0]}: {row[1]} functions")
    console.print()

    console.print(Panel(
        f"[green]✓ Successfully loaded fake data into {db_path}[/green]\n"
        f"[cyan]Total: {total_nodes:,} nodes, {total_edges:,} edges[/cyan]",
        title="Success",
        border_style="green"
    ))


if __name__ == "__main__":
    main()
