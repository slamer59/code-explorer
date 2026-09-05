"""Backend-neutral canonical graph records.

Phase 0 of the LatticeDB migration (see docs/explanation/latticedb-migration.md):
a generic id/type/properties shape that any CodeGraphBackend implementation can
consume, independent of Kuzu's column layout. Existing per-type dataclasses in
graph/models.py and analyzer/models.py are unaffected — use the conversion
helpers below at the boundary instead of rewriting extractors/query call sites.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass(slots=True, frozen=True)
class NodeRecord:
    """A single graph node in canonical form.

    id: stable identifier (e.g. 'fn_a1b2c3d4e5f6', or a file's relative path).
    type: canonical node type name (e.g. 'File', 'Function', 'Class').
    properties: type-specific fields, matching the corresponding node dataclass.
    """

    id: str
    type: str
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class EdgeRecord:
    """A single graph edge in canonical form.

    src_id / dst_id: NodeRecord.id of the endpoints.
    type: canonical edge type name (e.g. 'CALLS', 'CONTAINS_FUNCTION').
    properties: type-specific fields (e.g. call_line, confidence).
    src_type / dst_type: endpoint node labels, when they are NOT the single
        pair registered for this edge type in EDGE_ENDPOINT_TYPES.

        Every edge type but one has fixed endpoint labels, so the backends
        read them from that dict and an EdgeRecord carries only ids.
        DEPENDS_ON is the exception: one relation with a `kind` property
        covers inheritance (Class -> Class), decoration (Function|Class ->
        Function|Class) and imports (File -> File), and any of those may
        land on an ExternalSymbol when the target is outside the corpus.
        Splitting it into four typed edges to keep endpoints fixed is
        exactly what this schema decided against (see
        file_analyses_to_records in graph/ingest.py), so the label travels
        with the edge instead. Left None everywhere else.
    """

    src_id: str
    dst_id: str
    type: str
    properties: Dict[str, Any] = field(default_factory=dict)
    src_type: Optional[str] = None
    dst_type: Optional[str] = None


@dataclass(slots=True, frozen=True)
class SearchResult:
    """A single text-search hit, in canonical form.

    node_id: the canonical NodeRecord.id (e.g. 'fn_a1b2c3d4e5f6'), not the
        backend's internal id -- callers use this with get_function/
        get_callers/etc, which key off the canonical id.
    node_type: e.g. 'Function', 'Class'.
    name / file: for display and for calling get_function(file, name).
    score: backend-reported relevance score; not comparable across backends
        or across a mix of exact/fuzzy searches, only within one call's results.
    """

    node_id: str
    node_type: str
    name: str
    file: str
    score: float
