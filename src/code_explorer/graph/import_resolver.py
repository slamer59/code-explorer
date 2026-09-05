"""Import-aware, in-memory call resolution for backends without a durable
pending-call stream (SqliteBackend).

The naive ``CallResolver`` joins a call site to a definition *by name only*,
so a corpus-wide ``log()`` or ``test_x()`` fans out into a CALLS edge to every
same-named function -- measured at 246k edges on the 1,556-file gemseo library
vs ~15k import-aware edges. That spurious fan-out is what makes the depth-2/3
collect-then-rank expansion explode (median 14 / p90 1,187 nodes at depth 3 vs
2 / 11 / 19 on the accurate graph).

This module reuses the backend-agnostic resolution machinery already built for
the LatticeDB streaming path -- ``ProjectScope`` (module + defined-name corpus
facts), ``_records_for_file`` (call-site classification into internal /
external / unattributable), and ``LatticeStreamingIngestor._resolution`` (the
explicit-import / package-reexport / same-class / same-file / global-unique
rules) -- but drives it over an in-memory symbol index instead of LatticeDB
lookups, and emits ``CallResolver``-shaped rows so ``ingest_results`` and
``file_analyses_to_records`` keep working unchanged.

Phase 2a scope: resolves *internal* Function->Function CALLS correctly. Class
constructor targets, external-symbol boundary edges, and per-edge confidence
are deliberately deferred (the naive resolver this replaces also produced
function-only edges, so this is a strict improvement with no schema change).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from code_explorer.analyzer.export_parquet import (
    make_class_id,
    make_function_id,
    to_relative_path,
)
from code_explorer.analyzer.models import FileAnalysis
from code_explorer.graph.lattice_streaming import (
    LatticeStreamingIngestor,
    ProjectScope,
    _records_for_file,
)


def resolve_import_aware(
    results: List[FileAnalysis],
    project_root: Path,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Resolve internal calls import-aware, returning CallResolver-shaped rows.

    Returns:
        (resolved_calls, stats): ``resolved_calls`` is a list of dicts with the
        same keys ``CallResolver.resolve_all_calls()`` produced
        (caller_file, caller_function, caller_start_line, callee_file,
        callee_function, callee_start_line, call_line), and ``stats`` carries
        the resolution-method histogram plus skipped/external counts for the
        ingest summary.
    """
    if not results:
        return [], {}

    scope = ProjectScope.from_project_root(project_root)

    # In-memory symbol index over *functions only* (Phase 2a). Keyed exactly
    # like LatticeBackend.find_symbols_by_properties: (property_key, value) ->
    # list of candidate dicts carrying the fields _resolution() reads.
    index: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    # function id -> (relative_file, name, start_line), for both the caller and
    # callee sides of the CallResolver-shaped output.
    info_by_id: Dict[str, Tuple[str, str, int]] = {}

    for analysis in results:
        rel_file = to_relative_path(analysis.file_path, project_root)
        module = scope.module_for(rel_file)
        for function in analysis.functions:
            function_id = make_function_id(
                analysis.file_path, function.name, function.start_line, project_root
            )
            candidate = {
                "id": function_id,
                "name": function.name,
                "file": rel_file,
                "module": module,
                "parent_class": function.parent_class or "",
                "node_type": "Function",
            }
            index[("name", function.name)].append(candidate)
            index[("file", rel_file)].append(candidate)
            index[("module", module)].append(candidate)
            if function.parent_class:
                index[("parent_class", function.parent_class)].append(candidate)
            info_by_id[function_id] = (rel_file, function.name, function.start_line)

        # Class nodes are valid call targets too (constructor calls). A Class
        # candidate carries no parent_class, which _resolution() explicitly
        # admits for module-level `from pkg.mod import Thing; Thing()` sites.
        for class_info in analysis.classes:
            class_id = make_class_id(
                analysis.file_path, class_info.name, class_info.start_line, project_root
            )
            candidate = {
                "id": class_id,
                "name": class_info.name,
                "file": rel_file,
                "module": module,
                "parent_class": "",
                "node_type": "Class",
            }
            index[("name", class_info.name)].append(candidate)
            index[("file", rel_file)].append(candidate)
            index[("module", module)].append(candidate)
            info_by_id[class_id] = (rel_file, class_info.name, class_info.start_line)

    resolved_calls: List[Dict[str, Any]] = []
    resolution_methods: Counter = Counter()
    external_edges = 0
    skipped_calls = 0

    def collect_references(
        analyses: Iterable[FileAnalysis],
    ) -> List[Dict[str, Any]]:
        nonlocal external_edges, skipped_calls
        references: List[Dict[str, Any]] = []
        for analysis in analyses:
            (
                _nodes,
                _edges,
                refs,
                external_calls,
                _dependency_references,
                skipped,
            ) = _records_for_file(
                analysis, project_root, include_source=False, scope=scope
            )
            references.extend(refs)
            external_edges += len(external_calls)
            skipped_calls += skipped
        return references

    def resolve_one(
        reference: Dict[str, Any], finalize: bool
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        lookup_name = reference["target_name"] or reference["called_name"]
        candidates_by_id: Dict[str, Dict[str, Any]] = {
            candidate["id"]: candidate for candidate in index[("name", lookup_name)]
        }
        if reference["target_module"]:
            candidates_by_id.update(
                {
                    candidate["id"]: candidate
                    for candidate in index[("module", reference["target_module"])]
                }
            )
        candidates_by_id.update(
            {
                candidate["id"]: candidate
                for candidate in index[("file", reference["caller_file"])]
            }
        )
        for base in reference["caller_bases"] or []:
            candidates_by_id.update(
                {
                    candidate["id"]: candidate
                    for candidate in index[("parent_class", base)]
                }
            )
        return LatticeStreamingIngestor._resolution(
            reference, list(candidates_by_id.values()), finalize=finalize
        )

    def emit(reference: Dict[str, Any], target: Dict[str, Any], method: str) -> None:
        caller = info_by_id[reference["caller_id"]]
        callee = info_by_id[target["id"]]
        resolved_calls.append(
            {
                "caller_file": caller[0],
                "caller_function": caller[1],
                "caller_start_line": caller[2],
                "callee_file": callee[0],
                "callee_function": callee[1],
                "callee_start_line": callee[2],
                "callee_type": target["node_type"],
                "call_line": reference["call_line"],
            }
        )
        resolution_methods[method] += 1

    # First pass (finalize=False): resolve what the exact rules can, defer the
    # rest. Second pass (finalize=True): re-run with global-unique/ambiguous
    # rules enabled, mirroring the streaming path's durable two-pass flow.
    references = collect_references(results)
    pending: List[Dict[str, Any]] = []
    for finalize in (False, True):
        batch = references if not finalize else pending
        pending = []
        for reference in batch:
            target, method = resolve_one(reference, finalize=finalize)
            if target is not None and method is not None:
                emit(reference, target, method)
            else:
                pending.append(reference)

    stats: Dict[str, int] = {
        "calls_resolved": len(resolved_calls),
        "calls_unresolved": len(pending),
        "calls_skipped_unattributable": skipped_calls,
        "external_edges": external_edges,
    }
    for method, count in resolution_methods.items():
        stats[f"resolution_method_{method}"] = count
    return resolved_calls, stats
