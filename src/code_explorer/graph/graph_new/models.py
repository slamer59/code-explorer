"""
Data models for graph nodes.

Extracted from original graph.py lines 21-105.
"""

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class FunctionNode:
    """Represents a function in the dependency graph."""

    name: str
    file: str
    start_line: int
    end_line: int
    is_public: bool = True


@dataclass
class VariableNode:
    """Represents a variable in the dependency graph."""

    name: str
    file: str
    definition_line: int
    scope: str


@dataclass
class ClassNode:
    """Represents a class in the dependency graph."""

    name: str
    file: str
    start_line: int
    end_line: int
    bases: List[str]
    is_public: bool = True


@dataclass
class ImportNode:
    """Represents an import statement in the dependency graph."""

    imported_name: str
    import_type: str  # "module", "function", "class", "variable", "*"
    alias: Optional[str]
    line_number: int
    is_relative: bool
    file: str


@dataclass
class DecoratorNode:
    """Represents a decorator application in the dependency graph."""

    name: str
    file: str
    line_number: int
    arguments: str  # JSON-serialized decorator arguments


@dataclass
class AttributeNode:
    """Represents a class attribute in the dependency graph."""

    name: str
    class_name: str
    file: str
    definition_line: int
    type_hint: Optional[str]
    is_class_attribute: bool


@dataclass
class ExceptionNode:
    """Represents an exception in the dependency graph."""

    name: str
    file: str
    line_number: int


@dataclass
class ModuleNode:
    """Represents a module in the dependency graph."""

    name: str
    path: str
    is_package: bool
    docstring: Optional[str]
