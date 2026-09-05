"""Bounded, LatticeDB-only ingestion of parsed files and call facts."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import (
    Any,
    Callable,
    Dict,
    FrozenSet,
    Iterable,
    Iterator,
    List,
    Mapping,
    Optional,
    Sequence,
)

from code_explorer.analyzer.base_analyzer import discover_python_files
from code_explorer.analyzer.export_parquet import make_function_id, to_relative_path
from code_explorer.analyzer.models import FileAnalysis, FunctionCall, FunctionInfo
from code_explorer.graph.backends.lattice_backend import (
    PENDING_CALL_STREAM,
    UNRESOLVED_CALL_STREAM,
    LatticeBackend,
    _chunked,
)
from code_explorer.graph.ingest import (
    KIND_DECORATES,
    KIND_IMPORTS,
    KIND_INHERITS,
    dependency_edge,
    external_symbol_id,
    file_analyses_to_records,
    file_dependency_references,
    import_target as _import_target,
    module_name_for_file as _module_name,
    package_root_depth as _package_root_depth,
    reexporting_package as _reexporting_package,
    resolve_dependency_reference,
    resolve_import_reference,
)
from code_explorer.graph.records import EdgeRecord, NodeRecord


@dataclass
class LatticeIngestBatch:
    nodes: List[NodeRecord] = field(default_factory=list)
    structural_edges: List[EdgeRecord] = field(default_factory=list)
    call_references: List[Dict[str, Any]] = field(default_factory=list)
    external_calls: List[Dict[str, Any]] = field(default_factory=list)
    # Unresolved inheritance/decoration facts (graph/ingest.py's
    # file_dependency_references). Unlike calls these are not resolved per
    # batch: a base class is almost never defined in the same batch as the
    # class extending it, so a per-batch attempt would fail for nearly every
    # one and push it onto the pending stream anyway. They are accumulated
    # for the whole run and resolved once, after every node exists -- see
    # LatticeStreamingIngestor.ingest.
    dependency_refs: List[Dict[str, Any]] = field(default_factory=list)
    skipped_calls: int = 0
    operation_count: int = 0
    estimated_bytes: int = 0
    target_operations: int = 0


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


# Top-level-or-indented `def` / `async def` / `class` headers. A regex, not an
# AST walk, on purpose: measured at 72ms over the 2,107-file reference corpus
# (yielding 10,173 names), versus re-parsing every file. HYPOTHESIS: every name
# worth resolving a call to is written as a literal `def`/`class` header
# somewhere in the corpus. Dynamically created callables (setattr, type(),
# factory-returned closures, C extensions) are missed and their call sites are
# dropped as unattributable -- acceptable, because the resolver could not have
# resolved them either: there is no node in the graph to point an edge at.
_DEFINITION_HEADER = re.compile(
    r"^[ \t]*(?:async[ \t]+)?(?:def|class)[ \t]+([A-Za-z_][A-Za-z0-9_]*)",
    re.MULTILINE,
)


@dataclass(frozen=True)
class ProjectScope:
    """What counts as "inside this project" when classifying a call site.

    Built once per ingest run (not per file) because both sets are
    corpus-wide facts. Cost on the reference corpus: one file discovery plus
    a regex scan of 2,107 files, ~0.3s against a ~31s build -- paid back many
    times over by the ~27,000 references it stops writing to the pending-call
    stream.
    """

    modules: FrozenSet[str]
    defined_names: FrozenSet[str]
    # Project-root-relative posix path -> the module name an import
    # statement would use for that file, derived from its package root.
    # Only files that live under a package root differ from _module_name();
    # the map is kept whole anyway (2,103 short strings on the reference
    # corpus, well under a megabyte) so the lookup has no fallback branch.
    modules_by_file: Mapping[str, str] = field(default_factory=dict)

    def module_for(self, relative_file: str) -> str:
        """The module name imports use for this file, or the flat fallback.

        The fallback covers a file the scope never saw -- an analysis fed in
        from outside the discovered set, which the tests do.
        """
        return self.modules_by_file.get(relative_file) or _module_name(relative_file)

    @classmethod
    def from_project_root(
        cls, project_root: Path, files: Optional[Iterable[Path]] = None
    ) -> "ProjectScope":
        paths = list(discover_python_files(project_root) if files is None else files)
        relative_paths = [
            Path(to_relative_path(str(path), project_root)).as_posix() for path in paths
        ]
        # Directories that are real Python packages, so a file's import name
        # can be computed relative to its package root rather than to
        # project_root. This matters whenever project_root is not itself the
        # package root -- a src/ layout, or the reference corpus, which is a
        # parent directory holding three separate projects: there,
        # `gemseo/src/gemseo/core/x.py` is imported as `gemseo.core.x`, and
        # keying only off the project-root-relative path would classify every
        # internal import in the repository as external.
        package_dirs = {
            relative.rsplit("/", 1)[0] if "/" in relative else ""
            for relative in relative_paths
            if relative.endswith("__init__.py")
        }

        modules: set[str] = set()
        modules_by_file: Dict[str, str] = {}
        defined_names: set[str] = set()
        for path, relative in zip(paths, relative_paths):
            parts = relative.split("/")
            root_depth = _package_root_depth(parts, package_dirs)
            # Both spellings are registered: the package-relative one (what
            # imports actually say) and the project-root-relative one (right
            # for a flat repository, and for loose scripts outside any
            # package). Register every prefix of each too, so an import of
            # the package itself counts as internal even though only its
            # modules were discovered as files.
            for start in {0, root_depth}:
                module_parts = _module_name("/".join(parts[start:])).split(".")
                for depth in range(1, len(module_parts) + 1):
                    modules.add(".".join(module_parts[:depth]))
            # The package-relative spelling is the one a node's `module`
            # property gets: it is what `from x.y import z` writes, so it is
            # the only one the explicit-import rule can match against.
            modules_by_file[relative] = _module_name("/".join(parts[root_depth:]))
            try:
                source = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            defined_names.update(_DEFINITION_HEADER.findall(source))
        modules.discard("")
        return cls(
            modules=frozenset(modules),
            defined_names=frozenset(defined_names),
            modules_by_file=modules_by_file,
        )


# How a call site is classified before it ever reaches the resolver.
CALL_INTERNAL = "internal"
CALL_EXTERNAL = "external"
CALL_UNATTRIBUTABLE = "unattributable"


def _classify_call(
    target_module: str, called_name: str, scope: Optional[ProjectScope]
) -> str:
    """Decide whether a call site is worth resolving, recording, or dropping.

    Measured on the reference corpus, the 45,320 references that survived to
    the unresolved stream split into: 4,728 naming a project module (a
    resolution bug, kept), 13,844 naming a third-party/stdlib module
    (recorded as a boundary edge), and 26,748 with no attributable module at
    all -- `print`, `len`, `logger.info`, `session.commit`. Nothing
    user-facing ever read that stream, so all three buckets were pure cost.
    """
    if scope is None:
        # No scope (e.g. iter_lattice_ingest_batches called directly by a
        # test or a caller that has no project root to scan) -- classify
        # nothing and behave exactly as before this change.
        return CALL_INTERNAL
    if target_module:
        return CALL_INTERNAL if target_module in scope.modules else CALL_EXTERNAL
    # No import resolved the call. HYPOTHESIS: if the called name is not
    # defined anywhere in the corpus, no later batch can define it either, so
    # deferring it to the pending stream only buys a second failed lookup.
    # Attribute calls on locals (`session.commit`) are matched on the bare
    # attribute name, so a project-defined `commit` keeps them alive -- an
    # over-approximation we accept, since being wrong here only means keeping
    # a reference we used to keep unconditionally.
    if called_name in scope.defined_names:
        return CALL_INTERNAL
    return CALL_UNATTRIBUTABLE


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
    analysis: FileAnalysis,
    project_root: Path,
    include_source: bool,
    scope: Optional[ProjectScope] = None,
) -> tuple[
    List[NodeRecord],
    List[EdgeRecord],
    List[Dict[str, Any]],
    List[Dict[str, Any]],
    List[Dict[str, Any]],
    int,
]:
    nodes, structural_edges = file_analyses_to_records(
        [analysis],
        project_root,
        include_source=include_source,
        # One file is not a corpus: resolving `class X(Base)` against it
        # would only ever find a base defined in the same file. This path
        # collects references instead and resolves them at the end of the
        # run (see LatticeStreamingIngestor.ingest).
        emit_dependencies=False,
    )
    relative_file = to_relative_path(analysis.file_path, project_root)
    # Package-root-relative when a scope is available. Deriving the module
    # from the *indexed* root instead is what made `explicit_import` fire
    # zero times on the reference corpus: `gemseo/src/gemseo/algos/
    # design_space.py` yielded `gemseo.src.gemseo.algos.design_space` while
    # every import of it says `gemseo.algos.design_space`.
    module = (
        scope.module_for(relative_file) if scope is not None
        else _module_name(relative_file)
    )
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
        elif node.type == "Class":
            # Same module property Function nodes get: a class is a valid
            # call target (its constructor), and the explicit-import rule
            # matches candidates on module.
            properties["module"] = module
        enriched_nodes.append(
            NodeRecord(id=node.id, type=node.type, properties=properties)
        )

    classes = {class_info.name: class_info for class_info in analysis.classes}
    references: List[Dict[str, Any]] = []
    # Keyed by (caller_id, module, name): one CALLS_EXTERNAL edge per caller/
    # symbol pair, with the call sites counted rather than kept individually.
    # A caller lives in exactly one file, so deduping here is already global
    # dedup -- no cross-batch bookkeeping needed for the edges.
    external_by_pair: Dict[tuple[str, str, str], Dict[str, Any]] = {}
    skipped_calls = 0
    for occurrence, call in enumerate(analysis.function_calls):
        caller = _caller_for_call(analysis.functions, call)
        if caller is None:
            continue
        caller_id = make_function_id(
            analysis.file_path, caller.name, caller.start_line, project_root
        )
        target_module, target_name = _import_target(analysis, call, module)
        classification = _classify_call(target_module, call.called_name, scope)
        if classification == CALL_UNATTRIBUTABLE:
            skipped_calls += 1
            continue
        if classification == CALL_EXTERNAL:
            pair = (caller_id, target_module, target_name)
            entry = external_by_pair.get(pair)
            if entry is None:
                external_by_pair[pair] = {
                    "caller_id": caller_id,
                    "symbol_id": external_symbol_id(target_module, target_name),
                    "module": target_module,
                    "name": target_name,
                    "count": 1,
                }
            else:
                entry["count"] += 1
            continue
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
    return (
        enriched_nodes,
        structural_edges,
        references,
        list(external_by_pair.values()),
        file_dependency_references(analysis, project_root, module),
        skipped_calls,
    )


def iter_lattice_ingest_batches(
    analyses: Iterable[FileAnalysis],
    project_root: Path,
    *,
    batch_size: int,
    batch_bytes: int,
    include_source: bool = False,
    scope: Optional[ProjectScope] = None,
) -> Iterator[LatticeIngestBatch]:
    """Convert and group files without retaining repository-sized analyses."""
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    if batch_bytes < 1:
        raise ValueError("batch_bytes must be at least 1")

    def new_batch() -> LatticeIngestBatch:
        target_operations = batch_size
        if target_operations < 1:
            raise ValueError("batch size provider must return at least 1")
        return LatticeIngestBatch(target_operations=target_operations)

    batch = new_batch()
    for analysis in analyses:
        (
            nodes,
            edges,
            references,
            external_calls,
            dependency_refs,
            skipped,
        ) = _records_for_file(analysis, project_root, include_source, scope)
        file_operations = len(nodes) + len(edges) + len(references)
        file_operations += len(external_calls)
        file_bytes = sum(
            _value_bytes(record)
            for record in (*nodes, *edges, *references, *external_calls)
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
        batch.external_calls.extend(external_calls)
        batch.dependency_refs.extend(dependency_refs)
        batch.skipped_calls += skipped
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
        # Canonical ExternalSymbol id -> LatticeDB internal node id, for the
        # life of one ingestor. ~983 entries on the reference corpus, so the
        # cache is small and turns "look numpy.array up 2,247 times" into one
        # lookup.
        self._external_symbol_ids: Dict[str, int] = {}
        # How many CALLS edges each resolution rule produced, for the whole
        # run. Kept because the only way to tell a real improvement from a
        # reshuffle is the per-method split: a change can leave
        # `calls_resolved` flat while moving thousands of edges from a fuzzy
        # rule to an exact one (or the reverse). Surfaced in ingest()'s stats
        # as `resolution_method_<name>`.
        self._resolution_methods: Counter = Counter()
        # Every inherits/decorates/imports reference seen this run. Held
        # rather than resolved per batch: unlike a call, whose target is
        # usually in the same file, a base class or a registration decorator
        # is by definition somewhere else, so a per-batch attempt would miss
        # nearly all of them and defer them anyway. Size on the 2,107-file
        # reference corpus is a few tens of thousands of small dicts -- an
        # order of magnitude under the analyses this ingestor exists to
        # avoid retaining.
        self._dependency_refs: List[Dict[str, Any]] = []

    def _write_external_calls(
        self,
        external_calls: Sequence[Dict[str, Any]],
        node_id_map: Dict[tuple[str, str], int],
    ) -> int:
        """Materialize ExternalSymbol nodes and their CALLS_EXTERNAL edges."""
        if not external_calls:
            return 0
        new_nodes: List[NodeRecord] = []
        seen: set[str] = set()
        for call in external_calls:
            symbol_id = call["symbol_id"]
            if symbol_id in self._external_symbol_ids or symbol_id in seen:
                continue
            seen.add(symbol_id)
            new_nodes.append(
                NodeRecord(
                    id=symbol_id,
                    type="ExternalSymbol",
                    properties={
                        "id": symbol_id,
                        "module": call["module"],
                        "name": call["name"],
                        "qualified_name": f"{call['module']}.{call['name']}",
                    },
                )
            )
        # Never assume_new here, even on a fresh build: unlike Function/File
        # nodes, an ExternalSymbol is shared by the whole corpus, and an
        # incremental re-ingest (ingest_incremental passes assume_new=True)
        # would duplicate every symbol its changed files still call. The
        # existence lookup is paid once per distinct symbol per run.
        created = self.backend.upsert_nodes(new_nodes, assume_new=False)
        for (_node_type, canonical_id), internal_id in created.items():
            self._external_symbol_ids[canonical_id] = internal_id

        endpoints = dict(node_id_map)
        endpoints.update(
            {
                ("ExternalSymbol", canonical_id): internal_id
                for canonical_id, internal_id in self._external_symbol_ids.items()
            }
        )
        self.backend.upsert_edges(
            [
                EdgeRecord(
                    src_id=call["caller_id"],
                    dst_id=call["symbol_id"],
                    type="CALLS_EXTERNAL",
                    properties={"count": call["count"]},
                )
                for call in external_calls
            ],
            node_id_map=endpoints,
        )
        return len(external_calls)

    def _write_dependencies(
        self, files_by_module: Mapping[str, Optional[str]]
    ) -> Dict[str, int]:
        """Resolve the run's DEPENDS_ON references and write the edges.

        Runs after every batch, so every Function/Class/File node the corpus
        defines already exists and one pass can see all of them. Chunked the
        way _finalize_pending chunks the pending-call stream:
        find_symbols_by_properties opens a read transaction per call, and
        handing it tens of thousands of names at once is what that chunking
        exists to avoid.
        """
        stats = {
            f"dependencies_{kind}": 0
            for kind in (KIND_INHERITS, KIND_DECORATES, KIND_IMPORTS)
        }
        stats["dependencies_unresolved"] = 0
        edges: List[EdgeRecord] = []
        external: Dict[str, NodeRecord] = {}
        seen_imports: set[tuple[str, str]] = set()

        symbol_refs: List[Dict[str, Any]] = []
        for reference in self._dependency_refs:
            if reference["kind"] != KIND_IMPORTS:
                symbol_refs.append(reference)
                continue
            edge = resolve_import_reference(reference, files_by_module)
            if edge is None or (edge.src_id, edge.dst_id) in seen_imports:
                continue
            seen_imports.add((edge.src_id, edge.dst_id))
            edges.append(edge)
            stats["dependencies_" + KIND_IMPORTS] += 1

        for chunk in _chunked(symbol_refs, 1000):
            requests: Dict[tuple[str, str], int] = {}
            for reference in chunk:
                # 50 per label, not 2: unlike the call resolver's uniqueness
                # probe this needs the candidates themselves, to pick the one
                # whose module matches the import.
                requests[("name", reference["target_name"])] = 50
            candidates_by_key = self.backend.find_symbols_by_properties(requests)
            for reference in chunk:
                candidates = candidates_by_key.get(
                    ("name", reference["target_name"]), []
                )
                target, method, confidence = resolve_dependency_reference(
                    reference, candidates
                )
                if target is not None:
                    edges.append(
                        dependency_edge(
                            reference,
                            target["id"],
                            target.get("node_type", "Function"),
                            method,
                            confidence,
                        )
                    )
                    stats["dependencies_" + reference["kind"]] += 1
                    continue
                module = reference["target_module"]
                if not module or module in files_by_module:
                    stats["dependencies_unresolved"] += 1
                    continue
                # Outside the corpus: the existing external-symbol boundary,
                # reused rather than inventing a second unresolved-target
                # concept. `@app.route`, `pydantic.BaseModel`.
                symbol_id = external_symbol_id(module, reference["target_name"])
                if (
                    symbol_id not in external
                    and symbol_id not in self._external_symbol_ids
                ):
                    external[symbol_id] = NodeRecord(
                        id=symbol_id,
                        type="ExternalSymbol",
                        properties={
                            "id": symbol_id,
                            "module": module,
                            "name": reference["target_name"],
                            "qualified_name": f"{module}.{reference['target_name']}",
                        },
                    )
                edges.append(
                    dependency_edge(
                        reference,
                        symbol_id,
                        "ExternalSymbol",
                        "external_boundary",
                        "high",
                    )
                )
                stats["dependencies_" + reference["kind"]] += 1

        if external:
            created = self.backend.upsert_nodes(
                list(external.values()), assume_new=False
            )
            for (_label, canonical_id), internal_id in created.items():
                self._external_symbol_ids[canonical_id] = internal_id
        if edges:
            self.backend.upsert_edges(edges)
        self._dependency_refs = []
        return stats

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
            # Class candidates have no parent_class property at all (only
            # methods do), so `not candidate["parent_class"]` -- which exists
            # to reject a method reached by a bare module-level import --
            # admits them unchanged: a module-level class is exactly what a
            # `from pkg.mod import Thing; Thing()` site should resolve to.
            imported = [
                candidate
                for candidate in named
                if candidate["module"] == reference["target_module"]
                and not candidate["parent_class"]
            ]
            if len(imported) == 1:
                return imported[0], "explicit_import"
            if len(imported) > 1:
                return None, "ambiguous" if finalize else None

            # One approximation remains, for re-exports only. `from gemseo
            # import create_discipline` names a package whose __init__.py
            # re-exports a symbol defined in a submodule, so the definition
            # node's module (`gemseo.disciplines.factory`) is never equal to
            # the imported one (`gemseo`) -- following that would mean
            # parsing every __init__.py's own imports and chaining them.
            # Instead: accept a candidate defined anywhere *below* the
            # imported package, when it is the only such candidate.
            #
            # What this can get wrong: two same-named module-level symbols
            # under one package, only one of which is really re-exported at
            # the top. Uniqueness among fetched candidates bounds that but
            # does not eliminate it, so the result stays low-confidence. It
            # is self-limiting to project code -- a stdlib or third-party
            # `from x import y` has no candidate node whose module starts
            # with `x`.
            #
            # Scale, measured on the 2,103-file gemseo corpus: this rule
            # carried 6,062 resolutions while modules were derived from the
            # indexed root and it was papering over that bug. With modules
            # derived from the package root it fires 25 times, against 6,525
            # exact `explicit_import` matches. It is now what it was meant
            # to be -- a narrow fallback, not the main resolution path.
            target_module = reference["target_module"]
            related = [
                candidate
                for candidate in named
                if _reexporting_package(candidate["module"] or "", target_module)
                and not candidate["parent_class"]
            ]
            if len(related) == 1:
                return related[0], "package_reexport"
            return None, "ambiguous" if finalize and len(related) > 1 else None

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
        # Function *and* Class candidates: constructing a project class is a
        # call site whose definition is a Class node. Measured on the 2,107-
        # file gemseo corpus, 4,728 of 45,320 unresolved references pointed
        # at an internal module, dominated by class constructors
        # (DesignSpace: 250, MDOFunction: 199, AnalyticDiscipline: 103).
        candidates_by_key = self.backend.find_symbols_by_properties(requests)
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
                self._resolution_methods[method] += 1
                resolutions.append(
                    {
                        "reference": reference,
                        "target_id": target["id"],
                        "target_type": target.get("node_type", "Function"),
                        "resolution_method": method,
                        # package_reexport joins global_unique as "low": both
                        # are name-level guesses, not a followed import.
                        "confidence": (
                            "low"
                            if method in ("global_unique", "package_reexport")
                            else "high"
                        ),
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
        on_batch_committed: Optional[Callable[[Dict[str, int]], None]] = None,
        on_finalize_progress: Optional[Callable[[Dict[str, int]], None]] = None,
    ) -> Dict[str, int]:
        requeued_calls = self.backend.requeue_unresolved_calls()
        scope = ProjectScope.from_project_root(self.project_root)
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
            "external_symbols": 0,
            "external_edges": 0,
            "calls_skipped_unattributable": 0,
            "dependencies_inherits": 0,
            "dependencies_decorates": 0,
            "dependencies_imports": 0,
            "dependencies_unresolved": 0,
            "batch_target_size": batch_size,
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
            scope=scope,
        ):
            write_started = perf_counter()
            node_ids = self.backend.upsert_nodes(batch.nodes, assume_new=assume_new)
            self.backend.upsert_edges(batch.structural_edges, node_id_map=node_ids)
            external_edges = self._write_external_calls(batch.external_calls, node_ids)
            resolutions, pending = self._resolve_references(
                batch.call_references, finalize=False
            )
            resolved = self.backend.apply_call_outcomes(resolutions, pending)
            self._dependency_refs.extend(batch.dependency_refs)
            write_seconds = perf_counter() - write_started
            stats["batches"] += 1
            stats["total_nodes"] += len(batch.nodes)
            stats["total_edges"] += (
                len(batch.structural_edges) + resolved + external_edges
            )
            stats["files"] += sum(node.type == "File" for node in batch.nodes)
            stats["functions"] += sum(node.type == "Function" for node in batch.nodes)
            stats["classes"] += sum(node.type == "Class" for node in batch.nodes)
            stats["call_references"] += len(batch.call_references)
            stats["calls_resolved"] += resolved
            stats["calls_pending"] += len(pending)
            stats["external_edges"] += external_edges
            stats["external_symbols"] = len(self._external_symbol_ids)
            stats["calls_skipped_unattributable"] += batch.skipped_calls
            stats["batch_target_size"] = batch.target_operations
            stats["last_batch_operations"] = batch.operation_count
            stats["last_batch_bytes"] = batch.estimated_bytes
            stats["last_batch_write_ms"] = round(write_seconds * 1000)
            if on_batch_committed is not None:
                on_batch_committed(dict(stats))

        # After the last batch, so every definition a base class or a
        # decorator could name is already a node.
        files_by_module: Dict[str, Optional[str]] = {}
        for relative, module in scope.modules_by_file.items():
            if not module:
                continue
            files_by_module[module] = None if module in files_by_module else relative
        dependency_stats = self._write_dependencies(files_by_module)
        stats.update(dependency_stats)
        stats["total_edges"] += sum(
            count
            for key, count in dependency_stats.items()
            if key != "dependencies_unresolved"
        )

        resolved, unresolved = self._finalize_pending(
            stats["calls_pending"], on_progress=on_finalize_progress
        )
        stats["calls_resolved"] += resolved
        stats["calls_unresolved"] = unresolved
        for method, count in self._resolution_methods.items():
            stats[f"resolution_method_{method}"] = count
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
