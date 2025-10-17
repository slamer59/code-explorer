#!/usr/bin/env python3
"""
Command-line interface for Code Explorer.

Provides commands for analyzing Python codebases and tracking dependencies.
"""

import shutil
import sys
import time
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    track,
)
from rich.table import Table

console = Console()


@click.group()
@click.version_option(version="0.1.0")
def cli() -> None:
    """Code Explorer - Python dependency analysis tool.

    Analyze Python codebases to understand dependencies, track impact of changes,
    and visualize code relationships.

    The tool now tracks granular imports, decorators, class attributes, exceptions,
    and module hierarchy for comprehensive code analysis.

    Examples:
        code-explorer analyze /path/to/code
        code-explorer impact module.py:function_name
        code-explorer trace module.py:42 --variable user_input
        code-explorer stats
        code-explorer visualize module.py --output graph.md

    New capabilities:
        - Import tracking: See what imports a function/class
        - Decorator analysis: Track decorator usage and dependencies
        - Attribute tracking: Find what modifies class attributes
        - Exception analysis: Trace exception propagation
        - Module hierarchy: Understand package structure
    """
    pass


@cli.command()
@click.argument("path", type=click.Path(exists=True, file_okay=False, dir_okay=True))
@click.option(
    "--exclude",
    multiple=True,
    help="Patterns to exclude (can be specified multiple times)",
)
@click.option(
    "--include",
    multiple=True,
    help="Override default exclusions (e.g., --include .venv to analyze virtual environment)",
)
@click.option(
    "--workers",
    type=int,
    default=4,
    help="Number of parallel workers (default: 4)",
)
@click.option(
    "--db-path",
    type=click.Path(),
    default=None,
    help="Path to KuzuDB database (default: .code-explorer/graph.db)",
)
@click.option(
    "--refresh",
    is_flag=True,
    help="Force full re-analysis (clears existing database)",
)
def analyze(
    path: str,
    exclude: tuple[str, ...],
    include: tuple[str, ...],
    workers: int,
    db_path: Optional[str],
    refresh: bool,
) -> None:
    """Analyze Python codebase and build dependency graph.

    Scans all Python files in the specified directory, extracts functions,
    variables, and their relationships, and stores them in a graph database
    for fast querying.

    PATH: Directory containing Python code to analyze


    Examples:
        code-explorer analyze ./src
        code-explorer analyze /path/to/project --exclude tests --exclude migrations
    """
    try:
        from .analyzer import CodeAnalyzer
        from .graph import DependencyGraph
    except ImportError as e:
        console.print(
            "[red]Error:[/red] Missing required module. "
            "Please ensure analyzer.py and graph.py are implemented."
        )
        console.print(f"[dim]Details: {e}[/dim]")
        sys.exit(1)

    # Start timing
    start_time = time.time()

    target_path = Path(path).resolve()

    if db_path is None:
        db_path = Path.cwd() / ".code-explorer" / "graph.db"
    else:
        db_path = Path(db_path)

    console.print(f"[cyan]Analyzing codebase at:[/cyan] {target_path}")
    console.print(f"[cyan]Database location:[/cyan] {db_path}")

    # Build final exclusion list
    # Start with defaults
    default_exclusions = [
        "__pycache__",
        ".pytest_cache",
        "htmlcov",
        "dist",
        "build",
        ".git",
        ".venv",
        "venv",
    ]

    # Apply includes (remove from defaults)
    final_exclusions = [e for e in default_exclusions if e not in include]

    # Add custom excludes
    if exclude:
        final_exclusions.extend(exclude)

    # Display exclusion info
    if include:
        console.print(
            f"[cyan]Including (overriding defaults):[/cyan] {', '.join(include)}"
        )
    if final_exclusions:
        console.print(f"[dim]Excluding:[/dim] {', '.join(final_exclusions)}")

    # Initialize graph
    try:
        graph = DependencyGraph(db_path=db_path)

        if refresh:
            console.print("[yellow]Clearing existing database...[/yellow]")
            graph.clear_all()
            console.print("[green]Database cleared. Starting fresh analysis.[/green]")
    except Exception as e:
        console.print(f"[red]Error:[/red] Failed to initialize database: {e}")
        sys.exit(1)

    # Initialize analyzer
    analyzer = CodeAnalyzer()

    # Analyze directory
    try:
        step_start = time.time()
        results = analyzer.analyze_directory(
            target_path,
            parallel=(workers > 1),
            exclude_patterns=final_exclusions,  # Pass list directly (can be empty)
        )
        analysis_time = time.time() - step_start
        console.print(f"[dim]⏱  File analysis: {analysis_time:.2f}s[/dim]")

        # Populate graph with results using Parquet export + COPY FROM (23x faster!)
        console.print("\n[cyan]Building dependency graph...[/cyan]")

        files_processed = len(results)
        files_skipped = 0

        # Set up parquet directory
        parquet_dir = Path(".code-explorer") / "parquet"
        parquet_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Resolve function calls BEFORE export using CallResolver
            total_calls = sum(len(r.function_calls) for r in results)
            console.print(f"[cyan]Resolving {total_calls:,} function calls...[/cyan]")

            from code_explorer.analyzer.call_resolver import CallResolver

            step_start = time.time()
            resolver = CallResolver(results)
            all_matched_calls = resolver.resolve_all_calls()
            resolve_time = time.time() - step_start

            console.print(
                f"[green]✓[/green] Resolved {len(all_matched_calls):,} calls "
                f"({total_calls - len(all_matched_calls):,} unresolved) "
                f"in {resolve_time:.2f}s"
            )

            # Export everything including CALLS
            console.print("[cyan]Exporting to Parquet...[/cyan]")
            step_start = time.time()
            graph._export_results_to_parquet(
                results, parquet_dir, resolved_calls=all_matched_calls
            )
            export_time = time.time() - step_start
            console.print(f"[dim]⏱  Parquet export: {export_time:.2f}s[/dim]")

            # Load everything ONCE (including CALLS via COPY FROM)
            console.print("[cyan]Loading graph data using COPY FROM...[/cyan]")
            step_start = time.time()
            stats = graph.load_from_parquet(parquet_dir)
            load_time = time.time() - step_start

            # Extract node and edge times for backward compatibility
            nodes_time = sum(time for time, _ in stats.get("node_times", {}).values())
            edges_time = sum(time for time, _ in stats.get("edge_times", {}).values())

            console.print(
                f"[green]✓[/green] Loaded {stats['total_nodes']:,} nodes and "
                f"{stats['total_edges']:,} edges in {stats['total_time']:.2f}s "
                f"({(stats['total_nodes'] + stats['total_edges']) / stats['total_time']:.0f} rows/sec)"
            )

            # Clean up temporary Parquet files
            # shutil.rmtree(parquet_dir)

            # CALLS are now loaded via COPY FROM, no separate insert needed
            calls_insert_time = 0  # Included in load_time

        except Exception as e:
            console.print(f"[red]Error during graph loading: {e}[/red]")
            # Keep Parquet files for debugging
            console.print(f"[yellow]Parquet files preserved at: {parquet_dir}[/yellow]")
            raise

        # Compute statistics
        error_files = sum(1 for r in results if r.errors)
        total_classes = sum(len(r.classes) for r in results)
        total_functions = sum(len(r.functions) for r in results)
        total_variables = sum(len(r.variables) for r in results)
        total_imports_detailed = sum(len(r.imports_detailed) for r in results)
        total_decorators = sum(len(r.decorators) for r in results)
        total_attributes = sum(len(r.attributes) for r in results)
        total_exceptions = sum(len(r.exceptions) for r in results)
        files_with_modules = sum(1 for r in results if r.module_info is not None)

        # Print summary
        console.print("\n[bold green]Analysis complete![/bold green]")

        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Metric", style="cyan")
        table.add_column("Count", justify="right", style="green")

        table.add_row("Total files analyzed", str(len(results)))
        table.add_row("Files processed", str(files_processed))
        if files_skipped > 0:
            table.add_row("Files skipped (unchanged)", str(files_skipped))
        if error_files > 0:
            table.add_row("Files with errors", str(error_files))
        table.add_row("Total classes", str(total_classes))
        table.add_row("Total functions", str(total_functions))
        table.add_row("Total variables", str(total_variables))
        table.add_row("Total imports (detailed)", str(total_imports_detailed))
        table.add_row("Total decorators", str(total_decorators))
        table.add_row("Total attributes", str(total_attributes))
        table.add_row("Total exceptions", str(total_exceptions))
        table.add_row("Modules detected", str(files_with_modules))

        console.print(table)
        console.print(f"\n[green]Graph persisted to:[/green] {db_path}")
        if files_skipped > 0:
            console.print(f"[dim]Use --refresh to force re-analysis of all files[/dim]")

        # Display timing information
        elapsed_time = time.time() - start_time
        minutes, seconds = divmod(elapsed_time, 60)

        if minutes > 0:
            time_str = f"{int(minutes)}m {seconds:.2f}s"
        else:
            time_str = f"{seconds:.2f}s"

        # Create timing breakdown
        timing_text = f"[bold green]Total analysis time:[/bold green] [yellow]{time_str}[/yellow]\n\n"
        timing_text += "[bold cyan]Breakdown:[/bold cyan]\n"
        timing_text += f"  • File analysis: [yellow]{analysis_time:.2f}s[/yellow]\n"
        timing_text += f"  • Parquet export: [yellow]{export_time:.2f}s[/yellow]\n"
        timing_text += (
            f"  • Graph load (COPY FROM): [yellow]{load_time:.2f}s[/yellow]\n"
        )
        timing_text += f"    - Node insertion: [yellow]{nodes_time:.2f}s[/yellow]\n"
        timing_text += f"    - Edge insertion: [yellow]{edges_time:.2f}s[/yellow]\n"
        timing_text += f"  • Call resolution: [yellow]{resolve_time:.2f}s[/yellow]\n"
        timing_text += (
            f"  • Call edge insertion: [yellow]{calls_insert_time:.2f}s[/yellow]"
        )

        timing_panel = Panel(
            timing_text,
            border_style="green",
            padding=(0, 2),
            title="[bold white]⏱  Performance Metrics[/bold white]",
        )
        console.print("\n")
        console.print(timing_panel)

    except Exception as e:
        from rich import markup

        console.print(f"[red]Error during analysis:[/red] {markup.escape(str(e))}")
        import traceback

        console.print(f"[dim]{markup.escape(traceback.format_exc())}[/dim]")
        sys.exit(1)


@cli.command()
@click.argument("target")
@click.option(
    "--downstream",
    is_flag=True,
    help="Show downstream impact (what this function calls) instead of upstream",
)
@click.option(
    "--max-depth",
    type=int,
    default=5,
    help="Maximum depth for transitive analysis (default: 5)",
)
@click.option(
    "--db-path",
    type=click.Path(),
    default=None,
    help="Path to KuzuDB database (default: .code-explorer/graph.db)",
)
def impact(
    target: str,
    downstream: bool,
    max_depth: int,
    db_path: Optional[str],
) -> None:
    """Find impact of changing a function.

    Shows which functions will be affected if you change the specified function.
    By default, shows upstream impact (who calls this function). Use --downstream
    to see what this function calls.

    TARGET: Function to analyze in format "file.py:function_name"

    Examples:
        code-explorer impact module.py:process_data
        code-explorer impact utils.py:calculate --downstream
        code-explorer impact main.py:main --max-depth 3
    """
    try:
        from .graph import DependencyGraph
        from .impact import ImpactAnalyzer
    except ImportError as e:
        console.print(
            "[red]Error:[/red] Missing required module. "
            "Please ensure graph.py and impact.py are implemented."
        )
        console.print(f"[dim]Details: {e}[/dim]")
        sys.exit(1)

    # Parse target
    if ":" not in target:
        console.print(
            "[red]Error:[/red] Invalid target format. Expected 'file:function'"
        )
        console.print("[dim]Example: module.py:process_data[/dim]")
        sys.exit(1)

    file_name, function_name = target.split(":", 1)

    # Initialize graph
    if db_path is None:
        db_path = Path.cwd() / ".code-explorer" / "graph.db"
    else:
        db_path = Path(db_path)

    if not db_path.exists():
        console.print(
            "[red]Error:[/red] Database not found. Run 'analyze' command first."
        )
        console.print(f"[dim]Expected location: {db_path}[/dim]")
        sys.exit(1)

    try:
        graph = DependencyGraph(db_path=db_path)
        analyzer = ImpactAnalyzer(graph)
    except Exception as e:
        console.print(f"[red]Error:[/red] Failed to initialize graph: {e}")
        sys.exit(1)

    # Find function
    console.print(f"[cyan]Analyzing impact of:[/cyan] {file_name}::{function_name}")

    direction = "downstream" if downstream else "upstream"
    console.print(f"[cyan]Direction:[/cyan] {direction.title()}")
    console.print(f"[cyan]Max depth:[/cyan] {max_depth}")

    try:
        results = analyzer.analyze_function_impact(
            file=file_name,
            function=function_name,
            direction=direction,
            max_depth=max_depth,
        )

        if not results:
            console.print("[yellow]No impact found.[/yellow]")
            return

        # Display results using the format_as_table method
        table = analyzer.format_as_table(results)
        console.print(table)
        console.print(f"\n[green]Found {len(results)} impacted functions[/green]")

    except Exception as e:
        console.print(f"[red]Error during impact analysis:[/red] {e}")
        import traceback

        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        sys.exit(1)


@cli.command()
@click.argument("target")
@click.option(
    "--variable",
    required=True,
    help="Variable name to trace",
)
@click.option(
    "--db-path",
    type=click.Path(),
    default=None,
    help="Path to KuzuDB database (default: .code-explorer/graph.db)",
)
def trace(
    target: str,
    variable: str,
    db_path: Optional[str],
) -> None:
    """Trace variable data flow through the codebase.

    Shows where a variable is defined and how it flows through the code,
    helping track bugs and understand data dependencies.

    TARGET: Location in format "file.py:line_number"

    Examples:
        code-explorer trace module.py:42 --variable user_input
        code-explorer trace utils.py:15 --variable result
    """
    try:
        from .graph import DependencyGraph
        from .impact import ImpactAnalyzer
    except ImportError as e:
        console.print(
            "[red]Error:[/red] Missing required module. "
            "Please ensure graph.py and impact.py are implemented."
        )
        console.print(f"[dim]Details: {e}[/dim]")
        sys.exit(1)

    # Parse target
    if ":" not in target:
        console.print(
            "[red]Error:[/red] Invalid target format. Expected 'file:line_number'"
        )
        console.print("[dim]Example: module.py:42[/dim]")
        sys.exit(1)

    file_name, line_str = target.split(":", 1)

    try:
        line_number = int(line_str)
    except ValueError:
        console.print(f"[red]Error:[/red] Invalid line number: {line_str}")
        sys.exit(1)

    # Initialize graph
    if db_path is None:
        db_path = Path.cwd() / ".code-explorer" / "graph.db"
    else:
        db_path = Path(db_path)

    if not db_path.exists():
        console.print(
            "[red]Error:[/red] Database not found. Run 'analyze' command first."
        )
        console.print(f"[dim]Expected location: {db_path}[/dim]")
        sys.exit(1)

    try:
        graph = DependencyGraph(db_path=db_path)
        analyzer = ImpactAnalyzer(graph)
    except Exception as e:
        console.print(f"[red]Error:[/red] Failed to initialize graph: {e}")
        sys.exit(1)

    console.print(
        f"[cyan]Tracing variable:[/cyan] {variable} at {file_name}:{line_number}"
    )

    try:
        results = analyzer.analyze_variable_impact(file_name, variable, line_number)

        if not results:
            console.print("[yellow]No data flow found.[/yellow]")
            return

        # Display results in table
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("File", style="cyan")
        table.add_column("Function", style="green")
        table.add_column("Line", justify="right", style="yellow")

        for file, function, line in results:
            table.add_row(
                file,
                function,
                str(line),
            )

        console.print(table)
        console.print(f"\n[green]Found {len(results)} usages[/green]")

    except Exception as e:
        console.print(f"[red]Error during trace:[/red] {e}")
        import traceback

        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        sys.exit(1)


@cli.command()
@click.option(
    "--db-path",
    type=click.Path(),
    default=None,
    help="Path to KuzuDB database (default: .code-explorer/graph.db)",
)
@click.option(
    "--top",
    type=int,
    default=10,
    help="Number of top functions to show (default: 10)",
)
def stats(db_path: Optional[str], top: int) -> None:
    """Show statistics about the analyzed codebase.

    Displays summary statistics including total files, functions, variables,
    and the most-called functions in the codebase.

    Examples:
        code-explorer stats
        code-explorer stats --top 20
    """
    try:
        from .graph import DependencyGraph
    except ImportError as e:
        console.print(
            "[red]Error:[/red] Missing required module. "
            "Please ensure graph.py is implemented."
        )
        console.print(f"[dim]Details: {e}[/dim]")
        sys.exit(1)

    # Initialize graph
    if db_path is None:
        db_path = Path.cwd() / ".code-explorer" / "graph.db"
    else:
        db_path = Path(db_path)

    if not db_path.exists():
        console.print(
            "[red]Error:[/red] Database not found. Run 'analyze' command first."
        )
        console.print(f"[dim]Expected location: {db_path}[/dim]")
        sys.exit(1)

    try:
        graph = DependencyGraph(db_path=db_path)
    except Exception as e:
        console.print(f"[red]Error:[/red] Failed to initialize graph: {e}")
        sys.exit(1)

    console.print("[bold cyan]Codebase Statistics[/bold cyan]\n")

    try:
        stats_data = graph.get_statistics()

        # Overall statistics
        table = Table(show_header=True, header_style="bold cyan", title="Overview")
        table.add_column("Metric", style="cyan")
        table.add_column("Count", justify="right", style="green")

        table.add_row("Total files", str(stats_data.get("total_files", 0)))
        table.add_row("Total classes", str(stats_data.get("total_classes", 0)))
        table.add_row("Total functions", str(stats_data.get("total_functions", 0)))
        table.add_row("Total variables", str(stats_data.get("total_variables", 0)))
        table.add_row("Total edges", str(stats_data.get("total_edges", 0)))
        table.add_row("Function calls", str(stats_data.get("function_calls", 0)))

        # Show new node types if schema v2
        if stats_data.get("schema_version") == "v2":
            table.add_row(
                "Total imports (detailed)", str(stats_data.get("total_imports", 0))
            )
            table.add_row(
                "Total decorators", str(stats_data.get("total_decorators", 0))
            )
            table.add_row(
                "Total attributes", str(stats_data.get("total_attributes", 0))
            )
            table.add_row(
                "Total exceptions", str(stats_data.get("total_exceptions", 0))
            )
            table.add_row("Total modules", str(stats_data.get("total_modules", 0)))

        console.print(table)
        console.print()

        # Most-called functions
        most_called = stats_data.get("most_called_functions", [])

        if most_called:
            call_table = Table(
                show_header=True,
                header_style="bold cyan",
                title=f"Top {min(top, len(most_called))} Most-Called Functions",
            )
            call_table.add_column("Rank", justify="right", style="dim")
            call_table.add_column("Function", style="green")
            call_table.add_column("File", style="cyan")
            call_table.add_column("Calls", justify="right", style="yellow")

            for i, func in enumerate(most_called[:top], 1):
                call_table.add_row(
                    str(i),
                    func.get("name", ""),
                    func.get("file", ""),
                    str(func.get("call_count", 0)),
                )

            console.print(call_table)

    except Exception as e:
        console.print(f"[red]Error retrieving statistics:[/red] {e}")
        import traceback

        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        sys.exit(1)


@cli.command()
@click.argument("target")
@click.option(
    "--function",
    help="Specific function to highlight in the graph",
)
@click.option(
    "--output",
    type=click.Path(),
    default="graph.md",
    help="Output file for Mermaid diagram (default: graph.md)",
)
@click.option(
    "--max-depth",
    type=int,
    default=3,
    help="Maximum depth to traverse (default: 3)",
)
@click.option(
    "--db-path",
    type=click.Path(),
    default=None,
    help="Path to KuzuDB database (default: .code-explorer/graph.db)",
)
def visualize(
    target: str,
    function: Optional[str],
    output: str,
    max_depth: int,
    db_path: Optional[str],
) -> None:
    """Generate Mermaid diagram of dependency graph.

    Creates a visual representation of function dependencies in Mermaid format,
    which can be rendered in GitHub, VS Code, and other tools.

    TARGET: File to visualize (e.g., "module.py")

    Examples:
        code-explorer visualize module.py --output graph.md
        code-explorer visualize utils.py --function process_data --max-depth 2
    """
    try:
        from .graph import DependencyGraph
        from .visualizer import MermaidVisualizer
    except ImportError as e:
        console.print(
            "[red]Error:[/red] Missing required module. "
            "Please ensure graph.py and visualizer.py are implemented."
        )
        console.print(f"[dim]Details: {e}[/dim]")
        sys.exit(1)

    # Initialize graph
    if db_path is None:
        db_path = Path.cwd() / ".code-explorer" / "graph.db"
    else:
        db_path = Path(db_path)

    if not db_path.exists():
        console.print(
            "[red]Error:[/red] Database not found. Run 'analyze' command first."
        )
        console.print(f"[dim]Expected location: {db_path}[/dim]")
        sys.exit(1)

    try:
        graph = DependencyGraph(db_path=db_path)
        visualizer = MermaidVisualizer(graph)
    except Exception as e:
        console.print(f"[red]Error:[/red] Failed to initialize graph: {e}")
        sys.exit(1)

    console.print(f"[cyan]Generating diagram for:[/cyan] {target}")

    if function:
        console.print(f"[cyan]Highlighting function:[/cyan] {function}")
        console.print(f"[cyan]Max depth:[/cyan] {max_depth}")
    else:
        console.print(f"[cyan]Module visualization[/cyan]")

    console.print(f"[cyan]Output file:[/cyan] {output}")

    try:
        if function:
            # Generate function-focused diagram
            diagram = visualizer.generate_function_graph(
                focus_function=function,
                file=target,
                max_depth=max_depth,
                highlight_impact=True,
            )
        else:
            # Generate module diagram
            diagram = visualizer.generate_module_graph(
                file=target, include_imports=True
            )

        # Write to file
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        visualizer.save_to_file(diagram, output_path)

        console.print(f"[green]Diagram saved to:[/green] {output_path}")
        console.print(
            "[dim]View in GitHub, VS Code, or any Mermaid-compatible viewer[/dim]"
        )

    except Exception as e:
        console.print(f"[red]Error generating diagram:[/red] {e}")
        import traceback

        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        sys.exit(1)


if __name__ == "__main__":
    cli()
