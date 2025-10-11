"""
Decorator extraction from AST.

Extracted from analyzer.py lines 762-899.
"""

import ast
import json
import logging
from typing import Any, Dict

from code_explorer.analyzer.extractors.base import BaseExtractor
from code_explorer.analyzer.models import DecoratorInfo, FileAnalysis

logger = logging.getLogger(__name__)


class DecoratorExtractor(BaseExtractor):
    """Extracts decorator information from AST."""

    def extract(self, tree: ast.AST, result: FileAnalysis) -> None:
        """Extract decorators using ast.

        Extracted from _extract_decorators (lines 873-899).

        Args:
            tree: AST tree
            result: FileAnalysis to populate
        """
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                target_name = node.name
                target_type = (
                    "function" if isinstance(node, ast.FunctionDef) else "class"
                )

                for decorator in node.decorator_list:
                    # Get decorator name and arguments using helper
                    decorator_name, arguments = self._resolve_decorator_name(decorator)

                    decorator_info = DecoratorInfo(
                        name=decorator_name,
                        file=result.file_path,
                        line_number=decorator.lineno,
                        arguments=json.dumps(arguments),
                        target_name=target_name,
                        target_type=target_type,
                    )
                    result.decorators.append(decorator_info)

    def _parse_positional_args(self, args: list) -> Dict[str, Any]:
        """Parse positional arguments from decorator call.

        Extracted from _parse_positional_args (lines 762-783).

        Args:
            args: List of positional argument nodes

        Returns:
            Dictionary of positional arguments
        """
        args_dict = {}
        for i, arg in enumerate(args):
            try:
                # Try to evaluate simple literals
                value = ast.literal_eval(arg)
                args_dict[f"arg_{i}"] = value
            except (ValueError, TypeError):
                # Fall back to unparsing complex expressions
                try:
                    args_dict[f"arg_{i}"] = ast.unparse(arg)
                except Exception:
                    args_dict[f"arg_{i}"] = "<complex>"
        return args_dict

    def _parse_keyword_args(self, keywords: list) -> Dict[str, Any]:
        """Parse keyword arguments from decorator call.

        Extracted from _parse_keyword_args (lines 785-806).

        Args:
            keywords: List of keyword argument nodes

        Returns:
            Dictionary of keyword arguments
        """
        args_dict = {}
        for keyword in keywords:
            try:
                # Try to evaluate simple literals
                value = ast.literal_eval(keyword.value)
                args_dict[keyword.arg or "**kwargs"] = value
            except (ValueError, TypeError):
                # Fall back to unparsing
                try:
                    args_dict[keyword.arg or "**kwargs"] = ast.unparse(keyword.value)
                except Exception:
                    args_dict[keyword.arg or "**kwargs"] = "<complex>"
        return args_dict

    def _parse_decorator_args(self, decorator_call: ast.Call) -> Dict[str, Any]:
        """Parse decorator arguments to a dictionary.

        Extracted from _parse_decorator_args (lines 808-830).

        Args:
            decorator_call: AST Call node representing decorator with arguments

        Returns:
            Dictionary of argument names to values
        """
        args_dict = {}

        try:
            # Parse positional arguments
            positional = self._parse_positional_args(decorator_call.args)
            args_dict.update(positional)

            # Parse keyword arguments
            keywords = self._parse_keyword_args(decorator_call.keywords)
            args_dict.update(keywords)
        except Exception as e:
            logger.warning(f"Error parsing decorator arguments: {e}")

        return args_dict

    def _resolve_decorator_name(self, decorator: ast.expr) -> tuple:
        """Resolve decorator name and arguments from decorator expression.

        Extracted from _resolve_decorator_name (lines 832-871).

        Args:
            decorator: AST expression node representing a decorator

        Returns:
            Tuple of (decorator_name, arguments_dict)
        """
        decorator_name = ""
        arguments = {}

        if isinstance(decorator, ast.Name):
            # Simple decorator: @property
            decorator_name = decorator.id
        elif isinstance(decorator, ast.Call):
            # Decorator with arguments: @lru_cache(maxsize=128)
            if isinstance(decorator.func, ast.Name):
                decorator_name = decorator.func.id
            elif isinstance(decorator.func, ast.Attribute):
                # Decorated with attribute access: @dataclasses.dataclass
                try:
                    decorator_name = ast.unparse(decorator.func)
                except Exception:
                    decorator_name = decorator.func.attr
            arguments = self._parse_decorator_args(decorator)
        elif isinstance(decorator, ast.Attribute):
            # Decorator as attribute: @staticmethod
            try:
                decorator_name = ast.unparse(decorator)
            except Exception:
                decorator_name = decorator.attr
        else:
            # Complex decorator expression
            try:
                decorator_name = ast.unparse(decorator)
            except Exception:
                decorator_name = "<complex>"

        return decorator_name, arguments
