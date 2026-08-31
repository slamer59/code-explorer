#!/usr/bin/env python3
"""
Command-line interface for Code Explorer.

Provides commands for analyzing Python codebases and tracking dependencies.
"""

import shutil
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

import click
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
    track,
)
from rich.table import Table

from .console_styles import (
    create_summary_table,
    create_data_table,
    format_count,
    StyleGuide,
    create_header_panel,
)
from .settings import settings

console = Console()

# Plain text (no Rich markup) -- printed via click.echo, not console.print,
# so square brackets in example commands/flags render literally instead of
# being parsed as Rich style tags (see cli.py's search command output bug:
# real source code containing "[...]" gets silently mangled by
# console.print's markup=True default).
SKILLS_GUIDE = """\
code-explorer -- usage guide for AI agents

Use this instead of ad-hoc grep + manual file reads when you need to
understand a Python codebase's structure, dependencies, or call graph.

Quick reference:
  code-explorer search "query" PATH             BM25 keyword search + an
                                                 LLM-ready context bundle
                                                 (top hit's source, plus its
                                                 direct callers/callees)
  code-explorer search "query" PATH --fuzzy     same, typo-tolerant
  code-explorer search "query" PATH --semantic  same, conceptual search
                                                 (needs local Ollama +
                                                 nomic-embed-text)
  code-explorer analyze PATH                    Build the dependency graph
                                                 used by impact/trace/stats/
                                                 visualize
  code-explorer impact file.py:function_name    What breaks if this changes
                                                 (needs analyze first)
  code-explorer trace file.py:LINE --variable NAME
                                                 Trace where a variable's
                                                 value comes from/goes
  code-explorer stats                           Repo-wide statistics
  code-explorer visualize file.py               Mermaid dependency diagram

search vs. impact:
  - Only have a description of behavior, not the exact function -> search
  - Already know the exact function, want its dependents -> impact (after
    running analyze)

Gotchas:
  - search builds its own index at PATH/.code-explorer/graph.lattice on
    first run (separate from analyze's graph). There is no incremental
    update yet -- pass --reindex after the code under PATH changes.
  - --semantic requires a local Ollama server with the nomic-embed-text
    model pulled (ollama pull nomic-embed-text). Without it, use plain
    search or --fuzzy instead.
  - impact/trace/stats/visualize need analyze to have been run first;
    re-run analyze --refresh after code changes.
  - From a source checkout, run via:
      uv run --python 3.12 --extra dev code-explorer ...
    (the default Python on some systems has no tree-sitter-languages wheel)

Run `code-explorer <command> --help` for full per-command flags.
"""


def _print_skills_guide(ctx: click.Context, param: click.Parameter, value: bool) -> None:
    if not value or ctx.resilient_parsing:
        return
    click.echo(SKILLS_GUIDE)
    ctx.exit()


@click.group()
@click.version_option(version="0.1.0")
@click.option(
    "--skills",
    is_flag=True,
    is_eager=True,
    expose_value=False,
    callback=_print_skills_guide,
    help="Print a usage guide for AI agents (which command to use when, gotchas), then exit.",
)
def cli() -> None:
    """Code Explorer - Python dependency analysis tool.

    Analyze Python codebases to understand dependencies, track impact of changes,
    and visualize code relationships.

    The tool now tracks granular imports, decorators, class attributes, exceptions,
    and module hierarchy for comprehensive code analysis.

    LLM/agent usage: `search` is the entry point built for this -- give it a
    natural-language or keyword query and it returns a ranked hit list plus a
    ready-to-use context bundle (the top hit's source, plus its direct
    callers/callees) in one call, so an agent doesn't need to grep and then
    separately read files. `impact` answers "what breaks if I change this"
    once you already know the exact function. Run `code-explorer <command>
    --help` for full per-command options -- each command's help text is kept
    in sync with its actual flags, unlike a separate doc would be.

    Examples:
        code-explorer analyze /path/to/code
        code-explorer search "how do we refresh an auth token" /path/to/code
        code-explorer search "resolve_call" /path/to/code --fuzzy
        code-explorer impact module.py:function_name
        code-explorer trace module.py:42 --variable user_input
        code-explorer stats
        code-explorer visualize module.py --output graph.md

    New capabilities:
        - Code search: BM25/fuzzy/semantic search with an LLM-ready context
          bundle for the top hit (see `code-explorer search --help`)
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
    "-w",
    "--workers",
    type=int,
    default=None,
    help="Number of worker threads (default: auto-detect CPU count)",
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
    "--include-source",
    is_flag=True,
    help=(
        "Store each function/class's full source_code as a graph property "
        "(opt-in, off by default -- see "
        "docs/explanation/source-of-truth-and-search-representations.md). "
        "Only affects the generic ingestion path (non-Kuzu backends); the "
        "default Kuzu bulk-loader path always stores source_code."
    ),
)
def analyze(
    path: str,
    exclude: tuple[str, ...],
    include: tuple[str, ...],
    workers: int,
    db_path: Optional[str],
    refresh: bool,
    include_source: bool,
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
    default_exclusions = settings.default_exclude_patterns

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
            parallel=True,
            exclude_patterns=final_exclusions,  # Pass list directly (can be empty)
            max_workers=workers,
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

            from code_explorer.graph.backends.kuzu_backend import KuzuBackend

            if isinstance(graph.backend, KuzuBackend):
                # Export everything including CALLS
                console.print("[cyan]Exporting to Parquet...[/cyan]")
                step_start = time.time()
                graph._export_results_to_parquet(
                    results, parquet_dir, resolved_calls=all_matched_calls
                )
                export_time = time.time() - step_start
                console.print(f"[dim]⏱  Parquet export: {export_time:.2f}s[/dim]")

                # Load everything ONCE (including CALLS and INHERITS via COPY FROM)
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
            else:
                # No Parquet/COPY-FROM bulk loader for this backend (e.g.
                # LatticeDB) -- ingest via the generic NodeRecord/EdgeRecord path.
                console.print(
                    f"[cyan]Ingesting via generic backend interface "
                    f"({type(graph.backend).__name__})...[/cyan]"
                )
                step_start = time.time()
                stats = graph.ingest_results(
                    results, resolved_calls=all_matched_calls, include_source=include_source
                )
                load_time = time.time() - step_start
                nodes_time = 0
                edges_time = 0
                calls_insert_time = 0

                console.print(
                    f"[green]✓[/green] Loaded {stats['total_nodes']:,} nodes and "
                    f"{stats['total_edges']:,} edges in {load_time:.2f}s"
                )

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

        table = create_summary_table("Analysis Results")

        table.add_row("Total files analyzed", format_count(len(results)))
        table.add_row("Files processed", format_count(files_processed))
        if files_skipped > 0:
            table.add_row("Files skipped (unchanged)", format_count(files_skipped))
        if error_files > 0:
            table.add_row("Files with errors", format_count(error_files))
        table.add_row("Total classes", format_count(total_classes))
        table.add_row("Total functions", format_count(total_functions))
        table.add_row("Total variables", format_count(total_variables))
        table.add_row("Total imports (detailed)", format_count(total_imports_detailed))
        table.add_row("Total decorators", format_count(total_decorators))
        table.add_row("Total attributes", format_count(total_attributes))
        table.add_row("Total exceptions", format_count(total_exceptions))
        table.add_row("Modules detected", format_count(files_with_modules))

        console.print(table)
        console.print()

        # Display relationship statistics
        edge_times = stats.get("edge_times", {})
        if edge_times:
            rel_table = create_summary_table("Relationship Statistics")

            total_rel_edges = stats['total_edges']

            for edge_type in [
                "CONTAINS_FUNCTION",
                "CONTAINS_CLASS",
                "CONTAINS_VARIABLE",
                "METHOD_OF",
                "HAS_IMPORT",
                "HAS_ATTRIBUTE",
                "DECORATED_BY",
                "REFERENCES",
                "ACCESSES",
                "HANDLES_EXCEPTION",
                "CALLS",
                "INHERITS",
            ]:
                count = edge_times.get(edge_type, (0, 0))[1]  # Get count from (time, count) tuple
                if total_rel_edges > 0:
                    percentage = (count / total_rel_edges) * 100
                else:
                    percentage = 0

                if count > 0:
                    rel_table.add_row(
                        edge_type,
                        f"{format_count(count)} ({percentage:.1f}%)"
                    )

            console.print(rel_table)

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
        timing_text += f"  • Call resolution: [yellow]{resolve_time:.2f}s[/yellow]"

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

    # Display header
    console.print()
    direction = "downstream" if downstream else "upstream"
    console.print(
        create_header_panel(
            "Impact Analysis: Function Dependency",
            f"Target: {file_name}::{function_name} | Direction: {direction.title()} | Depth: {max_depth}"
        )
    )
    console.print()

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
        console.print(f"\n{StyleGuide.success_icon} Found [yellow]{format_count(len(results))}[/yellow] impacted functions")

    except Exception as e:
        console.print(f"[red]Error during impact analysis:[/red] {e}")
        import traceback

        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        sys.exit(1)


def _looks_like_exact_target(query: str) -> Optional[Tuple[str, str]]:
    """Detect a 'file:function_name' exact-target reference in a search
    query, matching the same shape `impact`/`trace` already accept.

    A minimal "try exact match, fall back to BM25" heuristic (see
    docs/explanation/latticedb-migration.md, Implementation Status ranking
    item #5) -- not a query classifier, just a cheap shape check so
    `code-explorer search file.py:func_name` can skip straight to the exact
    hit instead of running it through BM25 as a phrase.

    Returns (file, function_name) if `query` looks like an exact target
    reference, or None if it looks like an ordinary search phrase.
    """
    if query.count(":") != 1:
        return None
    file_part, func_part = query.split(":", 1)
    if not file_part or not func_part:
        return None
    if file_part != file_part.strip() or func_part != func_part.strip():
        # A space touching the colon (e.g. "a: b" or "topic : detail") reads
        # as a search phrase that happens to contain a colon, not a target.
        return None
    if " " in file_part or " " in func_part:
        return None
    if not func_part.isidentifier():
        return None
    return (file_part, func_part)


@cli.command()
@click.argument("query")
@click.argument("path", type=click.Path(exists=True), default=".")
@click.option(
    "--limit",
    type=int,
    default=5,
    help="Maximum number of search results to show (default: 5)",
)
@click.option(
    "--fuzzy",
    is_flag=True,
    help="Use typo-tolerant fuzzy search instead of BM25 lexical search",
)
@click.option(
    "--semantic",
    is_flag=True,
    help=(
        "Use vector (semantic) search instead of BM25 -- finds conceptually "
        "related code even with no shared keywords. Requires a local Ollama "
        "server running with the nomic-embed-text model pulled."
    ),
)
@click.option(
    "--no-context",
    is_flag=True,
    help="Only show search hits, skip assembling a context bundle for the top hit",
)
@click.option(
    "--reindex",
    is_flag=True,
    help="Force a fresh index instead of reusing an existing one",
)
@click.option(
    "--include-source",
    is_flag=True,
    help=(
        "Store each function/class's full source_code as a graph property "
        "alongside the compact search_text used for BM25/vector/context "
        "(opt-in, off by default -- see "
        "docs/explanation/source-of-truth-and-search-representations.md)."
    ),
)
def search(
    query: str,
    path: str,
    limit: int,
    fuzzy: bool,
    semantic: bool,
    no_context: bool,
    reindex: bool,
    include_source: bool,
) -> None:
    """Search code by keyword and show a ready-to-use context bundle.

    Searches function/class source code with BM25 (or --fuzzy for
    typo-tolerant matching, or --semantic for conceptual vector search),
    then assembles a bounded, LLM-ready context bundle (the top hit plus
    its direct callers/callees, with source attached) -- see
    docs/explanation/latticedb-migration.md, Section 18.

    This is LatticeDB-only for now (Kuzu has no full-text/vector search).
    It builds its own index at PATH/.code-explorer/graph.lattice (or
    graph_vectors.lattice for --semantic, which needs vectors enabled at
    index-creation time -- kept as a separate index so plain/fuzzy search
    doesn't pay for vector storage it doesn't use), separate from
    `analyze`'s Kuzu index. When an index already exists, changed/new/
    deleted files are re-indexed incrementally (content-hash based, Phase
    3) rather than reused as-is; --reindex forces a full rebuild instead.

    QUERY: text to search for, e.g. "refresh token"
    PATH: directory to search (default: current directory)

    Examples:
        code-explorer search "parse file"
        code-explorer search "refesh_token" --fuzzy
        code-explorer search "how do we renew an expired credential" --semantic
        code-explorer search "resolve call" --no-context --limit 10
    """
    from .analyzer.base_analyzer import CodeAnalyzer
    from .context import ContextAssembler
    from .graph import DependencyGraph
    from .graph.backends.lattice_backend import LatticeBackend
    from .hybrid_search import reciprocal_rank_fusion

    target = Path(path).resolve()
    bm25_db_path = target / ".code-explorer" / "graph.lattice"
    vector_db_path = target / ".code-explorer" / "graph_vectors.lattice"
    db_path = vector_db_path if semantic else bm25_db_path

    def _open_and_sync(db_path: Path, enable_vectors: bool, force_reindex: bool) -> DependencyGraph:
        """Open (building/updating as needed) one LatticeDB index. Used
        once for the primary index (BM25 or vector, per --semantic), and a
        second time for the vector index when hybrid retrieval kicks in
        (see the hybrid block below) -- factored out so both call sites
        share the same build/incremental-update/corrupt-recovery logic
        that previously lived inline here for the single-index case.
        """
        needs_index = force_reindex or not db_path.exists()
        if force_reindex:
            for stale in db_path.parent.glob(db_path.name + "*"):
                stale.unlink(missing_ok=True)

        def _build_index(needs_index: bool) -> DependencyGraph:
            backend = LatticeBackend(db_path, enable_vectors=enable_vectors)
            graph = DependencyGraph(db_path=db_path, project_root=target, backend=backend)
            if needs_index:
                console.print(f"[cyan]Indexing[/cyan] {target} for search ...")
                t0 = time.time()
                graph_task = None
                finalize_task = None
                graph_progress = Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    TimeElapsedColumn(),
                    console=console,
                )

                def show_graph_progress(batch_stats: dict) -> None:
                    nonlocal graph_task
                    batches = batch_stats["batches"]
                    tuning = ""
                    if batch_stats.get("adaptive_batching"):
                        selected = batch_stats.get("selected_batch_size", 0)
                        if selected:
                            tuning = f" · batch {selected:,} ops"
                        else:
                            tuning = (
                                f" · tune {batch_stats['adaptive_samples']}/"
                                f"{batch_stats['adaptive_required_samples']} "
                                f"@ {batch_stats['batch_target_size']:,}"
                            )
                    description = (
                        f"  ↳ Graph: {batches:,} "
                        f"{'batch' if batches == 1 else 'batches'} · "
                        f"{batch_stats['total_nodes']:,} nodes · "
                        f"{batch_stats['total_edges']:,} edges · "
                        f"{batch_stats['calls_resolved']:,} calls{tuning}"
                    )
                    if graph_task is None:
                        graph_task = graph_progress.add_task(description, total=None)
                    else:
                        graph_progress.update(graph_task, description=description)

                def show_finalize_progress(finalize_stats: dict) -> None:
                    nonlocal finalize_task
                    if finalize_task is None:
                        for task in list(analysis_progress.tasks):
                            analysis_progress.remove_task(task.id)
                        finalize_task = analysis_progress.add_task(
                            "Resolving pending calls...",
                            total=finalize_stats["total"],
                        )
                    analysis_progress.update(
                        finalize_task,
                        completed=finalize_stats["processed"],
                        description=(
                            "Resolving pending calls "
                            f"({finalize_stats['resolved']:,} resolved · "
                            f"{finalize_stats['unresolved']:,} unresolved)..."
                        ),
                    )

                analysis_progress = Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    MofNCompleteColumn(),
                    TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                    TimeElapsedColumn(),
                    TextColumn("ETA"),
                    TimeRemainingColumn(),
                    console=console,
                )
                with Live(
                    Group(analysis_progress, graph_progress),
                    console=console,
                    refresh_per_second=10,
                ):
                    analyses = CodeAnalyzer().iter_analyze_directory(
                        target,
                        max_workers=settings.analysis_workers,
                        progress=analysis_progress,
                    )
                    stats = graph.ingest_analysis_stream(
                        analyses,
                        batch_size=settings.upsert_batch_size,
                        batch_bytes=settings.ingest_batch_bytes,
                        include_source=include_source,
                        # This branch only runs after creating or deleting db_path.
                        assume_new=True,
                        adaptive=settings.adaptive_ingest_batching,
                        max_batch_size=settings.ingest_batch_max_size,
                        calibration_batches=settings.ingest_calibration_batches,
                        throughput_tolerance=settings.ingest_throughput_tolerance,
                        on_batch_committed=show_graph_progress,
                        on_finalize_progress=show_finalize_progress,
                    )
                    # Include calls resolved during the final durable-stream pass.
                    show_graph_progress(stats)
                    if graph_task is not None:
                        graph_progress.stop_task(graph_task)
                n_functions = stats["functions"]
                n_classes = stats["classes"]
                console.print(
                    f"[green]Done[/green] {stats['files']:,} files in "
                    f"{stats['batches']:,} bounded batches; "
                    f"{stats['calls_resolved']:,} calls resolved, "
                    f"{stats['calls_unresolved']:,} retained unresolved "
                    f"({time.time() - t0:.1f}s)."
                )
                if stats["adaptive_batching"]:
                    console.print(
                        "[dim]Adaptive batching selected "
                        f"{stats['selected_batch_size']:,} operations/batch from "
                        f"{stats['adaptive_samples']:,} measured batches.[/dim]"
                    )
                if enable_vectors:
                    console.print(
                        "[cyan]Generating embeddings via local Ollama[/cyan] "
                        "(batched Ollama HTTP calls, this is the slow "
                        "part) ..."
                    )
                    t1 = time.time()
                    with Progress(
                        SpinnerColumn(),
                        TextColumn("[progress.description]{task.description}"),
                        BarColumn(),
                        MofNCompleteColumn(),
                        TimeElapsedColumn(),
                        console=console,
                    ) as progress:
                        embed_task = progress.add_task(
                            "Embedding", total=n_functions + n_classes
                        )
                        n = graph.backend.build_vector_index(
                            on_progress=lambda: progress.advance(embed_task)
                        )
                    console.print(
                        f"[green]Embedded[/green] {n:,} nodes in {time.time() - t1:.1f}s."
                    )
            return graph

        try:
            graph = _build_index(needs_index)
            if not needs_index:
                # Index already exists and force_reindex wasn't passed: don't
                # silently reuse it as-is (stale data), and don't pay for a
                # full rebuild either -- hash every file, skip unchanged ones,
                # and invalidate+reprocess only what changed (Phase 3).
                t0 = time.time()
                stats = graph.ingest_incremental(target)
                elapsed = time.time() - t0
                if stats["reprocessed"] or stats["deleted"]:
                    console.print(
                        f"[cyan]Updated[/cyan] {stats['reprocessed']} changed file(s), "
                        f"removed {stats['deleted']} deleted file(s), "
                        f"{stats['unchanged']} unchanged ({elapsed:.1f}s)."
                    )
                    if enable_vectors and stats["changed_node_ids"]:
                        # ingest_incremental only touches nodes/edges/BM25 text --
                        # it doesn't call build_vector_index. Deleted/old vectors
                        # are already gone (delete_file removes the node itself),
                        # so the only gap is new/changed nodes having no vector
                        # yet -- re-embed just those (node_ids scoping, see
                        # LatticeBackend.build_vector_index), not the whole repo.
                        t1 = time.time()
                        n = graph.backend.build_vector_index(
                            node_ids=stats["changed_node_ids"]
                        )
                        console.print(
                            f"[cyan]Re-embedded[/cyan] {n} changed node(s) "
                            f"({time.time() - t1:.1f}s)."
                        )
        except Exception as e:
            if needs_index:
                # We were already building a fresh index -- this is a real
                # failure (permissions, disk, Ollama down for --semantic, etc.),
                # not a stale-index problem. Don't retry, just report it.
                console.print(f"[red]Error:[/red] Failed to build search index: {e}")
                sys.exit(1)
            # We tried to reuse an existing index and opening it failed -- most
            # likely leftover state from an interrupted previous run (a killed
            # process, a crash mid-write). It's a disposable derived cache, not
            # source data, so rebuild it automatically instead of surfacing a
            # raw "I/O error" and making the user diagnose it themselves.
            console.print(
                f"[yellow]Existing index at {db_path} looks corrupt or "
                f"incomplete ({e}) -- rebuilding from scratch...[/yellow]"
            )
            for stale in db_path.parent.glob(db_path.name + "*"):
                stale.unlink(missing_ok=True)
            try:
                graph = _build_index(needs_index=True)
            except Exception as e2:
                console.print(f"[red]Error:[/red] Failed to build search index: {e2}")
                sys.exit(1)
        return graph

    graph = _open_and_sync(db_path, enable_vectors=semantic, force_reindex=reindex)

    # Hybrid retrieval (Phase 6): only when the user asked for plain search
    # (no explicit --fuzzy/--semantic -- those mean "I want exactly that
    # mode") AND a vector index already exists on disk for this repo. Never
    # build the vector index here -- that would silently charge an Ollama
    # embedding bill to someone who never opted into --semantic. Once
    # --semantic has been run here at least once, ordinary `search` calls
    # get the BM25+vector fusion benefit for free from then on. See
    # docs/explanation/latticedb-migration.md's Phase 6 status for the
    # rejected alternative (always building both indexes).
    vector_graph: Optional[DependencyGraph] = None
    hybrid = not fuzzy and not semantic and vector_db_path.exists()
    if hybrid:
        vector_graph = _open_and_sync(vector_db_path, enable_vectors=True, force_reindex=False)

    def _close_all() -> None:
        graph.backend.close()
        if vector_graph is not None:
            vector_graph.backend.close()

    # Minimal "try exact match, fall back to BM25" heuristic (see
    # docs/explanation/latticedb-migration.md's Implementation Status
    # ranking, item #5) -- only for plain `search` (no explicit --fuzzy/
    # --semantic override, which mean the user wants that specific mode).
    if not fuzzy and not semantic:
        exact = _looks_like_exact_target(query)
        if exact is not None:
            exact_file, exact_name = exact
            console.print(
                f"[dim]{query!r} looks like an exact target -- checking "
                f"{exact_file}::{exact_name} before BM25...[/dim]"
            )
            fn = graph.get_function(exact_file, exact_name)
            if fn is not None:
                console.print(f"[green]Exact match:[/green] {exact_file}::{exact_name}")
                if not no_context:
                    console.print("[dim]Assembling context...[/dim]")
                    try:
                        ctx = ContextAssembler(graph).assemble_context(exact_file, exact_name)
                        console.print()
                        console.print(
                            create_header_panel(
                                "Context", f"Exact match: {exact_file}::{exact_name}"
                            )
                        )
                        console.print(ctx.to_markdown())
                    except (ValueError, FileNotFoundError) as e:
                        console.print(f"[yellow]Could not assemble context:[/yellow] {e}")
                _close_all()
                return
            # QUERY looked target-shaped but didn't resolve -- fall through
            # to BM25 below rather than erroring; it might just be a phrase
            # that happens to contain a single colon.

    if semantic:
        mode = "semantic (vector)"
    elif fuzzy:
        mode = "fuzzy BM25"
    elif hybrid:
        mode = "hybrid BM25+vector"
    else:
        mode = "BM25"
    console.print(f"[dim]Running {mode} search for {query!r}...[/dim]")
    t2 = time.time()
    try:
        if semantic:
            hits = graph.backend.search_vector(query, limit=limit)
        elif hybrid:
            bm25_hits = graph.backend.search_text(query, limit=limit)
            vector_hits = vector_graph.backend.search_vector(query, limit=limit)
            # RRF, not raw score blending -- BM25's score and vector's
            # distance aren't on comparable scales. See hybrid_search.py.
            hits = reciprocal_rank_fusion([bm25_hits, vector_hits], limit=limit)
        else:
            hits = graph.backend.search_text(query, limit=limit, fuzzy=fuzzy)
    except Exception as e:
        console.print(f"[red]Error during search:[/red] {e}")
        sys.exit(1)
    console.print(f"[dim]Search took {(time.time() - t2) * 1000:.0f}ms.[/dim]")

    if not hits:
        console.print(f"[yellow]No results for[/yellow] {query!r}")
        if not fuzzy and not semantic and not hybrid:
            console.print(
                "[dim]Try --fuzzy for typo tolerance, or --semantic for "
                "conceptual search (needs local Ollama).[/dim]"
            )
        _close_all()
        return

    console.print()
    if semantic:
        score_label = "Distance (lower=closer)"
    elif hybrid:
        score_label = "Fused rank score"
    else:
        score_label = "Score"
    table = Table(title=f"Search results for {query!r}")
    table.add_column("Type")
    table.add_column("Name")
    table.add_column("File")
    table.add_column(score_label, justify="right")
    for hit in hits:
        table.add_row(hit.node_type, hit.name, hit.file, f"{hit.score:.3f}")
    console.print(table)

    if not no_context:
        # ContextAssembler only knows how to look up Function seeds today
        # (its call-graph traversal is Function-to-Function only) -- Class
        # hits from search_text() have no callers/callees to assemble, so
        # pick the top-ranked *Function* hit rather than assuming hits[0].
        top = next((h for h in hits if h.node_type == "Function"), None)
        if top is None:
            console.print(
                "\n[yellow]No Function among the top results to build a "
                "context for (only Class hits) -- context assembly is "
                "Function-only for now.[/yellow]"
            )
        else:
            console.print(f"[dim]Assembling context for {top.file}::{top.name}...[/dim]")
            try:
                # Always via `graph` (the BM25/primary index), even in
                # hybrid mode: both indexes cover the same source and are
                # kept in sync (see _open_and_sync above), and only `graph`
                # is guaranteed non-None here.
                ctx = ContextAssembler(graph).assemble_context(top.file, top.name)
                console.print()
                console.print(
                    create_header_panel(
                        "Context", f"Top hit: {top.file}::{top.name}"
                    )
                )
                console.print(ctx.to_markdown())
            except (ValueError, FileNotFoundError) as e:
                console.print(f"[yellow]Could not assemble context for top hit:[/yellow] {e}")

    _close_all()


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

    # Display header
    console.print()
    console.print(
        create_header_panel(
            "Variable Trace Analysis",
            f"Tracing: {variable} at {file_name}:{line_number}"
        )
    )
    console.print()

    try:
        results = analyzer.analyze_variable_impact(file_name, variable, line_number)

        if not results:
            console.print("[yellow]No data flow found.[/yellow]")
            return

        # Display results in table with consistent styling
        table = create_data_table(
            f"Data Flow for '{variable}'",
            [
                ("File", "left", "cyan"),
                ("Function", "left", "green"),
                ("Line", "right", "yellow"),
            ]
        )

        for file, function, line in results:
            table.add_row(
                file,
                function,
                format_count(line),
            )

        console.print(table)
        console.print(
            f"\n[green]✓[/green] Found [yellow]{format_count(len(results))}[/yellow] usages"
        )

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

    # Display header
    console.print()
    console.print(create_header_panel("Codebase Statistics", "Analysis Summary"))
    console.print()

    try:
        stats_data = graph.get_statistics()

        # Overall statistics
        overview_table = create_summary_table("Overview")

        overview_table.add_row("Total files", format_count(stats_data.get("total_files", 0)))
        overview_table.add_row("Total classes", format_count(stats_data.get("total_classes", 0)))
        overview_table.add_row("Total functions", format_count(stats_data.get("total_functions", 0)))
        overview_table.add_row("Total variables", format_count(stats_data.get("total_variables", 0)))
        overview_table.add_row("Total edges", format_count(stats_data.get("total_edges", 0)))
        overview_table.add_row("Function calls", format_count(stats_data.get("function_calls", 0)))

        # Show new node types if schema v2
        if stats_data.get("schema_version") == "v2":
            overview_table.add_row(
                "Total imports (detailed)", format_count(stats_data.get("total_imports", 0))
            )
            overview_table.add_row(
                "Total decorators", format_count(stats_data.get("total_decorators", 0))
            )
            overview_table.add_row(
                "Total attributes", format_count(stats_data.get("total_attributes", 0))
            )
            overview_table.add_row(
                "Total exceptions", format_count(stats_data.get("total_exceptions", 0))
            )
            overview_table.add_row("Total modules", format_count(stats_data.get("total_modules", 0)))

        console.print(overview_table)
        console.print()

        # Relationship statistics
        edge_stats = stats_data.get("edge_stats", {})
        if edge_stats:
            relationship_table = create_data_table(
                "Relationship Types",
                [
                    ("Relationship", "left", "green"),
                    ("Count", "right", "yellow"),
                    ("% of Total", "right", "cyan"),
                ]
            )

            total_edges = stats_data.get("total_edges", 0)

            for edge_type in [
                "CONTAINS_FUNCTION",
                "CONTAINS_CLASS",
                "CONTAINS_VARIABLE",
                "METHOD_OF",
                "HAS_IMPORT",
                "HAS_ATTRIBUTE",
                "DECORATED_BY",
                "REFERENCES",
                "ACCESSES",
                "HANDLES_EXCEPTION",
                "CALLS",
                "INHERITS",
            ]:
                count = edge_stats.get(edge_type, 0)
                if total_edges > 0:
                    percentage = (count / total_edges) * 100
                else:
                    percentage = 0

                relationship_table.add_row(
                    edge_type,
                    format_count(count),
                    f"{percentage:.1f}%",
                )

            console.print(relationship_table)
            console.print()

        # Functions with multiple decorators
        try:
            multi_decorators = graph.get_functions_with_multiple_decorators()
            if multi_decorators:
                decorator_table = create_data_table(
                    f"Functions with Multiple Decorators ({len(multi_decorators)} found)",
                    [
                        ("Function", "left", "green"),
                        ("File", "left", "cyan"),
                        ("Count", "right", "yellow"),
                        ("Decorators", "left", "magenta"),
                    ]
                )

                for func in multi_decorators[:top]:
                    decorators_str = ", ".join(func["decorators"])
                    decorator_table.add_row(
                        func["name"],
                        func["file"],
                        format_count(func["decorator_count"]),
                        decorators_str,
                    )

                console.print(decorator_table)
                console.print()
        except Exception:
            pass

        # Most-called functions
        most_called = stats_data.get("most_called_functions", [])

        if most_called:
            call_table = create_data_table(
                f"Top {min(top, len(most_called))} Most-Called Functions",
                [
                    ("Rank", "right", "dim"),
                    ("Function", "left", "green"),
                    ("File", "left", "cyan"),
                    ("Calls", "right", "yellow"),
                ]
            )

            for i, func in enumerate(most_called[:top], 1):
                call_table.add_row(
                    format_count(i),
                    func.get("name", ""),
                    func.get("file", ""),
                    format_count(func.get("call_count", 0)),
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

    # Display header
    console.print()
    subtitle = f"Function: {function} | Depth: {max_depth}" if function else f"Module: {target}"
    console.print(
        create_header_panel("Dependency Graph Visualization", subtitle)
    )
    console.print()

    try:
        # Display configuration
        config_table = create_data_table(
            "Visualization Configuration",
            [
                ("Parameter", "left", "cyan"),
                ("Value", "left", "green"),
            ]
        )
        config_table.add_row("Target", target)
        config_table.add_row("Function", function if function else "Module-level")
        config_table.add_row("Max Depth", format_count(max_depth))
        config_table.add_row("Output", output)
        console.print(config_table)
        console.print()

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

        console.print(
            f"[green]✓[/green] Diagram saved to: [yellow]{output_path}[/yellow]"
        )
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
