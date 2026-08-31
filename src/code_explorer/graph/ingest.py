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
from typing import Iterable, Iterator, List, Mapping, Optional, Tuple

from code_explorer.analyzer.export_parquet import (
    make_class_id,
    make_function_id,
    to_relative_path,
)
from code_explorer.analyzer.models import FileAnalysis
from code_explorer.graph.records import EdgeRecord, NodeRecord


# Safety cap on _signature_text's line scan -- a well-formed def/class always
# has a line ending in ":" within a few lines (even with one parameter per
# line), so this only guards against a malformed/truncated source_code slice
# never finding one, which would otherwise pull in the whole function body
# and defeat the point of a compact search_text.
_MAX_SIGNATURE_LINES = 20


def _signature_text(source_code: str) -> str:
    """Return the def/class signature, joined across lines if it wraps.

    Many functions in this codebase have multi-line signatures (one
    parameter per line, ruff/black-formatted) -- using only the first
    physical line drops every parameter name after the first, silently
    starving BM25 of real vocabulary (e.g. a `reindex: bool` flag is
    invisible to search unless it also happens to appear in the docstring's
    first line). This joins lines until one ends with ":" -- the signature's
    closing line, whether or not it wrapped.
    """
    lines: List[str] = []
    for line in source_code.splitlines()[:_MAX_SIGNATURE_LINES]:
        stripped = line.strip()
        lines.append(stripped)
        if stripped.endswith(":"):
            break
    return " ".join(lines)


def _derive_search_text(
    rel_file: str,
    name: str,
    source_code: Optional[str],
    docstring: Optional[str],
    called_names: Optional[List[str]] = None,
) -> str:
    """Build a compact, indexing-time BM25/vector text for a symbol.

    Not part of the canonical NodeRecord model (see
    docs/explanation/source-of-truth-and-search-representations.md) --
    deliberately terse: qualified-ish name + the full (possibly multi-line)
    signature + first docstring line + called-name identifiers, not the
    full body.

    `docstring` and `called_names` are already extracted at extraction time
    (see analyzer/docstrings.py's extract_docstring and
    FunctionExtractor._extract_called_names, both called from
    analyzer/extractors/functions.py during the same tree-sitter walk that
    finds the def/class in the first place -- no second parse) -- no
    re-parsing happens here, just a cheap string join. `called_names` covers
    vocabulary that lives only in the body (e.g. a helper referenced by
    name) without storing the body text itself.
    """
    parts = [f"{rel_file}::{name}"]
    if source_code:
        parts.append(_signature_text(source_code))
    if docstring:
        parts.append(docstring)
    if called_names:
        parts.append("calls: " + ", ".join(called_names))
    return "\n".join(p for p in parts if p)


def iter_node_records(
    results: List[FileAnalysis],
    project_root: Path,
    include_source: bool = False,
) -> Iterator[NodeRecord]:
    """Yield canonical nodes without materializing a repository-sized list."""
    for result in results:
        rel_file = to_relative_path(result.file_path, project_root)
        yield NodeRecord(
            id=rel_file,
            type="File",
            properties={
                "path": rel_file,
                "language": "python",
                "content_hash": result.content_hash,
            },
        )

        seen_funcs = set()
        seen_classes = set()

        for func in result.functions:
            key = (rel_file, func.name, func.start_line)
            if key in seen_funcs:
                continue
            seen_funcs.add(key)

            func_id = make_function_id(
                result.file_path, func.name, func.start_line, project_root
            )
            func_properties = {
                "id": func_id,
                "name": func.name,
                "file": rel_file,
                "start_line": func.start_line,
                "end_line": func.end_line,
                "is_public": func.is_public,
                "search_text": _derive_search_text(
                    rel_file,
                    func.name,
                    func.source_code,
                    func.docstring,
                    func.called_names,
                ),
            }
            if include_source:
                func_properties["source_code"] = func.source_code or ""
            yield NodeRecord(
                id=func_id,
                type="Function",
                properties=func_properties,
            )

        for cls in result.classes:
            key = (rel_file, cls.name, cls.start_line)
            if key in seen_classes:
                continue
            seen_classes.add(key)

            class_id = make_class_id(
                result.file_path, cls.name, cls.start_line, project_root
            )
            class_properties = {
                "id": class_id,
                "name": cls.name,
                "file": rel_file,
                "start_line": cls.start_line,
                "end_line": cls.end_line,
                "bases": ",".join(cls.bases) if cls.bases else "",
                "is_public": cls.is_public,
                "search_text": _derive_search_text(
                    rel_file, cls.name, cls.source_code, cls.docstring
                ),
            }
            if include_source:
                class_properties["source_code"] = cls.source_code or ""
            yield NodeRecord(
                id=class_id,
                type="Class",
                properties=class_properties,
            )


def iter_edge_records(
    results: List[FileAnalysis],
    project_root: Path,
    resolved_calls: Optional[Iterable[Mapping[str, object]]] = None,
) -> Iterator[EdgeRecord]:
    """Yield containment and call edges without a full in-memory edge list."""
    for result in results:
        rel_file = to_relative_path(result.file_path, project_root)
        seen_funcs = set()
        seen_classes = set()

        for func in result.functions:
            key = (rel_file, func.name, func.start_line)
            if key in seen_funcs:
                continue
            seen_funcs.add(key)
            yield EdgeRecord(
                src_id=rel_file,
                dst_id=make_function_id(
                    result.file_path, func.name, func.start_line, project_root
                ),
                type="CONTAINS_FUNCTION",
                properties={},
            )

        for cls in result.classes:
            key = (rel_file, cls.name, cls.start_line)
            if key in seen_classes:
                continue
            seen_classes.add(key)
            yield EdgeRecord(
                src_id=rel_file,
                dst_id=make_class_id(
                    result.file_path, cls.name, cls.start_line, project_root
                ),
                type="CONTAINS_CLASS",
                properties={},
            )

    if resolved_calls is not None:
        for call in resolved_calls:
            caller_id = make_function_id(
                str(call["caller_file"]),
                str(call["caller_function"]),
                int(call["caller_start_line"]),
                project_root,
            )
            callee_id = make_function_id(
                str(call["callee_file"]),
                str(call["callee_function"]),
                int(call["callee_start_line"]),
                project_root,
            )
            yield EdgeRecord(
                src_id=caller_id,
                dst_id=callee_id,
                type="CALLS",
                properties={"call_line": int(call["call_line"])},
            )


def file_analyses_to_records(
    results: List[FileAnalysis],
    project_root: Path,
    resolved_calls: Optional[Iterable[Mapping[str, object]]] = None,
    include_source: bool = False,
) -> Tuple[List[NodeRecord], List[EdgeRecord]]:
    """Convert analyzer output into canonical NodeRecord/EdgeRecord lists.

    Args:
        results: FileAnalysis objects from CodeAnalyzer.analyze_directory.
        project_root: Root directory for relative paths (matches the ID
            hashing convention used elsewhere in the codebase).
        resolved_calls: Optional resolved CALLS edges from
            CallResolver.resolve_all_calls(), same shape export_to_parquet
            expects.
        include_source: If True, also store each function/class's full
            source_code as a graph property (opt-in -- see
            docs/explanation/source-of-truth-and-search-representations.md
            for why this isn't the default: it duplicates storage across a
            large repo and BM25/vector search always use the compact
            search_text field regardless of this flag).

    Returns:
        (nodes, edges) ready for CodeGraphBackend.upsert_nodes/upsert_edges.
    """
    return (
        list(iter_node_records(results, project_root, include_source)),
        list(iter_edge_records(results, project_root, resolved_calls)),
    )
