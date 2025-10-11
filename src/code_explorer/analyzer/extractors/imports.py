"""
Import extraction from AST.

Extracted from analyzer.py lines 503-760.
"""

import ast

from code_explorer.analyzer.extractors.base import BaseExtractor
from code_explorer.analyzer.models import (
    FileAnalysis,
    ImportDetailedInfo,
    ImportInfo,
)


class ImportExtractor(BaseExtractor):
    """Extracts import statements from AST."""

    def extract(self, tree: ast.AST, result: FileAnalysis) -> None:
        """Extract imports using ast.

        Extracted from _extract_imports_ast (lines 503-524) and
        _extract_imports_detailed (lines 718-760).

        Args:
            tree: AST tree
            result: FileAnalysis to populate
        """
        # Extract simple imports
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    import_info = ImportInfo(
                        module=alias.name, line_number=node.lineno, is_relative=False
                    )
                    result.imports.append(import_info)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    import_info = ImportInfo(
                        module=node.module,
                        line_number=node.lineno,
                        is_relative=node.level > 0,
                    )
                    result.imports.append(import_info)

        # Extract detailed imports
        self._extract_imports_detailed(tree, result)

    def _extract_imports_detailed(self, tree: ast.AST, result: FileAnalysis) -> None:
        """Extract detailed import information using ast.

        Extracted from _extract_imports_detailed (lines 718-760).

        Args:
            tree: AST tree
            result: FileAnalysis to populate
        """
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                # Handle: import module [as alias]
                for alias in node.names:
                    import_info = ImportDetailedInfo(
                        imported_name=alias.name,
                        import_type="module",
                        alias=alias.asname,
                        line_number=node.lineno,
                        is_relative=False,
                        module=None,
                    )
                    result.imports_detailed.append(import_info)
            elif isinstance(node, ast.ImportFrom):
                # Handle: from module import name [as alias]
                module_name = node.module or ""
                is_relative = node.level > 0

                for alias in node.names:
                    # Determine import type based on name
                    import_type = "unknown"
                    if alias.name == "*":
                        import_type = "*"
                    else:
                        # We'll try to infer type later, default to "unknown"
                        import_type = "unknown"

                    import_info = ImportDetailedInfo(
                        imported_name=alias.name,
                        import_type=import_type,
                        alias=alias.asname,
                        line_number=node.lineno,
                        is_relative=is_relative,
                        module=module_name if module_name else None,
                    )
                    result.imports_detailed.append(import_info)
