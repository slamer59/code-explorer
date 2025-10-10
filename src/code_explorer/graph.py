"""
Dependency graph data structure.

This module provides a simple in-memory graph for storing and querying
Python code dependencies. For production use, this would be replaced with
KuzuDB storage.
"""

from dataclasses import dataclass
from typing import Dict, List, Set, Tuple


@dataclass
class FunctionNode:
    """Represents a function in the dependency graph."""

    name: str
    file: str
    start_line: int
    end_line: int
    is_public: bool = True


@dataclass
class VariableNode:
    """Represents a variable in the dependency graph."""

    name: str
    file: str
    definition_line: int
    scope: str


class DependencyGraph:
    """In-memory dependency graph for testing.

    Stores functions, variables, and their relationships.
    In production, this would use KuzuDB for persistence and efficient queries.
    """

    def __init__(self):
        """Initialize empty dependency graph."""
        self.functions: Dict[Tuple[str, str], FunctionNode] = {}
        self.variables: Dict[Tuple[str, str, int], VariableNode] = {}

        # Edges: caller -> set of callees
        self._calls: Dict[Tuple[str, str], Set[Tuple[str, str, int]]] = {}
        # Reverse edges: callee -> set of callers
        self._called_by: Dict[Tuple[str, str], Set[Tuple[str, str, int]]] = {}

        # Variable usage edges
        self._defines: Dict[Tuple[str, str], Set[Tuple[str, str, int]]] = {}
        self._uses: Dict[Tuple[str, str], Set[Tuple[str, str, int]]] = {}

    def add_function(
        self,
        name: str,
        file: str,
        start_line: int,
        end_line: int,
        is_public: bool = True
    ) -> None:
        """Add a function to the graph.

        Args:
            name: Function name
            file: File path where function is defined
            start_line: Starting line number
            end_line: Ending line number
            is_public: Whether function is public (not starting with _)
        """
        key = (file, name)
        self.functions[key] = FunctionNode(
            name=name,
            file=file,
            start_line=start_line,
            end_line=end_line,
            is_public=is_public
        )

    def add_variable(
        self,
        name: str,
        file: str,
        definition_line: int,
        scope: str
    ) -> None:
        """Add a variable to the graph.

        Args:
            name: Variable name
            file: File path where variable is defined
            definition_line: Line number where variable is defined
            scope: Scope of the variable (e.g., "module", "function:func_name")
        """
        key = (file, name, definition_line)
        self.variables[key] = VariableNode(
            name=name,
            file=file,
            definition_line=definition_line,
            scope=scope
        )

    def add_call(
        self,
        caller_file: str,
        caller_function: str,
        callee_file: str,
        callee_function: str,
        call_line: int
    ) -> None:
        """Add a function call edge.

        Args:
            caller_file: File where caller is defined
            caller_function: Name of calling function
            callee_file: File where callee is defined
            callee_function: Name of called function
            call_line: Line number where call occurs
        """
        caller_key = (caller_file, caller_function)
        callee_key = (callee_file, callee_function)

        if caller_key not in self._calls:
            self._calls[caller_key] = set()
        self._calls[caller_key].add((callee_file, callee_function, call_line))

        if callee_key not in self._called_by:
            self._called_by[callee_key] = set()
        self._called_by[callee_key].add((caller_file, caller_function, call_line))

    def add_variable_usage(
        self,
        function_file: str,
        function_name: str,
        var_name: str,
        var_file: str,
        var_definition_line: int,
        usage_line: int,
        is_definition: bool = False
    ) -> None:
        """Add variable usage edge.

        Args:
            function_file: File where function is defined
            function_name: Name of function using the variable
            var_name: Variable name
            var_file: File where variable is defined
            var_definition_line: Line where variable is defined
            usage_line: Line where variable is used
            is_definition: True if function defines the variable
        """
        func_key = (function_file, function_name)
        var_key = (var_file, var_name, var_definition_line)

        if is_definition:
            if func_key not in self._defines:
                self._defines[func_key] = set()
            self._defines[func_key].add((var_file, var_name, var_definition_line))
        else:
            if func_key not in self._uses:
                self._uses[func_key] = set()
            self._uses[func_key].add((var_file, var_name, usage_line))

    def get_callers(
        self,
        file: str,
        function: str
    ) -> List[Tuple[str, str, int]]:
        """Get functions that call the specified function.

        Args:
            file: File where function is defined
            function: Function name

        Returns:
            List of (file, function_name, call_line) tuples
        """
        key = (file, function)
        return list(self._called_by.get(key, set()))

    def get_callees(
        self,
        file: str,
        function: str
    ) -> List[Tuple[str, str, int]]:
        """Get functions called by the specified function.

        Args:
            file: File where function is defined
            function: Function name

        Returns:
            List of (file, function_name, call_line) tuples
        """
        key = (file, function)
        return list(self._calls.get(key, set()))

    def get_variable_usage(
        self,
        file: str,
        var_name: str,
        definition_line: int
    ) -> List[Tuple[str, str, int]]:
        """Get functions that use the specified variable.

        Args:
            file: File where variable is defined
            var_name: Variable name
            definition_line: Line where variable is defined

        Returns:
            List of (file, function_name, usage_line) tuples
        """
        results = []
        for func_key, var_set in self._uses.items():
            for var_file, name, usage_line in var_set:
                if var_file == file and name == var_name:
                    results.append((func_key[0], func_key[1], usage_line))
        return results

    def get_function(self, file: str, name: str) -> FunctionNode | None:
        """Get function node by file and name.

        Args:
            file: File path
            name: Function name

        Returns:
            FunctionNode if found, None otherwise
        """
        return self.functions.get((file, name))

    def get_all_functions_in_file(self, file: str) -> List[FunctionNode]:
        """Get all functions defined in a file.

        Args:
            file: File path

        Returns:
            List of FunctionNode objects
        """
        return [
            node for (f, _), node in self.functions.items()
            if f == file
        ]

    def get_statistics(self) -> Dict[str, any]:
        """Get statistics about the graph.

        Returns:
            Dictionary with graph statistics
        """
        # Get unique files
        files = set(f for f, _ in self.functions.keys())
        files.update(f for f, _, _ in self.variables.keys())

        # Count total edges
        total_call_edges = sum(len(callees) for callees in self._calls.values())

        # Find most-called functions
        call_counts = {}
        for (file, func) in self.functions.keys():
            callers = self._called_by.get((file, func), set())
            if callers:
                call_counts[(file, func)] = len(callers)

        most_called = [
            {"name": func, "file": file, "call_count": count}
            for (file, func), count in sorted(
                call_counts.items(), key=lambda x: x[1], reverse=True
            )
        ]

        return {
            "total_files": len(files),
            "total_functions": len(self.functions),
            "total_variables": len(self.variables),
            "total_edges": total_call_edges,
            "function_calls": total_call_edges,
            "most_called_functions": most_called,
        }
