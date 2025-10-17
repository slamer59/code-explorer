"""
Performance instrumentation module for tracking timing in code blocks and functions.

This module provides a Timer class that can be used as a context manager or decorator
to measure and report execution time. It supports nested timing operations and integrates
with rich console for pretty printing.

Examples:
    Using as a context manager:
        >>> with Timer("database_query"):
        ...     perform_query()
        ⏱️  database_query: 1.234s

    Using as a decorator:
        >>> @timer("api_call")
        ... def fetch_data():
        ...     return requests.get(url)
        >>> fetch_data()
        ⏱️  api_call: 0.567s

    Nested timing operations:
        >>> with Timer("parent_operation") as parent:
        ...     process_step_1()
        ...     with Timer("child_operation") as child:
        ...         process_step_2()
        ⏱️    child_operation: 0.100s
        ⏱️  parent_operation: 0.500s

    Silent mode for benchmarking:
        >>> with Timer("benchmark", silent=True) as t:
        ...     expensive_operation()
        >>> print(f"Operation took {t.elapsed:.3f}s")
        Operation took 2.345s
"""

import functools
import time
from contextlib import contextmanager
from typing import Optional, Callable, Any
from dataclasses import dataclass, field

from rich.console import Console


# Global console instance for rich output
_console: Optional[Console] = None


def get_console() -> Console:
    """Get or create the global console instance.

    Returns:
        Console: The rich Console instance for output
    """
    global _console
    if _console is None:
        _console = Console()
    return _console


# Thread-local storage for nesting depth tracking
import threading
_local = threading.local()


def _get_nesting_depth() -> int:
    """Get current timer nesting depth for the current thread.

    Returns:
        int: Current nesting depth (0 for top-level timers)
    """
    if not hasattr(_local, 'depth'):
        _local.depth = 0
    return _local.depth


def _increment_depth() -> int:
    """Increment and return the nesting depth.

    Returns:
        int: New nesting depth after increment
    """
    if not hasattr(_local, 'depth'):
        _local.depth = 0
    _local.depth += 1
    return _local.depth


def _decrement_depth() -> int:
    """Decrement and return the nesting depth.

    Returns:
        int: New nesting depth after decrement
    """
    if not hasattr(_local, 'depth'):
        _local.depth = 0
    if _local.depth > 0:
        _local.depth -= 1
    return _local.depth


@dataclass
class TimerResult:
    """Result of a timed operation.

    Attributes:
        name: Name of the timed operation
        elapsed: Elapsed time in seconds
        start_time: Start timestamp (from time.perf_counter)
        end_time: End timestamp (from time.perf_counter)
        nesting_level: Nesting depth (0 for top-level)
        error: Exception that occurred during timing, if any
    """
    name: str
    elapsed: float
    start_time: float
    end_time: float
    nesting_level: int = 0
    error: Optional[Exception] = None

    @property
    def success(self) -> bool:
        """Check if the timed operation completed successfully.

        Returns:
            bool: True if no error occurred
        """
        return self.error is None

    def __str__(self) -> str:
        """String representation of the timer result.

        Returns:
            str: Human-readable timing information
        """
        indent = "  " * self.nesting_level
        status = "✓" if self.success else "✗"
        return f"{indent}{status} {self.name}: {self.elapsed:.3f}s"


class Timer:
    """Context manager and decorator for timing code execution.

    This class can be used as a context manager to time code blocks or as a
    decorator to time function calls. It supports nested timing, pretty printing
    with rich console, and silent mode for programmatic access to timing data.

    Attributes:
        name: Name of the operation being timed
        silent: If True, suppress automatic output
        console: Optional rich Console instance for output
        elapsed: Time elapsed in seconds (available after timing completes)
        result: TimerResult object with detailed timing information

    Examples:
        Context manager with automatic output:
            >>> with Timer("operation"):
            ...     do_something()
            ⏱️  operation: 1.234s

        Context manager with silent mode:
            >>> with Timer("operation", silent=True) as t:
            ...     do_something()
            >>> print(f"Took {t.elapsed:.3f}s")
            Took 1.234s

        Decorator usage:
            >>> @timer("function_name")
            ... def my_function():
            ...     return 42
            >>> result = my_function()
            ⏱️  function_name: 0.001s
            >>> result
            42
    """

    def __init__(
        self,
        name: str,
        silent: bool = False,
        console: Optional[Console] = None
    ):
        """Initialize a Timer instance.

        Args:
            name: Name of the operation being timed
            silent: If True, suppress automatic timing output (default: False)
            console: Optional rich Console instance. If None, uses global console.
        """
        self.name = name
        self.silent = silent
        self.console = console or get_console()

        self._start_time: float = 0.0
        self._end_time: float = 0.0
        self._nesting_level: int = 0
        self.elapsed: float = 0.0
        self.result: Optional[TimerResult] = None

    def __enter__(self) -> "Timer":
        """Enter the context manager and start timing.

        Returns:
            Timer: Self for use in 'as' clause
        """
        self._nesting_level = _get_nesting_depth()
        _increment_depth()
        self._start_time = time.perf_counter()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        """Exit the context manager and stop timing.

        Args:
            exc_type: Exception type if an exception occurred
            exc_val: Exception value if an exception occurred
            exc_tb: Exception traceback if an exception occurred

        Returns:
            bool: False to propagate exceptions
        """
        self._end_time = time.perf_counter()
        self.elapsed = self._end_time - self._start_time
        _decrement_depth()

        # Create result object
        self.result = TimerResult(
            name=self.name,
            elapsed=self.elapsed,
            start_time=self._start_time,
            end_time=self._end_time,
            nesting_level=self._nesting_level,
            error=exc_val if exc_type is not None else None
        )

        # Print timing unless silent or error occurred
        if not self.silent:
            self._print_timing(error=exc_val)

        # Don't suppress exceptions
        return False

    def _print_timing(self, error: Optional[Exception] = None) -> None:
        """Print timing information with rich formatting.

        Args:
            error: Optional exception that occurred during timing
        """
        indent = "  " * self._nesting_level

        if error:
            # Error case - show with error symbol
            self.console.print(
                f"[red]{indent}⏱️  {self.name}: {self.elapsed:.3f}s "
                f"(failed with {type(error).__name__})[/red]"
            )
        else:
            # Success case - use color based on duration
            color = self._get_color_for_duration(self.elapsed)
            self.console.print(
                f"[{color}]{indent}⏱️  {self.name}: {self.elapsed:.3f}s[/{color}]"
            )

    def _get_color_for_duration(self, duration: float) -> str:
        """Get color based on operation duration.

        Args:
            duration: Duration in seconds

        Returns:
            str: Rich color name for the duration
        """
        if duration < 0.1:
            return "green"
        elif duration < 1.0:
            return "yellow"
        elif duration < 5.0:
            return "orange1"
        else:
            return "red"

    def __call__(self, func: Callable) -> Callable:
        """Support using Timer as a decorator.

        This method allows Timer to be used as a function decorator. Note that
        when used as a decorator, the timer instance's silent and console settings
        are used for all invocations.

        Args:
            func: Function to be decorated

        Returns:
            Callable: Wrapped function that times execution

        Example:
            >>> timer_instance = Timer("my_function", silent=False)
            >>> @timer_instance
            ... def my_function():
            ...     return 42
        """
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with Timer(self.name, silent=self.silent, console=self.console):
                return func(*args, **kwargs)
        return wrapper


def timer(
    name: Optional[str] = None,
    silent: bool = False,
    console: Optional[Console] = None
) -> Callable:
    """Decorator factory for timing functions.

    This is a convenience function for creating Timer decorators. It returns
    a decorator that will time the decorated function and optionally print
    the timing information.

    Args:
        name: Name for the timed operation. If None, uses function name.
        silent: If True, suppress automatic timing output (default: False)
        console: Optional rich Console instance for output

    Returns:
        Callable: Decorator that times function execution

    Examples:
        With explicit name:
            >>> @timer("api_call")
            ... def fetch_data():
            ...     return requests.get(url)
            >>> fetch_data()
            ⏱️  api_call: 0.567s

        Using function name:
            >>> @timer()
            ... def process_data():
            ...     return [1, 2, 3]
            >>> process_data()
            ⏱️  process_data: 0.001s

        Silent mode:
            >>> @timer(silent=True)
            ... def expensive_operation():
            ...     time.sleep(1)
            ...     return "done"
            >>> result = expensive_operation()  # No output
            >>> result
            'done'
    """
    def decorator(func: Callable) -> Callable:
        operation_name = name if name is not None else func.__name__

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with Timer(operation_name, silent=silent, console=console):
                return func(*args, **kwargs)
        return wrapper

    return decorator


@contextmanager
def timing_group(
    group_name: str,
    silent: bool = False,
    console: Optional[Console] = None
):
    """Context manager for grouping related timing operations.

    This is a convenience wrapper around Timer that provides clearer semantics
    for timing groups of related operations.

    Args:
        group_name: Name of the operation group
        silent: If True, suppress automatic timing output
        console: Optional rich Console instance for output

    Yields:
        Timer: Timer instance for the group

    Example:
        >>> with timing_group("data_processing"):
        ...     with Timer("load_data"):
        ...         data = load_data()
        ...     with Timer("transform_data"):
        ...         result = transform_data(data)
        ⏱️    load_data: 0.100s
        ⏱️    transform_data: 0.050s
        ⏱️  data_processing: 0.150s
    """
    with Timer(group_name, silent=silent, console=console) as t:
        yield t


class TimingContext:
    """Accumulator for timing data across multiple operations.

    This class allows you to collect timing data from multiple operations
    and generate summary reports. Useful for benchmarking and performance
    analysis.

    Attributes:
        results: List of TimerResult objects from recorded operations
        console: Rich Console instance for output

    Examples:
        >>> ctx = TimingContext()
        >>> with Timer("op1", silent=True) as t1:
        ...     do_something()
        >>> ctx.record(t1.result)
        >>> with Timer("op2", silent=True) as t2:
        ...     do_something_else()
        >>> ctx.record(t2.result)
        >>> ctx.print_summary()
        ═══════════════════════════════════════════════════════════════
        TIMING SUMMARY
        ═══════════════════════════════════════════════════════════════
        op1                                          1.234s
        op2                                          0.567s
        ───────────────────────────────────────────────────────────────
        Total                                        1.801s
        Average                                      0.901s
        Min                                          0.567s
        Max                                          1.234s
        ═══════════════════════════════════════════════════════════════
    """

    def __init__(self, console: Optional[Console] = None):
        """Initialize a TimingContext.

        Args:
            console: Optional rich Console instance for output
        """
        self.results: list[TimerResult] = []
        self.console = console or get_console()

    def record(self, result: TimerResult) -> None:
        """Record a timing result.

        Args:
            result: TimerResult object to record
        """
        self.results.append(result)

    @contextmanager
    def measure(self, name: str, silent: bool = True):
        """Context manager that times an operation and records the result.

        Args:
            name: Name of the operation
            silent: If True, suppress automatic output (default: True)

        Yields:
            Timer: Timer instance for the operation

        Example:
            >>> ctx = TimingContext()
            >>> with ctx.measure("operation"):
            ...     do_something()
            >>> ctx.print_summary()
        """
        timer = Timer(name, silent=silent, console=self.console)
        try:
            with timer as t:
                yield t
        finally:
            # Record result even if an exception occurred
            if timer.result:
                self.record(timer.result)

    def print_summary(self, title: str = "TIMING SUMMARY") -> None:
        """Print a summary of all recorded timings.

        Args:
            title: Title for the summary report
        """
        if not self.results:
            self.console.print("[dim]No timing data recorded[/dim]")
            return

        self.console.print("\n" + "=" * 70)
        self.console.print(f"[bold]{title}[/bold]")
        self.console.print("=" * 70)

        # Print individual results
        for result in self.results:
            indent = "  " * result.nesting_level
            status = "✓" if result.success else "✗"
            color = "green" if result.success else "red"
            self.console.print(
                f"[{color}]{indent}{status} {result.name:40s} {result.elapsed:8.3f}s[/{color}]"
            )

        # Print statistics
        successful = [r for r in self.results if r.success]
        if successful:
            total_time = sum(r.elapsed for r in successful)
            avg_time = total_time / len(successful)
            min_time = min(r.elapsed for r in successful)
            max_time = max(r.elapsed for r in successful)

            self.console.print("-" * 70)
            self.console.print(f"[bold]Total{'':45s} {total_time:8.3f}s[/bold]")
            self.console.print(f"[dim]Average{'':43s} {avg_time:8.3f}s[/dim]")
            self.console.print(f"[dim]Min{'':47s} {min_time:8.3f}s[/dim]")
            self.console.print(f"[dim]Max{'':47s} {max_time:8.3f}s[/dim]")

        self.console.print("=" * 70 + "\n")

    def get_total_time(self) -> float:
        """Get total time of all successful operations.

        Returns:
            float: Total elapsed time in seconds
        """
        return sum(r.elapsed for r in self.results if r.success)

    def get_average_time(self) -> float:
        """Get average time of all successful operations.

        Returns:
            float: Average elapsed time in seconds
        """
        successful = [r for r in self.results if r.success]
        if not successful:
            return 0.0
        return self.get_total_time() / len(successful)

    def clear(self) -> None:
        """Clear all recorded results."""
        self.results.clear()
