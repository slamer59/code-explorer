"""
Benchmark for current batch loading performance.

Tests the existing batch operations from batch_operations.py
to establish baseline performance metrics.
"""

import gc
import json
from pathlib import Path
from datetime import datetime

import pandas as pd
import psutil
from codetiming import Timer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from code_explorer.graph.graph import DependencyGraph
from code_explorer.analyzer.models import (
    FileAnalysis,
    FunctionInfo,
    ClassInfo,
    VariableInfo,
    ImportDetailedInfo,
    DecoratorInfo,
    AttributeInfo,
    ExceptionInfo,
)


console = Console()


def get_memory_mb() -> float:
    """Get current process memory usage in MB."""
    process = psutil.Process()
    return process.memory_info().rss / 1024 / 1024


def load_parquet_data(data_dir: Path) -> dict:
    """Load all Parquet files from data directory.

    Args:
        data_dir: Path to directory containing nodes/ and edges/ subdirectories

    Returns:
        Dictionary with 'nodes' and 'edges' dataframes
    """
    nodes_dir = data_dir / "nodes"
    edges_dir = data_dir / "edges"

    data = {
        "nodes": {
            "files": pd.read_parquet(nodes_dir / "files.parquet"),
            "functions": pd.read_parquet(nodes_dir / "functions.parquet"),
            "classes": pd.read_parquet(nodes_dir / "classes.parquet"),
            "variables": pd.read_parquet(nodes_dir / "variables.parquet"),
            "imports": pd.read_parquet(nodes_dir / "imports.parquet"),
            "decorators": pd.read_parquet(nodes_dir / "decorators.parquet"),
            "attributes": pd.read_parquet(nodes_dir / "attributes.parquet"),
            "exceptions": pd.read_parquet(nodes_dir / "exceptions.parquet"),
        },
        "edges": {
            "contains_function": pd.read_parquet(edges_dir / "contains_function.parquet"),
            "contains_class": pd.read_parquet(edges_dir / "contains_class.parquet"),
            "contains_variable": pd.read_parquet(edges_dir / "contains_variable.parquet"),
            "method_of": pd.read_parquet(edges_dir / "method_of.parquet"),
            "inherits": pd.read_parquet(edges_dir / "inherits.parquet"),
            "has_import": pd.read_parquet(edges_dir / "has_import.parquet"),
            "has_attribute": pd.read_parquet(edges_dir / "has_attribute.parquet"),
        }
    }

    return data


def convert_to_file_analysis(data: dict) -> list[FileAnalysis]:
    """Convert Parquet data to FileAnalysis objects.

    Args:
        data: Dictionary with nodes and edges dataframes

    Returns:
        List of FileAnalysis objects, one per file
    """
    results = []

    # Get unique files
    files_df = data["nodes"]["files"]
    functions_df = data["nodes"]["functions"]
    classes_df = data["nodes"]["classes"]
    variables_df = data["nodes"]["variables"]
    imports_df = data["nodes"]["imports"]
    decorators_df = data["nodes"]["decorators"]
    attributes_df = data["nodes"]["attributes"]
    exceptions_df = data["nodes"]["exceptions"]

    # Group by file
    for _, file_row in files_df.iterrows():
        file_path = file_row["path"]

        # Get functions for this file
        file_functions = functions_df[functions_df["file"] == file_path]
        functions = [
            FunctionInfo(
                name=row["name"],
                file=row["file"],
                start_line=row["start_line"],
                end_line=row["end_line"],
                is_public=row["is_public"],
                source_code=row.get("source_code", ""),
                parent_class=None,  # Will be populated from METHOD_OF edges
            )
            for _, row in file_functions.iterrows()
        ]

        # Get classes for this file
        file_classes = classes_df[classes_df["file"] == file_path]
        classes = []
        for _, row in file_classes.iterrows():
            # Parse bases - can be empty string, JSON string, or single value
            bases_str = row["bases"]
            if not bases_str:
                bases = []
            elif bases_str.startswith('['):
                # JSON array
                bases = json.loads(bases_str)
            else:
                # Single base class name
                bases = [bases_str]

            classes.append(ClassInfo(
                name=row["name"],
                file=row["file"],
                start_line=row["start_line"],
                end_line=row["end_line"],
                bases=bases,
                methods=[],  # Not used in batch operations
                is_public=row["is_public"],
                source_code=row.get("source_code", ""),
            ))

        # Get variables for this file (module-level only)
        file_variables = variables_df[variables_df["file"] == file_path]
        variables = [
            VariableInfo(
                name=row["name"],
                file=row["file"],
                definition_line=row["definition_line"],
                scope=row["scope"],
            )
            for _, row in file_variables.iterrows()
        ]

        # Get imports for this file
        file_imports = imports_df[imports_df["file"] == file_path]
        imports_detailed = [
            ImportDetailedInfo(
                imported_name=row["imported_name"],
                import_type=row["import_type"],
                alias=row["alias"] if row["alias"] else None,
                line_number=row["line_number"],
                is_relative=row["is_relative"],
                module=None,  # Not stored in node
            )
            for _, row in file_imports.iterrows()
        ]

        # Get decorators for this file
        file_decorators = decorators_df[decorators_df["file"] == file_path]
        decorators = [
            DecoratorInfo(
                name=row["name"],
                file=row["file"],
                line_number=row["line_number"],
                arguments=row["arguments"],
                target_name="",  # Not needed for batch operations
                target_type="",  # Not needed for batch operations
            )
            for _, row in file_decorators.iterrows()
        ]

        # Get attributes for this file
        file_attributes = attributes_df[attributes_df["file"] == file_path]
        attributes = [
            AttributeInfo(
                name=row["name"],
                class_name=row["class_name"],
                file=row["file"],
                definition_line=row["definition_line"],
                type_hint=row["type_hint"] if row["type_hint"] else None,
                is_class_attribute=row["is_class_attribute"],
            )
            for _, row in file_attributes.iterrows()
        ]

        # Get exceptions for this file
        file_exceptions = exceptions_df[exceptions_df["file"] == file_path]
        exceptions = [
            ExceptionInfo(
                name=row["name"],
                file=row["file"],
                line_number=row["line_number"],
                context="raise",  # Not stored in node
                function_name=None,  # Not stored in node
            )
            for _, row in file_exceptions.iterrows()
        ]

        # Create FileAnalysis object
        file_analysis = FileAnalysis(
            file_path=file_path,
            content_hash=file_row.get("content_hash", ""),
            functions=functions,
            classes=classes,
            variables=variables,
            imports_detailed=imports_detailed,
            decorators=decorators,
            attributes=attributes,
            exceptions=exceptions,
        )

        results.append(file_analysis)

    return results


def main():
    """Run benchmark for current batch loading implementation."""

    # Configuration
    data_dir = Path(__file__).parent / "data" / "output"
    db_path = Path(__file__).parent / "benchmark_batch.db"

    # Clean up existing database (handle both file and directory)
    if db_path.exists():
        import shutil
        if db_path.is_dir():
            shutil.rmtree(db_path)
        else:
            db_path.unlink()
        console.print(f"[dim]Removed existing database at {db_path}[/dim]")

    # Display header
    console.print()
    console.print(Panel.fit(
        "[bold cyan]Current Batch Loading Benchmark[/bold cyan]",
        border_style="cyan"
    ))
    console.print()

    # Step 1: Load Parquet files
    console.print("[yellow]Step 1:[/yellow] Loading Parquet files...")
    mem_before_load = get_memory_mb()

    with Timer(name="load_parquet", text="✓ Loaded in {:.2f}s", logger=console.print):
        data = load_parquet_data(data_dir)

    mem_after_load = get_memory_mb()
    mem_delta_load = mem_after_load - mem_before_load

    # Count total rows
    total_node_rows = sum(len(df) for df in data["nodes"].values())
    total_edge_rows = sum(len(df) for df in data["edges"].values())
    total_rows = total_node_rows + total_edge_rows

    console.print(f"  [dim]Memory: {mem_before_load:.1f}MB → {mem_after_load:.1f}MB (Δ{mem_delta_load:+.1f}MB)[/dim]")
    console.print(f"  [dim]Rows: {total_node_rows:,} nodes + {total_edge_rows:,} edges = {total_rows:,} total[/dim]")
    console.print()

    # Step 2: Convert to FileAnalysis objects
    console.print("[yellow]Step 2:[/yellow] Converting to FileAnalysis objects...")
    mem_before_convert = get_memory_mb()

    with Timer(name="convert", text="✓ Converted in {:.2f}s", logger=console.print):
        results = convert_to_file_analysis(data)

    mem_after_convert = get_memory_mb()
    mem_delta_convert = mem_after_convert - mem_before_convert

    console.print(f"  [dim]Memory: {mem_before_convert:.1f}MB → {mem_after_convert:.1f}MB (Δ{mem_delta_convert:+.1f}MB)[/dim]")
    console.print(f"  [dim]Files: {len(results):,}[/dim]")
    console.print()

    # Save counts before freeing data
    node_counts = {name: len(df) for name, df in data["nodes"].items()}
    edge_counts = {name: len(df) for name, df in data["edges"].items()}

    # Free original dataframes
    del data
    gc.collect()
    mem_after_gc = get_memory_mb()
    console.print(f"[dim]After cleanup: {mem_after_gc:.1f}MB[/dim]")
    console.print()

    # Step 3: Create DependencyGraph
    console.print("[yellow]Step 3:[/yellow] Creating DependencyGraph...")
    mem_before_graph = get_memory_mb()

    with Timer(name="create_graph", text="✓ Graph created in {:.2f}s", logger=console.print):
        graph = DependencyGraph(
            db_path=db_path,
            read_only=False,
            project_root=Path.cwd(),
        )

    mem_after_graph = get_memory_mb()
    mem_delta_graph = mem_after_graph - mem_before_graph

    console.print(f"  [dim]Memory: {mem_before_graph:.1f}MB → {mem_after_graph:.1f}MB (Δ{mem_delta_graph:+.1f}MB)[/dim]")
    console.print()

    # Step 4: Batch insert nodes
    console.print("[yellow]Step 4:[/yellow] Batch inserting nodes...")
    mem_before_nodes = get_memory_mb()

    with Timer(name="batch_nodes", text="✓ Nodes loaded in {:.2f}s") as timer_nodes:
        graph.batch_add_all_from_results(results)

    mem_after_nodes = get_memory_mb()
    mem_delta_nodes = mem_after_nodes - mem_before_nodes
    nodes_time = timer_nodes.last

    console.print(f"  [dim]Memory: {mem_before_nodes:.1f}MB → {mem_after_nodes:.1f}MB (Δ{mem_delta_nodes:+.1f}MB)[/dim]")
    console.print()

    # Step 5: Batch insert edges
    console.print("[yellow]Step 5:[/yellow] Batch inserting edges...")
    mem_before_edges = get_memory_mb()

    with Timer(name="batch_edges", text="✓ Edges loaded in {:.2f}s") as timer_edges:
        graph.batch_add_all_edges_from_results(results)

    mem_after_edges = get_memory_mb()
    mem_delta_edges = mem_after_edges - mem_before_edges
    edges_time = timer_edges.last

    console.print(f"  [dim]Memory: {mem_before_edges:.1f}MB → {mem_after_edges:.1f}MB (Δ{mem_delta_edges:+.1f}MB)[/dim]")
    console.print()

    # Calculate total time and throughput
    total_time = nodes_time + edges_time
    rows_per_sec = total_rows / total_time if total_time > 0 else 0

    # Display summary
    console.print()
    console.print(Panel.fit(
        f"[bold green]Total: {total_rows:,} rows in {total_time:.1f}s ({rows_per_sec:,.0f} rows/sec)[/bold green]",
        border_style="green"
    ))
    console.print()

    # Display detailed breakdown table
    table = Table(title="Performance Breakdown", show_header=True, header_style="bold cyan")
    table.add_column("Phase", style="cyan", width=25)
    table.add_column("Time (s)", justify="right", style="yellow")
    table.add_column("Memory Delta", justify="right", style="magenta")
    table.add_column("Peak Memory", justify="right", style="blue")

    table.add_row(
        "Load Parquet files",
        f"{Timer.timers.mean('load_parquet'):.2f}",
        f"{mem_delta_load:+.1f}MB",
        f"{mem_after_load:.1f}MB"
    )
    table.add_row(
        "Convert to FileAnalysis",
        f"{Timer.timers.mean('convert'):.2f}",
        f"{mem_delta_convert:+.1f}MB",
        f"{mem_after_convert:.1f}MB"
    )
    table.add_row(
        "Create DependencyGraph",
        f"{Timer.timers.mean('create_graph'):.2f}",
        f"{mem_delta_graph:+.1f}MB",
        f"{mem_after_graph:.1f}MB"
    )
    table.add_row(
        "Batch insert nodes",
        f"{nodes_time:.2f}",
        f"{mem_delta_nodes:+.1f}MB",
        f"{mem_after_nodes:.1f}MB"
    )
    table.add_row(
        "Batch insert edges",
        f"{edges_time:.2f}",
        f"{mem_delta_edges:+.1f}MB",
        f"{mem_after_edges:.1f}MB"
    )
    table.add_row(
        "[bold]Total[/bold]",
        f"[bold]{total_time:.2f}[/bold]",
        f"[bold]{mem_after_edges - mem_before_load:+.1f}MB[/bold]",
        f"[bold]{mem_after_edges:.1f}MB[/bold]",
        style="bold"
    )

    console.print(table)
    console.print()

    # Display data statistics
    stats_table = Table(title="Data Statistics", show_header=True, header_style="bold cyan")
    stats_table.add_column("Category", style="cyan", width=20)
    stats_table.add_column("Count", justify="right", style="yellow")

    stats_table.add_row("Files", f"{node_counts['files']:,}")
    stats_table.add_row("Functions", f"{node_counts['functions']:,}")
    stats_table.add_row("Classes", f"{node_counts['classes']:,}")
    stats_table.add_row("Variables", f"{node_counts['variables']:,}")
    stats_table.add_row("Imports", f"{node_counts['imports']:,}")
    stats_table.add_row("Decorators", f"{node_counts['decorators']:,}")
    stats_table.add_row("Attributes", f"{node_counts['attributes']:,}")
    stats_table.add_row("Exceptions", f"{node_counts['exceptions']:,}")
    stats_table.add_row("[bold]Total Nodes[/bold]", f"[bold]{total_node_rows:,}[/bold]", style="bold")
    stats_table.add_row("", "")
    stats_table.add_row("[bold]Total Edges[/bold]", f"[bold]{total_edge_rows:,}[/bold]", style="bold")
    stats_table.add_row("[bold green]Grand Total[/bold green]", f"[bold green]{total_rows:,}[/bold green]", style="bold green")

    console.print(stats_table)
    console.print()

    console.print(f"[dim]Database created at: {db_path.absolute()}[/dim]")


if __name__ == "__main__":
    main()
