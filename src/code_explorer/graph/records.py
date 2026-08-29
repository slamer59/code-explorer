"""Backend-neutral canonical graph records.

Phase 0 of the LatticeDB migration (see docs/explanation/latticedb-migration.md):
a generic id/type/properties shape that any CodeGraphBackend implementation can
consume, independent of Kuzu's column layout. Existing per-type dataclasses in
graph/models.py and analyzer/models.py are unaffected — use the conversion
helpers below at the boundary instead of rewriting extractors/query call sites.
"""

from dataclasses import dataclass, field
from typing import Any, Dict


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
    """

    src_id: str
    dst_id: str
    type: str
    properties: Dict[str, Any] = field(default_factory=dict)


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
