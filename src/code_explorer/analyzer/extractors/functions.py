"""
Function extraction from AST.

Extracted from analyzer.py lines 373-604.
"""

import ast
import logging
from typing import Optional

import astroid
from astroid.nodes import Attribute, Call, FunctionDef, Module, Name

from code_explorer.analyzer.extractors.base import BaseExtractor
from code_explorer.analyzer.models import FileAnalysis, FunctionCall, FunctionInfo

logger = logging.getLogger(__name__)


class FunctionExtractor(BaseExtractor):
    """Extracts function definitions and function calls from AST."""

    def extract(self, tree: ast.AST, result: FileAnalysis) -> None:
        """Extract functions using ast.

        Extracted from _extract_functions_ast (lines 373-409).

        Args:
            tree: AST tree
            result: FileAnalysis to populate
        """
        # Read file to extract source code
        source_lines = None
        try:
            with open(result.file_path, "r", encoding="utf-8") as f:
                source_lines = f.readlines()
        except Exception as e:
            logger.warning(f"Could not read source for {result.file_path}: {e}")

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                # Extract source code if available
                source_code = None
                if source_lines and node.lineno and node.end_lineno:
                    try:
                        # Extract lines (1-indexed to 0-indexed)
                        func_lines = source_lines[node.lineno - 1 : node.end_lineno]
                        source_code = "".join(func_lines)
                    except Exception as e:
                        logger.warning(f"Could not extract source for {node.name}: {e}")

                func_info = FunctionInfo(
                    name=node.name,
                    file=result.file_path,
                    start_line=node.lineno,
                    end_line=node.end_lineno or node.lineno,
                    is_public=not node.name.startswith("_"),
                    source_code=source_code,
                    parent_class=None,  # Will be updated by ClassExtractor
                )
                result.functions.append(func_info)

    def extract_function_calls_ast(self, tree: ast.AST, result: FileAnalysis) -> None:
        """Extract function calls using simple ast traversal.

        This is a fallback when astroid fails. It's less precise but more robust.
        Extracted from _extract_function_calls_ast (lines 526-557).

        Args:
            tree: AST tree
            result: FileAnalysis to populate
        """
        # Build a map of function nodes to their names
        function_nodes = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                function_nodes[id(node)] = node.name

        # Find calls within each function
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                caller_name = node.name
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        # Skip if lineno is None
                        if child.lineno is None:
                            continue
                        called_name = self._get_call_name(child.func)
                        if called_name:
                            call_info = FunctionCall(
                                caller_function=caller_name,
                                called_name=called_name,
                                call_line=child.lineno,
                            )
                            result.function_calls.append(call_info)

    def _get_call_name(self, node: ast.AST) -> Optional[str]:
        """Extract function name from a call node.

        Extracted from _get_call_name (lines 559-573).

        Args:
            node: AST node representing the called function

        Returns:
            Function name or None
        """
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            # For method calls like obj.method(), just return 'method'
            return node.attr
        return None

    def extract_function_calls_astroid(
        self, module: Module, result: FileAnalysis
    ) -> None:
        """Extract function calls using astroid for better name resolution.

        Extracted from _extract_function_calls_astroid (lines 575-604).

        Args:
            module: Astroid module
            result: FileAnalysis to populate
        """
        # Find all function definitions
        for node in module.nodes_of_class(FunctionDef):
            caller_name = node.name

            # Find all calls within this function
            for call_node in node.nodes_of_class(Call):
                called_name = None

                if isinstance(call_node.func, Name):
                    called_name = call_node.func.name
                elif isinstance(call_node.func, Attribute):
                    called_name = call_node.func.attrname

                # Skip if lineno is None (type safety)
                if called_name and call_node.lineno is not None:
                    call_info = FunctionCall(
                        caller_function=caller_name,
                        called_name=called_name,
                        call_line=call_node.lineno,
                    )
                    result.function_calls.append(call_info)
