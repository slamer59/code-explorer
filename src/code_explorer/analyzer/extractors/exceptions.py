"""
Exception extraction from AST and Tree-sitter.

Supports both standard Python AST and Tree-sitter parsing.
Extracted from analyzer.py lines 1017-1132.
"""

import ast
import logging
from typing import Optional, Union, Any, List

from code_explorer.analyzer.extractors.base import BaseExtractor
from code_explorer.analyzer.models import ExceptionInfo, FileAnalysis
from code_explorer.analyzer.parser import get_parser_type

try:
    from code_explorer.analyzer.tree_sitter_adapter import (
        TreeSitterAdapter, TreeSitterNode, get_tree_sitter_adapter, walk_tree
    )
    TREE_SITTER_AVAILABLE = True
except ImportError:
    TREE_SITTER_AVAILABLE = False
    TreeSitterAdapter = None
    TreeSitterNode = None
    walk_tree = None

logger = logging.getLogger(__name__)


class ExceptionExtractor(BaseExtractor):
    """Extracts exception raising and handling from AST and Tree-sitter."""

    def extract(self, tree: Union[ast.AST, Any], result: FileAnalysis) -> None:
        """Extract exceptions using AST or Tree-sitter.

        Extracted from _extract_exceptions (lines 1120-1132).

        Args:
            tree: AST tree or Tree-sitter root node
            result: FileAnalysis to populate
        """
        # Detect parser type and use appropriate extraction method
        parser_type = get_parser_type(tree)

        if parser_type == "tree_sitter":
            self._extract_tree_sitter(tree, result)
        else:
            self._extract_ast(tree, result)

    def _extract_ast(self, tree: ast.AST, result: FileAnalysis) -> None:
        """Extract exceptions using standard AST.

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

    def _extract_tree_sitter(self, root_node: TreeSitterNode, result: FileAnalysis) -> None:
        """Extract exceptions using Tree-sitter.

        Args:
            root_node: Tree-sitter root node
            result: FileAnalysis to populate
        """
        if not TREE_SITTER_AVAILABLE or walk_tree is None:
            logger.warning("Tree-sitter not available, falling back to AST")
            return

        try:
            # Walk the tree looking for function definitions
            for node in walk_tree(root_node):
                # Check if this is a function_definition node
                if hasattr(node, "type") and node.type == "function_definition":
                    func_name_child = node.child_by_field_name("name") if hasattr(node, "child_by_field_name") else None
                    if func_name_child and hasattr(func_name_child, "text"):
                        try:
                            func_name = func_name_child.text.decode('utf8') if isinstance(func_name_child.text, bytes) else func_name_child.text
                            self._extract_raise_statements_tree_sitter(node, func_name, result)
                            self._extract_except_handlers_tree_sitter(node, func_name, result)
                        except Exception as e:
                            logger.debug(f"Error processing function {func_name}: {e}")

                # Also extract raise statements and except clauses at module level
                elif hasattr(node, "type") and node.type == "raise_statement":
                    self._process_raise_statement_tree_sitter(node, None, result)
                elif hasattr(node, "type") and node.type == "except_clause":
                    self._process_except_clause_tree_sitter(node, None, result)
        except Exception as e:
            logger.error(f"Tree-sitter exception extraction failed: {e}")
            raise

    def _extract_raise_statements_tree_sitter(
        self, func_node: Any, func_name: str, result: FileAnalysis
    ) -> None:
        """Extract raise statements from within a Tree-sitter function node.

        Args:
            func_node: Tree-sitter function_definition node
            func_name: Name of the function
            result: FileAnalysis to populate
        """
        # Get function body
        body_node = func_node.child_by_field_name("body") if hasattr(func_node, "child_by_field_name") else None
        if not body_node:
            return

        # Walk children looking for raise_statement nodes
        self._walk_for_raise_statements(body_node, func_name, result)

    def _walk_for_raise_statements(
        self, node: Any, func_name: Optional[str], result: FileAnalysis
    ) -> None:
        """Recursively walk node looking for raise_statement nodes.

        Args:
            node: Tree-sitter node to walk
            func_name: Name of the function (if in function context)
            result: FileAnalysis to populate
        """
        # Check if this node is a raise_statement
        if hasattr(node, "type") and node.type == "raise_statement":
            self._process_raise_statement_tree_sitter(node, func_name, result)

        # Recursively walk children
        if hasattr(node, "children"):
            for child in node.children:
                self._walk_for_raise_statements(child, func_name, result)

    def _extract_except_handlers_tree_sitter(
        self, func_node: Any, func_name: str, result: FileAnalysis
    ) -> None:
        """Extract except handlers from within a Tree-sitter function node.

        Args:
            func_node: Tree-sitter function_definition node
            func_name: Name of the function
            result: FileAnalysis to populate
        """
        # Get function body
        body_node = func_node.child_by_field_name("body") if hasattr(func_node, "child_by_field_name") else None
        if not body_node:
            return

        # Walk children looking for except_clause nodes
        self._walk_for_except_clauses(body_node, func_name, result)

    def _walk_for_except_clauses(
        self, node: Any, func_name: Optional[str], result: FileAnalysis
    ) -> None:
        """Recursively walk node looking for except_clause nodes.

        Args:
            node: Tree-sitter node to walk
            func_name: Name of the function (if in function context)
            result: FileAnalysis to populate
        """
        # Check if this node is an except_clause
        if hasattr(node, "type") and node.type == "except_clause":
            self._process_except_clause_tree_sitter(node, func_name, result)

        # Recursively walk children
        if hasattr(node, "children"):
            for child in node.children:
                self._walk_for_except_clauses(child, func_name, result)

    def _process_raise_statement_tree_sitter(
        self, raise_node: Any, func_name: Optional[str], result: FileAnalysis
    ) -> None:
        """Process a raise_statement node from Tree-sitter.

        Args:
            raise_node: Tree-sitter raise_statement node
            func_name: Function name (if in function context) or None
            result: FileAnalysis to populate
        """
        exception_node = raise_node.child_by_field_name("exception") if hasattr(raise_node, "child_by_field_name") else None

        # Get line number from start_point
        lineno = 0
        if hasattr(raise_node, "start_point"):
            lineno = raise_node.start_point[0] + 1

        if exception_node:
            exc_name = self._get_exception_name_tree_sitter(exception_node)
            if exc_name:
                exc_info = ExceptionInfo(
                    name=exc_name,
                    file=result.file_path,
                    line_number=lineno,
                    context="raise",
                    function_name=func_name,
                )
                result.exceptions.append(exc_info)
        else:
            # Bare raise (re-raise)
            exc_info = ExceptionInfo(
                name="<bare-raise>",
                file=result.file_path,
                line_number=lineno,
                context="raise",
                function_name=func_name,
            )
            result.exceptions.append(exc_info)

    def _process_except_clause_tree_sitter(
        self, except_node: Any, func_name: Optional[str], result: FileAnalysis
    ) -> None:
        """Process an except_clause node from Tree-sitter.

        Args:
            except_node: Tree-sitter except_clause node
            func_name: Function name (if in function context) or None
            result: FileAnalysis to populate
        """
        # Extract exception types from the except clause
        exc_type_node = except_node.child_by_field_name("type") if hasattr(except_node, "child_by_field_name") else None

        # Get line number from start_point
        lineno = 0
        if hasattr(except_node, "start_point"):
            lineno = except_node.start_point[0] + 1

        exc_names = []
        if exc_type_node:
            exc_names = self._extract_exception_types_tree_sitter(exc_type_node)
        else:
            # Bare except (no type specified)
            exc_names = ["<bare-except>"]

        # Record all caught exception types
        for exc_name in exc_names:
            exc_info = ExceptionInfo(
                name=exc_name,
                file=result.file_path,
                line_number=lineno,
                context="catch",
                function_name=func_name,
            )
            result.exceptions.append(exc_info)

    def _get_exception_name_tree_sitter(self, exc_node: Any) -> Optional[str]:
        """Extract exception name from a raw Tree-sitter exception node.

        Args:
            exc_node: Tree-sitter exception node

        Returns:
            Exception name or None
        """
        if not hasattr(exc_node, "type"):
            return None

        node_type = exc_node.type

        if node_type == "identifier":
            try:
                return exc_node.text.decode('utf8') if isinstance(exc_node.text, bytes) else exc_node.text
            except Exception:
                pass
        elif node_type == "call":
            # Exception instantiation like ValueError("message")
            func_node = exc_node.child_by_field_name("function") if hasattr(exc_node, "child_by_field_name") else None
            if func_node and hasattr(func_node, "type") and func_node.type == "identifier":
                try:
                    return func_node.text.decode('utf8') if isinstance(func_node.text, bytes) else func_node.text
                except Exception:
                    pass
            elif func_node:
                # Could be module.ExceptionType()
                return self._get_exception_name_tree_sitter(func_node)
        elif node_type == "attribute":
            # Attribute like module.ExceptionType
            try:
                return exc_node.text.decode('utf8') if isinstance(exc_node.text, bytes) else exc_node.text
            except Exception:
                # Try to get attribute name
                attr_child = exc_node.child_by_field_name("attribute") if hasattr(exc_node, "child_by_field_name") else None
                if attr_child and hasattr(attr_child, "text"):
                    try:
                        return attr_child.text.decode('utf8') if isinstance(attr_child.text, bytes) else attr_child.text
                    except Exception:
                        pass
        else:
            # Try to get the text representation as fallback
            try:
                return exc_node.text.decode('utf8') if isinstance(exc_node.text, bytes) else exc_node.text
            except Exception:
                pass

        return None

    def _extract_exception_types_tree_sitter(self, exc_type_node: Any) -> List[str]:
        """Extract exception type names from a raw Tree-sitter exception type node.

        Handles single exceptions and tuples of exceptions.

        Args:
            exc_type_node: Tree-sitter exception type node

        Returns:
            List of exception names
        """
        exc_names = []

        if not hasattr(exc_type_node, "type"):
            return exc_names

        # Check if it's a tuple of exceptions
        if exc_type_node.type == "tuple":
            if hasattr(exc_type_node, "children"):
                for child in exc_type_node.children:
                    child_type = child.type if hasattr(child, "type") else None
                    if child_type in ("identifier", "attribute", "call"):
                        exc_name = self._get_exception_name_tree_sitter(child)
                        if exc_name:
                            exc_names.append(exc_name)
        else:
            # Single exception
            exc_name = self._get_exception_name_tree_sitter(exc_type_node)
            if exc_name:
                exc_names.append(exc_name)

        return exc_names

    def _tree_sitter_get_exception_name(self, exc_node: TreeSitterAdapter) -> Optional[str]:
        """Extract exception name from exception node.

        Extracted from _get_exception_name (lines 1017-1039).

        Args:
            exc_node: Tree-sitter exception node

        Returns:
            Exception name or None
        """
        if exc_node.node_type == "identifier":
            return exc_node.get_original_node().text.decode('utf8')
        elif exc_node.node_type == "call":
            # Exception instantiation like ValueError("message")
            func_node = exc_node.child_by_field_name("function")
            if func_node and func_node.node_type == "identifier":
                return func_node.get_original_node().text.decode('utf8')
            elif func_node:
                # Could be module.ExceptionType()
                return self._tree_sitter_get_exception_name(func_node)
        elif exc_node.node_type == "attribute":
            # Attribute like module.ExceptionType
            try:
                return exc_node.get_original_node().text.decode('utf8')
            except Exception:
                attr_child = exc_node.child_by_field_name("attr")
                if attr_child:
                    return attr_child.get_original_node().text.decode('utf8')
        else:
            # Try to get the text representation as fallback
            try:
                return exc_node.get_original_node().text.decode('utf8')
            except Exception:
                pass

        return None

    def _tree_sitter_extract_exception_types(self, exc_type_node: TreeSitterAdapter) -> List[str]:
        """Extract exception type names from exception type node.

        Handles single exceptions and tuples of exceptions.

        Args:
            exc_type_node: Tree-sitter exception type node

        Returns:
            List of exception names
        """
        exc_names = []

        # Check if it's a tuple of exceptions
        if exc_type_node.node_type == "tuple":
            for child in exc_type_node.children:
                if child.node_type in ("identifier", "attribute", "call"):
                    exc_name = self._tree_sitter_get_exception_name(child)
                    if exc_name:
                        exc_names.append(exc_name)
        else:
            # Single exception
            exc_name = self._tree_sitter_get_exception_name(exc_type_node)
            if exc_name:
                exc_names.append(exc_name)

        return exc_names

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
