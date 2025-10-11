"""
Backward compatibility redirect.
Import from the new modular structure.
"""
from code_explorer.graph.graph import DependencyGraph
from code_explorer.graph.models import (
    AttributeNode,
    ClassNode,
    DecoratorNode,
    ExceptionNode,
    FunctionNode,
    ImportNode,
    ModuleNode,
    VariableNode,
)

__all__ = [
    "DependencyGraph",
    "FunctionNode",
    "VariableNode",
    "ClassNode",
    "ImportNode",
    "DecoratorNode",
    "AttributeNode",
    "ExceptionNode",
    "ModuleNode",
]
