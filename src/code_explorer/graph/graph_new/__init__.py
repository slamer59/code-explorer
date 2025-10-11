"""
Graph module for dependency graph storage and querying.

This module provides a refactored structure for the dependency graph:
- models: Data classes for nodes
- schema: Database schema creation
- node_operations: Node CRUD operations
- edge_operations: Edge CRUD operations
- queries: Query operations
- batch_operations: Batch insert operations
- graph: Main DependencyGraph facade
"""

# Backward compatibility: Export everything from the facade
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
