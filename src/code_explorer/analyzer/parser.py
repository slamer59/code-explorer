"""
Tree-sitter Parser Module

Provides core Tree-sitter parsing functionality for Python code analysis.
"""

import logging
from pathlib import Path
from typing import Any, Tuple

from tree_sitter import Parser, Language
import tree_sitter_python

logger = logging.getLogger(__name__)

# Type aliases
TreeSitterNode = Any  # tree_sitter.Node


class ParserInitializationError(Exception):
    """Raised when Tree-sitter parser initialization fails."""

    pass


class ParseError(Exception):
    """Raised when parsing fails."""

    pass


def parse_python_file(
    source_code: str,
    filename: str = "<unknown>",
) -> Any:
    """
    Parse Python source code using Tree-sitter.

    Args:
        source_code: Python source code to parse
        filename: Filename for error reporting

    Returns:
        Tree-sitter root node

    Raises:
        ParseError: If parsing fails
    """
    try:
        return _parse_with_tree_sitter(source_code)
    except Exception as e:
        raise ParseError(f"Failed to parse {filename}: {e}") from e


def _parse_with_tree_sitter(source_code: str) -> Any:
    """
    Internal function to parse using Tree-sitter.

    Args:
        source_code: Python source code to parse

    Returns:
        Tree-sitter root node

    Raises:
        Exception: If parsing fails
    """
    try:
        parser = get_python_parser()
        tree = parser.parse(bytes(source_code, "utf-8"))
        return tree.root_node
    except Exception as e:
        logger.error(f"Tree-sitter parsing failed: {e}")
        raise


def get_parser_type(tree: Any) -> str:
    """
    Detect the type of parser that created the tree.

    Args:
        tree: Parsed tree (Tree-sitter node)

    Returns:
        "tree_sitter" (always, since we only support Tree-sitter)
    """
    return "tree_sitter"


def parse_file(file_path: str | Path) -> Any:
    """
    Parse a Python file.

    Args:
        file_path: Path to the Python file

    Returns:
        Tree-sitter root node

    Raises:
        ParseError: If parsing fails
    """
    file_path = Path(file_path)

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            source_code = f.read()
    except UnicodeDecodeError as e:
        raise ParseError(f"Encoding error reading {file_path}: {e}") from e
    except IOError as e:
        raise ParseError(f"Error reading {file_path}: {e}") from e

    return parse_python_file(source_code, filename=str(file_path))


def get_python_parser() -> Parser:
    """
    Initialize and return a Tree-sitter parser for Python.

    Returns:
        Parser: Configured Tree-sitter parser for Python

    Raises:
        ParserInitializationError: If parser initialization fails

    Examples:
        >>> parser = get_python_parser()
        >>> tree = parser.parse(b"def hello(): pass")
    """
    try:
        # Get Python language from tree-sitter-python
        py_language = Language(tree_sitter_python.language())

        # Initialize parser
        parser = Parser()
        parser.language = py_language

        logger.debug("Tree-sitter Python parser initialized successfully")
        return parser
    except Exception as e:
        logger.error(f"Failed to initialize Tree-sitter parser: {e}")
        raise ParserInitializationError(f"Cannot initialize parser: {e}") from e


def extract_source_text(node: TreeSitterNode, source_code: bytes) -> str:
    """
    Extract source text from a Tree-sitter node.

    Args:
        node: Tree-sitter node
        source_code: Original source code as bytes

    Returns:
        str: Text content of the node

    Raises:
        ValueError: If node or source_code is invalid

    Examples:
        >>> code = b"def hello():\\n    pass"
        >>> tree = parse_python_file(code.decode())
        >>> text = extract_source_text(tree, code)
        >>> print(text)
        'def hello():\\n    pass'
    """
    try:
        if not hasattr(node, "start_byte") or not hasattr(node, "end_byte"):
            raise ValueError("Node does not have start_byte/end_byte attributes")

        start = node.start_byte
        end = node.end_byte

        if start < 0 or end < 0 or start > end:
            raise ValueError(f"Invalid node byte offsets: start={start}, end={end}")

        if start > len(source_code) or end > len(source_code):
            raise ValueError(
                f"Node offsets out of bounds: [{start}, {end}] "
                f"for source of length {len(source_code)}"
            )

        # Extract and decode the text
        text = source_code[start:end].decode("utf-8")
        return text
    except AttributeError as e:
        logger.error(f"Node missing required attributes: {e}")
        raise ValueError(f"Invalid node object: {e}") from e
    except UnicodeDecodeError as e:
        logger.error(f"Failed to decode node text: {e}")
        raise ValueError(f"Cannot decode node text: {e}") from e
    except Exception as e:
        logger.error(f"Failed to extract source text: {e}")
        raise ValueError(f"Cannot extract source text: {e}") from e


def get_node_text(node: TreeSitterNode, source_bytes: bytes) -> str:
    """
    Helper function to get text from a Tree-sitter node.

    Alias for extract_source_text for convenience.

    Args:
        node: Tree-sitter node
        source_bytes: Original source code as bytes

    Returns:
        str: Text content of the node

    Raises:
        ValueError: If node or source_bytes is invalid

    Examples:
        >>> code = b"x = 42"
        >>> tree = parse_python_file(code.decode())
        >>> text = get_node_text(tree, code)
    """
    return extract_source_text(node, source_bytes)


def parse_and_extract(
    source_code: str, file_path: str = "<string>"
) -> Tuple[TreeSitterNode, bytes]:
    """
    Parse Python code and return both the parse tree and source bytes.

    Convenience function for parsing when you need both the tree and source.

    Args:
        source_code: Python source code as string
        file_path: Optional file path for logging/debugging

    Returns:
        Tuple[TreeSitterNode, bytes]: Parsed tree root node and source bytes

    Raises:
        ParseError: If parsing fails

    Examples:
        >>> code = "def hello(): pass"
        >>> tree, source_bytes = parse_and_extract(code)
        >>> print(tree.type)
        'module'
    """
    tree = parse_python_file(source_code, file_path)
    source_bytes = source_code.encode("utf-8")
    return tree, source_bytes
