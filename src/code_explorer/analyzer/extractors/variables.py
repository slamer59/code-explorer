"""
Variable extraction from AST and Tree-sitter.

Extracted from analyzer.py lines 606-716.
Enhanced to support both standard AST and Tree-sitter parsing.
Uses Tree-sitter for improved performance and accuracy.
"""

import ast
import logging
from typing import List, Optional, Union, Any

import astroid
from astroid.nodes import FunctionDef, Module, Name

from code_explorer.analyzer.extractors.base import BaseExtractor
from code_explorer.analyzer.models import FileAnalysis, VariableInfo, VariableUsage
from code_explorer.analyzer.parser import get_parser_type

try:
    from code_explorer.analyzer.tree_sitter_adapter import ASTNode, walk_tree
    TREE_SITTER_AVAILABLE = True
except ImportError:
    TREE_SITTER_AVAILABLE = False
    ASTNode = None
    walk_tree = None

logger = logging.getLogger(__name__)


class VariableExtractor(BaseExtractor):
    """Extracts variable definitions and usage from AST and Tree-sitter."""

    def extract(self, tree: Union[ast.AST, Any], result: FileAnalysis) -> None:
        """Extract variables using AST or Tree-sitter.

        Extracted from _extract_variables_ast (lines 606-642).
        Enhanced to support both AST and Tree-sitter parsing.

        Args:
            tree: AST tree or Tree-sitter root node
            result: FileAnalysis to populate
        """
        # Detect parser type and extract accordingly
        parser_type = get_parser_type(tree)

        if parser_type == "tree_sitter":
            self._extract_variables_tree_sitter(tree, result)
        else:
            self._extract_variables_ast(tree, result)

    def _extract_variables_tree_sitter(self, tree: Any, result: FileAnalysis) -> None:
        """Extract variable definitions using Tree-sitter.

        Tree-sitter node types:
        - assignment: for 'x = value'
        - augmented_assignment: for 'x += value', 'x -= value', etc.
        - named_expression: for 'x := value' (walrus operator)
        - typed_parameter: for type-annotated function parameters

        Handles:
        - Simple assignments: x = value
        - Tuple unpacking: x, y = value
        - Augmented assignments: x += value
        - Walrus operator: (x := value)
        - Type annotations: x: int = value

        Args:
            tree: Tree-sitter root node
            result: FileAnalysis to populate
        """
        if not TREE_SITTER_AVAILABLE or walk_tree is None:
            logger.warning("Tree-sitter not available, skipping Tree-sitter extraction")
            return

        # Build a map of function nodes to their names and line ranges for scope tracking
        function_map = self._build_function_map_tree_sitter(tree)

        # Extract module-level and function-level variables
        for node in walk_tree(tree):
            if not hasattr(node, 'type'):
                continue

            if node.type == 'assignment':
                # Handle regular assignment: x = value
                self._extract_assignment_tree_sitter(node, result, function_map)

            elif node.type == 'augmented_assignment':
                # Handle augmented assignment: x += value, x -= value, etc.
                self._extract_augmented_assignment_tree_sitter(node, result, function_map)

            elif node.type == 'named_expression':
                # Handle walrus operator: (x := value)
                self._extract_named_expression_tree_sitter(node, result, function_map)

    def _build_function_map_tree_sitter(self, tree: Any) -> dict:
        """Build a map of line numbers to function names for scope tracking.

        Creates a dictionary mapping function line ranges to function names,
        which allows efficient scope determination for any variable.

        Args:
            tree: Tree-sitter root node

        Returns:
            Dictionary mapping (start_line, end_line) tuples to function names
        """
        func_map = {}
        for node in walk_tree(tree):
            if not hasattr(node, 'type'):
                continue

            if node.type == 'function_definition':
                # Extract function name
                name_node = None
                if hasattr(node, 'child_by_field_name'):
                    name_node = node.child_by_field_name('name')
                else:
                    # Fallback: look for identifier child
                    for child in getattr(node, 'children', []):
                        if hasattr(child, 'type') and child.type == 'identifier':
                            name_node = child
                            break

                if name_node:
                    try:
                        func_name = (name_node.text.decode('utf-8')
                                    if isinstance(name_node.text, bytes)
                                    else name_node.text)
                        start_line = node.start_point[0] + 1
                        end_line = node.end_point[0] + 1
                        func_map[(start_line, end_line)] = func_name
                    except (AttributeError, UnicodeDecodeError) as e:
                        logger.warning(f"Could not extract function name: {e}")

        return func_map

    def _determine_scope_tree_sitter(self, node: Any, function_map: dict) -> str:
        """Determine the scope of a variable assignment.

        Walks up the parent chain to find the enclosing function.

        Args:
            node: Variable assignment node
            function_map: Map of function line ranges to names

        Returns:
            Scope string ("module" or "function:func_name")
        """
        line_num = node.start_point[0] + 1

        # Check if line is within any function
        for (start_line, end_line), func_name in function_map.items():
            if start_line < line_num <= end_line:
                return f"function:{func_name}"

        return "module"

    def _extract_assignment_tree_sitter(
        self, node: Any, result: FileAnalysis, function_map: dict
    ) -> None:
        """Extract variable from a regular assignment node.

        Handles: x = value, x, y = value, etc.

        Args:
            node: Tree-sitter assignment node
            result: FileAnalysis to populate
            function_map: Map of function line ranges to names
        """
        # Get the left-hand side (targets)
        targets_node = None

        for child in getattr(node, 'children', []):
            if not hasattr(child, 'type'):
                continue
            # Skip operators and whitespace
            if child.type not in ('=', 'comment', '(', ')', '\n'):
                targets_node = child
                break

        if targets_node:
            var_names = self._extract_assignment_targets_tree_sitter(targets_node)
            scope = self._determine_scope_tree_sitter(node, function_map)
            line_num = node.start_point[0] + 1

            for var_name in var_names:
                var_info = VariableInfo(
                    name=var_name,
                    file=result.file_path,
                    definition_line=line_num,
                    scope=scope,
                )
                result.variables.append(var_info)

    def _extract_augmented_assignment_tree_sitter(
        self, node: Any, result: FileAnalysis, function_map: dict
    ) -> None:
        """Extract variable from an augmented assignment node.

        Handles: x += value, x -= value, etc.

        Args:
            node: Tree-sitter augmented_assignment node
            result: FileAnalysis to populate
            function_map: Map of function line ranges to names
        """
        target_node = None
        for child in getattr(node, 'children', []):
            if hasattr(child, 'type') and child.type == 'identifier':
                target_node = child
                break

        if target_node:
            try:
                var_name = (target_node.text.decode('utf-8')
                           if isinstance(target_node.text, bytes)
                           else target_node.text)
                scope = self._determine_scope_tree_sitter(node, function_map)
                line_num = node.start_point[0] + 1

                var_info = VariableInfo(
                    name=var_name,
                    file=result.file_path,
                    definition_line=line_num,
                    scope=scope,
                )
                result.variables.append(var_info)
            except (AttributeError, UnicodeDecodeError) as e:
                logger.warning(f"Could not extract variable from augmented assignment: {e}")

    def _extract_named_expression_tree_sitter(
        self, node: Any, result: FileAnalysis, function_map: dict
    ) -> None:
        """Extract variable from a named expression (walrus operator).

        Handles: (x := value)

        Args:
            node: Tree-sitter named_expression node
            result: FileAnalysis to populate
            function_map: Map of function line ranges to names
        """
        target_node = None
        for child in getattr(node, 'children', []):
            if hasattr(child, 'type') and child.type == 'identifier':
                target_node = child
                break

        if target_node:
            try:
                var_name = (target_node.text.decode('utf-8')
                           if isinstance(target_node.text, bytes)
                           else target_node.text)
                scope = self._determine_scope_tree_sitter(node, function_map)
                line_num = node.start_point[0] + 1

                var_info = VariableInfo(
                    name=var_name,
                    file=result.file_path,
                    definition_line=line_num,
                    scope=scope,
                )
                result.variables.append(var_info)
            except (AttributeError, UnicodeDecodeError) as e:
                logger.warning(f"Could not extract variable from named expression: {e}")

    def _extract_assignment_targets_tree_sitter(self, node: Any) -> List[str]:
        """Extract variable names from assignment targets (Tree-sitter).

        Recursively handles nested unpacking and complex assignment patterns:
        - Simple identifier: x
        - Tuple unpacking: x, y = ...
        - List unpacking: [x, y] = ...
        - Parenthesized: (x) = ...
        - Subscripts (only extracts base): x[0] = ...
        - Attributes (only extracts base): x.y = ...

        Args:
            node: Tree-sitter node representing assignment target(s)

        Returns:
            List of variable names
        """
        names = []

        if not hasattr(node, 'type'):
            return names

        try:
            if node.type == 'identifier':
                # Simple variable name
                var_name = (node.text.decode('utf-8')
                           if isinstance(node.text, bytes)
                           else node.text)
                names.append(var_name)

            elif node.type in ('tuple', 'list'):
                # Handle unpacking: (x, y) = ... or [x, y] = ...
                for child in getattr(node, 'children', []):
                    if not hasattr(child, 'type'):
                        continue
                    if child.type in ('identifier', 'tuple', 'list', 'pattern_list'):
                        names.extend(self._extract_assignment_targets_tree_sitter(child))

            elif node.type == 'pattern_list':
                # Another unpacking pattern type
                for child in getattr(node, 'children', []):
                    if not hasattr(child, 'type'):
                        continue
                    if child.type in ('identifier', 'tuple', 'list', 'pattern_list'):
                        names.extend(self._extract_assignment_targets_tree_sitter(child))

            elif node.type == 'subscript':
                # Handle subscript assignment: x[0] = value (only track base variable)
                # Extract the object being subscripted
                if hasattr(node, 'children'):
                    for child in node.children:
                        if hasattr(child, 'type'):
                            if child.type == 'identifier':
                                var_name = (child.text.decode('utf-8')
                                           if isinstance(child.text, bytes)
                                           else child.text)
                                names.append(var_name)
                                break
                            elif child.type == 'attribute':
                                # For x.y[0], still extract x
                                names.extend(self._extract_assignment_targets_tree_sitter(child))
                                break

            elif node.type == 'attribute':
                # Handle attribute assignment: x.y = value (only track base variable)
                if hasattr(node, 'children'):
                    for child in node.children:
                        if hasattr(child, 'type') and child.type == 'identifier':
                            var_name = (child.text.decode('utf-8')
                                       if isinstance(child.text, bytes)
                                       else child.text)
                            names.append(var_name)
                            break

        except (AttributeError, UnicodeDecodeError, TypeError) as e:
            logger.warning(f"Error extracting assignment targets: {e}")

        return names

    def _extract_variables_ast(self, tree: ast.AST, result: FileAnalysis) -> None:
        """Extract variable definitions using standard AST.

        Extracted from _extract_variables_ast (lines 606-642).

        Args:
            tree: AST tree
            result: FileAnalysis to populate
        """
        # Extract module-level variables
        if isinstance(tree, ast.Module):
            for node in tree.body:
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        var_names = self._get_assignment_targets_ast(target)
                        for var_name in var_names:
                            var_info = VariableInfo(
                                name=var_name,
                                file=result.file_path,
                                definition_line=node.lineno,
                                scope="module",
                            )
                            result.variables.append(var_info)
                elif isinstance(node, ast.AugAssign):
                    # Handle augmented assignment: x += value
                    if isinstance(node.target, ast.Name):
                        var_info = VariableInfo(
                            name=node.target.id,
                            file=result.file_path,
                            definition_line=node.lineno,
                            scope="module",
                        )
                        result.variables.append(var_info)

        # Extract function-level variables
        for func_node in ast.walk(tree):
            if isinstance(func_node, ast.FunctionDef):
                for node in ast.walk(func_node):
                    if isinstance(node, ast.Assign):
                        for target in node.targets:
                            var_names = self._get_assignment_targets_ast(target)
                            for var_name in var_names:
                                var_info = VariableInfo(
                                    name=var_name,
                                    file=result.file_path,
                                    definition_line=node.lineno,
                                    scope=f"function:{func_node.name}",
                                )
                                result.variables.append(var_info)
                    elif isinstance(node, ast.AugAssign):
                        # Handle augmented assignment in function
                        if isinstance(node.target, ast.Name):
                            var_info = VariableInfo(
                                name=node.target.id,
                                file=result.file_path,
                                definition_line=node.lineno,
                                scope=f"function:{func_node.name}",
                            )
                            result.variables.append(var_info)
                    elif isinstance(node, ast.NamedExpr):
                        # Handle walrus operator: (x := value)
                        if isinstance(node.target, ast.Name):
                            var_info = VariableInfo(
                                name=node.target.id,
                                file=result.file_path,
                                definition_line=node.lineno,
                                scope=f"function:{func_node.name}",
                            )
                            result.variables.append(var_info)

    def _get_assignment_targets_ast(self, node: ast.AST) -> List[str]:
        """Extract variable names from assignment targets (AST).

        Extracted from _get_assignment_targets (lines 644-659).

        Args:
            node: AST node representing assignment target

        Returns:
            List of variable names
        """
        names = []
        if isinstance(node, ast.Name):
            names.append(node.id)
        elif isinstance(node, (ast.Tuple, ast.List)):
            for elt in node.elts:
                names.extend(self._get_assignment_targets_ast(elt))
        elif isinstance(node, ast.Starred):
            # Handle starred unpacking: *x
            names.extend(self._get_assignment_targets_ast(node.value))
        return names

    def extract_variable_usage_ast(self, tree: ast.AST, result: FileAnalysis) -> None:
        """Extract variable usage using ast.

        Extracted from _extract_variable_usage_ast (lines 661-680).

        Args:
            tree: AST tree
            result: FileAnalysis to populate
        """
        # Find variable usage within each function
        for func_node in ast.walk(tree):
            if isinstance(func_node, ast.FunctionDef):
                func_name = func_node.name
                for node in ast.walk(func_node):
                    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                        # This is a variable being read (not assigned)
                        usage_info = VariableUsage(
                            variable_name=node.id,
                            function_name=func_name,
                            usage_line=node.lineno,
                        )
                        result.variable_usage.append(usage_info)

    def extract_variable_usage_astroid(
        self, module: Module, result: FileAnalysis
    ) -> None:
        """Extract variable usage using astroid.

        Extracted from _extract_variable_usage_astroid (lines 682-716).

        Args:
            module: Astroid module
            result: FileAnalysis to populate
        """
        # Find all function definitions
        for func_node in module.nodes_of_class(FunctionDef):
            func_name = func_node.name

            # Find all name references within this function
            for name_node in func_node.nodes_of_class(Name):
                # Skip if lineno is None (type safety)
                if name_node.lineno is None:
                    continue

                # Check if it's a load context (reading, not assigning)
                try:
                    # astroid uses different context types; check if it's a load
                    # Note: astroid Name nodes may not have ctx attribute
                    if hasattr(name_node, "ctx"):
                        ctx_name = str(type(name_node.ctx).__name__)
                        if ctx_name == "Load":
                            usage_info = VariableUsage(
                                variable_name=name_node.name,
                                function_name=func_name,
                                usage_line=name_node.lineno,
                            )
                            result.variable_usage.append(usage_info)
                except (AttributeError, TypeError):
                    # Some nodes might not have ctx or it might be None
                    pass
