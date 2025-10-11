"""
Variable extraction from AST.

Extracted from analyzer.py lines 606-716.
"""

import ast
from typing import List

import astroid
from astroid.nodes import FunctionDef, Module, Name

from code_explorer.analyzer.extractors.base import BaseExtractor
from code_explorer.analyzer.models import FileAnalysis, VariableInfo, VariableUsage


class VariableExtractor(BaseExtractor):
    """Extracts variable definitions and usage from AST."""

    def extract(self, tree: ast.AST, result: FileAnalysis) -> None:
        """Extract variables using ast.

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
                        var_names = self._get_assignment_targets(target)
                        for var_name in var_names:
                            var_info = VariableInfo(
                                name=var_name,
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
                            var_names = self._get_assignment_targets(target)
                            for var_name in var_names:
                                var_info = VariableInfo(
                                    name=var_name,
                                    file=result.file_path,
                                    definition_line=node.lineno,
                                    scope=f"function:{func_node.name}",
                                )
                                result.variables.append(var_info)

    def _get_assignment_targets(self, node: ast.AST) -> List[str]:
        """Extract variable names from assignment targets.

        Extracted from _get_assignment_targets (lines 644-659).

        Args:
            node: AST node representing assignment target

        Returns:
            List of variable names
        """
        names = []
        if isinstance(node, ast.Name):
            names.append(node.id)
        elif isinstance(node, ast.Tuple) or isinstance(node, ast.List):
            for elt in node.elts:
                names.extend(self._get_assignment_targets(elt))
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
