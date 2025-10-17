"""
Import extraction from AST and Tree-sitter.

Extracted from analyzer.py lines 503-760.
Enhanced to support both standard AST and Tree-sitter parsing.
"""

import ast
import logging
from typing import Any, Optional, Union

from code_explorer.analyzer.extractors.base import BaseExtractor
from code_explorer.analyzer.models import (
    FileAnalysis,
    ImportDetailedInfo,
    ImportInfo,
)
from code_explorer.analyzer.tree_sitter_adapter import detect_parser_type, walk_tree

logger = logging.getLogger(__name__)


class ImportExtractor(BaseExtractor):
    """Extracts import statements from AST and Tree-sitter."""

    def extract(self, tree: Union[ast.AST, Any], result: FileAnalysis) -> None:
        """Extract imports using AST or Tree-sitter.

        Extracted from _extract_imports_ast (lines 503-524) and
        _extract_imports_detailed (lines 718-760).
        Enhanced to support both AST and Tree-sitter parsing.

        Args:
            tree: AST tree or Tree-sitter node
            result: FileAnalysis to populate
        """
        # Detect parser type and extract accordingly
        parser_type = detect_parser_type(tree)

        if parser_type == "tree_sitter":
            # Use Tree-sitter extraction
            self._extract_imports_tree_sitter(tree, result)
            self._extract_imports_detailed_tree_sitter(tree, result)
        else:
            # Use standard AST extraction
            self._extract_imports_ast(tree, result)
            self._extract_imports_detailed_ast(tree, result)

    def _extract_imports_tree_sitter(self, tree: Any, result: FileAnalysis) -> None:
        """Extract simple imports using Tree-sitter.

        Tree-sitter node types:
        - import_statement: for 'import module [as alias]'
        - import_from_statement: for 'from module import name [as alias]'

        Args:
            tree: Tree-sitter root node
            result: FileAnalysis to populate
        """
        for node in walk_tree(tree):
            if hasattr(node, 'type') and node.type == 'import_statement':
                # Handle: import module [as alias]
                # Flatten dotted names from import_statement children
                if hasattr(node, 'children'):
                    for child in node.children:
                        if hasattr(child, 'type'):
                            if child.type == 'dotted_name':
                                try:
                                    module_name = child.text.decode('utf-8') if isinstance(child.text, bytes) else child.text
                                    import_info = ImportInfo(
                                        module=module_name,
                                        line_number=node.start_point[0] + 1 if hasattr(node, 'start_point') else 0,
                                        is_relative=False,
                                    )
                                    result.imports.append(import_info)
                                except Exception as e:
                                    logger.warning(f"Could not extract import module from dotted_name: {e}")
                            elif child.type == 'aliased_import':
                                # Handle aliased imports: import x as y
                                for alias_child in child.children:
                                    if hasattr(alias_child, 'type') and alias_child.type == 'dotted_name':
                                        try:
                                            module_name = alias_child.text.decode('utf-8') if isinstance(alias_child.text, bytes) else alias_child.text
                                            import_info = ImportInfo(
                                                module=module_name,
                                                line_number=node.start_point[0] + 1 if hasattr(node, 'start_point') else 0,
                                                is_relative=False,
                                            )
                                            result.imports.append(import_info)
                                        except Exception as e:
                                            logger.warning(f"Could not extract import module from aliased_import: {e}")

            elif hasattr(node, 'type') and node.type == 'import_from_statement':
                # Handle: from module import name [as alias]
                # Extract source module from dotted_name or identifier field
                module_name = None
                is_relative = False
                level = 0

                # Check for relative imports (dots)
                if hasattr(node, 'children'):
                    for child in node.children:
                        if hasattr(child, 'type'):
                            if child.type == 'import_keyword':
                                break
                            if child.type == '.':
                                level += 1

                is_relative = level > 0

                # Get the module name (if present)
                if hasattr(node, 'children'):
                    for child in node.children:
                        if hasattr(child, 'type'):
                            if child.type == 'dotted_name':
                                try:
                                    module_name = child.text.decode('utf-8') if isinstance(child.text, bytes) else child.text
                                except Exception as e:
                                    logger.warning(f"Could not extract from module name (dotted): {e}")
                                break
                            elif child.type == 'identifier':
                                try:
                                    module_name = child.text.decode('utf-8') if isinstance(child.text, bytes) else child.text
                                except Exception as e:
                                    logger.warning(f"Could not extract from module name (identifier): {e}")
                                break

                # Only add if we have a module name
                if module_name:
                    import_info = ImportInfo(
                        module=module_name,
                        line_number=node.start_point[0] + 1 if hasattr(node, 'start_point') else 0,
                        is_relative=is_relative,
                    )
                    result.imports.append(import_info)

    def _extract_imports_ast(self, tree: ast.AST, result: FileAnalysis) -> None:
        """Extract simple imports using standard AST.

        Args:
            tree: AST tree
            result: FileAnalysis to populate
        """
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

    def _extract_imports_detailed_tree_sitter(self, tree: Any, result: FileAnalysis) -> None:
        """Extract detailed import information using Tree-sitter.

        Args:
            tree: Tree-sitter root node
            result: FileAnalysis to populate
        """
        for node in walk_tree(tree):
            if hasattr(node, 'type') and node.type == 'import_statement':
                # Handle: import module [as alias]
                module_name = None
                alias_name = None

                # Extract from dotted_name or aliased_import
                if hasattr(node, 'children'):
                    for i, child in enumerate(node.children):
                        if hasattr(child, 'type'):
                            if child.type == 'dotted_name':
                                try:
                                    module_name = child.text.decode('utf-8') if isinstance(child.text, bytes) else child.text
                                    # Check if next token is 'as'
                                    if i + 1 < len(node.children) - 1:
                                        next_child = node.children[i + 1]
                                        if hasattr(next_child, 'type') and next_child.type == 'as' and i + 2 < len(node.children):
                                            alias_node = node.children[i + 2]
                                            if hasattr(alias_node, 'type') and alias_node.type == 'identifier':
                                                alias_name = alias_node.text.decode('utf-8') if isinstance(alias_node.text, bytes) else alias_node.text

                                    if module_name:
                                        import_info = ImportDetailedInfo(
                                            imported_name=module_name,
                                            import_type="module",
                                            alias=alias_name,
                                            line_number=node.start_point[0] + 1 if hasattr(node, 'start_point') else 0,
                                            is_relative=False,
                                            module=None,
                                        )
                                        result.imports_detailed.append(import_info)
                                        module_name = None
                                        alias_name = None
                                except Exception as e:
                                    logger.warning(f"Could not extract detailed import from dotted_name: {e}")

                            elif child.type == 'aliased_import':
                                # Extract from aliased_import node
                                if hasattr(child, 'children'):
                                    for alias_child in child.children:
                                        if hasattr(alias_child, 'type') and alias_child.type == 'dotted_name':
                                            try:
                                                module_name = alias_child.text.decode('utf-8') if isinstance(alias_child.text, bytes) else alias_child.text
                                                # Look for 'as' and alias
                                                for j, sub_child in enumerate(child.children):
                                                    if hasattr(sub_child, 'type') and sub_child.type == 'as' and j + 1 < len(child.children):
                                                        next_node = child.children[j + 1]
                                                        if hasattr(next_node, 'type') and next_node.type == 'identifier':
                                                            alias_name = next_node.text.decode('utf-8') if isinstance(next_node.text, bytes) else next_node.text
                                                            break

                                                if module_name:
                                                    import_info = ImportDetailedInfo(
                                                        imported_name=module_name,
                                                        import_type="module",
                                                        alias=alias_name,
                                                        line_number=node.start_point[0] + 1 if hasattr(node, 'start_point') else 0,
                                                        is_relative=False,
                                                        module=None,
                                                    )
                                                    result.imports_detailed.append(import_info)
                                                    module_name = None
                                                    alias_name = None
                                            except Exception as e:
                                                logger.warning(f"Could not extract detailed import from aliased_import: {e}")

            elif hasattr(node, 'type') and node.type == 'import_from_statement':
                # Handle: from module import name [as alias]
                module_name = None
                is_relative = False
                level = 0

                # Check for relative imports
                if hasattr(node, 'children'):
                    for child in node.children:
                        if hasattr(child, 'type'):
                            if child.type == 'import_keyword':
                                break
                            if child.type == '.':
                                level += 1

                is_relative = level > 0

                # Extract module name
                if hasattr(node, 'children'):
                    for child in node.children:
                        if hasattr(child, 'type'):
                            if child.type == 'dotted_name':
                                try:
                                    module_name = child.text.decode('utf-8') if isinstance(child.text, bytes) else child.text
                                except Exception as e:
                                    logger.warning(f"Could not extract from module name: {e}")
                                break
                            elif child.type == 'identifier':
                                try:
                                    module_name = child.text.decode('utf-8') if isinstance(child.text, bytes) else child.text
                                except Exception as e:
                                    logger.warning(f"Could not extract from module name: {e}")
                                break

                # Extract imported names
                if hasattr(node, 'children'):
                    for i, child in enumerate(node.children):
                        if hasattr(child, 'type') and child.type == 'import_keyword':
                            # Look at next siblings for imported names
                            if i + 1 < len(node.children):
                                next_node = node.children[i + 1]
                                self._extract_imported_names_tree_sitter(
                                    next_node, result, module_name, is_relative, node.start_point[0] + 1 if hasattr(node, 'start_point') else 0
                                )
                            break

    def _extract_imported_names_tree_sitter(self, node: Any, result: FileAnalysis, module_name: Optional[str], is_relative: bool, line_number: int) -> None:
        """Extract individual imported names from import_from_statement.

        Args:
            node: Tree-sitter node containing imported names
            result: FileAnalysis to populate
            module_name: Source module name (for 'from X import Y')
            is_relative: Whether this is a relative import
            line_number: Line number of the import statement
        """
        if not hasattr(node, 'type'):
            return

        if node.type == '*':
            # Handle: from module import *
            import_info = ImportDetailedInfo(
                imported_name='*',
                import_type='*',
                alias=None,
                line_number=line_number,
                is_relative=is_relative,
                module=module_name,
            )
            result.imports_detailed.append(import_info)

        elif node.type == 'import_alias':
            # Handle single aliased import
            imported_name = None
            alias_name = None

            if hasattr(node, 'children'):
                for child in node.children:
                    if hasattr(child, 'type') and child.type == 'identifier':
                        try:
                            name = child.text.decode('utf-8') if isinstance(child.text, bytes) else child.text
                            if imported_name is None:
                                imported_name = name
                            else:
                                alias_name = name
                        except Exception as e:
                            logger.warning(f"Could not extract imported name from alias: {e}")

            if imported_name:
                import_info = ImportDetailedInfo(
                    imported_name=imported_name,
                    import_type='unknown',
                    alias=alias_name,
                    line_number=line_number,
                    is_relative=is_relative,
                    module=module_name,
                )
                result.imports_detailed.append(import_info)

        elif node.type == 'import_alias_list':
            # Handle multiple imports: from X import a, b, c
            if hasattr(node, 'children'):
                for child in node.children:
                    if hasattr(child, 'type') and child.type == 'import_alias':
                        self._extract_imported_names_tree_sitter(
                            child, result, module_name, is_relative, line_number
                        )
        elif node.type == 'identifier':
            # Handle single simple import: from module import name
            try:
                imported_name = node.text.decode('utf-8') if isinstance(node.text, bytes) else node.text
                import_info = ImportDetailedInfo(
                    imported_name=imported_name,
                    import_type='unknown',
                    alias=None,
                    line_number=line_number,
                    is_relative=is_relative,
                    module=module_name,
                )
                result.imports_detailed.append(import_info)
            except Exception as e:
                logger.warning(f"Could not extract simple import name: {e}")

    def _extract_imports_detailed_ast(self, tree: ast.AST, result: FileAnalysis) -> None:
        """Extract detailed import information using standard AST.

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
