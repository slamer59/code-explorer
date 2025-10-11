"""
Attribute extraction from AST.

Extracted from analyzer.py lines 901-1015.
"""

import ast
from typing import Optional

from code_explorer.analyzer.extractors.base import BaseExtractor
from code_explorer.analyzer.models import AttributeInfo, FileAnalysis


class AttributeExtractor(BaseExtractor):
    """Extracts class attribute information from AST."""

    def extract(self, tree: ast.AST, result: FileAnalysis) -> None:
        """Extract attributes using ast.

        Extracted from _extract_attributes (lines 997-1015).

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
