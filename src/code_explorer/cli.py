#!/usr/bin/env python3
"""
Command-line interface for Code Explorer.

Provides commands for analyzing Python codebases and tracking dependencies.
"""

import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
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
@click.option(
    "--no-source",
    is_flag=True,
    help="Don't store function/class source code in database (saves space)",
)
@click.option(
    "--source-lines",
    type=int,
    default=None,
    help="Store only first N lines of source code (preview mode)",
)
@click.option(
    "--verbose-progress",
    is_flag=True,
    help="Show detailed nested progress bars for each file being analyzed",
)
def analyze(
    path: str,
    exclude: tuple[str, ...],
    workers: int,
    db_path: Optional[str],
    refresh: bool,
    no_source: bool,
    source_lines: Optional[int],
    verbose_progress: bool,
) -> None:
    """Analyze Python codebase and build dependency graph.

    Scans all Python files in the specified directory, extracts functions,
    variables, and their relationships, and stores them in a graph database
    for fast querying.

    PATH: Directory containing Python code to analyze

    Source code storage options:
        --no-source: Don't store source code (saves space)
        --source-lines N: Store only first N lines (preview mode)

    Examples:
        code-explorer analyze ./src
        code-explorer analyze /path/to/project --exclude tests --exclude migrations
        code-explorer analyze ./src --no-source
        code-explorer analyze ./src --source-lines 10
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

    target_path = Path(path).resolve()

    if db_path is None:
        db_path = Path.cwd() / ".code-explorer" / "graph.db"
    else:
        db_path = Path(db_path)

    console.print(f"[cyan]Analyzing codebase at:[/cyan] {target_path}")
    console.print(f"[cyan]Database location:[/cyan] {db_path}")

    if exclude:
        console.print(f"[cyan]Excluding patterns:[/cyan] {', '.join(exclude)}")

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

    # Helper function to prepare source code based on flags
    def prepare_source(source_code: Optional[str]) -> Optional[str]:
        """Process source code according to storage flags."""
        if no_source:
            return None
        if source_lines and source_code:
            lines = source_code.split('\n')
            return '\n'.join(lines[:source_lines])
        return source_code

    # Analyze directory
    try:
        results = analyzer.analyze_directory(
            target_path,
            parallel=(workers > 1),
            exclude_patterns=list(exclude) if exclude else None,
            verbose_progress=verbose_progress
        )

        # Populate graph with results using BATCH operations
        console.print("\n[cyan]Building dependency graph...[/cyan]")

        files_processed = len(results)
        files_skipped = 0

        # BATCH INSERT: All nodes at once (MUCH faster than one-by-one!)
        console.print("[cyan]Batch inserting nodes...[/cyan]")
        graph.batch_add_all_from_results(results)

        # BATCH INSERT: All edges at once
        console.print("[cyan]Batch inserting edges...[/cyan]")
        graph.batch_add_all_edges_from_results(results)

        # Function calls still need special handling (cross-file references)
        console.print("[cyan]Processing function calls...[/cyan]")
        call_count = 0
        for result in results:
            for call in result.function_calls:
                # Try to find the called function in the graph
                caller_file = result.file_path
                caller_func = call.caller_function
                called_name = call.called_name
                call_line = call.call_line

                # Find caller function start_line
                caller_start_line = None
                for func in result.functions:
                    if func.name == caller_func:
                        caller_start_line = func.start_line
                        break

                if caller_start_line is None:
                    continue  # Skip if caller function not found

                # Find matching callee function (simple name matching)
                for func_result in results:
                    for f in func_result.functions:
                        if f.name == called_name:
                            graph.add_call(
                                caller_file=caller_file,
                                caller_function=caller_func,
                                caller_start_line=caller_start_line,
                                callee_file=f.file,
                                callee_function=f.name,
                                callee_start_line=f.start_line,
                                call_line=call_line
                            )
                            call_count += 1
                            break

        console.print(f"[green]Added {call_count} function call edges[/green]")

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

    except Exception as e:
        console.print(f"[red]Error during analysis:[/red] {e}")
        import traceback
        console.print(f"[dim]{traceback.format_exc()}[/dim]")
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
    console.print(
        f"[cyan]Analyzing impact of:[/cyan] {file_name}::{function_name}"
    )

    direction = "downstream" if downstream else "upstream"
    console.print(f"[cyan]Direction:[/cyan] {direction.title()}")
    console.print(f"[cyan]Max depth:[/cyan] {max_depth}")

    try:
        results = analyzer.analyze_function_impact(
            file=file_name,
            function=function_name,
            direction=direction,
            max_depth=max_depth
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
            table.add_row("Total imports (detailed)", str(stats_data.get("total_imports", 0)))
            table.add_row("Total decorators", str(stats_data.get("total_decorators", 0)))
            table.add_row("Total attributes", str(stats_data.get("total_attributes", 0)))
            table.add_row("Total exceptions", str(stats_data.get("total_exceptions", 0)))
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
                highlight_impact=True
            )
        else:
            # Generate module diagram
            diagram = visualizer.generate_module_graph(
                file=target,
                include_imports=True
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
