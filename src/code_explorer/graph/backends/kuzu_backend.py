"""Kuzu implementation of CodeGraphBackend.

Wraps the kuzu.Database/kuzu.Connection construction and SchemaManager that used
to live directly in DependencyGraph.__init__ (see graph/graph.py). This is
Phase 0's proof that the CodeGraphBackend interface fits the existing behavior
before a LatticeBackend is attempted.

upsert_nodes/upsert_edges are a generic implementation of the canonical
NodeRecord/EdgeRecord shape, driven by the same primary keys and FROM/TO
endpoint types declared in graph/schema.py's DDL. DependencyGraph does not use
them yet -- it still calls the specialized NodeOperations/EdgeOperations/
QueryOperations classes directly via `backend.conn`, which remains unchanged in
Phase 0 (see docs/explanation/latticedb-migration.md, Phase 0 scope).
"""

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import kuzu

from code_explorer.graph.records import EdgeRecord, NodeRecord
from code_explorer.graph.schema import SchemaManager

# Primary key property per node type, mirroring the CREATE NODE TABLE ...
# PRIMARY KEY(...) clauses in schema.py.
NODE_PRIMARY_KEY: Dict[str, str] = {
    "File": "path",
    "Function": "id",
    "Variable": "id",
    "Class": "id",
    "Import": "id",
    "Decorator": "id",
    "Attribute": "id",
    "Exception": "id",
    "Module": "id",
}

# (src_type, dst_type) per edge type, mirroring the CREATE REL TABLE ... FROM
# ... TO ... clauses in schema.py.
EDGE_ENDPOINT_TYPES: Dict[str, Tuple[str, str]] = {
    "CALLS": ("Function", "Function"),
    "REFERENCES": ("Function", "Variable"),
    "CONTAINS_FUNCTION": ("File", "Function"),
    "CONTAINS_CLASS": ("File", "Class"),
    "CONTAINS_VARIABLE": ("File", "Variable"),
    "IMPORTS": ("File", "File"),
    "INHERITS": ("Class", "Class"),
    "DEPENDS_ON": ("Class", "Class"),
    "METHOD_OF": ("Function", "Class"),
    "HAS_IMPORT": ("File", "Import"),
    "IMPORTS_FROM": ("Import", "Function"),
    "DECORATED_BY": ("Function", "Decorator"),
    "HAS_ATTRIBUTE": ("Class", "Attribute"),
    "ACCESSES": ("Function", "Attribute"),
    "HANDLES_EXCEPTION": ("Function", "Exception"),
    "CONTAINS_MODULE": ("Module", "Module"),
    "MODULE_OF": ("File", "Module"),
}

# Node types deleted (with their owned edges) when a file is removed/re-indexed,
# matching DependencyGraph.node_ops.delete_file_data.
FILE_SCOPED_NODE_TYPES = (
    "Function",
    "Class",
    "Variable",
    "Import",
    "Decorator",
    "Attribute",
    "Exception",
)


class KuzuBackend:
    """CodeGraphBackend implementation backed by KuzuDB."""

    def __init__(self, db_path: Path, read_only: bool = False):
        self.db_path = db_path
        self.read_only = read_only
        self.db: Optional[kuzu.Database] = None
        self.conn: Optional[kuzu.Connection] = None
        self.schema_manager: Optional[SchemaManager] = None

    def open(self) -> None:
        if not self.read_only:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = kuzu.Database(str(self.db_path), read_only=self.read_only)
        self.conn = kuzu.Connection(self.db)
        self.schema_manager = SchemaManager(self.conn)

    def close(self) -> None:
        self.conn = None
        self.db = None
        self.schema_manager = None

    def initialize_schema(self) -> None:
        if self.read_only:
            return
        self.schema_manager.create_schema()

    def detect_schema_version(self) -> str:
        """Preserved from SchemaManager for DependencyGraph's existing use."""
        return self.schema_manager.detect_schema_version()

    def upsert_nodes(self, nodes: Iterable[NodeRecord]) -> None:
        for node in nodes:
            pk = NODE_PRIMARY_KEY.get(node.type)
            if pk is None:
                raise ValueError(f"Unknown node type for upsert: {node.type}")
            pk_value = node.properties.get(pk, node.id)
            set_props = {k: v for k, v in node.properties.items() if k != pk}
            set_clause = ", ".join(f"n.{k} = ${k}" for k in set_props)
            params = {pk: pk_value, **set_props}
            query = f"MERGE (n:{node.type} {{{pk}: ${pk}}})"
            if set_clause:
                query += f" ON CREATE SET {set_clause} ON MATCH SET {set_clause}"
            self.conn.execute(query, params)

    def upsert_edges(self, edges: Iterable[EdgeRecord]) -> None:
        for edge in edges:
            endpoints = EDGE_ENDPOINT_TYPES.get(edge.type)
            if endpoints is None:
                raise ValueError(f"Unknown edge type for upsert: {edge.type}")
            src_type, dst_type = endpoints
            src_pk = NODE_PRIMARY_KEY[src_type]
            dst_pk = NODE_PRIMARY_KEY[dst_type]
            set_clause = ", ".join(f"r.{k} = ${k}" for k in edge.properties)
            params = {
                "src": edge.src_id,
                "dst": edge.dst_id,
                **edge.properties,
            }
            query = (
                f"MATCH (a:{src_type} {{{src_pk}: $src}}), "
                f"(b:{dst_type} {{{dst_pk}: $dst}}) "
                f"MERGE (a)-[r:{edge.type}]->(b)"
            )
            if set_clause:
                query += f" SET {set_clause}"
            self.conn.execute(query, params)

    def delete_file(self, file_key: str) -> None:
        for node_type in FILE_SCOPED_NODE_TYPES:
            self.conn.execute(
                f"MATCH (n:{node_type} {{file: $path}}) DETACH DELETE n",
                {"path": file_key},
            )
        self.conn.execute(
            "MATCH (f:File {path: $path}) DETACH DELETE f",
            {"path": file_key},
        )

    def clear_all(self) -> None:
        for node_type in NODE_PRIMARY_KEY:
            self.conn.execute(f"MATCH (n:{node_type}) DETACH DELETE n")

    def query(
        self, statement: str, params: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        result = self.conn.execute(statement, params or {})
        columns = result.get_column_names()
        rows: List[Dict[str, Any]] = []
        while result.has_next():
            rows.append(dict(zip(columns, result.get_next())))
        return rows
