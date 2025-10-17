"""
Graph module for dependency graph storage and querying.

This module provides a refactored structure for the dependency graph:
- models: Data classes for nodes
- schema: Database schema creation
- node_operations: Node CRUD operations
- edge_operations: Edge CRUD operations
- queries: Query operations
- bulk_loader: High-performance bulk loading from Parquet
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
from code_explorer.graph.bulk_loader import (
    load_from_parquet,
    load_from_parquet_sync,
    create_schema,
    preprocess_files_parquet,
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
    "load_from_parquet",
    "load_from_parquet_sync",
    "create_schema",
    "preprocess_files_parquet",
]
