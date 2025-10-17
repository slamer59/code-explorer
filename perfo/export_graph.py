#!/usr/bin/env python3
"""
Export KuzuDB graph to Parquet files for performance analysis and data science.

This script reads from the code-explorer KuzuDB database in READ-ONLY mode
and exports all node types and edge types to separate Parquet files.

Usage:
    python perfo/export_graph.py

Output:
    - perfo/output/nodes/*.parquet (one file per node type)
    - perfo/output/edges/*.parquet (one file per edge type)
"""

import sys
from pathlib import Path
from typing import Any

import kuzu
import pandas as pd
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table
from rich.panel import Panel

# Add project root to path for imports if needed
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

console = Console()


class GraphExporter:
    """Export KuzuDB graph to Parquet files."""

    # Node types to export
    NODE_TYPES = [
        "File",
        "Function",
        "Class",
        "Variable",
        "Import",
        "Decorator",
        "Attribute",
        "Exception",
        "Module",
    ]

    # Edge types to export with their relationship names
    EDGE_TYPES = [
        ("CALLS", "calls"),
        ("REFERENCES", "references"),
        ("CONTAINS_FUNCTION", "contains_function"),
        ("CONTAINS_CLASS", "contains_class"),
        ("CONTAINS_VARIABLE", "contains_variable"),
        ("IMPORTS", "file_imports"),
        ("INHERITS", "inherits"),
        ("DEPENDS_ON", "depends_on"),
        ("METHOD_OF", "method_of"),
        ("HAS_IMPORT", "has_import"),
        ("IMPORTS_FROM", "imports_from"),
        ("DECORATED_BY", "decorated_by"),
        ("HAS_ATTRIBUTE", "has_attribute"),
        ("ACCESSES", "accesses"),
        ("HANDLES_EXCEPTION", "handles_exception"),
        ("CONTAINS_MODULE", "contains_module"),
        ("MODULE_OF", "module_of"),
    ]

    def __init__(self, db_path: str, output_dir: Path):
        """Initialize the exporter.

        Args:
            db_path: Path to the KuzuDB database
            output_dir: Base output directory for Parquet files
        """
        self.db_path = db_path
        self.output_dir = output_dir
        self.nodes_dir = output_dir / "nodes"
        self.edges_dir = output_dir / "edges"
        self.db = None
        self.conn = None
        self.stats = {
            "nodes": {},
            "edges": {},
            "errors": [],
        }

    def __enter__(self):
        """Open database connection in READ-ONLY mode."""
        try:
            # Open database in READ-ONLY mode
            self.db = kuzu.Database(self.db_path, read_only=True)
            self.conn = kuzu.Connection(self.db)
            console.print(f"[green]✓[/green] Connected to database: {self.db_path}")
            return self
        except Exception as e:
            console.print(f"[red]✗[/red] Failed to connect to database: {e}")
            raise

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Close database connection."""
        if self.conn:
            self.conn = None
        if self.db:
            self.db = None
        console.print("[green]✓[/green] Database connection closed")

    def create_output_dirs(self) -> None:
        """Create output directories if they don't exist."""
        self.nodes_dir.mkdir(parents=True, exist_ok=True)
        self.edges_dir.mkdir(parents=True, exist_ok=True)
        console.print(f"[green]✓[/green] Output directories ready:")
        console.print(f"  - Nodes: {self.nodes_dir}")
        console.print(f"  - Edges: {self.edges_dir}")

    def export_node_type(self, node_type: str) -> tuple[str, int, str | None]:
        """Export a single node type to Parquet.

        Args:
            node_type: The node type label (e.g., "File", "Function")

        Returns:
            Tuple of (node_type, row_count, error_message)
        """
        output_file = self.nodes_dir / f"{node_type.lower()}s.parquet"

        try:
            # Query all nodes of this type
            query = f"MATCH (n:{node_type}) RETURN n.*"
            result = self.conn.execute(query)

            # Convert to pandas DataFrame
            df = result.get_as_df()

            if len(df) == 0:
                return (node_type, 0, "No data (might not exist in this schema version)")

            # Write to Parquet
            df.to_parquet(output_file, index=False, compression="snappy")

            return (node_type, len(df), None)

        except Exception as e:
            error_msg = str(e)
            # Check if it's a "table doesn't exist" error
            if "does not exist" in error_msg.lower() or "not found" in error_msg.lower():
                return (node_type, 0, "Table does not exist in schema")
            return (node_type, 0, f"Error: {error_msg}")

    def export_edge_type(self, rel_name: str, file_name: str) -> tuple[str, int, str | None]:
        """Export a single edge type to Parquet.

        Args:
            rel_name: The relationship type name (e.g., "CALLS", "REFERENCES")
            file_name: The output file name (e.g., "calls", "references")

        Returns:
            Tuple of (rel_name, row_count, error_message)
        """
        output_file = self.edges_dir / f"{file_name}.parquet"

        try:
            # Query all edges of this type
            # We need to get the primary keys of source and destination nodes
            # Different edge types connect different node types, so we handle them differently

            # Mapping of edge types to their source and destination node types and PKs
            edge_configs = {
                "CALLS": ("Function", "id", "Function", "id"),
                "REFERENCES": ("Function", "id", "Variable", "id"),
                "CONTAINS_FUNCTION": ("File", "path", "Function", "id"),
                "CONTAINS_CLASS": ("File", "path", "Class", "id"),
                "CONTAINS_VARIABLE": ("File", "path", "Variable", "id"),
                "IMPORTS": ("File", "path", "File", "path"),
                "INHERITS": ("Class", "id", "Class", "id"),
                "DEPENDS_ON": ("Class", "id", "Class", "id"),
                "METHOD_OF": ("Function", "id", "Class", "id"),
                "HAS_IMPORT": ("File", "path", "Import", "id"),
                "IMPORTS_FROM": ("Import", "id", "Function", "id"),
                "DECORATED_BY": ("Function", "id", "Decorator", "id"),
                "HAS_ATTRIBUTE": ("Class", "id", "Attribute", "id"),
                "ACCESSES": ("Function", "id", "Attribute", "id"),
                "HANDLES_EXCEPTION": ("Function", "id", "Exception", "id"),
                "CONTAINS_MODULE": ("Module", "id", "Module", "id"),
                "MODULE_OF": ("File", "path", "Module", "id"),
            }

            if rel_name not in edge_configs:
                return (rel_name, 0, f"Unknown edge type configuration")

            src_type, src_pk, dst_type, dst_pk = edge_configs[rel_name]

            # Build query to get edge properties and node primary keys
            query = f"""
                MATCH (src:{src_type})-[r:{rel_name}]->(dst:{dst_type})
                RETURN r.*, src.{src_pk} as src_id, dst.{dst_pk} as dst_id
            """
            result = self.conn.execute(query)

            # Convert to pandas DataFrame
            df = result.get_as_df()

            if len(df) == 0:
                return (rel_name, 0, "No data (might not exist in this schema version)")

            # Write to Parquet
            df.to_parquet(output_file, index=False, compression="snappy")

            return (rel_name, len(df), None)

        except Exception as e:
            error_msg = str(e)
            # Check if it's a "table doesn't exist" error
            if "does not exist" in error_msg.lower() or "not found" in error_msg.lower():
                return (rel_name, 0, "Table does not exist in schema")
            return (rel_name, 0, f"Error: {error_msg}")

    def export_nodes(self) -> None:
        """Export all node types to Parquet files."""
        console.print("\n[bold cyan]Exporting Node Types[/bold cyan]")
        console.print("=" * 60)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:

            task = progress.add_task("[cyan]Exporting nodes...", total=len(self.NODE_TYPES))

            for node_type in self.NODE_TYPES:
                progress.update(task, description=f"[cyan]Exporting {node_type}...")
                node_type_name, count, error = self.export_node_type(node_type)

                self.stats["nodes"][node_type_name] = {
                    "count": count,
                    "error": error,
                }

                if error:
                    console.print(f"  [yellow]⚠[/yellow] {node_type}: {error}")
                else:
                    console.print(f"  [green]✓[/green] {node_type}: {count:,} nodes")

                progress.advance(task)

    def export_edges(self) -> None:
        """Export all edge types to Parquet files."""
        console.print("\n[bold cyan]Exporting Edge Types[/bold cyan]")
        console.print("=" * 60)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:

            task = progress.add_task("[cyan]Exporting edges...", total=len(self.EDGE_TYPES))

            for rel_name, file_name in self.EDGE_TYPES:
                progress.update(task, description=f"[cyan]Exporting {rel_name}...")
                edge_name, count, error = self.export_edge_type(rel_name, file_name)

                self.stats["edges"][edge_name] = {
                    "count": count,
                    "error": error,
                }

                if error:
                    console.print(f"  [yellow]⚠[/yellow] {rel_name}: {error}")
                else:
                    console.print(f"  [green]✓[/green] {rel_name}: {count:,} edges")

                progress.advance(task)

    def print_summary(self) -> None:
        """Print export summary statistics."""
        console.print("\n[bold cyan]Export Summary[/bold cyan]")
        console.print("=" * 60)

        # Node statistics
        table = Table(title="Node Statistics", show_header=True, header_style="bold magenta")
        table.add_column("Node Type", style="cyan", width=20)
        table.add_column("Count", justify="right", style="green", width=15)
        table.add_column("Status", width=25)

        total_nodes = 0
        for node_type, stats in self.stats["nodes"].items():
            count = stats["count"]
            error = stats["error"]
            total_nodes += count

            if error:
                status = f"[yellow]{error}[/yellow]"
            else:
                status = "[green]✓ Exported[/green]"

            table.add_row(node_type, f"{count:,}", status)

        table.add_row("", "", "", style="dim")
        table.add_row("[bold]TOTAL", f"[bold]{total_nodes:,}", "")
        console.print(table)

        # Edge statistics
        table = Table(title="Edge Statistics", show_header=True, header_style="bold magenta")
        table.add_column("Edge Type", style="cyan", width=20)
        table.add_column("Count", justify="right", style="green", width=15)
        table.add_column("Status", width=25)

        total_edges = 0
        for edge_type, stats in self.stats["edges"].items():
            count = stats["count"]
            error = stats["error"]
            total_edges += count

            if error:
                status = f"[yellow]{error}[/yellow]"
            else:
                status = "[green]✓ Exported[/green]"

            table.add_row(edge_type, f"{count:,}", status)

        table.add_row("", "", "", style="dim")
        table.add_row("[bold]TOTAL", f"[bold]{total_edges:,}", "")
        console.print(table)

        # File size summary
        console.print(f"\n[bold]Output Location:[/bold]")
        console.print(f"  {self.output_dir}")

        # Calculate total size
        total_size = 0
        file_count = 0
        for parquet_file in self.output_dir.rglob("*.parquet"):
            total_size += parquet_file.stat().st_size
            file_count += 1

        # Format size
        if total_size < 1024:
            size_str = f"{total_size} B"
        elif total_size < 1024 * 1024:
            size_str = f"{total_size / 1024:.2f} KB"
        elif total_size < 1024 * 1024 * 1024:
            size_str = f"{total_size / (1024 * 1024):.2f} MB"
        else:
            size_str = f"{total_size / (1024 * 1024 * 1024):.2f} GB"

        console.print(f"[bold]Total Size:[/bold] {size_str} ({file_count} files)")

    def run(self) -> None:
        """Run the complete export process."""
        console.print(Panel.fit(
            "[bold cyan]KuzuDB Graph Exporter[/bold cyan]\n"
            "Exporting code dependency graph to Parquet files",
            border_style="cyan"
        ))

        # Create output directories
        self.create_output_dirs()

        # Export nodes and edges
        self.export_nodes()
        self.export_edges()

        # Print summary
        self.print_summary()

        console.print("\n[bold green]✓ Export completed successfully![/bold green]")


def main():
    """Main entry point."""
    # Paths
    project_root = Path(__file__).parent.parent
    db_path = project_root / ".code-explorer" / "graph.db"
    output_dir = Path(__file__).parent / "output"

    # Validate database exists
    if not db_path.exists():
        console.print(f"[red]✗[/red] Database not found: {db_path}")
        console.print("[yellow]![/yellow] Please run code-explorer to build the graph first.")
        sys.exit(1)

    # Run export
    try:
        with GraphExporter(str(db_path), output_dir) as exporter:
            exporter.run()
    except Exception as e:
        console.print(f"\n[red]✗[/red] Export failed: {e}")
        import traceback
        console.print(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
