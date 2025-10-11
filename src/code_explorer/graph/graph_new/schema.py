"""
Database schema management for KuzuDB.

To be implemented by Agent 1.
"""

import kuzu


class SchemaManager:
    """Manages database schema creation and versioning."""

    def __init__(self, conn: kuzu.Connection):
        """Initialize schema manager."""
        raise NotImplementedError("Agent 1: Implement SchemaManager")

    def create_schema(self) -> None:
        """Create all node and edge tables."""
        raise NotImplementedError("Agent 1: Extract from _create_schema")

    def detect_version(self) -> str:
        """Detect schema version (v1 or v2)."""
        raise NotImplementedError("Agent 1: Extract from _detect_schema_version")
