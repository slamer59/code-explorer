"""
Edge CRUD operations for the dependency graph.

To be implemented by Agent 1.
"""

import kuzu


class EdgeOperations:
    """Handles all edge creation operations."""

    def __init__(self, conn: kuzu.Connection, read_only: bool = False):
        """Initialize edge operations."""
        raise NotImplementedError("Agent 1: Implement EdgeOperations")

    # TODO: Agent 1 - Extract these methods from DependencyGraph:
    # - add_call
    # - add_variable_usage
    # - add_exception_handling
    # - add_attribute_access
    # - add_class_dependency
