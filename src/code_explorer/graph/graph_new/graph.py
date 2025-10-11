"""
Main DependencyGraph facade.

This facade delegates to specialized operation classes.
To be implemented by Agent 1.
"""

import hashlib
import kuzu
from pathlib import Path
from typing import Optional


class DependencyGraph:
    """
    Main facade for the dependency graph.

    Delegates operations to specialized classes:
    - SchemaManager: schema creation
    - NodeOperations: node CRUD
    - EdgeOperations: edge CRUD
    - QueryOperations: queries
    - BatchOperations: batch inserts
    """

    def __init__(
        self,
        db_path: Optional[Path] = None,
        read_only: bool = False,
        project_root: Optional[Path] = None,
    ):
        """Initialize dependency graph."""
        raise NotImplementedError("Agent 1: Implement DependencyGraph facade")

    # TODO: Agent 1 - Create facade methods that delegate to operation classes
    # All public methods from old DependencyGraph should be available here
