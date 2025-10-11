"""
Class extraction from AST.

Extracted from analyzer.py lines 411-501.
"""

import ast
import logging
from typing import List, Tuple

from code_explorer.analyzer.extractors.base import BaseExtractor
from code_explorer.analyzer.models import ClassInfo, FileAnalysis

logger = logging.getLogger(__name__)


class ClassExtractor(BaseExtractor):
    """Extracts class definitions from AST."""

    def extract(self, tree: ast.AST, result: FileAnalysis) -> None:
        """Extract classes using ast.

        Extracted from _extract_classes_ast (lines 448-501).

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
            if isinstance(node, ast.ClassDef):
                # Extract base class names using helper
                bases = [self._parse_base_class(base) for base in node.bases]

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
                        logger.warning(
                            f"Could not extract source for class {node.name}: {e}"
                        )

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

    def _parse_base_class(self, base: ast.expr) -> str:
        """Parse a base class expression to extract its name.

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

    def _link_methods_to_class(
        self, methods: List[Tuple[str, int]], class_name: str, result: FileAnalysis
    ) -> None:
        """Link method names to their parent class in FunctionInfo objects.

        Extracted from _link_methods_to_class (lines 429-446).

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
