"""Bounded, LatticeDB-only ingestion of parsed files and call facts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from statistics import median
from time import perf_counter
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Sequence

from code_explorer.analyzer.export_parquet import make_function_id, to_relative_path
from code_explorer.analyzer.models import FileAnalysis, FunctionCall, FunctionInfo
from code_explorer.graph.backends.lattice_backend import (
    PENDING_CALL_STREAM,
    UNRESOLVED_CALL_STREAM,
    LatticeBackend,
)
from code_explorer.graph.ingest import file_analyses_to_records
from code_explorer.graph.records import EdgeRecord, NodeRecord


@dataclass
class LatticeIngestBatch:
    nodes: List[NodeRecord] = field(default_factory=list)
    structural_edges: List[EdgeRecord] = field(default_factory=list)
    call_references: List[Dict[str, Any]] = field(default_factory=list)
    operation_count: int = 0
    estimated_bytes: int = 0
    target_operations: int = 0


@dataclass(frozen=True)
class BatchMeasurement:
    target_size: int
    operation_count: int
    estimated_bytes: int
    duration_seconds: float

    @property
    def operations_per_second(self) -> float:
        return self.operation_count / max(self.duration_seconds, 1e-9)


class AdaptiveBatchController:
    """Explore bounded batch sizes, then hold the empirical throughput knee.

    Candidate sizes are interleaved rather than tested in contiguous phases,
    reducing bias from repository ordering and database growth. After every
    candidate has enough samples, the controller chooses the smallest size
    whose median throughput is within ``throughput_tolerance`` of the peak.
    """

    def __init__(
        self,
        *,
        initial_size: int,
        max_size: int,
        samples_per_size: int = 3,
        throughput_tolerance: float = 0.05,
    ) -> None:
        if initial_size < 1:
            raise ValueError("initial_size must be at least 1")
        if max_size < initial_size:
            raise ValueError("max_size must be at least initial_size")
        if samples_per_size < 1:
            raise ValueError("samples_per_size must be at least 1")
        if not 0 <= throughput_tolerance < 1:
            raise ValueError("throughput_tolerance must be in [0, 1)")

        self.initial_size = initial_size
        candidates = [initial_size]
        while candidates[-1] < max_size:
            candidates.append(min(candidates[-1] * 2, max_size))
        self.candidates = tuple(candidates)
        self.samples_per_size = samples_per_size
        self.throughput_tolerance = throughput_tolerance
        self.measurements: List[BatchMeasurement] = []
        self.selected_size: Optional[int] = None

    @property
    def required_samples(self) -> int:
        return len(self.candidates) * self.samples_per_size

    @property
    def current_size(self) -> int:
        if self.selected_size is not None:
            return self.selected_size
        return self.candidates[len(self.measurements) % len(self.candidates)]

    def observe(
        self,
        *,
        target_size: int,
        operation_count: int,
        estimated_bytes: int,
        duration_seconds: float,
    ) -> None:
        if self.selected_size is not None:
            return
        self.measurements.append(
            BatchMeasurement(
                target_size=target_size,
                operation_count=operation_count,
                estimated_bytes=estimated_bytes,
                duration_seconds=duration_seconds,
            )
        )
        if len(self.measurements) < self.required_samples:
            return

        self._select_size()

    def _select_size(self) -> None:
        sampled_candidates = {
            measurement.target_size for measurement in self.measurements
        }
        throughput_by_size = {
            candidate: median(
                measurement.operations_per_second
                for measurement in self.measurements
                if measurement.target_size == candidate
            )
            for candidate in sampled_candidates
        }
        peak = max(throughput_by_size.values())
        near_peak = peak * (1 - self.throughput_tolerance)
        self.selected_size = min(
            candidate
            for candidate, throughput in throughput_by_size.items()
            if throughput >= near_peak
        )

    def finish(self) -> int:
        """Select from partial calibration data when the input stream ends."""
        if self.selected_size is None:
            if self.measurements:
                self._select_size()
            else:
                self.selected_size = self.initial_size
        assert self.selected_size is not None
        return self.selected_size


def _value_bytes(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return len(value.encode("utf-8"))
    if isinstance(value, bytes):
        return len(value)
    if isinstance(value, dict):
        return sum(_value_bytes(k) + _value_bytes(v) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return sum(_value_bytes(item) for item in value)
    if isinstance(value, NodeRecord):
        return (
            _value_bytes(value.id)
            + _value_bytes(value.type)
            + _value_bytes(value.properties)
        )
    if isinstance(value, EdgeRecord):
        return (
            _value_bytes(value.src_id)
            + _value_bytes(value.dst_id)
            + _value_bytes(value.type)
            + _value_bytes(value.properties)
        )
    return 8


def _module_name(relative_file: str) -> str:
    parts = list(PurePosixPath(relative_file).parts)
    if not parts:
        return ""
    if parts[-1] == "__init__.py":
        parts.pop()
    elif parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]
    return ".".join(parts)


def _resolve_relative_module(
    caller_module: str, imported_module: Optional[str], is_relative: bool
) -> str:
    imported_module = imported_module or ""
    if not is_relative:
        return imported_module
    package = caller_module.rsplit(".", 1)[0] if "." in caller_module else ""
    return ".".join(part for part in (package, imported_module) if part)


def _caller_for_call(
    functions: Sequence[FunctionInfo], call: FunctionCall
) -> Optional[FunctionInfo]:
    candidates = [
        function
        for function in functions
        if function.name == call.caller_function
        and function.start_line <= call.call_line <= function.end_line
    ]
    if not candidates:
        candidates = [f for f in functions if f.name == call.caller_function]
    if not candidates:
        return None
    return min(candidates, key=lambda f: (f.end_line - f.start_line, -f.start_line))


def _import_target(
    analysis: FileAnalysis, call: FunctionCall, caller_module: str
) -> tuple[str, str]:
    for imported in analysis.imports_detailed:
        binding = imported.alias or imported.imported_name
        if imported.module is not None:
            if call.qualifier is None and call.called_name == binding:
                return (
                    _resolve_relative_module(
                        caller_module, imported.module, imported.is_relative
                    ),
                    imported.imported_name,
                )
            continue

        module_binding = imported.alias or imported.imported_name.split(".", 1)[0]
        if call.qualifier == module_binding:
            return imported.imported_name, call.called_name
        if not imported.alias and call.qualifier == imported.imported_name:
            return imported.imported_name, call.called_name
    return "", call.called_name


def _call_reference_id(
    caller_id: str,
    called_name: str,
    qualifier: Optional[str],
    call_line: int,
    occurrence: int,
) -> str:
    identity = (
        f"{caller_id}\0{qualifier or ''}\0{called_name}\0{call_line}\0{occurrence}"
    )
    return "call_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]


def _records_for_file(
    analysis: FileAnalysis, project_root: Path, include_source: bool
) -> tuple[List[NodeRecord], List[EdgeRecord], List[Dict[str, Any]]]:
    nodes, structural_edges = file_analyses_to_records(
        [analysis], project_root, include_source=include_source
    )
    relative_file = to_relative_path(analysis.file_path, project_root)
    module = _module_name(relative_file)
    functions_by_key = {
        (function.name, function.start_line): function
        for function in analysis.functions
    }

    enriched_nodes: List[NodeRecord] = []
    for node in nodes:
        properties = dict(node.properties)
        if node.type == "File":
            properties["module"] = module
        elif node.type == "Function":
            function = functions_by_key[(properties["name"], properties["start_line"])]
            properties["module"] = module
            properties["parent_class"] = function.parent_class or ""
        enriched_nodes.append(
            NodeRecord(id=node.id, type=node.type, properties=properties)
        )

    classes = {class_info.name: class_info for class_info in analysis.classes}
    references: List[Dict[str, Any]] = []
    for occurrence, call in enumerate(analysis.function_calls):
        caller = _caller_for_call(analysis.functions, call)
        if caller is None:
            continue
        caller_id = make_function_id(
            analysis.file_path, caller.name, caller.start_line, project_root
        )
        target_module, target_name = _import_target(analysis, call, module)
        caller_class = caller.parent_class or ""
        caller_bases = (
            classes[caller_class].bases
            if caller_class and caller_class in classes
            else []
        )
        references.append(
            {
                "id": _call_reference_id(
                    caller_id,
                    call.called_name,
                    call.qualifier,
                    call.call_line,
                    occurrence,
                ),
                "caller_id": caller_id,
                "caller_file": relative_file,
                "caller_content_hash": analysis.content_hash,
                "caller_class": caller_class,
                "caller_bases": caller_bases,
                "called_name": call.called_name,
                "qualifier": call.qualifier or "",
                "call_line": call.call_line,
                "target_module": target_module,
                "target_name": target_name,
            }
        )
    return enriched_nodes, structural_edges, references


def iter_lattice_ingest_batches(
    analyses: Iterable[FileAnalysis],
    project_root: Path,
    *,
    batch_size: int,
    batch_bytes: int,
    include_source: bool = False,
    batch_size_provider: Optional[Callable[[], int]] = None,
) -> Iterator[LatticeIngestBatch]:
    """Convert and group files without retaining repository-sized analyses."""
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    if batch_bytes < 1:
        raise ValueError("batch_bytes must be at least 1")

    def new_batch() -> LatticeIngestBatch:
        target_operations = (
            batch_size_provider() if batch_size_provider is not None else batch_size
        )
        if target_operations < 1:
            raise ValueError("batch size provider must return at least 1")
        return LatticeIngestBatch(target_operations=target_operations)

    batch = new_batch()
    for analysis in analyses:
        nodes, edges, references = _records_for_file(
            analysis, project_root, include_source
        )
        file_operations = len(nodes) + len(edges) + len(references)
        file_bytes = sum(
            _value_bytes(record) for record in (*nodes, *edges, *references)
        )
        exceeds_limit = (
            batch.operation_count + file_operations > batch.target_operations
            or batch.estimated_bytes + file_bytes > batch_bytes
        )
        if batch.operation_count and exceeds_limit:
            yield batch
            batch = new_batch()

        batch.nodes.extend(nodes)
        batch.structural_edges.extend(edges)
        batch.call_references.extend(references)
        batch.operation_count += file_operations
        batch.estimated_bytes += file_bytes

        if (
            batch.operation_count >= batch.target_operations
            or batch.estimated_bytes >= batch_bytes
        ):
            yield batch
            batch = new_batch()

    if batch.operation_count:
        yield batch


class LatticeStreamingIngestor:
    def __init__(self, backend: LatticeBackend, project_root: Path):
        self.backend = backend
        self.project_root = project_root

    @staticmethod
    def _resolution(
        reference: Dict[str, Any],
        candidates: Sequence[Dict[str, Any]],
        *,
        finalize: bool,
    ) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
        target_name = reference["target_name"] or reference["called_name"]
        named = [
            candidate for candidate in candidates if candidate["name"] == target_name
        ]

        if reference["target_module"]:
            imported = [
                candidate
                for candidate in named
                if candidate["module"] == reference["target_module"]
                and not candidate["parent_class"]
            ]
            if len(imported) == 1:
                return imported[0], "explicit_import"
            return None, "ambiguous" if finalize and len(imported) > 1 else None

        if reference["qualifier"] == "self" and reference["caller_class"]:
            same_class = [
                candidate
                for candidate in named
                if candidate["file"] == reference["caller_file"]
                and candidate["parent_class"] == reference["caller_class"]
            ]
            if len(same_class) == 1:
                return same_class[0], "same_class"
            for base in reference["caller_bases"] or []:
                base_methods = [
                    candidate
                    for candidate in named
                    if candidate["parent_class"] == base
                ]
                if len(base_methods) == 1:
                    return base_methods[0], "direct_base"

        if not reference["qualifier"]:
            same_module = [
                candidate
                for candidate in named
                if candidate["file"] == reference["caller_file"]
                and not candidate["parent_class"]
            ]
            if len(same_module) == 1:
                return same_module[0], "same_file"
            if finalize and len(same_module) > 1:
                return None, "ambiguous"

        if finalize:
            if len(named) == 1:
                return named[0], "global_unique"
            if len(named) > 1:
                return None, "ambiguous"
        return None, None

    def _resolve_references(
        self, references: Sequence[Dict[str, Any]], *, finalize: bool
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        resolutions: List[Dict[str, Any]] = []
        deferred: List[Dict[str, Any]] = []
        requests: Dict[tuple[str, str], int] = {}
        for reference in references:
            if finalize:
                requests[("name", reference["target_name"])] = 2
            requests[("file", reference["caller_file"])] = 10_000
            if reference["target_module"]:
                requests[("module", reference["target_module"])] = 10_000
            for base in reference["caller_bases"] or []:
                requests[("parent_class", base)] = 10_000
        candidates_by_key = self.backend.find_functions_by_properties(requests)
        file_hashes = self.backend.get_file_content_hashes(
            reference["caller_file"] for reference in references
        )

        def indexed(property_key: str, value: str) -> List[Dict[str, Any]]:
            return candidates_by_key.get((property_key, value), [])

        for reference in references:
            caller_file = reference["caller_file"]
            if file_hashes[caller_file] != reference["caller_content_hash"]:
                continue

            lookup_name = reference["target_name"] or reference["called_name"]
            candidates_by_id: Dict[str, Dict[str, Any]] = {
                candidate["id"]: candidate for candidate in indexed("name", lookup_name)
            }
            if reference["target_module"]:
                candidates_by_id.update(
                    {
                        candidate["id"]: candidate
                        for candidate in indexed("module", reference["target_module"])
                    }
                )
            candidates_by_id.update(
                {
                    candidate["id"]: candidate
                    for candidate in indexed("file", caller_file)
                }
            )
            for base in reference["caller_bases"] or []:
                candidates_by_id.update(
                    {
                        candidate["id"]: candidate
                        for candidate in indexed("parent_class", base)
                    }
                )

            target, method = self._resolution(
                reference, list(candidates_by_id.values()), finalize=finalize
            )
            if target is not None and method is not None:
                resolutions.append(
                    {
                        "reference": reference,
                        "target_id": target["id"],
                        "resolution_method": method,
                        "confidence": "low" if method == "global_unique" else "high",
                    }
                )
            else:
                pending = dict(reference)
                if finalize:
                    pending["status"] = (
                        "call.ambiguous" if method == "ambiguous" else "call.unresolved"
                    )
                deferred.append(pending)
        return resolutions, deferred

    def _finalize_pending(
        self,
        total: int,
        on_progress: Optional[Callable[[Dict[str, int]], None]] = None,
    ) -> tuple[int, int]:
        resolved = 0
        unresolved = 0
        processed = 0
        windows = 0
        after = 0
        if total and on_progress is not None:
            on_progress(
                {
                    "total": total,
                    "processed": 0,
                    "resolved": 0,
                    "unresolved": 0,
                    "windows": 0,
                }
            )
        while records := self.backend.db.read_stream(
            PENDING_CALL_STREAM, after_sequence=after, limit=1000
        ):
            through = records[-1].sequence
            references = [dict(record.payload) for record in records]
            resolutions, deferred = self._resolve_references(references, finalize=True)
            resolved += self.backend.apply_call_outcomes(
                resolutions,
                deferred,
                deferred_stream=UNRESOLVED_CALL_STREAM,
                trim_stream=PENDING_CALL_STREAM,
                trim_through=through,
            )
            unresolved += len(deferred)
            processed += len(records)
            windows += 1
            if on_progress is not None:
                on_progress(
                    {
                        "total": total,
                        "processed": processed,
                        "resolved": resolved,
                        "unresolved": unresolved,
                        "windows": windows,
                    }
                )
            after = through
        return resolved, unresolved

    def ingest(
        self,
        analyses: Iterable[FileAnalysis],
        *,
        batch_size: int,
        batch_bytes: int,
        include_source: bool = False,
        assume_new: bool = False,
        adaptive: bool = False,
        max_batch_size: Optional[int] = None,
        calibration_batches: int = 3,
        throughput_tolerance: float = 0.05,
        on_batch_committed: Optional[Callable[[Dict[str, int]], None]] = None,
        on_finalize_progress: Optional[Callable[[Dict[str, int]], None]] = None,
    ) -> Dict[str, int]:
        requeued_calls = self.backend.requeue_unresolved_calls()
        controller = (
            AdaptiveBatchController(
                initial_size=batch_size,
                max_size=max(batch_size, max_batch_size or batch_size),
                samples_per_size=calibration_batches,
                throughput_tolerance=throughput_tolerance,
            )
            if adaptive
            else None
        )
        stats = {
            "batches": 0,
            "total_nodes": 0,
            "total_edges": 0,
            "files": 0,
            "functions": 0,
            "classes": 0,
            "call_references": 0,
            "calls_resolved": 0,
            "calls_unresolved": 0,
            "calls_pending": requeued_calls,
            "adaptive_batching": int(controller is not None),
            "adaptive_samples": 0,
            "adaptive_required_samples": (
                controller.required_samples if controller is not None else 0
            ),
            "batch_target_size": batch_size,
            "selected_batch_size": 0,
            "last_batch_operations": 0,
            "last_batch_bytes": 0,
            "last_batch_write_ms": 0,
        }
        for batch in iter_lattice_ingest_batches(
            analyses,
            self.project_root,
            batch_size=batch_size,
            batch_bytes=batch_bytes,
            include_source=include_source,
            batch_size_provider=(
                (lambda: controller.current_size) if controller is not None else None
            ),
        ):
            write_started = perf_counter()
            node_ids = self.backend.upsert_nodes(batch.nodes, assume_new=assume_new)
            self.backend.upsert_edges(batch.structural_edges, node_id_map=node_ids)
            resolutions, pending = self._resolve_references(
                batch.call_references, finalize=False
            )
            resolved = self.backend.apply_call_outcomes(resolutions, pending)
            write_seconds = perf_counter() - write_started
            if controller is not None:
                controller.observe(
                    target_size=batch.target_operations,
                    operation_count=batch.operation_count,
                    estimated_bytes=batch.estimated_bytes,
                    duration_seconds=write_seconds,
                )

            stats["batches"] += 1
            stats["total_nodes"] += len(batch.nodes)
            stats["total_edges"] += len(batch.structural_edges) + resolved
            stats["files"] += sum(node.type == "File" for node in batch.nodes)
            stats["functions"] += sum(node.type == "Function" for node in batch.nodes)
            stats["classes"] += sum(node.type == "Class" for node in batch.nodes)
            stats["call_references"] += len(batch.call_references)
            stats["calls_resolved"] += resolved
            stats["calls_pending"] += len(pending)
            stats["adaptive_samples"] = (
                len(controller.measurements) if controller is not None else 0
            )
            stats["batch_target_size"] = batch.target_operations
            stats["selected_batch_size"] = (
                (controller.selected_size or 0) if controller is not None else 0
            )
            stats["last_batch_operations"] = batch.operation_count
            stats["last_batch_bytes"] = batch.estimated_bytes
            stats["last_batch_write_ms"] = round(write_seconds * 1000)
            if on_batch_committed is not None:
                on_batch_committed(dict(stats))

        if controller is not None:
            stats["selected_batch_size"] = controller.finish()
        resolved, unresolved = self._finalize_pending(
            stats["calls_pending"], on_progress=on_finalize_progress
        )
        stats["calls_resolved"] += resolved
        stats["calls_unresolved"] = unresolved
        stats["calls_pending"] = unresolved
        stats["total_edges"] += resolved
        # Build the BM25 indexes here, after the last write transaction has
        # closed rather than maintaining them across every node write. A no-op
        # when they already exist (re-index / incremental runs), which is why
        # this is safe to call unconditionally. Must stay outside any
        # db.write() block -- LatticeDB raises LatticeLockTimeoutError if an
        # index is created while a write transaction is open.
        self.backend.ensure_fts_indexes()
        return stats
