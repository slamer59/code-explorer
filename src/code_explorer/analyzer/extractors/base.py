"""
Base extractor interface.

All extractors inherit from BaseExtractor and implement the extract method.
Uses Tree-sitter exclusively for parsing.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Union

from code_explorer.analyzer.models import FileAnalysis
from code_explorer.analyzer.tree_sitter_adapter import (
    ASTNode, TreeSitterAdapter, TreeSitterNode,
    NodeWrapper, detect_parser_type, wrap_node,
    walk_tree, get_node_name,
    is_function_node, is_call_node
)

logger = logging.getLogger(__name__)


class BaseExtractor(ABC):
    """Base class for all extractors.

    Extractors analyze Tree-sitter trees and populate FileAnalysis results.
    Each extractor is responsible for one aspect of code analysis.

    Uses Tree-sitter exclusively for parsing.
    """

    def __init__(self):
        """Initialize the extractor."""
        self.parser_type = "tree_sitter"

    def wrap_node(self, node: Any) -> NodeWrapper:
        """
        Wrap a Tree-sitter node in the appropriate wrapper.

        Args:
            node: Tree-sitter node or adapter

        Returns:
            NodeWrapper that provides unified interface
        """
        return wrap_node(node)

    def walk_tree(self, tree: Any):
        """
        Walk a Tree-sitter tree.

        Args:
            tree: Tree-sitter root node

        Returns:
            Iterator over nodes in pre-order traversal
        """
        return walk_tree(tree)

    @abstractmethod
    def extract(self, tree: 'ASTNode', result: FileAnalysis) -> None:
        """Extract information from Tree-sitter tree and populate result.

        Args:
            tree: Tree-sitter root node
            result: FileAnalysis object to populate with extracted information
        """
        pass

    # Helper methods for common operations
    def is_function_node(self, node: Any) -> bool:
        """
        Check if a node represents a function definition.

        Args:
            node: Node to check

        Returns:
            True if node is a function definition
        """
        return is_function_node(node)

    def is_call_node(self, node: Any) -> bool:
        """
        Check if a node represents a function call.

        Args:
            node: Node to check

        Returns:
            True if node is a function call
        """
        return is_call_node(node)

    def get_node_name(self, node: Any) -> Union[str, None]:
        """
        Get the name of a Tree-sitter node.

        Args:
            node: Node to get name from

        Returns:
            Node name or None if not applicable
        """
        return get_node_name(node)

    def get_node_line_range(self, node: Any) -> tuple[int, int]:
        """
        Get the line range of a Tree-sitter node.

        Args:
            node: Node to get range from

        Returns:
            Tuple of (start_line, end_line) using 1-based line numbers
        """
        wrapped = self.wrap_node(node)
        start_line = wrapped.lineno or 0
        end_line = wrapped.end_lineno or start_line
        return (start_line, end_line)
