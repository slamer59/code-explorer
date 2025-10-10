"""
Mermaid diagram generation for dependency visualization.

This module generates Mermaid diagrams to visualize function call dependencies
and module relationships in Python codebases.
"""

from pathlib import Path
from typing import Set, Tuple

from .graph import DependencyGraph


class MermaidVisualizer:
    """Generate Mermaid diagrams from dependency graphs.

    Creates visual representations of function call relationships
    using Mermaid syntax for rendering in documentation or tools.
    """

    def __init__(self, graph: DependencyGraph):
        """Initialize visualizer.

        Args:
            graph: Dependency graph to visualize
        """
        self.graph = graph

    def generate_function_graph(
        self,
        focus_function: str,
        file: str,
        max_depth: int = 2,
        highlight_impact: bool = True
    ) -> str:
        """Generate Mermaid diagram centered on a function.

        Creates a graph showing callers (upstream) and callees (downstream)
        of the focus function, with optional highlighting.

        Args:
            focus_function: Name of function to center diagram on
            file: File where focus function is defined
            max_depth: Maximum depth to traverse in each direction (default: 2)
            highlight_impact: Whether to highlight impacted nodes (default: True)

        Returns:
            Mermaid markdown string ready for rendering

        Example:
            ```mermaid
            graph TB
                caller1[caller_func] -->|calls| focus[focus_func]
                focus -->|calls| callee1[callee_func]

                classDef focus fill:#ff9
                class focus focus
            ```
        """
        lines = ["graph TB"]

        # Track nodes and edges to avoid duplicates
        nodes: Set[Tuple[str, str]] = set()
        edges: Set[Tuple[str, str, str, str]] = set()

        # Add focus function
        focus_key = (file, focus_function)
        focus_id = self._make_node_id(file, focus_function)
        nodes.add(focus_key)

        # Find upstream (callers) - traversal with depth
        upstream_nodes = self._collect_upstream(file, focus_function, max_depth)
        for caller_file, caller_func, call_line in upstream_nodes:
            caller_key = (caller_file, caller_func)
            nodes.add(caller_key)
            edges.add((caller_file, caller_func, file, focus_function))

        # Find downstream (callees) - traversal with depth
        downstream_nodes = self._collect_downstream(file, focus_function, max_depth)
        for callee_file, callee_func, call_line in downstream_nodes:
            callee_key = (callee_file, callee_func)
            nodes.add(callee_key)
            edges.add((file, focus_function, callee_file, callee_func))

        # Generate node declarations
        lines.append("")
        lines.append("    %% Nodes")
        for node_file, node_func in sorted(nodes):
            node_id = self._make_node_id(node_file, node_func)
            label = self._make_node_label(node_file, node_func)
            lines.append(f"    {node_id}[{label}]")

        # Generate edges
        lines.append("")
        lines.append("    %% Edges")
        for src_file, src_func, dst_file, dst_func in sorted(edges):
            src_id = self._make_node_id(src_file, src_func)
            dst_id = self._make_node_id(dst_file, dst_func)
            lines.append(f"    {src_id} -->|calls| {dst_id}")

        # Add styling if highlighting enabled
        if highlight_impact:
            lines.append("")
            lines.append("    %% Styling")
            lines.append("    classDef focus fill:#ff9,stroke:#333,stroke-width:3px")
            lines.append("    classDef caller fill:#f96,stroke:#333,stroke-width:2px")
            lines.append("    classDef callee fill:#9cf,stroke:#333,stroke-width:2px")

            # Apply focus style
            lines.append(f"    class {focus_id} focus")

            # Apply caller styles (upstream)
            caller_ids = [
                self._make_node_id(f, fn)
                for f, fn, _ in upstream_nodes
            ]
            if caller_ids:
                lines.append(f"    class {','.join(caller_ids)} caller")

            # Apply callee styles (downstream)
            callee_ids = [
                self._make_node_id(f, fn)
                for f, fn, _ in downstream_nodes
            ]
            if callee_ids:
                lines.append(f"    class {','.join(callee_ids)} callee")

        return "\n".join(lines)

    def generate_module_graph(
        self,
        file: str,
        include_imports: bool = True
    ) -> str:
        """Generate Mermaid diagram for all functions in a file.

        Shows internal function calls within a module and optionally
        external imports.

        Args:
            file: File path to visualize
            include_imports: Whether to show imported functions (default: True)

        Returns:
            Mermaid markdown string
        """
        lines = ["graph TB"]

        # Get all functions in the file
        functions = self.graph.get_all_functions_in_file(file)

        if not functions:
            return "graph TB\n    note[No functions found in file]"

        # Track nodes and edges
        nodes: Set[Tuple[str, str]] = set()
        edges: Set[Tuple[str, str, str, str]] = set()

        # Add all functions in the file as nodes
        for func in functions:
            nodes.add((file, func.name))

            # Get callees of each function
            callees = self.graph.get_callees(file, func.name)
            for callee_file, callee_func, _ in callees:
                # Internal call or external?
                if callee_file == file:
                    # Internal call
                    nodes.add((callee_file, callee_func))
                    edges.add((file, func.name, callee_file, callee_func))
                elif include_imports:
                    # External call
                    nodes.add((callee_file, callee_func))
                    edges.add((file, func.name, callee_file, callee_func))

        # Generate node declarations
        lines.append("")
        lines.append("    %% Nodes")
        for node_file, node_func in sorted(nodes):
            node_id = self._make_node_id(node_file, node_func)
            label = self._make_node_label(node_file, node_func)

            # Different shape for external functions
            if node_file == file:
                lines.append(f"    {node_id}[{label}]")
            else:
                # External function - use different bracket style
                lines.append(f"    {node_id}({label})")

        # Generate edges
        lines.append("")
        lines.append("    %% Edges")
        for src_file, src_func, dst_file, dst_func in sorted(edges):
            src_id = self._make_node_id(src_file, src_func)
            dst_id = self._make_node_id(dst_file, dst_func)
            lines.append(f"    {src_id} --> {dst_id}")

        # Add styling
        lines.append("")
        lines.append("    %% Styling")
        lines.append("    classDef internal fill:#9cf,stroke:#333,stroke-width:2px")
        lines.append("    classDef external fill:#ccc,stroke:#333,stroke-width:1px")

        # Apply styles
        internal_ids = [
            self._make_node_id(file, func.name)
            for func in functions
        ]
        if internal_ids:
            lines.append(f"    class {','.join(internal_ids)} internal")

        external_ids = [
            self._make_node_id(f, fn)
            for f, fn in nodes
            if f != file
        ]
        if external_ids:
            lines.append(f"    class {','.join(external_ids)} external")

        return "\n".join(lines)

    def save_to_file(self, mermaid_code: str, output_path: Path) -> None:
        """Save Mermaid diagram to a markdown file.

        Args:
            mermaid_code: Mermaid diagram code
            output_path: Path where to save the .md file
        """
        content = f"""# Dependency Graph

```mermaid
{mermaid_code}
```
"""
        output_path.write_text(content, encoding="utf-8")

    def _make_node_id(self, file: str, function: str) -> str:
        """Create a valid Mermaid node ID from file and function.

        Args:
            file: File path
            function: Function name

        Returns:
            Valid node ID for Mermaid
        """
        # Sanitize file path - extract just filename
        filename = Path(file).stem

        # Create ID: filename_functionname
        # Replace any non-alphanumeric characters with underscores
        node_id = f"{filename}_{function}".replace("-", "_").replace(".", "_")

        # Remove any remaining invalid characters
        node_id = "".join(c if c.isalnum() or c == "_" else "_" for c in node_id)

        return node_id

    def _make_node_label(self, file: str, function: str) -> str:
        """Create a human-readable label for a node.

        Args:
            file: File path
            function: Function name

        Returns:
            Display label for the node
        """
        filename = Path(file).name
        return f"{function}<br/><small>{filename}</small>"

    def _collect_upstream(
        self,
        file: str,
        function: str,
        max_depth: int
    ) -> Set[Tuple[str, str, int]]:
        """Collect all upstream callers up to max_depth.

        Args:
            file: File where function is defined
            function: Function name
            max_depth: Maximum depth to traverse

        Returns:
            Set of (file, function, line) tuples
        """
        results: Set[Tuple[str, str, int]] = set()
        visited: Set[Tuple[str, str]] = set()
        queue = [(file, function, 0)]

        while queue:
            current_file, current_func, depth = queue.pop(0)
            current_key = (current_file, current_func)

            if current_key in visited or depth >= max_depth:
                continue

            visited.add(current_key)

            callers = self.graph.get_callers(current_file, current_func)
            for caller_file, caller_func, call_line in callers:
                results.add((caller_file, caller_func, call_line))
                queue.append((caller_file, caller_func, depth + 1))

        return results

    def _collect_downstream(
        self,
        file: str,
        function: str,
        max_depth: int
    ) -> Set[Tuple[str, str, int]]:
        """Collect all downstream callees up to max_depth.

        Args:
            file: File where function is defined
            function: Function name
            max_depth: Maximum depth to traverse

        Returns:
            Set of (file, function, line) tuples
        """
        results: Set[Tuple[str, str, int]] = set()
        visited: Set[Tuple[str, str]] = set()
        queue = [(file, function, 0)]

        while queue:
            current_file, current_func, depth = queue.pop(0)
            current_key = (current_file, current_func)

            if current_key in visited or depth >= max_depth:
                continue

            visited.add(current_key)

            callees = self.graph.get_callees(current_file, current_func)
            for callee_file, callee_func, call_line in callees:
                results.add((callee_file, callee_func, call_line))
                queue.append((callee_file, callee_func, depth + 1))

        return results
