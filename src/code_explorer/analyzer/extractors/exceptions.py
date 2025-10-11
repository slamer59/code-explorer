"""
Exception extraction from AST.

Extracted from analyzer.py lines 1017-1132.
"""

import ast
from typing import Optional

from code_explorer.analyzer.extractors.base import BaseExtractor
from code_explorer.analyzer.models import ExceptionInfo, FileAnalysis


class ExceptionExtractor(BaseExtractor):
    """Extracts exception raising and handling from AST."""

    def extract(self, tree: ast.AST, result: FileAnalysis) -> None:
        """Extract exceptions using ast.

        Extracted from _extract_exceptions (lines 1120-1132).

        Args:
            tree: AST tree
            result: FileAnalysis to populate
        """
        # Find exceptions in functions
        for func_node in ast.walk(tree):
            if isinstance(func_node, ast.FunctionDef):
                func_name = func_node.name
                self._extract_raise_statements(func_node, func_name, result)
                self._extract_except_handlers(func_node, func_name, result)

    def _get_exception_name(self, exc_node: ast.AST) -> Optional[str]:
        """Extract exception name from exception node.

        Extracted from _get_exception_name (lines 1017-1039).

        Args:
            exc_node: AST node representing exception

        Returns:
            Exception name or None
        """
        if isinstance(exc_node, ast.Name):
            return exc_node.id
        elif isinstance(exc_node, ast.Call) and isinstance(exc_node.func, ast.Name):
            return exc_node.func.id
        elif isinstance(exc_node, ast.Attribute):
            try:
                return ast.unparse(exc_node)
            except Exception:
                return exc_node.attr
        else:
            try:
                return ast.unparse(exc_node)
            except Exception:
                return None

    def _extract_raise_statements(
        self, func_node: ast.FunctionDef, func_name: str, result: FileAnalysis
    ) -> None:
        """Extract raise statements from a function node.

        Extracted from _extract_raise_statements (lines 1041-1073).

        Args:
            func_node: Function AST node
            func_name: Name of the function
            result: FileAnalysis to populate
        """
        for node in ast.walk(func_node):
            if isinstance(node, ast.Raise):
                if node.exc:
                    exc_name = self._get_exception_name(node.exc)
                    if exc_name:
                        exc_info = ExceptionInfo(
                            name=exc_name,
                            file=result.file_path,
                            line_number=node.lineno,
                            context="raise",
                            function_name=func_name,
                        )
                        result.exceptions.append(exc_info)
                else:
                    # Bare raise (re-raise)
                    exc_info = ExceptionInfo(
                        name="<bare-raise>",
                        file=result.file_path,
                        line_number=node.lineno,
                        context="raise",
                        function_name=func_name,
                    )
                    result.exceptions.append(exc_info)

    def _extract_except_handlers(
        self, func_node: ast.FunctionDef, func_name: str, result: FileAnalysis
    ) -> None:
        """Extract except handlers from a function node.

        Extracted from _extract_except_handlers (lines 1075-1118).

        Args:
            func_node: Function AST node
            func_name: Name of the function
            result: FileAnalysis to populate
        """
        for node in ast.walk(func_node):
            if isinstance(node, ast.ExceptHandler):
                if node.type:
                    # Handle multiple exception types in tuple
                    exc_names = []
                    if isinstance(node.type, ast.Tuple):
                        for elt in node.type.elts:
                            exc_name = self._get_exception_name(elt)
                            if exc_name:
                                exc_names.append(exc_name)
                    else:
                        exc_name = self._get_exception_name(node.type)
                        if exc_name:
                            exc_names.append(exc_name)

                    for exc_name in exc_names:
                        exc_info = ExceptionInfo(
                            name=exc_name,
                            file=result.file_path,
                            line_number=node.lineno,
                            context="catch",
                            function_name=func_name,
                        )
                        result.exceptions.append(exc_info)
                else:
                    # Bare except
                    exc_info = ExceptionInfo(
                        name="<bare-except>",
                        file=result.file_path,
                        line_number=node.lineno,
                        context="catch",
                        function_name=func_name,
                    )
                    result.exceptions.append(exc_info)
