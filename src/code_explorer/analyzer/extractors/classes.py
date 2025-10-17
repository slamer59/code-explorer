"""
Class extraction from AST and Tree-sitter.

Extracted from analyzer.py lines 411-501.
Enhanced to support both standard AST and Tree-sitter parsing.
"""

import ast
import logging
from typing import Any, List, Optional, Tuple, Union

from code_explorer.analyzer.extractors.base import BaseExtractor
from code_explorer.analyzer.models import ClassInfo, FileAnalysis
from code_explorer.analyzer.tree_sitter_adapter import detect_parser_type, walk_tree

logger = logging.getLogger(__name__)


class ClassExtractor(BaseExtractor):
    """Extracts class definitions from AST and Tree-sitter."""

    def extract(self, tree: Union[ast.AST, Any], result: FileAnalysis) -> None:
        """Extract classes using AST or Tree-sitter.

        Extracted from _extract_classes_ast (lines 448-501).
        Enhanced to support both AST and Tree-sitter parsing.

        Args:
            tree: AST tree or Tree-sitter root node
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

        # Detect parser type and extract accordingly
        parser_type = detect_parser_type(tree)

        if parser_type == "tree_sitter":
            self._extract_classes_tree_sitter(tree, result, source_lines)
        else:
            self._extract_classes_ast(tree, result, source_lines)

    def _extract_classes_ast(
        self, tree: ast.AST, result: FileAnalysis, source_lines: Optional[List[str]]
    ) -> None:
        """Extract classes from AST tree.

        Args:
            tree: AST tree
            result: FileAnalysis to populate
            source_lines: Source code lines for extracting source code
        """
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                self._extract_class_from_ast(node, result, source_lines)

    def _extract_classes_tree_sitter(
        self, tree: Any, result: FileAnalysis, source_lines: Optional[List[str]]
    ) -> None:
        """Extract classes from Tree-sitter tree.

        Args:
            tree: Tree-sitter root node
            result: FileAnalysis to populate
            source_lines: Source code lines for extracting source code
        """
        for node in walk_tree(tree):
            # Check if this is a class_definition node
            if hasattr(node, "type") and node.type == "class_definition":
                self._extract_class_from_tree_sitter(node, result, source_lines)

    def _extract_class_from_tree_sitter(
        self, node: Any, result: FileAnalysis, source_lines: Optional[List[str]]
    ) -> None:
        """Extract class information from Tree-sitter class_definition node.

        Args:
            node: Tree-sitter class_definition node
            result: FileAnalysis to populate
            source_lines: Source code lines for extracting source code
        """
        # Extract class name using child_by_field_name
        name_node = (
            node.child_by_field_name("name")
            if hasattr(node, "child_by_field_name")
            else None
        )

        if name_node is None:
            start_line = node.start_point[0] + 1 if hasattr(node, "start_point") else 0
            logger.warning(f"Class definition without name at line {start_line}")
            return

        # Get class name from the identifier node
        try:
            class_name = (
                name_node.text.decode("utf-8")
                if isinstance(name_node.text, bytes)
                else name_node.text
            )
        except Exception as e:
            logger.warning(f"Could not extract class name: {e}")
            return

        # Extract base classes using Tree-sitter helper
        bases = self._parse_base_classes_tree_sitter(node)

        # Extract method information from class body
        method_info = self._extract_methods_tree_sitter(node)
        methods = [name for name, _ in method_info]

        # Link methods to this class using helper
        self._link_methods_to_class(method_info, class_name, result)

        # Extract line numbers (Tree-sitter uses 0-based lines, we need 1-based)
        start_line = node.start_point[0] + 1 if hasattr(node, "start_point") else 0
        end_line = node.end_point[0] + 1 if hasattr(node, "end_point") else start_line

        # Extract source code if available
        source_code = None
        if source_lines and start_line > 0 and end_line > 0:
            try:
                # Convert to 0-based indexing for list slicing
                class_lines = source_lines[start_line - 1 : end_line]
                source_code = "".join(class_lines)
            except Exception as e:
                logger.warning(f"Could not extract source for class {class_name}: {e}")

        class_info = ClassInfo(
            name=class_name,
            file=result.file_path,
            start_line=start_line,
            end_line=end_line,
            bases=bases,
            methods=methods,
            is_public=not class_name.startswith("_"),
            source_code=source_code,
        )

        result.classes.append(class_info)

    def _extract_class_from_ast(
        self, node: ast.ClassDef, result: FileAnalysis, source_lines: List[str]
    ) -> None:
        """Extract class information from AST ClassDef node (original implementation).

        Args:
            node: AST ClassDef node
            result: FileAnalysis to populate
            source_lines: Source code lines for extracting source code
        """
        # Extract base class names using helper
        bases = [self._parse_base_class_ast(base) for base in node.bases]

        # Extract method names and their line numbers
        method_info = [
            (item.name, item.lineno)
            for item in node.body
            if isinstance(item, ast.FunctionDef)
        ]
        methods = [name for name, _ in method_info]

        # Link methods to this class using helper
        self._link_methods_to_class(method_info, node.name, result)

        # Extract source code if available
        source_code = None
        if source_lines and node.lineno and node.end_lineno:
            try:
                # Extract lines (1-indexed to 0-indexed)
                class_lines = source_lines[node.lineno - 1 : node.end_lineno]
                source_code = "".join(class_lines)
            except Exception as e:
                logger.warning(f"Could not extract source for class {node.name}: {e}")

        class_info = ClassInfo(
            name=node.name,
            file=result.file_path,
            start_line=node.lineno,
            end_line=node.end_lineno or node.lineno,
            bases=bases,
            methods=methods,
            is_public=not node.name.startswith("_"),
            source_code=source_code,
        )
        result.classes.append(class_info)

    def _parse_base_classes_tree_sitter(self, node: Any) -> List[str]:
        """Parse base class expressions from Tree-sitter class_definition node.

        Tree-sitter represents inheritance using 'argument_list' field containing
        the base class expressions.

        Args:
            node: Tree-sitter class_definition node

        Returns:
            List of base class names as strings
        """
        bases = []

        # Tree-sitter uses 'superclasses' field for base classes
        superclasses = (
            node.child_by_field_name("superclasses")
            if hasattr(node, "child_by_field_name")
            else None
        )

        if (
            superclasses
            and hasattr(superclasses, "type")
            and superclasses.type == "argument_list"
        ):
            # Extract each base class from the argument list
            if hasattr(superclasses, "children"):
                for child in superclasses.children:
                    if hasattr(child, "type"):
                        if child.type == "identifier":
                            # Simple base class like "ClassName"
                            try:
                                text = (
                                    child.text.decode("utf-8")
                                    if isinstance(child.text, bytes)
                                    else child.text
                                )
                                bases.append(text)
                            except Exception as e:
                                logger.warning(
                                    f"Could not extract base class name: {e}"
                                )
                        elif child.type in ("attribute", "subscript", "call"):
                            # Complex base class expressions
                            try:
                                text = (
                                    child.text.decode("utf-8")
                                    if isinstance(child.text, bytes)
                                    else child.text
                                )
                                bases.append(text)
                            except Exception as e:
                                logger.warning(
                                    f"Could not extract base class expression: {e}"
                                )
                        elif child.type == "string":
                            # String-based base class (rare but possible)
                            try:
                                text = (
                                    child.text.decode("utf-8")
                                    if isinstance(child.text, bytes)
                                    else child.text
                                )
                                bases.append(text.strip("\"'"))
                            except Exception as e:
                                logger.warning(
                                    f"Could not extract string base class: {e}"
                                )
        elif superclasses:
            # Single base class (not in argument list)
            try:
                text = (
                    superclasses.text.decode("utf-8")
                    if isinstance(superclasses.text, bytes)
                    else superclasses.text
                )
                bases.append(text)
            except Exception as e:
                logger.warning(f"Could not extract single base class: {e}")

        return bases

    def _parse_base_class_ast(self, base: ast.expr) -> str:
        """Parse a base class expression to extract its name (AST version).

        Extracted from _parse_base_class (lines 411-427).

        Args:
            base: AST expression node representing a base class

        Returns:
            String representation of the base class name
        """
        if isinstance(base, ast.Name):
            return base.id
        else:
            # For complex base expressions, use unparse
            try:
                return ast.unparse(base)
            except Exception:
                return "<complex>"

    def _extract_methods_tree_sitter(self, node: Any) -> List[Tuple[str, int]]:
        """Extract method information from Tree-sitter class body.

        Args:
            node: Tree-sitter class_definition node

        Returns:
            List of tuples containing (method_name, line_number)
        """
        method_info = []

        # Get the class body (Tree-sitter uses 'body' field)
        body = (
            node.child_by_field_name("body")
            if hasattr(node, "child_by_field_name")
            else None
        )
        if not body or not hasattr(body, "children"):
            return method_info

        # Look for function definitions in the class body
        for child in body.children:
            if hasattr(child, "type") and child.type == "function_definition":
                # Extract method name
                name_node = (
                    child.child_by_field_name("name")
                    if hasattr(child, "child_by_field_name")
                    else None
                )
                if name_node:
                    try:
                        method_name = (
                            name_node.text.decode("utf-8")
                            if isinstance(name_node.text, bytes)
                            else name_node.text
                        )
                        method_line = (
                            child.start_point[0] + 1
                            if hasattr(child, "start_point")
                            else 0
                        )
                        if method_name and method_line > 0:
                            method_info.append((method_name, method_line))
                    except Exception as e:
                        logger.warning(f"Could not extract method information: {e}")

        return method_info

    def _link_methods_to_class(
        self, methods: List[Tuple[str, int]], class_name: str, result: FileAnalysis
    ) -> None:
        """Link method names to their parent class in FunctionInfo objects.

        Extracted from _link_methods_to_class (lines 429-446).
        Works with both AST and Tree-sitter extracted function information.

        Args:
            methods: List of tuples containing (method_name, line_number)
            class_name: Name of the parent class
            result: FileAnalysis object to update
        """
        for method_name, method_line in methods:
            for func_info in result.functions:
                if (
                    func_info.name == method_name
                    and func_info.start_line == method_line
                ):
                    func_info.parent_class = class_name
                    break
