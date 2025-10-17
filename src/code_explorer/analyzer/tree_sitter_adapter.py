"""
Tree-sitter adapter for code-explorer.

Provides a compatibility layer between Tree-sitter nodes and AST nodes,
allowing extractors to work with both parsing systems transparently.
"""

import ast
import logging
from typing import Any, Dict, List, Optional, Union

try:
    import tree_sitter
    import tree_sitter_languages
except ImportError:
    tree_sitter = None
    tree_sitter_languages = None

logger = logging.getLogger(__name__)

# Type aliases for better readability
ASTNode = ast.AST
TreeSitterNode = Any  # tree_sitter.Node if available

# Tree-sitter Python node types mapping
# Reference: https://github.com/tree-sitter/tree-sitter-python/blob/master/src/node-types.json
TREE_SITTER_NODE_TYPES: Dict[str, str] = {
    # Statements
    "module": "Module",
    "function_definition": "FunctionDef",
    "class_definition": "ClassDef",
    "decorated_definition": "Decorated",
    "if_statement": "If",
    "for_statement": "For",
    "while_statement": "While",
    "with_statement": "With",
    "try_statement": "Try",
    "except_clause": "ExceptHandler",
    "finally_clause": "Finally",
    "return_statement": "Return",
    "raise_statement": "Raise",
    "break_statement": "Break",
    "continue_statement": "Continue",
    "pass_statement": "Pass",
    "delete_statement": "Delete",
    "assert_statement": "Assert",
    "import_statement": "Import",
    "import_from_statement": "ImportFrom",
    "print_statement": "Print",
    "exec_statement": "Exec",
    "global_statement": "Global",
    "nonlocal_statement": "Nonlocal",
    "yield_statement": "Yield",
    "expression_statement": "Expr",
    # Expressions
    "call": "Call",
    "attribute": "Attribute",
    "subscript": "Subscript",
    "list": "List",
    "tuple": "Tuple",
    "dict": "Dict",
    "set": "Set",
    "string": "Constant",
    "number": "Constant",
    "name": "Name",
    "identifier": "Identifier",
    "binary_operation": "BinOp",
    "unary_operation": "UnaryOp",
    "lambda": "Lambda",
    "conditional_expression": "IfExp",
    "comparison": "Compare",
    "boolean_operator": "BoolOp",
    "boolean_operation": "BoolOp",
    "list_comprehension": "ListComp",
    "dict_comprehension": "DictComp",
    "set_comprehension": "SetComp",
    "generator_expression": "GeneratorExp",
    # Others
    "parameters": "Parameters",
    "parameter": "Parameter",
    "default_parameter": "DefaultParameter",
    "typed_parameter": "TypedParameter",
    "keyword_argument": "KeywordArg",
    "comment": "Comment",
}


class TreeSitterAdapter:
    """
    Adapter class to provide AST-like interface for Tree-sitter nodes.

    This adapter wraps Tree-sitter nodes and provides methods that mimic
    the AST node interface, allowing existing extractors to work without
    modification.
    """

    def __init__(self, node: TreeSitterNode):
        """Initialize adapter with a Tree-sitter node.

        Args:
            node: Tree-sitter node to wrap
        """
        if tree_sitter is None:
            raise ImportError("tree_sitter is not installed")

        self._node = node
        self._children_cache: Optional[List['TreeSitterAdapter']] = None

    @property
    def node_type(self) -> str:
        """Get the Tree-sitter node type."""
        return self._node.type

    def is_ast_node(self) -> bool:
        """Check if this is an AST node (always False for adapter)."""
        return False

    def is_tree_sitter_node(self) -> bool:
        """Check if this is a Tree-sitter node (always True for adapter)."""
        return True

    def get_original_node(self) -> TreeSitterNode:
        """Get the original Tree-sitter node."""
        return self._node

    @property
    def children(self) -> List['TreeSitterAdapter']:
        """Get child nodes as adapters."""
        if self._children_cache is None:
            self._children_cache = [
                TreeSitterAdapter(child)
                for child in self._node.children
            ]
        return self._children_cache

    def child_by_field_name(self, field_name: str) -> Optional['TreeSitterAdapter']:
        """Get child by field name."""
        child = self._node.child_by_field_name(field_name)
        return TreeSitterAdapter(child) if child else None

    def walk(self) -> 'TreeSitterWalker':
        """Get a walker for traversing the tree."""
        return TreeSitterWalker(self)

    # AST-like properties for compatibility
    @property
    def lineno(self) -> Optional[int]:
        """Get line number (1-based like AST)."""
        if hasattr(self._node, 'start_point'):
            return self._node.start_point[0] + 1
        return None

    @property
    def end_lineno(self) -> Optional[int]:
        """Get end line number (1-based like AST)."""
        if hasattr(self._node, 'end_point'):
            return self._node.end_point[0] + 1
        return None

    @property
    def col_offset(self) -> Optional[int]:
        """Get column offset (0-based like AST)."""
        if hasattr(self._node, 'start_point'):
            return self._node.start_point[1]
        return None

    @property
    def end_col_offset(self) -> Optional[int]:
        """Get end column offset (0-based like AST)."""
        if hasattr(self._node, 'end_point'):
            return self._node.end_point[1]
        return None

    def __getattr__(self, name: str) -> Any:
        """Delegate attribute access to the underlying node."""
        return getattr(self._node, name)


class TreeSitterWalker:
    """Walker class for traversing Tree-sitter trees."""

    def __init__(self, node: TreeSitterAdapter):
        """Initialize walker with a node adapter."""
        self._node = node
        self._stack = [node]
        self._visited = set()

    def __iter__(self):
        """Make walker iterable."""
        return self

    def __next__(self) -> TreeSitterAdapter:
        """Get next node in pre-order traversal."""
        while self._stack:
            node = self._stack.pop()
            node_id = id(node._node)

            if node_id not in self._visited:
                self._visited.add(node_id)
                # Add children in reverse order for correct traversal
                for child in reversed(node.children):
                    self._stack.append(child)
                return node

        raise StopIteration


class NodeWrapper:
    """
    Wrapper that can hold either AST or Tree-sitter nodes.

    This provides a unified interface for working with both types of nodes.
    """

    def __init__(self, node: Union[ASTNode, TreeSitterNode, TreeSitterAdapter]):
        """Initialize wrapper with either AST or Tree-sitter node."""
        if isinstance(node, TreeSitterAdapter):
            self._adapter = node
            self._node = node.get_original_node()
            self._is_ast = False
        elif tree_sitter is not None and hasattr(node, 'type'):
            # Likely a Tree-sitter node
            self._adapter = TreeSitterAdapter(node)
            self._node = node
            self._is_ast = False
        else:
            # AST node
            self._adapter = None
            self._node = node
            self._is_ast = True

    @property
    def node(self) -> Union[ASTNode, TreeSitterNode]:
        """Get the original node."""
        return self._node

    @property
    def adapter(self) -> Optional[TreeSitterAdapter]:
        """Get the Tree-sitter adapter (if applicable)."""
        return self._adapter

    def is_ast(self) -> bool:
        """Check if this wraps an AST node."""
        return self._is_ast

    def is_tree_sitter(self) -> bool:
        """Check if this wraps a Tree-sitter node."""
        return not self._is_ast

    def walk(self) -> Union[ast.NodeVisitor, TreeSitterWalker]:
        """Get appropriate walker for the node type."""
        if self._is_ast:
            return ast.walk(self._node)
        else:
            return self._adapter.walk()

    # Common properties that work for both node types
    @property
    def lineno(self) -> Optional[int]:
        """Get line number."""
        if self._is_ast:
            return getattr(self._node, 'lineno', None)
        else:
            return self._adapter.lineno

    @property
    def end_lineno(self) -> Optional[int]:
        """Get end line number."""
        if self._is_ast:
            return getattr(self._node, 'end_lineno', None)
        else:
            return self._adapter.end_lineno

    def get_node_type(self) -> str:
        """Get node type name."""
        if self._is_ast:
            return type(self._node).__name__
        else:
            return self._adapter.node_type

    def get_children(self) -> List['NodeWrapper']:
        """Get children as wrapped nodes."""
        if self._is_ast:
            # AST nodes don't have a standard children interface
            # This would need to be implemented based on specific node types
            return []
        else:
            return [NodeWrapper(child) for child in self._adapter.children]

    def get_attribute(self, attr_name: str) -> Any:
        """Get attribute from the underlying node."""
        if self._is_ast:
            return getattr(self._node, attr_name, None)
        else:
            # For Tree-sitter, try field name first
            child = self._adapter.child_by_field_name(attr_name)
            if child:
                return NodeWrapper(child)
            # Fall back to attribute
            return getattr(self._node, attr_name, None)


def is_tree_sitter_available() -> bool:
    """Check if Tree-sitter is available."""
    return tree_sitter is not None


def wrap_node(node: Union[ASTNode, TreeSitterNode, TreeSitterAdapter]) -> NodeWrapper:
    """
    Wrap a node in the appropriate wrapper.

    Args:
        node: AST node, Tree-sitter node, or TreeSitterAdapter

    Returns:
        NodeWrapper that provides unified interface
    """
    return NodeWrapper(node)


def detect_parser_type(tree: Any) -> str:
    """
    Detect what type of parser was used to create the tree.

    Args:
        tree: Parsed tree object

    Returns:
        "ast", "tree_sitter", or "unknown"
    """
    if isinstance(tree, ast.AST):
        return "ast"
    elif tree_sitter is not None and hasattr(tree, 'type'):
        return "tree_sitter"
    elif isinstance(tree, TreeSitterAdapter):
        return "tree_sitter"
    else:
        return "unknown"


def get_tree_sitter_adapter(node: TreeSitterNode) -> TreeSitterAdapter:
    """
    Get a Tree-sitter adapter for a node.

    Args:
        node: Tree-sitter node to wrap

    Returns:
        TreeSitterAdapter instance
    """
    return TreeSitterAdapter(node)


def walk_tree(tree: Union[ASTNode, TreeSitterNode, TreeSitterAdapter, NodeWrapper]) -> Union:
    """
    Walk a tree using the appropriate walker.

    Args:
        tree: Tree to walk (AST or Tree-sitter)

    Returns:
        Iterator over nodes
    """
    if isinstance(tree, NodeWrapper):
        return tree.walk()
    elif isinstance(tree, TreeSitterAdapter):
        return tree.walk()
    elif tree_sitter is not None and hasattr(tree, 'type'):
        # Raw Tree-sitter node
        return TreeSitterAdapter(tree).walk()
    else:
        # Assume AST node
        return ast.walk(tree)


def get_tree_sitter_language() -> Optional[Any]:
    """
    Get Tree-sitter Python language parser.

    Returns:
        Tree-sitter language object or None if not available
    """
    if tree_sitter is None or tree_sitter_languages is None:
        logger.warning("tree_sitter or tree_sitter_languages not available")
        return None

    try:
        # Get Python language from tree-sitter-languages
        return tree_sitter_languages.get_language("python")
    except Exception as e:
        logger.warning(f"Tree-sitter Python language not available: {e}")
        return None


def parse_with_tree_sitter(source_code: str, language: Optional[Any] = None) -> Optional[TreeSitterNode]:
    """
    Parse source code using Tree-sitter.

    Args:
        source_code: Python source code to parse
        language: Tree-sitter language object

    Returns:
        Tree-sitter root node or None if parsing fails
    """
    if tree_sitter is None:
        logger.warning("Tree-sitter not available, falling back to AST")
        return None

    if language is None:
        language = get_tree_sitter_language()
        if language is None:
            logger.warning("Tree-sitter Python language not available")
            return None

    try:
        parser = tree_sitter.Parser()
        parser.set_language(language)
        tree = parser.parse(bytes(source_code, 'utf8'))
        return tree.root_node
    except Exception as e:
        logger.error(f"Tree-sitter parsing failed: {e}")
        return None


def is_function_node(node: Union[ASTNode, TreeSitterNode, TreeSitterAdapter, NodeWrapper]) -> bool:
    """
    Check if a node represents a function definition.

    Args:
        node: Node to check

    Returns:
        True if node is a function definition
    """
    if isinstance(node, NodeWrapper):
        if node.is_ast():
            return isinstance(node.node, ast.FunctionDef)
        else:
            return node.adapter.node_type == "function_definition"
    elif isinstance(node, TreeSitterAdapter):
        return node.node_type == "function_definition"
    else:
        return isinstance(node, ast.FunctionDef)


def is_call_node(node: Union[ASTNode, TreeSitterNode, TreeSitterAdapter, NodeWrapper]) -> bool:
    """
    Check if a node represents a function call.

    Args:
        node: Node to check

    Returns:
        True if node is a function call
    """
    if isinstance(node, NodeWrapper):
        if node.is_ast():
            return isinstance(node.node, ast.Call)
        else:
            return node.adapter.node_type == "call"
    elif isinstance(node, TreeSitterAdapter):
        return node.node_type == "call"
    else:
        return isinstance(node, ast.Call)


def get_node_name(node: Union[ASTNode, TreeSitterNode, TreeSitterAdapter, NodeWrapper]) -> Optional[str]:
    """
    Get the name of a node (function name, variable name, etc.).

    Args:
        node: Node to get name from

    Returns:
        Node name or None if not applicable
    """
    if isinstance(node, NodeWrapper):
        if node.is_ast():
            ast_node = node.node
            if isinstance(ast_node, ast.FunctionDef):
                return ast_node.name
            elif isinstance(ast_node, ast.Name):
                return ast_node.id
            elif isinstance(ast_node, ast.Attribute):
                return ast_node.attr
            return None
        else:
            # Tree-sitter node
            adapter = node.adapter
            if adapter.node_type == "function_definition":
                # Try to get the name from the identifier child
                name_child = adapter.child_by_field_name("name")
                if name_child:
                    return name_child.get_original_node().text.decode('utf8')
            elif adapter.node_type == "identifier":
                return adapter.get_original_node().text.decode('utf8')
            return None
    elif isinstance(node, TreeSitterAdapter):
        if node.node_type == "function_definition":
            name_child = node.child_by_field_name("name")
            if name_child:
                return name_child.get_original_node().text.decode('utf8')
        elif node.node_type == "identifier":
            return node.get_original_node().text.decode('utf8')
        return None
    else:
        # AST node
        if isinstance(node, ast.FunctionDef):
            return node.name
        elif isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return node.attr
        return None