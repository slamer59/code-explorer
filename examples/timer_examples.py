"""
Examples of using the timer module for performance instrumentation.

This file demonstrates practical usage patterns for the timer module,
including context managers, decorators, nested timing, and benchmarking.
"""

import time
from code_explorer.utils.timer import Timer, timer, timing_group, TimingContext


def example_basic_context_manager():
    """Example 1: Basic context manager usage."""
    print("\n" + "="*70)
    print("Example 1: Basic Context Manager Usage")
    print("="*70)

    with Timer("database_query"):
        # Simulate a database query
        time.sleep(0.1)

    with Timer("file_processing"):
        # Simulate file processing
        time.sleep(0.05)


def example_decorator():
    """Example 2: Using timer as a function decorator."""
    print("\n" + "="*70)
    print("Example 2: Decorator Usage")
    print("="*70)

    @timer("fetch_user_data")
    def fetch_user_data(user_id: int):
        """Simulate fetching user data from API."""
        time.sleep(0.08)
        return {"id": user_id, "name": "John Doe"}

    @timer("process_user_data")
    def process_user_data(user_data: dict):
        """Simulate processing user data."""
        time.sleep(0.05)
        return user_data["name"].upper()

    # Call the decorated functions
    user = fetch_user_data(123)
    result = process_user_data(user)
    print(f"Result: {result}")


def example_nested_timing():
    """Example 3: Nested timing operations."""
    print("\n" + "="*70)
    print("Example 3: Nested Timing Operations")
    print("="*70)

    with Timer("data_pipeline"):
        with Timer("load_data"):
            # Simulate loading data
            time.sleep(0.05)

        with Timer("transform_data"):
            # Simulate transformation
            time.sleep(0.08)

            with Timer("validate_schema"):
                # Nested validation step
                time.sleep(0.02)

        with Timer("save_data"):
            # Simulate saving
            time.sleep(0.03)


def example_silent_mode():
    """Example 4: Silent mode for programmatic access."""
    print("\n" + "="*70)
    print("Example 4: Silent Mode for Programmatic Access")
    print("="*70)

    with Timer("computation", silent=True) as t:
        # Perform computation
        result = sum(i**2 for i in range(1000))
        time.sleep(0.01)

    # Access timing data programmatically
    print(f"Computation completed in {t.elapsed:.4f} seconds")
    print(f"Result: {result}")

    if t.elapsed > 0.1:
        print("⚠️  Warning: Operation took longer than expected!")
    else:
        print("✓ Operation completed within acceptable time")


def example_timing_context():
    """Example 5: Accumulating timing data with TimingContext."""
    print("\n" + "="*70)
    print("Example 5: TimingContext for Accumulation")
    print("="*70)

    ctx = TimingContext()

    # Measure multiple operations
    with ctx.measure("parse_config"):
        time.sleep(0.02)

    with ctx.measure("initialize_database"):
        time.sleep(0.05)

    with ctx.measure("load_plugins"):
        time.sleep(0.03)

    with ctx.measure("start_server"):
        time.sleep(0.04)

    # Print comprehensive summary
    ctx.print_summary(title="APPLICATION STARTUP TIMING")


def example_benchmarking():
    """Example 6: Benchmarking with repeated measurements."""
    print("\n" + "="*70)
    print("Example 6: Benchmarking Pattern")
    print("="*70)

    ctx = TimingContext()

    # Run multiple iterations
    iterations = 5
    for i in range(iterations):
        with ctx.measure(f"iteration_{i+1}"):
            # Simulate work with some variance
            time.sleep(0.01 + (i * 0.002))

    # Print summary
    ctx.print_summary(title="BENCHMARK RESULTS")

    # Access statistics
    print(f"\nStatistics:")
    print(f"  Total time:   {ctx.get_total_time():.4f}s")
    print(f"  Average time: {ctx.get_average_time():.4f}s")


def example_timing_group():
    """Example 7: Using timing_group for semantic clarity."""
    print("\n" + "="*70)
    print("Example 7: Timing Groups")
    print("="*70)

    with timing_group("image_processing"):
        with Timer("load_image"):
            time.sleep(0.03)

        with Timer("resize_image"):
            time.sleep(0.04)

        with Timer("apply_filters"):
            time.sleep(0.05)

        with Timer("save_image"):
            time.sleep(0.02)


def example_error_handling():
    """Example 8: Timing with error handling."""
    print("\n" + "="*70)
    print("Example 8: Error Handling")
    print("="*70)

    ctx = TimingContext()

    # Successful operation
    with ctx.measure("successful_operation"):
        time.sleep(0.02)

    # Failed operation
    try:
        with ctx.measure("failing_operation"):
            time.sleep(0.01)
            raise ValueError("Simulated error")
    except ValueError as e:
        print(f"Caught error: {e}")

    # Another successful operation
    with ctx.measure("recovery_operation"):
        time.sleep(0.02)

    # Print summary showing both successes and failures
    ctx.print_summary(title="OPERATIONS WITH ERRORS")


def example_export_parquet_instrumentation():
    """Example 9: Practical instrumentation for export_parquet.py."""
    print("\n" + "="*70)
    print("Example 9: Instrumenting export_parquet Function")
    print("="*70)

    # Simulate the export_to_parquet function structure
    ctx = TimingContext()

    with ctx.measure("collect_nodes"):
        # Simulate collecting node data
        time.sleep(0.08)

    with ctx.measure("build_lookups"):
        # Simulate building lookup dictionaries
        time.sleep(0.05)

    with ctx.measure("create_edges"):
        # Simulate edge creation
        time.sleep(0.12)

    with ctx.measure("write_parquet_files"):
        # Simulate writing Parquet files
        with Timer("write_nodes"):
            time.sleep(0.06)

        with Timer("write_edges"):
            time.sleep(0.04)

    ctx.print_summary(title="EXPORT TO PARQUET TIMING")


def example_decorator_with_custom_name():
    """Example 10: Decorator with custom naming."""
    print("\n" + "="*70)
    print("Example 10: Custom Named Decorators")
    print("="*70)

    @timer("API: Fetch Users")
    def get_users():
        time.sleep(0.05)
        return ["user1", "user2", "user3"]

    @timer("API: Fetch Orders")
    def get_orders():
        time.sleep(0.07)
        return ["order1", "order2"]

    users = get_users()
    orders = get_orders()

    print(f"Fetched {len(users)} users and {len(orders)} orders")


def main():
    """Run all examples."""
    print("\n" + "="*70)
    print("TIMER MODULE EXAMPLES")
    print("="*70)

    example_basic_context_manager()
    example_decorator()
    example_nested_timing()
    example_silent_mode()
    example_timing_context()
    example_benchmarking()
    example_timing_group()
    example_error_handling()
    example_export_parquet_instrumentation()
    example_decorator_with_custom_name()

    print("\n" + "="*70)
    print("ALL EXAMPLES COMPLETED")
    print("="*70 + "\n")


if __name__ == "__main__":
    main()
