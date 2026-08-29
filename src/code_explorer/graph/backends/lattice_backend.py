"""LatticeDB implementation of CodeGraphBackend.

Phase 1 of the LatticeDB migration (see docs/explanation/latticedb-migration.md):
the first real, non-Kuzu CodeGraphBackend, verified against latticedb==0.15.0's
actual Python API (confirmed interactively before writing this file -- see
scratchpad smoke scripts referenced in the implementation session).

Key differences from KuzuBackend that shape this implementation:

- LatticeDB nodes/edges are schema-less: a node is (internal int id, labels,
  properties dict). There is no CREATE TABLE / typed-column DDL, so
  initialize_schema() only creates property indexes (for upsert-by-canonical-id
  lookups) instead of tables.
- Our canonical NodeRecord.id (e.g. 'fn_a1b2c3d4e5f6', or a File's relative
  path) is not the same as LatticeDB's internal node id. upsert_nodes looks up
  existing nodes by the same primary-key property Kuzu uses (see
  NODE_PRIMARY_KEY in kuzu_backend.py) via find_nodes_by_label_property, and
  creates a new node only if none is found.
- delete_node does NOT cascade-delete attached edges (confirmed empirically:
  a dangling Edge remains referencing a deleted node id). delete_file must
  therefore delete a node's incoming/outgoing edges explicitly before deleting
  the node itself -- there is no DETACH DELETE equivalent.
"""

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import latticedb

from code_explorer.graph.backends.kuzu_backend import (
    EDGE_ENDPOINT_TYPES,
    FILE_SCOPED_NODE_TYPES,
    NODE_PRIMARY_KEY,
)
from code_explorer.graph.records import EdgeRecord, NodeRecord


class LatticeBackend:
    """CodeGraphBackend implementation backed by LatticeDB."""

    def __init__(self, db_path: Path, read_only: bool = False):
        self.db_path = db_path
        self.read_only = read_only
        self.db: Optional[latticedb.Database] = None

    def open(self) -> None:
        if not self.read_only:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = latticedb.Database(
            self.db_path,
            create=not self.read_only,
            read_only=self.read_only,
        )
        self.db.open()

    def close(self) -> None:
        if self.db is not None:
            self.db.close()
        self.db = None

    def _ensure_node_property_index(self, label: str, prop: str) -> None:
        try:
            self.db.create_node_property_index(label, prop)
        except latticedb.LatticeAlreadyExistsError:
            pass

    def initialize_schema(self) -> None:
        if self.read_only:
            return
        # find_nodes_by_label_property requires a property index to exist for
        # the (label, property) pair -- confirmed empirically, it raises
        # LatticeUnsupportedError otherwise rather than falling back to a scan.
        for label, pk in NODE_PRIMARY_KEY.items():
            self._ensure_node_property_index(label, pk)
        # delete_file looks nodes up by their owning file's path via the
        # 'file' property, which also needs an index.
        for label in FILE_SCOPED_NODE_TYPES:
            self._ensure_node_property_index(label, "file")

    def detect_schema_version(self) -> str:
        """No versioned schema in LatticeDB (schema-less); always current."""
        return "v2"

    def _find_node_id(
        self, txn: "latticedb.Transaction", node_type: str, pk_value: Any
    ) -> Optional[int]:
        pk = NODE_PRIMARY_KEY[node_type]
        matches = txn.find_nodes_by_label_property(node_type, pk, pk_value, limit=1)
        return matches[0] if matches else None

    def upsert_nodes(self, nodes: Iterable[NodeRecord]) -> None:
        with self.db.write() as txn:
            for node in nodes:
                pk = NODE_PRIMARY_KEY.get(node.type)
                if pk is None:
                    raise ValueError(f"Unknown node type for upsert: {node.type}")
                pk_value = node.properties.get(pk, node.id)
                existing_id = self._find_node_id(txn, node.type, pk_value)
                if existing_id is not None:
                    for key, value in node.properties.items():
                        txn.set_property(existing_id, key, value)
                else:
                    txn.create_node(labels=[node.type], properties=dict(node.properties))
            txn.commit()

    def upsert_edges(self, edges: Iterable[EdgeRecord]) -> None:
        with self.db.write() as txn:
            for edge in edges:
                endpoints = EDGE_ENDPOINT_TYPES.get(edge.type)
                if endpoints is None:
                    raise ValueError(f"Unknown edge type for upsert: {edge.type}")
                src_type, dst_type = endpoints
                src_id = self._find_node_id(txn, src_type, edge.src_id)
                dst_id = self._find_node_id(txn, dst_type, edge.dst_id)
                if src_id is None or dst_id is None:
                    raise ValueError(
                        f"Cannot create {edge.type} edge: endpoint node not found "
                        f"(src={edge.src_id!r} found={src_id is not None}, "
                        f"dst={edge.dst_id!r} found={dst_id is not None})"
                    )
                txn.create_edge(
                    src_id, dst_id, edge.type, properties=dict(edge.properties)
                )
            txn.commit()

    def delete_file(self, file_key: str) -> None:
        with self.db.write() as txn:
            node_ids: List[int] = []
            for node_type in FILE_SCOPED_NODE_TYPES:
                node_ids.extend(
                    txn.find_nodes_by_label_property(
                        node_type, "file", file_key, limit=100_000
                    )
                )
            file_id = self._find_node_id(txn, "File", file_key)
            if file_id is not None:
                node_ids.append(file_id)

            for node_id in node_ids:
                for edge in txn.get_outgoing_edges(node_id):
                    txn.delete_edge(edge.source_id, edge.target_id, edge.edge_type)
                for edge in txn.get_incoming_edges(node_id):
                    txn.delete_edge(edge.source_id, edge.target_id, edge.edge_type)
            for node_id in node_ids:
                txn.delete_node(node_id)
            txn.commit()

    def query(
        self, statement: str, params: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        return self.db.query(statement, params or {}).fetchall()
