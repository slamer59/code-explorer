"""
Decorator extraction from AST and Tree-sitter.

Extracted from analyzer.py lines 762-899.
Enhanced to support both standard AST and Tree-sitter parsing.
Uses Tree-sitter for improved performance and accuracy.
"""

import ast
import json
import logging
from typing import Any, Dict, Optional, Union, List, Tuple

from code_explorer.analyzer.extractors.base import BaseExtractor
from code_explorer.analyzer.models import DecoratorInfo, FileAnalysis
from code_explorer.analyzer.parser import get_parser_type

try:
    from code_explorer.analyzer.tree_sitter_adapter import ASTNode, walk_tree
    TREE_SITTER_AVAILABLE = True
except ImportError:
    TREE_SITTER_AVAILABLE = False
    ASTNode = None
    walk_tree = None

logger = logging.getLogger(__name__)


class DecoratorExtractor(BaseExtractor):
    """Extracts decorator information from AST and Tree-sitter."""

    def _sanitize_for_json(self, obj: Any) -> Any:
        """Sanitize value to be JSON-serializable.

        Converts non-JSON-serializable Python types to strings while preserving
        JSON-safe types (str, int, float, bool, None, list, dict).

        Args:
            obj: Value to sanitize

        Returns:
            JSON-serializable version of the value
        """
        # Handle None
        if obj is None:
            return None

        # Handle basic JSON-safe types
        if isinstance(obj, (str, int, float, bool)):
            return obj

        # Handle complex numbers - convert to string
        if isinstance(obj, complex):
            return str(obj)

        # Handle bytes - convert to string representation
        if isinstance(obj, bytes):
            return str(obj)

        # Handle sets and frozensets - convert to list, then sanitize elements
        if isinstance(obj, (set, frozenset)):
            return str(sorted([self._sanitize_for_json(item) for item in obj]))

        # Handle lists and tuples - sanitize each element
        if isinstance(obj, (list, tuple)):
            return [self._sanitize_for_json(item) for item in obj]

        # Handle dictionaries - sanitize keys and values
        if isinstance(obj, dict):
            sanitized = {}
            for key, value in obj.items():
                # Convert non-string keys to strings
                if not isinstance(key, str):
                    key = str(key)
                sanitized[key] = self._sanitize_for_json(value)
            return sanitized

        # For any other type, convert to string
        return str(obj)

    def extract(self, tree: Any, result: FileAnalysis) -> None:
        """Extract decorators using AST or Tree-sitter.

        Extracted from _extract_decorators (lines 873-899).
        Enhanced to support both AST and Tree-sitter parsing.

        Args:
            tree: AST tree or Tree-sitter root node
            result: FileAnalysis to populate
        """
        # Detect parser type and extract accordingly
        parser_type = get_parser_type(tree)

        if parser_type == "tree_sitter":
            self._extract_decorators_tree_sitter(tree, result)
        else:
            self._extract_decorators_ast(tree, result)

    def _extract_decorators_tree_sitter(self, tree: Any, result: FileAnalysis) -> None:
        """Extract decorators from Tree-sitter tree.

        Tree-sitter decorator structure:
        - decorated_definition contains decorators and the decorated node
        - decorator nodes contain the decorator expression
        - Can have chained/nested decorators

        Args:
            tree: Tree-sitter root node
            result: FileAnalysis to populate
        """
        if not TREE_SITTER_AVAILABLE or walk_tree is None:
            logger.warning("Tree-sitter not available, skipping Tree-sitter extraction")
            return

        for node in walk_tree(tree):
            if not hasattr(node, 'type'):
                continue

            # Look for decorated_definition nodes
            if node.type == 'decorated_definition':
                self._extract_decorators_from_decorated_node(node, result)

    def _extract_decorators_from_decorated_node(self, node: Any, result: FileAnalysis) -> None:
        """Extract decorators from a decorated_definition node.

        Args:
            node: Tree-sitter decorated_definition node
            result: FileAnalysis to populate
        """
        # Find the target (function or class definition)
        target_node = None
        decorators = []

        for child in getattr(node, 'children', []):
            if not hasattr(child, 'type'):
                continue

            if child.type == 'decorator':
                decorators.append(child)
            elif child.type in ('function_definition', 'class_definition'):
                target_node = child

        if not target_node or not decorators:
            return

        # Extract target information
        target_name = self._extract_function_or_class_name(target_node)
        if not target_name:
            return

        target_type = 'function' if target_node.type == 'function_definition' else 'class'

        # Process each decorator
        for decorator_node in decorators:
            self._process_decorator_node(decorator_node, target_name, target_type, result)

    def _extract_function_or_class_name(self, node: Any) -> Optional[str]:
        """Extract the name from a function_definition or class_definition node.

        Args:
            node: Tree-sitter function_definition or class_definition node

        Returns:
            Name of the function/class or None
        """
        try:
            # Try using field access
            if hasattr(node, 'child_by_field_name'):
                name_node = node.child_by_field_name('name')
                if name_node:
                    return (name_node.text.decode('utf-8')
                           if isinstance(name_node.text, bytes)
                           else name_node.text)

            # Fallback: find identifier child
            for child in getattr(node, 'children', []):
                if hasattr(child, 'type') and child.type == 'identifier':
                    return (child.text.decode('utf-8')
                           if isinstance(child.text, bytes)
                           else child.text)
        except (AttributeError, UnicodeDecodeError) as e:
            logger.warning(f"Could not extract name from function/class: {e}")

        return None

    def _process_decorator_node(
        self, decorator_node: Any, target_name: str, target_type: str, result: FileAnalysis
    ) -> None:
        """Process a single decorator node.

        Args:
            decorator_node: Tree-sitter decorator node
            target_name: Name of decorated function/class
            target_type: "function" or "class"
            result: FileAnalysis to populate
        """
        # Get line number from decorator node
        line_number = decorator_node.start_point[0] + 1

        # Extract decorator identifier and arguments
        decorator_name, arguments = self._extract_decorator_info_tree_sitter(decorator_node)

        if decorator_name:
            decorator_info = DecoratorInfo(
                name=decorator_name,
                file=result.file_path,
                line_number=line_number,
                arguments=json.dumps(self._sanitize_for_json(arguments)),
                target_name=target_name,
                target_type=target_type,
            )
            result.decorators.append(decorator_info)

    def _extract_decorator_info_tree_sitter(self, decorator_node: Any) -> Tuple[str, Dict[str, Any]]:
        """Extract decorator name and arguments from a Tree-sitter decorator node.

        Handles:
        - Simple decorator: @property
        - Decorator with arguments: @lru_cache(maxsize=128)
        - Chained decorators: @dataclasses.dataclass
        - Complex expressions: custom decorators

        Args:
            decorator_node: Tree-sitter decorator node

        Returns:
            Tuple of (decorator_name, arguments_dict)
        """
        decorator_name = ""
        arguments = {}

        # Find the decorator expression (usually first non-@ child)
        for child in getattr(decorator_node, 'children', []):
            if not hasattr(child, 'type'):
                continue

            if child.type == '@':
                continue

            # The first meaningful child is the decorator expression
            if child.type == 'identifier':
                # Simple decorator: @property
                try:
                    decorator_name = (child.text.decode('utf-8')
                                     if isinstance(child.text, bytes)
                                     else child.text)
                except (AttributeError, UnicodeDecodeError):
                    pass

            elif child.type == 'call':
                # Decorator with arguments: @decorator(args)
                decorator_name, arguments = self._extract_decorator_call_tree_sitter(child)

            elif child.type == 'attribute':
                # Attribute decorator: @module.decorator
                decorator_name = self._extract_attribute_path_tree_sitter(child)

            elif child.type == 'subscript':
                # Complex decorator with subscript
                decorator_name = self._extract_subscript_text(child)

            # For other types, try to get text representation
            elif hasattr(child, 'text'):
                try:
                    decorator_name = (child.text.decode('utf-8')
                                     if isinstance(child.text, bytes)
                                     else child.text)
                except (AttributeError, UnicodeDecodeError):
                    pass

            break  # Process only the first meaningful child

        return decorator_name, arguments

    def _extract_decorator_call_tree_sitter(self, call_node: Any) -> Tuple[str, Dict[str, Any]]:
        """Extract decorator name and arguments from a call node.

        Args:
            call_node: Tree-sitter call node

        Returns:
            Tuple of (decorator_name, arguments_dict)
        """
        decorator_name = ""
        arguments = {}

        # Find function and arguments
        func_node = None
        args_node = None

        for child in getattr(call_node, 'children', []):
            if not hasattr(child, 'type'):
                continue

            if child.type in ('identifier', 'attribute'):
                func_node = child
            elif child.type == 'arguments':
                args_node = child

        if func_node:
            if func_node.type == 'identifier':
                try:
                    decorator_name = (func_node.text.decode('utf-8')
                                     if isinstance(func_node.text, bytes)
                                     else func_node.text)
                except (AttributeError, UnicodeDecodeError):
                    pass

            elif func_node.type == 'attribute':
                decorator_name = self._extract_attribute_path_tree_sitter(func_node)

        # Extract arguments if present
        if args_node:
            arguments = self._extract_arguments_tree_sitter(args_node)

        return decorator_name, arguments

    def _extract_attribute_path_tree_sitter(self, attr_node: Any) -> str:
        """Extract full attribute path from an attribute node.

        For example: module.submodule.decorator

        Args:
            attr_node: Tree-sitter attribute node

        Returns:
            Full attribute path as string
        """
        parts = []

        def extract_parts(node):
            if not hasattr(node, 'type'):
                return

            if node.type == 'attribute':
                # Recursively extract parts
                for child in getattr(node, 'children', []):
                    extract_parts(child)
            elif node.type == 'identifier':
                try:
                    part = (node.text.decode('utf-8')
                           if isinstance(node.text, bytes)
                           else node.text)
                    if part != '.':
                        parts.append(part)
                except (AttributeError, UnicodeDecodeError):
                    pass

        extract_parts(attr_node)
        return '.'.join(parts)

    def _extract_subscript_text(self, subscript_node: Any) -> str:
        """Extract text representation of a subscript node.

        Args:
            subscript_node: Tree-sitter subscript node

        Returns:
            Text representation
        """
        try:
            return (subscript_node.text.decode('utf-8')
                   if isinstance(subscript_node.text, bytes)
                   else subscript_node.text)
        except (AttributeError, UnicodeDecodeError, TypeError):
            return "<subscript>"

    def _extract_arguments_tree_sitter(self, args_node: Any) -> Dict[str, Any]:
        """Extract arguments from an arguments node.

        Args:
            args_node: Tree-sitter arguments node

        Returns:
            Dictionary of argument names/indices to values
        """
        arguments = {}
        arg_index = 0

        for child in getattr(args_node, 'children', []):
            if not hasattr(child, 'type'):
                continue

            if child.type == '(' or child.type == ')' or child.type == ',':
                continue

            # Try to extract argument value
            if child.type == 'keyword_argument':
                # keyword=value format
                self._extract_keyword_argument_tree_sitter(child, arguments)
            else:
                # Positional argument
                arg_value = self._extract_argument_value_tree_sitter(child)
                if arg_value is not None:
                    arguments[f"arg_{arg_index}"] = arg_value
                    arg_index += 1

        return arguments

    def _extract_keyword_argument_tree_sitter(
        self, keyword_node: Any, arguments: Dict[str, Any]
    ) -> None:
        """Extract a keyword argument from a keyword_argument node.

        Args:
            keyword_node: Tree-sitter keyword_argument node
            arguments: Dictionary to populate
        """
        try:
            keyword_name = None
            value = None

            for child in getattr(keyword_node, 'children', []):
                if not hasattr(child, 'type'):
                    continue

                if keyword_name is None and child.type == 'identifier':
                    keyword_name = (child.text.decode('utf-8')
                                   if isinstance(child.text, bytes)
                                   else child.text)
                elif child.type == '=':
                    continue
                elif value is None:
                    value = self._extract_argument_value_tree_sitter(child)

            if keyword_name and value is not None:
                arguments[keyword_name] = value
        except Exception as e:
            logger.warning(f"Error extracting keyword argument: {e}")

    def _extract_argument_value_tree_sitter(self, arg_node: Any) -> Any:
        """Extract the value of an argument node.

        Handles:
        - Literals: "string", 123, True, None
        - Identifiers: variable names
        - Attributes: obj.attr
        - Calls: func()
        - Lists/Dicts: [], {}

        Args:
            arg_node: Tree-sitter argument node

        Returns:
            Extracted value or string representation
        """
        try:
            if not hasattr(arg_node, 'type'):
                return None

            # Try to extract text representation
            if hasattr(arg_node, 'text'):
                text = (arg_node.text.decode('utf-8')
                       if isinstance(arg_node.text, bytes)
                       else arg_node.text)

                # For simple literals, try to evaluate
                if arg_node.type in ('string', 'integer', 'float', 'true', 'false', 'none'):
                    try:
                        return ast.literal_eval(text)
                    except (ValueError, SyntaxError):
                        return text

                return text

            return None
        except Exception as e:
            logger.warning(f"Error extracting argument value: {e}")
            return None

    def _extract_decorators_ast(self, tree: ast.AST, result: FileAnalysis) -> None:
        """Extract decorators using standard AST.

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
                        arguments=json.dumps(self._sanitize_for_json(arguments)),
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
