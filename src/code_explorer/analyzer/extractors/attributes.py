"""
Attribute extraction from AST and Tree-sitter.

Supports both standard Python AST and Tree-sitter parsing.
Extracted from analyzer.py lines 901-1015.
"""

import ast
import logging
from typing import Optional, Union, Any, List

from code_explorer.analyzer.extractors.base import BaseExtractor
from code_explorer.analyzer.models import AttributeInfo, FileAnalysis
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


class AttributeExtractor(BaseExtractor):
    """Extracts class attribute information from AST and Tree-sitter."""

    def extract(self, tree: Union[ast.AST, Any], result: FileAnalysis) -> None:
        """Extract attributes using AST or Tree-sitter.

        Extracted from _extract_attributes (lines 997-1015).

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
        """Extract attributes using standard AST.

        Args:
            tree: AST tree
            result: FileAnalysis to populate
        """
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                class_name = node.name

                # Extract class-level attributes using helper
                self._extract_class_level_attributes(node, class_name, result)

                # Extract instance attributes from __init__ using helper
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                        self._extract_instance_attributes(item, class_name, result)
                        break  # Only process the first __init__ found

    def _extract_tree_sitter(self, root_node: TreeSitterNode, result: FileAnalysis) -> None:
        """Extract attributes using Tree-sitter.

        Args:
            root_node: Tree-sitter root node
            result: FileAnalysis to populate
        """
        if not TREE_SITTER_AVAILABLE or walk_tree is None:
            logger.warning("Tree-sitter not available, falling back to AST")
            return

        try:
            # Walk the entire tree looking for class_definition nodes
            for node in walk_tree(root_node):
                # Check if this is a class_definition node using node.type
                if hasattr(node, "type") and node.type == "class_definition":
                    self._extract_attributes_from_class(node, result)
        except Exception as e:
            logger.error(f"Tree-sitter extraction failed: {e}")
            raise

    def _extract_attributes_from_class(self, class_node: Any, result: FileAnalysis) -> None:
        """Extract attributes from a Tree-sitter class_definition node.

        Args:
            class_node: Tree-sitter class_definition node
            result: FileAnalysis to populate
        """
        # Extract class name
        class_name_child = class_node.child_by_field_name("name") if hasattr(class_node, "child_by_field_name") else None
        if not class_name_child:
            logger.warning(f"Class definition without name at line {getattr(class_node, 'start_point', (0, 0))[0] + 1}")
            return

        try:
            class_name = class_name_child.text.decode('utf8') if isinstance(class_name_child.text, bytes) else class_name_child.text
        except Exception as e:
            logger.warning(f"Could not extract class name: {e}")
            return

        # Extract class-level attributes from class body
        self._extract_tree_sitter_class_level_attributes(class_node, class_name, result)

        # Find and extract __init__ instance attributes
        body_child = class_node.child_by_field_name("body") if hasattr(class_node, "child_by_field_name") else None
        if body_child:
            self._extract_tree_sitter_init_attributes(body_child, class_name, result)

    def _extract_tree_sitter_class_level_attributes(
        self, class_node: Any, class_name: str, result: FileAnalysis
    ) -> None:
        """Extract class-level attributes from Tree-sitter class node.

        Args:
            class_node: Tree-sitter class_definition node
            class_name: Name of the class
            result: FileAnalysis to populate
        """
        body_child = class_node.child_by_field_name("body") if hasattr(class_node, "child_by_field_name") else None
        if not body_child or not hasattr(body_child, "children"):
            return

        for child in body_child.children:
            # Check node type
            node_type = child.type if hasattr(child, "type") else None
            if node_type == "ERROR":
                continue

            # Handle type-annotated class attribute (name: type = value)
            if node_type == "annotated_assignment":
                self._process_tree_sitter_annotated_assignment(child, class_name, result, is_instance=False)

            # Handle regular class attribute (name = value)
            elif node_type == "assignment":
                self._process_tree_sitter_assignment(child, class_name, result, is_instance=False)

    def _extract_tree_sitter_init_attributes(
        self, body_node: Any, class_name: str, result: FileAnalysis
    ) -> None:
        """Extract instance attributes from __init__ method.

        Args:
            body_node: Tree-sitter block node containing class methods
            class_name: Name of the parent class
            result: FileAnalysis to populate
        """
        # Find __init__ method
        init_method = None
        if hasattr(body_node, "children"):
            for child in body_node.children:
                node_type = child.type if hasattr(child, "type") else None
                if node_type == "function_definition":
                    func_name_child = child.child_by_field_name("name") if hasattr(child, "child_by_field_name") else None
                    if func_name_child and hasattr(func_name_child, "text"):
                        try:
                            func_name = func_name_child.text.decode('utf8') if isinstance(func_name_child.text, bytes) else func_name_child.text
                            if func_name == "__init__":
                                init_method = child
                                break
                        except Exception:
                            continue

        if not init_method:
            return

        # Extract attributes from __init__ body
        init_body = init_method.child_by_field_name("body") if hasattr(init_method, "child_by_field_name") else None
        if init_body:
            self._walk_init_body_for_attributes(init_body, class_name, result)

    def _walk_init_body_for_attributes(
        self, body_node: Any, class_name: str, result: FileAnalysis
    ) -> None:
        """Walk __init__ body and extract self.attribute assignments.

        Args:
            body_node: Tree-sitter block node
            class_name: Name of the parent class
            result: FileAnalysis to populate
        """
        if not hasattr(body_node, "children"):
            return

        for child in body_node.children:
            node_type = child.type if hasattr(child, "type") else None
            if node_type == "ERROR":
                continue

            # Handle self.attribute assignments
            if node_type == "expression_statement":
                # Check children for assignments
                if hasattr(child, "children"):
                    for expr_child in child.children:
                        expr_type = expr_child.type if hasattr(expr_child, "type") else None
                        if expr_type == "assignment":
                            self._process_tree_sitter_self_assignment(expr_child, class_name, result)

            # Handle type-annotated self.attribute
            elif node_type == "annotated_assignment":
                self._process_tree_sitter_annotated_self_assignment(child, class_name, result)

            # Handle nested blocks (if/for/while/with/try)
            elif node_type in ("if_statement", "for_statement", "while_statement", "with_statement", "try_statement"):
                # Recursively search nested blocks
                if hasattr(child, "children"):
                    for nested_child in child.children:
                        nested_type = nested_child.type if hasattr(nested_child, "type") else None
                        if nested_type == "block":
                            self._walk_init_body_for_attributes(nested_child, class_name, result)

    def _process_tree_sitter_assignment(
        self, assign_node: Any, class_name: str, result: FileAnalysis, is_instance: bool = True
    ) -> None:
        """Process a Tree-sitter assignment node (name = value).

        Args:
            assign_node: Tree-sitter assignment node
            class_name: Name of the class
            result: FileAnalysis to populate
            is_instance: Whether this is instance (self) or class attribute
        """
        left_child = assign_node.child_by_field_name("left") if hasattr(assign_node, "child_by_field_name") else None
        if not left_child:
            return

        attr_name = None
        left_type = left_child.type if hasattr(left_child, "type") else None

        if left_type == "identifier":
            try:
                attr_name = left_child.text.decode('utf8') if isinstance(left_child.text, bytes) else left_child.text
            except Exception:
                pass
        elif left_type == "attribute" and is_instance:
            # Check if it's self.attribute
            if self._is_self_attribute(left_child):
                attr_name = self._extract_attribute_name(left_child)

        if attr_name:
            # Get line number from start_point
            lineno = 0
            if hasattr(assign_node, "start_point"):
                lineno = assign_node.start_point[0] + 1

            attr_info = AttributeInfo(
                name=attr_name,
                class_name=class_name,
                file=result.file_path,
                definition_line=lineno,
                type_hint=None,
                is_class_attribute=not is_instance,
            )
            result.attributes.append(attr_info)

    def _process_tree_sitter_annotated_assignment(
        self, ann_assign_node: Any, class_name: str, result: FileAnalysis, is_instance: bool = False
    ) -> None:
        """Process a Tree-sitter annotated assignment node (name: type = value).

        Args:
            ann_assign_node: Tree-sitter annotated_assignment node
            class_name: Name of the class
            result: FileAnalysis to populate
            is_instance: Whether this is instance (self) or class attribute
        """
        left_child = ann_assign_node.child_by_field_name("left") if hasattr(ann_assign_node, "child_by_field_name") else None
        type_child = ann_assign_node.child_by_field_name("type") if hasattr(ann_assign_node, "child_by_field_name") else None

        if not left_child:
            return

        attr_name = None
        left_type = left_child.type if hasattr(left_child, "type") else None

        if left_type == "identifier":
            try:
                attr_name = left_child.text.decode('utf8') if isinstance(left_child.text, bytes) else left_child.text
            except Exception:
                pass
        elif left_type == "attribute" and is_instance:
            if self._is_self_attribute(left_child):
                attr_name = self._extract_attribute_name(left_child)

        if attr_name:
            type_hint = None
            if type_child and hasattr(type_child, "text"):
                try:
                    type_hint = type_child.text.decode('utf8') if isinstance(type_child.text, bytes) else type_child.text
                except Exception:
                    pass

            # Get line number from start_point
            lineno = 0
            if hasattr(ann_assign_node, "start_point"):
                lineno = ann_assign_node.start_point[0] + 1

            attr_info = AttributeInfo(
                name=attr_name,
                class_name=class_name,
                file=result.file_path,
                definition_line=lineno,
                type_hint=type_hint,
                is_class_attribute=not is_instance,
            )
            result.attributes.append(attr_info)

    def _process_tree_sitter_self_assignment(
        self, assign_node: Any, class_name: str, result: FileAnalysis
    ) -> None:
        """Process self.attribute assignment in __init__.

        Args:
            assign_node: Tree-sitter assignment node
            class_name: Name of the class
            result: FileAnalysis to populate
        """
        self._process_tree_sitter_assignment(assign_node, class_name, result, is_instance=True)

    def _process_tree_sitter_annotated_self_assignment(
        self, ann_assign_node: Any, class_name: str, result: FileAnalysis
    ) -> None:
        """Process self.attribute type-annotated assignment in __init__.

        Args:
            ann_assign_node: Tree-sitter annotated_assignment node
            class_name: Name of the class
            result: FileAnalysis to populate
        """
        self._process_tree_sitter_annotated_assignment(ann_assign_node, class_name, result, is_instance=True)

    def _is_self_attribute(self, attr_node: Any) -> bool:
        """Check if an attribute node is self.something.

        Args:
            attr_node: Tree-sitter attribute node

        Returns:
            True if the attribute is on 'self'
        """
        object_child = attr_node.child_by_field_name("object") if hasattr(attr_node, "child_by_field_name") else None
        if object_child and hasattr(object_child, "type") and object_child.type == "identifier":
            try:
                obj_name = object_child.text.decode('utf8') if isinstance(object_child.text, bytes) else object_child.text
                return obj_name == "self"
            except Exception:
                pass
        return False

    def _extract_attribute_name(self, attr_node: Any) -> Optional[str]:
        """Extract attribute name from attribute node (right side of dot).

        Handles both simple attributes (a.b) and chained attributes (a.b.c).

        Args:
            attr_node: Tree-sitter attribute node

        Returns:
            Attribute name or None
        """
        try:
            # For attribute nodes, the attribute field contains the attribute name
            attr_child = attr_node.child_by_field_name("attribute") if hasattr(attr_node, "child_by_field_name") else None
            if attr_child and hasattr(attr_child, "text"):
                return attr_child.text.decode('utf8') if isinstance(attr_child.text, bytes) else attr_child.text

            # Fallback: get the last identifier in the chain
            # For a.b.c, we want to return 'c'
            if hasattr(attr_node, "children"):
                children = attr_node.children
                if children:
                    # The last non-DOT token should be the attribute name
                    for child in reversed(children):
                        child_type = child.type if hasattr(child, "type") else None
                        if child_type == "identifier":
                            try:
                                return child.text.decode('utf8') if isinstance(child.text, bytes) else child.text
                            except Exception:
                                continue
        except Exception:
            pass

        return None

    def _extract_type_hint(self, annotation: Optional[ast.AST]) -> Optional[str]:
        """Extract type hint from annotation node.

        Extracted from _extract_type_hint (lines 901-916).

        Args:
            annotation: AST annotation node

        Returns:
            String representation of type hint or None
        """
        if annotation is None:
            return None

        try:
            return ast.unparse(annotation)
        except Exception:
            return None

    def _extract_class_level_attributes(
        self, class_node: ast.ClassDef, class_name: str, result: FileAnalysis
    ) -> None:
        """Extract class-level attributes from a class definition.

        Extracted from _extract_class_level_attributes (lines 918-952).

        Args:
            class_node: AST ClassDef node
            class_name: Name of the class
            result: FileAnalysis object to populate
        """
        for item in class_node.body:
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                # Type-annotated class attribute: name: type = value
                attr_info = AttributeInfo(
                    name=item.target.id,
                    class_name=class_name,
                    file=result.file_path,
                    definition_line=item.lineno,
                    type_hint=self._extract_type_hint(item.annotation),
                    is_class_attribute=True,
                )
                result.attributes.append(attr_info)
            elif isinstance(item, ast.Assign):
                # Regular class attribute: name = value
                for target in item.targets:
                    if isinstance(target, ast.Name):
                        attr_info = AttributeInfo(
                            name=target.id,
                            class_name=class_name,
                            file=result.file_path,
                            definition_line=item.lineno,
                            type_hint=None,
                            is_class_attribute=True,
                        )
                        result.attributes.append(attr_info)

    def _extract_instance_attributes(
        self, init_node: ast.FunctionDef, class_name: str, result: FileAnalysis
    ) -> None:
        """Extract instance attributes from __init__ method.

        Extracted from _extract_instance_attributes (lines 954-995).

        Args:
            init_node: AST FunctionDef node for __init__ method
            class_name: Name of the parent class
            result: FileAnalysis object to populate
        """
        for child in ast.walk(init_node):
            if isinstance(child, ast.Assign):
                for target in child.targets:
                    # Look for self.attribute assignments
                    if isinstance(target, ast.Attribute) and isinstance(
                        target.value, ast.Name
                    ):
                        if target.value.id == "self":
                            attr_info = AttributeInfo(
                                name=target.attr,
                                class_name=class_name,
                                file=result.file_path,
                                definition_line=child.lineno,
                                type_hint=None,
                                is_class_attribute=False,
                            )
                            result.attributes.append(attr_info)
            elif isinstance(child, ast.AnnAssign):
                # Type-annotated instance attribute: self.name: type = value
                if isinstance(child.target, ast.Attribute) and isinstance(
                    child.target.value, ast.Name
                ):
                    if child.target.value.id == "self":
                        attr_info = AttributeInfo(
                            name=child.target.attr,
                            class_name=class_name,
                            file=result.file_path,
                            definition_line=child.lineno,
                            type_hint=self._extract_type_hint(child.annotation),
                            is_class_attribute=False,
                        )
                        result.attributes.append(attr_info)
