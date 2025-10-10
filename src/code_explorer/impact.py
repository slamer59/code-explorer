"""
Impact analysis for code dependencies.

This module provides tools to analyze the impact of code changes by tracing
function calls and variable usage through the dependency graph.
"""

from dataclasses import dataclass
from typing import List, Tuple

from rich.table import Table

from .graph import DependencyGraph


@dataclass
class ImpactResult:
    """Result of impact analysis.

    Represents a function or location impacted by a change,
    with information about how it's connected.
    """

    function_name: str
    file_path: str
    line_number: int
    impact_type: str  # "caller" or "callee"
    depth: int  # how many hops away from the origin


class ImpactAnalyzer:
    """Analyze impact of code changes using dependency graph.

    Provides methods to find upstream dependencies (callers that depend on a function)
    and downstream dependencies (callees that a function depends on).
    """

    def __init__(self, graph: DependencyGraph):
        """Initialize impact analyzer.

        Args:
            graph: Dependency graph to analyze
        """
        self.graph = graph

    def analyze_function_impact(
        self,
        file: str,
        function: str,
        direction: str = "upstream",
        max_depth: int = 5
    ) -> List[ImpactResult]:
        """Analyze impact of changing a function.

        Args:
            file: File path where function is defined
            function: Function name
            direction: "upstream" (callers), "downstream" (callees), or "both"
            max_depth: Maximum depth to traverse (default: 5)

        Returns:
            List of ImpactResult objects sorted by depth, then file path

        Raises:
            ValueError: If direction is not valid
        """
        if direction not in ("upstream", "downstream", "both"):
            raise ValueError(
                f"Invalid direction: {direction}. "
                "Must be 'upstream', 'downstream', or 'both'"
            )

        results: List[ImpactResult] = []

        if direction in ("upstream", "both"):
            upstream = self._analyze_upstream(file, function, max_depth)
            results.extend(upstream)

        if direction in ("downstream", "both"):
            downstream = self._analyze_downstream(file, function, max_depth)
            results.extend(downstream)

        # Sort by depth first, then file path, then function name
        results.sort(key=lambda r: (r.depth, r.file_path, r.function_name))

        return results

    def _analyze_upstream(
        self,
        file: str,
        function: str,
        max_depth: int
    ) -> List[ImpactResult]:
        """Find all functions that call this function (upstream dependencies).

        These are functions that will break if we change the signature
        of the target function.

        Args:
            file: File path where function is defined
            function: Function name
            max_depth: Maximum depth to traverse

        Returns:
            List of ImpactResult objects for callers
        """
        results: List[ImpactResult] = []
        visited: set[Tuple[str, str]] = set()
        queue: List[Tuple[str, str, int]] = [(file, function, 0)]

        while queue:
            current_file, current_func, depth = queue.pop(0)
            current_key = (current_file, current_func)

            # Skip if already visited or beyond max depth
            if current_key in visited or depth > max_depth:
                continue

            visited.add(current_key)

            # Get callers
            callers = self.graph.get_callers(current_file, current_func)

            for caller_file, caller_func, call_line in callers:
                # Add to results (skip depth 0, which is the original function)
                if depth < max_depth:
                    results.append(ImpactResult(
                        function_name=caller_func,
                        file_path=caller_file,
                        line_number=call_line,
                        impact_type="caller",
                        depth=depth + 1
                    ))

                    # Add to queue for further traversal
                    if depth + 1 < max_depth:
                        queue.append((caller_file, caller_func, depth + 1))

        return results

    def _analyze_downstream(
        self,
        file: str,
        function: str,
        max_depth: int
    ) -> List[ImpactResult]:
        """Find all functions that this function calls (downstream dependencies).

        These are functions that will cause our function to break if they change.

        Args:
            file: File path where function is defined
            function: Function name
            max_depth: Maximum depth to traverse

        Returns:
            List of ImpactResult objects for callees
        """
        results: List[ImpactResult] = []
        visited: set[Tuple[str, str]] = set()
        queue: List[Tuple[str, str, int]] = [(file, function, 0)]

        while queue:
            current_file, current_func, depth = queue.pop(0)
            current_key = (current_file, current_func)

            # Skip if already visited or beyond max depth
            if current_key in visited or depth > max_depth:
                continue

            visited.add(current_key)

            # Get callees
            callees = self.graph.get_callees(current_file, current_func)

            for callee_file, callee_func, call_line in callees:
                # Add to results (skip depth 0, which is the original function)
                if depth < max_depth:
                    results.append(ImpactResult(
                        function_name=callee_func,
                        file_path=callee_file,
                        line_number=call_line,
                        impact_type="callee",
                        depth=depth + 1
                    ))

                    # Add to queue for further traversal
                    if depth + 1 < max_depth:
                        queue.append((callee_file, callee_func, depth + 1))

        return results

    def analyze_variable_impact(
        self,
        file: str,
        var_name: str,
        definition_line: int
    ) -> List[Tuple[str, str, int]]:
        """Find where a variable is used.

        Args:
            file: File path where variable is defined
            var_name: Variable name
            definition_line: Line number where variable is defined

        Returns:
            List of (file, function, line) tuples where variable is used
        """
        return self.graph.get_variable_usage(file, var_name, definition_line)

    def format_as_table(self, results: List[ImpactResult]) -> Table:
        """Format impact results as a Rich table for CLI display.

        Args:
            results: List of ImpactResult objects

        Returns:
            Rich Table object ready for display
        """
        table = Table(title="Impact Analysis Results", show_header=True)

        table.add_column("Depth", style="cyan", justify="right")
        table.add_column("Type", style="magenta")
        table.add_column("File", style="green")
        table.add_column("Function", style="yellow")
        table.add_column("Line", style="blue", justify="right")

        for result in results:
            # Color code the impact type
            impact_type_colored = (
                f"[red]←[/red] {result.impact_type}"
                if result.impact_type == "caller"
                else f"[green]→[/green] {result.impact_type}"
            )

            table.add_row(
                str(result.depth),
                impact_type_colored,
                result.file_path,
                result.function_name,
                str(result.line_number)
            )

        return table
