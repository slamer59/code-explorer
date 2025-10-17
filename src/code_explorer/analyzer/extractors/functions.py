"""
Function extraction from Tree-sitter.

Extracts function definitions and function calls using Tree-sitter AST.
"""

import logging
from typing import Any, List, Optional, Tuple

from code_explorer.analyzer.extractors.base import BaseExtractor
from code_explorer.analyzer.models import FileAnalysis, FunctionCall, FunctionInfo
from code_explorer.analyzer.tree_sitter_adapter import walk_tree

logger = logging.getLogger(__name__)


class FunctionExtractor(BaseExtractor):
    """Extracts function definitions and function calls from Tree-sitter."""

    def extract(self, tree: Any, result: FileAnalysis) -> None:
        """Extract function definitions and calls from Tree-sitter tree.

        Args:
            tree: Tree-sitter root node
            result: FileAnalysis to populate
        """
        # Use cached source lines if available, otherwise read file
        source_lines = result._source_lines
        if source_lines is None:
            try:
                with open(result.file_path, "r", encoding="utf-8") as f:
                    source_lines = f.readlines()
            except Exception as e:
                logger.warning(f"Could not read source for {result.file_path}: {e}")

        # Extract function definitions
        self._extract_function_definitions(tree, result, source_lines)

        # Extract function calls
        self._extract_function_calls(tree, result)

    def _extract_function_definitions(
        self, tree: Any, result: FileAnalysis, source_lines: Optional[List[str]]
    ) -> None:
        """Extract function definitions from Tree-sitter tree.

        Args:
            tree: Tree-sitter root node
            result: FileAnalysis to populate
            source_lines: Source code lines for extracting source code
        """
        for node in walk_tree(tree):
            # Check if this is a function_definition node
            if hasattr(node, "type") and node.type == "function_definition":
                self._extract_function_info(node, result, source_lines)

    def _extract_function_info(
        self, node: Any, result: FileAnalysis, source_lines: Optional[List[str]]
    ) -> None:
        """Extract function information from a Tree-sitter function_definition node.

        Args:
            node: Tree-sitter function_definition node
            result: FileAnalysis to populate
            source_lines: Source code lines for extracting source code
        """
        # Extract function name using child_by_field_name
        name_node = node.child_by_field_name("name") if hasattr(node, "child_by_field_name") else None

        if name_node is None:
            logger.warning(f"Function definition without name at line {node.start_point[0] + 1}")
            return

        # Get function name from the identifier node
        try:
            func_name = name_node.text.decode("utf-8") if isinstance(name_node.text, bytes) else name_node.text
        except Exception as e:
            logger.warning(f"Could not extract function name: {e}")
            return

        # Extract line numbers (Tree-sitter uses 0-based lines, we need 1-based)
        start_line = node.start_point[0] + 1 if hasattr(node, "start_point") else 0
        end_line = node.end_point[0] + 1 if hasattr(node, "end_point") else start_line

        # Extract source code if available
        source_code = None
        if source_lines and start_line > 0 and end_line > 0:
            try:
                # Convert to 0-based indexing for list slicing
                func_lines = source_lines[start_line - 1 : end_line]
                source_code = "".join(func_lines)
            except Exception as e:
                logger.warning(f"Could not extract source for {func_name}: {e}")

        func_info = FunctionInfo(
            name=func_name,
            file=result.file_path,
            start_line=start_line,
            end_line=end_line,
            is_public=not func_name.startswith("_"),
            source_code=source_code,
            parent_class=None,  # Will be updated by ClassExtractor
        )
        result.functions.append(func_info)

    def _extract_function_calls(self, tree: Any, result: FileAnalysis) -> None:
        """Extract function calls from Tree-sitter tree.

        Traverses the tree to find all function calls and links them to their
        containing function.

        Args:
            tree: Tree-sitter root node
            result: FileAnalysis to populate
        """
        # Build a map of current function context during traversal
        current_function_stack: List[str] = []

        # First pass: collect all function definitions and their positions
        func_positions: dict[Tuple[int, int], str] = {}
        for node in walk_tree(tree):
            if hasattr(node, "type") and node.type == "function_definition":
                name_node = node.child_by_field_name("name") if hasattr(node, "child_by_field_name") else None
                if name_node:
                    try:
                        func_name = name_node.text.decode("utf-8") if isinstance(name_node.text, bytes) else name_node.text
                        start_line = node.start_point[0] + 1 if hasattr(node, "start_point") else 0
                        end_line = node.end_point[0] + 1 if hasattr(node, "end_point") else start_line
                        func_positions[(start_line, end_line)] = func_name
                    except Exception:
                        pass

        # Second pass: find function calls and determine their context
        for node in walk_tree(tree):
            if hasattr(node, "type") and node.type == "call":
                call_line = node.start_point[0] + 1 if hasattr(node, "start_point") else 0

                # Find which function contains this call
                caller_name = self._find_containing_function(call_line, func_positions)
                if not caller_name:
                    continue

                # Extract the called function name
                called_name = self._extract_call_name(node)
                if called_name:
                    call_info = FunctionCall(
                        caller_function=caller_name,
                        called_name=called_name,
                        call_line=call_line,
                    )
                    result.function_calls.append(call_info)

    def _find_containing_function(
        self, line: int, func_positions: dict[Tuple[int, int], str]
    ) -> Optional[str]:
        """Find the function that contains a given line number.

        Args:
            line: Line number to check
            func_positions: Map of (start_line, end_line) to function name

        Returns:
            Function name or None if not in a function
        """
        for (start_line, end_line), func_name in func_positions.items():
            if start_line <= line <= end_line:
                return func_name
        return None

    def _extract_call_name(self, call_node: Any) -> Optional[str]:
        """Extract the name of the called function from a Tree-sitter call node.

        Args:
            call_node: Tree-sitter call node

        Returns:
            Function name or None
        """
        if not hasattr(call_node, "children") or len(call_node.children) == 0:
            return None

        # The first child of a call node is typically the function being called
        func_node = call_node.children[0]

        try:
            if hasattr(func_node, "type"):
                if func_node.type == "identifier":
                    # Simple function call: func()
                    text = func_node.text.decode("utf-8") if isinstance(func_node.text, bytes) else func_node.text
                    return text
                elif func_node.type == "attribute":
                    # Method call: obj.method()
                    # Get the attribute name (last child is usually the attribute)
                    if hasattr(func_node, "children") and len(func_node.children) > 0:
                        # For attribute access, the last child is typically the attribute name
                        attr_node = func_node.children[-1]
                        if hasattr(attr_node, "type") and attr_node.type == "identifier":
                            text = attr_node.text.decode("utf-8") if isinstance(attr_node.text, bytes) else attr_node.text
                            return text
                    # Fallback: try field_name access
                    attr_node = func_node.child_by_field_name("attribute") if hasattr(func_node, "child_by_field_name") else None
                    if attr_node:
                        text = attr_node.text.decode("utf-8") if isinstance(attr_node.text, bytes) else attr_node.text
                        return text
        except Exception as e:
            logger.debug(f"Could not extract call name: {e}")

        return None
