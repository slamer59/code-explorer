"""
Example showing how to instrument export_parquet.py with the timer module.

This demonstrates how to add performance instrumentation to identify
bottlenecks in the parquet export process.
"""

from pathlib import Path
from typing import List
from code_explorer.utils import Timer, TimingContext


def instrumented_export_to_parquet_example(
    results: List,
    output_dir: Path,
    project_root: Path,
    resolved_calls: List = None,
) -> None:
    """
    Example of how to instrument the export_to_parquet function.

    This is a simplified version showing where to add timing instrumentation.
    Apply similar patterns to the actual export_parquet.py file.
    """
    # Create a timing context to collect all timing data
    ctx = TimingContext()

    with Timer("export_to_parquet_total"):
        # 1. Directory setup (usually fast, but good to verify)
        with ctx.measure("setup_directories"):
            nodes_dir = output_dir / "nodes"
            edges_dir = output_dir / "edges"
            nodes_dir.mkdir(parents=True, exist_ok=True)
            edges_dir.mkdir(parents=True, exist_ok=True)

        # 2. Collect node data from FileAnalysis results
        with ctx.measure("collect_node_data"):
            # This is the main loop that processes all FileAnalysis results
            # Nested timers show detail within this phase
            with Timer("process_files"):
                files_data = []
                functions_data = []
                classes_data = []
                # ... other node data collections

                for result in results:
                    # In the real implementation, you might add a timer
                    # inside this loop if processing individual files is slow
                    pass

        # 3. Build lookup dictionaries (critical optimization point)
        with ctx.measure("build_lookup_dictionaries"):
            # This is where the O(n²) -> O(1) optimization happens
            func_lookup = {}
            class_lookup = {}
            # ... other lookups

        # 4. Create edges using lookups
        with ctx.measure("create_edges"):
            # Break down edge creation by type to find bottlenecks
            with Timer("create_method_of_edges"):
                method_of_data = []
                # ... create METHOD_OF edges

            with Timer("create_references_edges"):
                references_data = []
                # ... create REFERENCES edges

            with Timer("create_decorated_by_edges"):
                decorated_by_data = []
                # ... create DECORATED_BY edges

            with Timer("create_has_attribute_edges"):
                has_attribute_data = []
                # ... create HAS_ATTRIBUTE edges

            with Timer("create_handles_exception_edges"):
                handles_exception_data = []
                # ... create HANDLES_EXCEPTION edges

        # 5. Process resolved calls if provided
        if resolved_calls:
            with ctx.measure("process_resolved_calls"):
                calls_data = []
                # ... process calls

        # 6. Write Parquet files
        with ctx.measure("write_parquet_files"):
            # Break down by node vs edge writes
            with Timer("write_node_tables"):
                # Write all node tables
                pass

            with Timer("write_edge_tables"):
                # Write all edge tables
                pass

    # Print detailed timing summary
    ctx.print_summary(title="PARQUET EXPORT PERFORMANCE PROFILE")

    # Print any warnings about slow operations
    print("\n" + "="*70)
    print("PERFORMANCE WARNINGS")
    print("="*70)

    slow_operations = [r for r in ctx.results if r.success and r.elapsed > 0.5]
    if slow_operations:
        for op in slow_operations:
            print(f"⚠️  {op.name} took {op.elapsed:.3f}s (> 0.5s threshold)")
    else:
        print("✓ All operations completed within acceptable time")
    print("="*70)


def show_decorator_approach():
    """
    Alternative approach: Using decorators on helper functions.

    This works well when you want to time specific helper functions
    without modifying the main function structure.
    """
    from code_explorer.utils import timer

    @timer("make_function_id")
    def make_function_id(file: str, name: str, start_line: int, project_root: Path) -> str:
        """Timed version of make_function_id."""
        import hashlib
        # ... implementation
        return "fn_abc123"

    @timer("make_class_id")
    def make_class_id(file: str, name: str, start_line: int, project_root: Path) -> str:
        """Timed version of make_class_id."""
        import hashlib
        # ... implementation
        return "cls_def456"

    # These decorators will automatically print timing when called


def show_conditional_instrumentation():
    """
    Show how to enable/disable instrumentation based on environment.

    Useful for development vs production scenarios.
    """
    import os

    # Enable detailed timing in development
    ENABLE_TIMING = os.getenv("CODE_EXPLORER_TIMING", "false").lower() == "true"

    if ENABLE_TIMING:
        from code_explorer.utils import Timer, TimingContext

        ctx = TimingContext()

        def process_data():
            with ctx.measure("processing"):
                # ... do work
                pass

        process_data()
        ctx.print_summary()
    else:
        # Production mode - no timing overhead
        def process_data():
            # ... do work
            pass

        process_data()


def main():
    """Demonstrate instrumentation patterns."""
    print("\n" + "="*70)
    print("EXPORT_PARQUET INSTRUMENTATION EXAMPLES")
    print("="*70)

    print("\nTo instrument export_parquet.py, follow these steps:")
    print("\n1. Import the timer module:")
    print("   from code_explorer.utils import Timer, TimingContext")

    print("\n2. Create a TimingContext at the start of export_to_parquet:")
    print("   ctx = TimingContext()")

    print("\n3. Wrap major sections with ctx.measure():")
    print("   with ctx.measure('collect_node_data'):")
    print("       # ... existing code")

    print("\n4. Add nested Timer() calls for detailed timing:")
    print("   with Timer('write_node_tables'):")
    print("       # ... existing code")

    print("\n5. Print summary at the end:")
    print("   ctx.print_summary(title='PARQUET EXPORT TIMING')")

    print("\n" + "="*70)
    print("RECOMMENDED INSTRUMENTATION POINTS")
    print("="*70)

    points = [
        ("collect_node_data", "Main loop processing FileAnalysis results"),
        ("build_lookup_dictionaries", "Building global lookups (critical for performance)"),
        ("create_edges", "Edge creation using lookups"),
        ("write_parquet_files", "Writing all Parquet files to disk"),
        ("write_node_tables", "Writing node tables (nested in write_parquet_files)"),
        ("write_edge_tables", "Writing edge tables (nested in write_parquet_files)"),
    ]

    for name, description in points:
        print(f"• {name:30s} - {description}")

    print("\n" + "="*70)
    print("USAGE TIPS")
    print("="*70)

    tips = [
        "Start with coarse-grained timing of major sections",
        "Add nested timers only where you suspect bottlenecks",
        "Use silent=True for ctx.measure() to avoid cluttering output",
        "Print the summary at the end to see all timings together",
        "Color coding helps identify slow operations at a glance",
        "Use TimingContext to compare timings across different runs",
    ]

    for i, tip in enumerate(tips, 1):
        print(f"{i}. {tip}")

    print("\n" + "="*70 + "\n")


if __name__ == "__main__":
    main()
