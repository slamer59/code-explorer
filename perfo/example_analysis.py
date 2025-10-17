#!/usr/bin/env python3
"""
Example analysis script using exported Parquet files.

This demonstrates various analyses you can perform on the exported graph data
using pandas, without needing to query KuzuDB directly.
"""

from pathlib import Path
import pandas as pd
from rich.console import Console
from rich.table import Table

console = Console()

# Paths
OUTPUT_DIR = Path(__file__).parent / "output"
NODES_DIR = OUTPUT_DIR / "nodes"
EDGES_DIR = OUTPUT_DIR / "edges"


def load_data():
    """Load the exported Parquet files."""
    data = {}

    # Load nodes
    console.print("[cyan]Loading node data...[/cyan]")
    for node_file in NODES_DIR.glob("*.parquet"):
        node_type = node_file.stem
        data[node_type] = pd.read_parquet(node_file)
        console.print(f"  Loaded {node_type}: {len(data[node_type]):,} rows")

    # Load edges
    console.print("\n[cyan]Loading edge data...[/cyan]")
    for edge_file in EDGES_DIR.glob("*.parquet"):
        edge_type = edge_file.stem
        data[edge_type] = pd.read_parquet(edge_file)
        console.print(f"  Loaded {edge_type}: {len(data[edge_type]):,} rows")

    return data


def analyze_most_called_functions(data):
    """Find the most frequently called functions."""
    console.print("\n[bold cyan]Most Called Functions[/bold cyan]")

    if "calls" not in data or "functions" not in data:
        console.print("[yellow]Missing data for this analysis[/yellow]")
        return

    # Count calls per function
    calls = data["calls"]
    functions = data["functions"]

    call_counts = (
        calls.groupby("dst_id")
        .size()
        .reset_index(name="call_count")
        .sort_values("call_count", ascending=False)
        .head(10)
    )

    # Join with function names
    call_counts = call_counts.merge(
        functions[["n.id", "n.name", "n.file"]],
        left_on="dst_id",
        right_on="n.id",
        how="left"
    )

    # Display results
    table = Table(title="Top 10 Most Called Functions", show_header=True)
    table.add_column("Function", style="cyan")
    table.add_column("File", style="dim")
    table.add_column("Times Called", justify="right", style="green")

    for _, row in call_counts.iterrows():
        func_name = row["n.name"]
        file_path = Path(row["n.file"]).name if pd.notna(row["n.file"]) else "?"
        count = row["call_count"]
        table.add_row(func_name, file_path, f"{count:,}")

    console.print(table)


def analyze_class_hierarchy(data):
    """Analyze class inheritance depth."""
    console.print("\n[bold cyan]Class Inheritance Analysis[/bold cyan]")

    if "inherits" not in data or "classs" not in data:
        console.print("[yellow]Missing data for this analysis[/yellow]")
        return

    classes = data["classs"]
    inherits = data["inherits"]

    # Count inheritance relationships
    inheritance_count = (
        inherits.groupby("src_id")
        .size()
        .reset_index(name="base_count")
        .sort_values("base_count", ascending=False)
        .head(10)
    )

    # Join with class names
    inheritance_count = inheritance_count.merge(
        classes[["n.id", "n.name", "n.file"]],
        left_on="src_id",
        right_on="n.id",
        how="left"
    )

    # Display results
    table = Table(title="Classes with Most Base Classes", show_header=True)
    table.add_column("Class", style="cyan")
    table.add_column("File", style="dim")
    table.add_column("Base Classes", justify="right", style="green")

    for _, row in inheritance_count.iterrows():
        class_name = row["n.name"]
        file_path = Path(row["n.file"]).name if pd.notna(row["n.file"]) else "?"
        count = row["base_count"]
        table.add_row(class_name, file_path, f"{count:,}")

    console.print(table)

    # Overall stats
    total_classes = len(classes)
    classes_with_bases = len(inheritance_count)
    total_inheritance = len(inherits)

    console.print(f"\nTotal classes: {total_classes:,}")
    console.print(f"Classes with inheritance: {classes_with_bases:,}")
    console.print(f"Total inheritance relationships: {total_inheritance:,}")


def analyze_file_complexity(data):
    """Analyze file complexity by counting entities."""
    console.print("\n[bold cyan]File Complexity Analysis[/bold cyan]")

    if "files" not in data or "functions" not in data:
        console.print("[yellow]Missing data for this analysis[/yellow]")
        return

    files = data["files"]
    functions = data["functions"]
    classes = data.get("classs", pd.DataFrame())
    variables = data.get("variables", pd.DataFrame())

    # Count entities per file
    func_counts = functions.groupby("n.file").size().rename("functions")
    class_counts = classes.groupby("n.file").size().rename("classes") if not classes.empty else pd.Series(dtype=int)
    var_counts = variables.groupby("n.file").size().rename("variables") if not variables.empty else pd.Series(dtype=int)

    # Combine counts
    complexity = pd.concat([func_counts, class_counts, var_counts], axis=1).fillna(0)
    complexity["total_entities"] = complexity.sum(axis=1)
    complexity = complexity.sort_values("total_entities", ascending=False).head(10)

    # Display results
    table = Table(title="Top 10 Most Complex Files", show_header=True)
    table.add_column("File", style="cyan")
    table.add_column("Functions", justify="right", style="yellow")
    table.add_column("Classes", justify="right", style="magenta")
    table.add_column("Variables", justify="right", style="blue")
    table.add_column("Total", justify="right", style="bold green")

    for file_path, row in complexity.iterrows():
        file_name = Path(file_path).name
        table.add_row(
            file_name,
            f"{int(row['functions']):,}",
            f"{int(row['classes']):,}",
            f"{int(row['variables']):,}",
            f"{int(row['total_entities']):,}"
        )

    console.print(table)


def analyze_imports(data):
    """Analyze import patterns."""
    console.print("\n[bold cyan]Import Analysis[/bold cyan]")

    if "imports" not in data:
        console.print("[yellow]Missing data for this analysis[/yellow]")
        return

    imports = data["imports"]

    # Most common imports
    import_counts = (
        imports.groupby("n.imported_name")
        .size()
        .reset_index(name="import_count")
        .sort_values("import_count", ascending=False)
        .head(15)
    )

    # Display results
    table = Table(title="Top 15 Most Imported Modules", show_header=True)
    table.add_column("Module", style="cyan")
    table.add_column("Import Count", justify="right", style="green")

    for _, row in import_counts.iterrows():
        table.add_row(row["n.imported_name"], f"{row['import_count']:,}")

    console.print(table)

    # Import types
    import_types = imports["n.import_type"].value_counts()
    console.print("\n[bold]Import Types:[/bold]")
    for import_type, count in import_types.items():
        console.print(f"  {import_type}: {count:,}")


def main():
    """Run all analyses."""
    console.print("[bold cyan]Graph Data Analysis Examples[/bold cyan]\n")

    # Check if data exists
    if not NODES_DIR.exists() or not EDGES_DIR.exists():
        console.print("[red]Error:[/red] Output directory not found.")
        console.print("Please run [cyan]python perfo/export_graph.py[/cyan] first.")
        return

    # Load data
    data = load_data()

    # Run analyses
    analyze_most_called_functions(data)
    analyze_class_hierarchy(data)
    analyze_file_complexity(data)
    analyze_imports(data)

    console.print("\n[green]Analysis complete![/green]")


if __name__ == "__main__":
    main()
