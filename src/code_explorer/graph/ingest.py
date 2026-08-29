"""Generic FileAnalysis -> NodeRecord/EdgeRecord conversion.

Phase 1 of the LatticeDB migration (see docs/explanation/latticedb-migration.md):
lets `analyze` populate any CodeGraphBackend, not just Kuzu. KuzuBackend has a
much faster dedicated path (Parquet export + COPY FROM, see
graph/bulk_loader.py and analyzer/export_parquet.py) which this module does
NOT replace -- this exists for backends without a bulk-loader equivalent
(e.g. LatticeBackend), going through the generic upsert_nodes/upsert_edges
interface instead.

Only covers File, Function, Class nodes (+ CONTAINS_FUNCTION, CONTAINS_CLASS,
CALLS edges) -- enough for `analyze` + `impact` to work end to end. Variable,
Import, Decorator, Attribute, Exception, Module and their edges are not
converted here; add them the same way if/when a backend needs them.

Reuses export_parquet.py's ID-generation helpers (make_function_id,
make_class_id, to_relative_path) rather than adding a third copy of that
hashing logic alongside graph/graph.py's private _make_*_id methods and
export_parquet.py's own copy.
"""

from pathlib import Path
from typing import List, Optional, Tuple

from code_explorer.analyzer.export_parquet import (
    make_class_id,
    make_function_id,
    to_relative_path,
)
from code_explorer.analyzer.models import FileAnalysis
from code_explorer.graph.records import EdgeRecord, NodeRecord


def file_analyses_to_records(
    results: List[FileAnalysis],
    project_root: Path,
    resolved_calls: Optional[List[dict]] = None,
) -> Tuple[List[NodeRecord], List[EdgeRecord]]:
    """Convert analyzer output into canonical NodeRecord/EdgeRecord lists.

    Args:
        results: FileAnalysis objects from CodeAnalyzer.analyze_directory.
        project_root: Root directory for relative paths (matches the ID
            hashing convention used elsewhere in the codebase).
        resolved_calls: Optional resolved CALLS edges from
            CallResolver.resolve_all_calls(), same shape export_to_parquet
            expects.

    Returns:
        (nodes, edges) ready for CodeGraphBackend.upsert_nodes/upsert_edges.
    """
    nodes: List[NodeRecord] = []
    edges: List[EdgeRecord] = []

    seen_files = set()
    seen_funcs = set()
    seen_classes = set()

    for result in results:
        rel_file = to_relative_path(result.file_path, project_root)

        if rel_file not in seen_files:
            seen_files.add(rel_file)
            nodes.append(
                NodeRecord(
                    id=rel_file,
                    type="File",
                    properties={
                        "path": rel_file,
                        "language": "python",
                        "content_hash": result.content_hash,
                    },
                )
            )

        for func in result.functions:
            key = (rel_file, func.name, func.start_line)
            if key in seen_funcs:
                continue
            seen_funcs.add(key)

            func_id = make_function_id(
                result.file_path, func.name, func.start_line, project_root
            )
            nodes.append(
                NodeRecord(
                    id=func_id,
                    type="Function",
                    properties={
                        "id": func_id,
                        "name": func.name,
                        "file": rel_file,
                        "start_line": func.start_line,
                        "end_line": func.end_line,
                        "is_public": func.is_public,
                        "source_code": func.source_code or "",
                    },
                )
            )
            edges.append(
                EdgeRecord(
                    src_id=rel_file,
                    dst_id=func_id,
                    type="CONTAINS_FUNCTION",
                    properties={},
                )
            )

        for cls in result.classes:
            key = (rel_file, cls.name, cls.start_line)
            if key in seen_classes:
                continue
            seen_classes.add(key)

            class_id = make_class_id(
                result.file_path, cls.name, cls.start_line, project_root
            )
            nodes.append(
                NodeRecord(
                    id=class_id,
                    type="Class",
                    properties={
                        "id": class_id,
                        "name": cls.name,
                        "file": rel_file,
                        "start_line": cls.start_line,
                        "end_line": cls.end_line,
                        "bases": ",".join(cls.bases) if cls.bases else "",
                        "is_public": cls.is_public,
                        "source_code": cls.source_code or "",
                    },
                )
            )
            edges.append(
                EdgeRecord(
                    src_id=rel_file,
                    dst_id=class_id,
                    type="CONTAINS_CLASS",
                    properties={},
                )
            )

    if resolved_calls:
        for call in resolved_calls:
            caller_id = make_function_id(
                call["caller_file"],
                call["caller_function"],
                call["caller_start_line"],
                project_root,
            )
            callee_id = make_function_id(
                call["callee_file"],
                call["callee_function"],
                call["callee_start_line"],
                project_root,
            )
            edges.append(
                EdgeRecord(
                    src_id=caller_id,
                    dst_id=callee_id,
                    type="CALLS",
                    properties={"call_line": call["call_line"]},
                )
            )

    return nodes, edges
