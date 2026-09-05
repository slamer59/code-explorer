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

import hashlib
from pathlib import Path, PurePosixPath
import re
from typing import (
    AbstractSet,
    Any,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)

from code_explorer.analyzer.export_parquet import (
    make_class_id,
    make_function_id,
    to_relative_path,
)
from code_explorer.analyzer.models import FileAnalysis, FunctionCall
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


def _identifier_words(name: str) -> List[str]:
    """Split an identifier into the words an LLM would plausibly type.

    `compute_gradient` -> ["compute", "gradient"]; `computeGradient` and
    `HTTPServerError` likewise. The retrieval model this serves is: the LLM
    guesses a plausible *name*, BM25 finds it, the graph expands from there.
    A guess is rarely character-exact -- "compute gradient" for
    `compute_gradient` is the common case -- and neither backend's tokenizer
    splits identifiers for us (measured: LatticeDB indexes `compute_gradient`
    as a single token, so the spaced query matched only docstring prose and
    returned `pow2_jac`; SQLite's FTS5 unicode61 splits on `_` but not on
    camelCase).
    """
    words = re.split(r"[_\W]+", name)
    out: List[str] = []
    for word in words:
        if not word:
            continue
        # camelCase / PascalCase / HTTPServer -> boundaries before a capital
        # that starts a new word.
        out.extend(re.findall(r"[A-Z]+(?![a-z])|[A-Z][a-z]*|[a-z]+|\d+", word))
    return [w.lower() for w in out if w]


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
    # The name carries far more retrieval signal than the docstring, but a
    # single flat field lets prose outscore it: BM25 rewards term density, and
    # a wordy docstring beats a one-token name. Measured on gemseo, the query
    # "compute gradient" returned `pow2_jac` (whose docstring reads "Compute
    # the gradient of the objective") above `compute_gradient` itself.
    # Emitting the identifier, then its split words, then both again weights
    # name matches above body/docstring matches without needing per-field
    # boosting -- which neither backend's FTS exposes.
    identifier_words = _identifier_words(name)
    parts = [f"{rel_file}::{name}", name]
    if identifier_words:
        parts.append(" ".join(identifier_words))
        parts.append(" ".join(identifier_words))
    if source_code:
        parts.append(_signature_text(source_code))
    if docstring:
        parts.append(docstring)
    if called_names:
        parts.append("calls: " + ", ".join(called_names))
    return "\n".join(p for p in parts if p)


# --------------------------------------------------------------------------
# Module naming and import-binding resolution.
#
# These four helpers used to live in graph/lattice_streaming.py, which is
# where the only caller was. They moved here because the influence relations
# below need exactly the same two facts -- "what module is this file?" and
# "what does this bare name in this file refer to?" -- and a second copy of
# `pkg.sub` prefix matching is the kind of duplication that produced three
# call-resolution bugs in one session. lattice_streaming.py imports them from
# here; behaviour is unchanged.
# --------------------------------------------------------------------------


def module_name_for_file(relative_file: str) -> str:
    parts = list(PurePosixPath(relative_file).parts)
    if not parts:
        return ""
    if parts[-1] == "__init__.py":
        parts.pop()
    elif parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]
    return ".".join(parts)


def package_root_depth(parts: Sequence[str], package_dirs: AbstractSet[str]) -> int:
    """How many leading path segments of a file are *above* its package root.

    Standard rule: walk up from the file's directory while `__init__.py`
    exists; the first directory without one is the package root, and the
    module name is the path relative to that. Handles src layout, flat
    layout, and a parent directory holding several projects.

    HYPOTHESIS: a directory holding an `__init__.py` is a package, and one
    holding none is not. Namespace packages (PEP 420) carry no
    `__init__.py`, so the walk cannot see them. Two consequences, both
    deliberate:

     - If the file's own directory is not a package, no walk happens at all
       and the module stays project-root-relative -- the pre-existing
       behaviour, which is the right answer for a flat repository and for
       `models/space.py` imported as `models.space` with the repository
       root on sys.path.
     - A package nested inside a namespace package (`src/ns/pkg/mod.py`
       where only `pkg` has an `__init__.py`) is named from `pkg`, i.e. one
       segment too short. Rarer than the src-layout case this fixes, and
       ProjectScope still registers both spellings as internal modules, so
       the cost is a missed `explicit_import`, not a wrong edge.
    """
    directories = list(parts[:-1])
    root_depth = len(directories)
    if root_depth and "/".join(directories) not in package_dirs:
        return 0
    while root_depth > 0 and "/".join(directories[:root_depth]) in package_dirs:
        root_depth -= 1
    return root_depth


def reexporting_package(module: str, imported_module: str) -> bool:
    """True when `imported_module` is an ancestor package of `module`.

    Prefix-only, and segment-aligned so `pkg.algos` does not match
    `pkg.algorithms`. This is the shape of a genuine re-export: `from pkg
    import create_thing` names the package, while the definition lives in
    `pkg.factory` below it.

    This used to accept the *suffix* direction too, which was the only way
    to match a src-layout file whose module was mis-derived as
    `pkg.src.pkg.algos.space`. With modules now derived from the package
    root that direction is dead: dropping it moved zero resolutions on the
    2,103-file reference corpus (package_reexport 25 either way, calls
    resolved 15,435 either way), so what it can no longer do is match a
    vendored copy of a package sitting below the real one -- which it should
    not have been doing.
    """
    if not module or not imported_module:
        return False
    return module == imported_module or module.startswith(f"{imported_module}.")


def resolve_relative_module(
    caller_module: str, imported_module: Optional[str], is_relative: bool
) -> str:
    imported_module = imported_module or ""
    if not is_relative:
        return imported_module
    package = caller_module.rsplit(".", 1)[0] if "." in caller_module else ""
    return ".".join(part for part in (package, imported_module) if part)


def import_target(
    analysis: FileAnalysis, call: FunctionCall, caller_module: str
) -> Tuple[str, str]:
    for imported in analysis.imports_detailed:
        binding = imported.alias or imported.imported_name
        if imported.module is not None:
            if call.qualifier is None and call.called_name == binding:
                return (
                    resolve_relative_module(
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


def external_symbol_id(module: str, name: str) -> str:
    """Canonical id for an ExternalSymbol node, stable across runs."""
    identity = f"{module}\0{name}"
    return "ext_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]


def modules_by_file(relative_files: Iterable[str]) -> Dict[str, str]:
    """Project-root-relative path -> the module name an import would use.

    Same derivation as ProjectScope.from_project_root, but from a list of
    paths instead of a filesystem walk, so the generic (non-streaming)
    ingest path can resolve imports without a second directory scan.
    """
    relative_files = [PurePosixPath(f).as_posix() for f in relative_files]
    package_dirs = {
        relative.rsplit("/", 1)[0] if "/" in relative else ""
        for relative in relative_files
        if relative.endswith("__init__.py")
    }
    out: Dict[str, str] = {}
    for relative in relative_files:
        parts = relative.split("/")
        depth = package_root_depth(parts, package_dirs)
        out[relative] = module_name_for_file("/".join(parts[depth:]))
    return out


# --------------------------------------------------------------------------
# Influence that is not a function call: DEPENDS_ON.
#
# ONE relation carrying a `kind`, not four typed edge types. The Function /
# Class *label* split in this codebase was inherited from Kuzu's typed rel
# tables and reproduced in a schema-less database; it caused three separate
# bugs in one session (call resolution ignoring Class targets;
# get_call_edges_with_lines silently returning ([], []) for a Class id; two
# FTS indexes where one would do). Four new typed edges -- INHERITS,
# DECORATED_BY, IMPORTS, ... -- buy the same class of problem: every
# consumer has to enumerate them, and the one it forgets returns "(none)"
# rather than an error. A consumer instead walks DEPENDS_ON once and reads
# `kind` as data.
#
# Direction is "depends on", i.e. edges point at what INFLUENCES the source:
#
#   (subclass:Class)      -DEPENDS_ON {kind:"inherits"}->  (base:Class)
#   (decorated:Function)  -DEPENDS_ON {kind:"decorates"}-> (decorator:Function)
#   (importer:File)       -DEPENDS_ON {kind:"imports"}->   (imported:File)
#
# So outgoing DEPENDS_ON = "what influences me" (upstream, the set an LLM
# needs to judge whether a change is safe) and incoming DEPENDS_ON = "what I
# influence" (downstream: the fifteen plugins extending this base class).
# Note this is the opposite orientation from CALLS, where the arrow points
# downstream -- hence naming the relation for the direction it encodes.
# --------------------------------------------------------------------------

DEPENDS_ON = "DEPENDS_ON"
KIND_INHERITS = "inherits"
KIND_DECORATES = "decorates"
KIND_IMPORTS = "imports"

# Bases that are never worth an edge: `object` is implicit and universal, and
# the typing/Protocol markers are structural noise that would connect every
# generic class in the corpus to one hub node.
_UNINTERESTING_BASES = frozenset(
    {
        "object",
        "Generic",
        "Protocol",
        "ABC",
        "abc.ABC",
        "typing.Generic",
        "typing.Protocol",
        "Enum",
        "enum.Enum",
        "NamedTuple",
        "TypedDict",
    }
)


def _binding_target(
    analysis: FileAnalysis, dotted_name: str, file_module: str
) -> Tuple[str, str]:
    """(module, name) that a dotted reference in this file points at.

    `functools.lru_cache` -> ("functools", "lru_cache") via the `import
    functools` binding; a bare `BasePlugin` -> ("demo.base", "BasePlugin")
    via `from demo.base import BasePlugin`. ("", name) when no import
    explains the name, which leaves the name-level rules to resolve it.

    What this can get wrong: only the first and last segments of a dotted
    name are used, so `a.b.C` is looked up as qualifier `a` + name `C` --
    an attribute chain through an intermediate object resolves to the wrong
    module. Same approximation the CALLS resolver makes (see import_target),
    kept identical on purpose so both paths are wrong in the same way rather
    than in two ways.
    """
    parts = dotted_name.split(".")
    call = FunctionCall(
        caller_function="",
        called_name=parts[-1],
        call_line=0,
        qualifier=parts[0] if len(parts) > 1 else None,
    )
    return import_target(analysis, call, file_module)


def _decorated_node_id(
    decorator_line: int,
    target_name: str,
    target_type: str,
    functions: Sequence[Tuple[int, str, str]],
    classes: Sequence[Tuple[int, str, str]],
) -> Optional[str]:
    """Node id of the def/class a decorator is attached to.

    DecoratorInfo records the target's *name*, not its line, so the two are
    matched by position: the decorated definition is the nearest same-named
    def/class starting at or after the decorator's line.

    What this can get wrong: two same-named definitions where the decorator
    sits between them (a conditional redefinition, or a `@property` /
    `@x.setter` pair whose getter and setter are both `def x`). The
    setter case attaches to the right one -- the decorator line always
    precedes its own def -- so the residual error is redefinition, which is
    rare enough not to justify re-parsing the file here.
    """
    pool = functions if target_type == "function" else classes
    named = [entry for entry in pool if entry[1] == target_name]
    if not named:
        return None
    after = [entry for entry in named if entry[0] >= decorator_line]
    return min(after or named, key=lambda entry: entry[0])[2]


def file_dependency_references(
    analysis: FileAnalysis,
    project_root: Path,
    file_module: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Unresolved `inherits` / `decorates` facts for one file.

    Shaped like the call references graph/lattice_streaming.py already
    defers and resolves (same keys, plus `kind` / `src_type`), so the
    streaming path can hand them to the *same* resolver rather than growing
    a parallel one. Targets are left unresolved here because a base class
    almost never lives in the file that extends it -- resolution needs the
    whole corpus, which neither this function nor a streaming batch has.

    `imports` references are produced too, but they are a different kind
    of unresolved: the target is a module name that maps to exactly one File
    node or to none, with no name-level ambiguity. Both callers resolve them
    with a plain module -> path lookup rather than the candidate ladder.
    """
    relative_file = to_relative_path(analysis.file_path, project_root)
    module = file_module if file_module is not None else module_name_for_file(relative_file)
    references: List[Dict[str, Any]] = []

    functions = [
        (
            function.start_line,
            function.name,
            make_function_id(
                analysis.file_path, function.name, function.start_line, project_root
            ),
        )
        for function in analysis.functions
    ]
    classes = [
        (
            class_info.start_line,
            class_info.name,
            make_class_id(
                analysis.file_path, class_info.name, class_info.start_line, project_root
            ),
        )
        for class_info in analysis.classes
    ]

    def add(src_id: str, src_type: str, kind: str, raw_name: str, line: int) -> None:
        target_module, target_name = _binding_target(analysis, raw_name, module)
        references.append(
            {
                "id": f"dep_{kind}_{src_id}_{raw_name}_{line}",
                "kind": kind,
                "src_type": src_type,
                # Aliases of src_id/src_file. The streaming resolver reads
                # `caller_*`; keeping both names means these dicts drop into
                # it unmodified while readers here still see the honest
                # spelling.
                "src_id": src_id,
                "src_file": relative_file,
                "caller_id": src_id,
                "caller_file": relative_file,
                "caller_content_hash": analysis.content_hash,
                "caller_class": "",
                "caller_bases": [],
                "called_name": raw_name.split(".")[-1],
                "qualifier": "",
                "call_line": line,
                "target_module": target_module,
                "target_name": target_name,
            }
        )

    for class_info in analysis.classes:
        src_id = make_class_id(
            analysis.file_path, class_info.name, class_info.start_line, project_root
        )
        for base in class_info.bases:
            base = base.strip()
            # Subscripted generics (`Sequence[str]`) and keyword bases
            # (`metaclass=ABCMeta`) reach us as raw source text; take the
            # name in front of the bracket and skip anything else.
            base = base.split("[", 1)[0].strip()
            if not base or "=" in base or base in _UNINTERESTING_BASES:
                continue
            add(src_id, "Class", KIND_INHERITS, base, class_info.start_line)

    for imported in analysis.imports:
        imported_module = resolve_relative_module(
            module, imported.module, imported.is_relative
        )
        if not imported_module:
            continue
        references.append(
            {
                "id": f"dep_{KIND_IMPORTS}_{relative_file}_{imported_module}",
                "kind": KIND_IMPORTS,
                "src_type": "File",
                "src_id": relative_file,
                "src_file": relative_file,
                "caller_id": relative_file,
                "caller_file": relative_file,
                "caller_content_hash": analysis.content_hash,
                "caller_class": "",
                "caller_bases": [],
                "called_name": imported_module.rsplit(".", 1)[-1],
                "qualifier": "",
                "call_line": imported.line_number,
                "target_module": imported_module,
                "target_name": "",
            }
        )

    for decorator in analysis.decorators:
        src_id = _decorated_node_id(
            decorator.line_number,
            decorator.target_name,
            decorator.target_type,
            functions,
            classes,
        )
        if src_id is None:
            continue
        src_type = "Class" if decorator.target_type == "class" else "Function"
        add(src_id, src_type, KIND_DECORATES, decorator.name, decorator.line_number)

    return references


def resolve_dependency_reference(
    reference: Mapping[str, Any], candidates: Sequence[Mapping[str, Any]]
) -> Tuple[Optional[Mapping[str, Any]], Optional[str], Optional[str]]:
    """Pick the definition a dependency reference names.

    Returns (candidate, resolution_method, confidence) or (None, None, None).
    Deliberately the same rule ladder, in the same order, as
    LatticeStreamingIngestor._resolution uses for calls -- module-exact
    first, then a re-export prefix, then same-file, then corpus-unique --
    minus the `self.`/base-class branches, which have no meaning for a base
    class or a decorator name.
    """
    target_name = reference["target_name"] or reference["called_name"]
    named = [c for c in candidates if c.get("name") == target_name]
    top_level = [c for c in named if not c.get("parent_class")]
    module = reference.get("target_module") or ""

    if module:
        exact = [c for c in top_level if (c.get("module") or "") == module]
        if len(exact) == 1:
            return exact[0], "explicit_import", "high"
        if len(exact) > 1:
            return None, None, None
        related = [
            c for c in top_level if reexporting_package(c.get("module") or "", module)
        ]
        if len(related) == 1:
            return related[0], "package_reexport", "low"
        return None, None, None

    same_file = [c for c in top_level if c.get("file") == reference["src_file"]]
    if len(same_file) == 1:
        return same_file[0], "same_file", "high"
    if len(top_level) == 1:
        return top_level[0], "global_unique", "low"
    return None, None, None


def resolve_import_reference(
    reference: Mapping[str, Any], files_by_module: Mapping[str, Optional[str]]
) -> Optional[EdgeRecord]:
    """The File -> File DEPENDS_ON edge for an `imports` reference, or None.

    Only project-internal imports become edges. A third-party import is
    already visible where it matters -- as a CALLS_EXTERNAL edge from the
    function that actually uses it -- and giving every `import os` a File ->
    ExternalSymbol edge would add roughly one edge per file per stdlib
    module to answer a question nobody asks ("does this file import os?").

    What this can get wrong: `from pkg import thing` where `pkg` is a
    package records a dependency on `pkg/__init__.py`, not on the submodule
    that really defines `thing`. Following that would mean parsing every
    __init__.py's re-exports; the inherits/decorates edges already point at
    the real definition, so the import edge is left as the coarse
    file-level fact it is.
    """
    target = files_by_module.get(reference["target_module"])
    if target is None or target == reference["src_id"]:
        return None
    return EdgeRecord(
        src_id=reference["src_id"],
        dst_id=target,
        type=DEPENDS_ON,
        src_type="File",
        dst_type="File",
        properties={
            "kind": KIND_IMPORTS,
            "line_number": reference["call_line"],
            "resolution_method": "module_path",
            "confidence": "high",
        },
    )


def dependency_edge(
    reference: Mapping[str, Any],
    target_id: str,
    target_type: str,
    resolution_method: str,
    confidence: str,
) -> EdgeRecord:
    """The DEPENDS_ON edge for one resolved dependency reference."""
    return EdgeRecord(
        src_id=reference["src_id"],
        dst_id=target_id,
        type=DEPENDS_ON,
        src_type=reference["src_type"],
        dst_type=target_type,
        properties={
            "kind": reference["kind"],
            "line_number": reference["call_line"],
            "resolution_method": resolution_method,
            "confidence": confidence,
            # The unresolved fact, carried on the edge exactly as CALLS
            # carries call_reference: re-indexing the *target* file deletes
            # this edge, and republishing the fact is the only way the
            # subclass's dependency survives without re-parsing the
            # subclass. See LatticeBackend.delete_file.
            "dependency_reference": dict(reference),
        },
    )


def file_analyses_to_records(
    results: List[FileAnalysis],
    project_root: Path,
    resolved_calls: Optional[List[dict]] = None,
    include_source: bool = False,
    emit_dependencies: bool = True,
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
        emit_dependencies: If True (the default), also emit DEPENDS_ON edges
            for inheritance, decoration and imports, resolved against
            `results` treated as the whole corpus. The streaming path passes
            False: it calls this once per file, where a corpus-wide
            resolution would be wrong (a base class is almost never in the
            file that extends it), and resolves its own references later --
            see graph/lattice_streaming.py.

            LIMITATION: "the whole corpus" is exactly `results`. On an
            incremental re-ingest of a handful of changed files, a base
            class or decorator defined in an unchanged file is not among
            them, so its edge falls back to the external boundary or is
            dropped -- and, more rarely, a name that is ambiguous corpus-
            wide can look unique within the subset and resolve to the
            wrong definition. The streaming path does not have this
            problem (it resolves against the database, not the batch).
            Left as-is because the generic path's only production use is a
            full build (see cli.py: it is the branch for backends without
            LatticeDB's durable call streams).

    Returns:
        (nodes, edges) ready for CodeGraphBackend.upsert_nodes/upsert_edges.
    """
    nodes: List[NodeRecord] = []
    edges: List[EdgeRecord] = []

    seen_files = set()
    seen_funcs = set()
    seen_classes = set()

    file_modules = modules_by_file(
        to_relative_path(result.file_path, project_root) for result in results
    )
    # module -> relative path, for `kind:"imports"` edges. Ambiguous module
    # names (two files claiming one name, possible in a repository holding
    # several projects) are dropped rather than guessed.
    files_by_module: Dict[str, Optional[str]] = {}
    for relative, module in file_modules.items():
        if not module:
            continue
        files_by_module[module] = None if module in files_by_module else relative
    # Every Function/Class candidate, for resolve_dependency_reference.
    dependency_candidates: Dict[str, List[Dict[str, Any]]] = {}

    for result in results:
        rel_file = to_relative_path(result.file_path, project_root)
        file_module = file_modules.get(rel_file, "")

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
            func_properties = {
                "id": func_id,
                "name": func.name,
                "file": rel_file,
                "start_line": func.start_line,
                "end_line": func.end_line,
                "is_public": func.is_public,
                # Previously written only by the streaming path, which left
                # both empty on a generic (SqliteBackend) build -- so
                # context.py's `MATCH (f:Function {file, parent_class})`
                # matched nothing there, and dependency resolution could not
                # tell a method from a module-level function. Set here so
                # both ingest paths agree; the streaming path still
                # overwrites `module` with its package-root-derived spelling,
                # which is the more accurate one when project_root sits above
                # the package.
                "module": file_module,
                "parent_class": func.parent_class or "",
                "search_text": _derive_search_text(
                    rel_file, func.name, func.source_code, func.docstring, func.called_names
                ),
            }
            if include_source:
                func_properties["source_code"] = func.source_code or ""
            nodes.append(
                NodeRecord(
                    id=func_id,
                    type="Function",
                    properties=func_properties,
                )
            )
            dependency_candidates.setdefault(func.name, []).append(
                {
                    "id": func_id,
                    "node_type": "Function",
                    "name": func.name,
                    "file": rel_file,
                    "module": file_module,
                    "parent_class": func.parent_class or "",
                }
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
            class_properties = {
                "id": class_id,
                "name": cls.name,
                "file": rel_file,
                "start_line": cls.start_line,
                "end_line": cls.end_line,
                # Kept as the comma-joined string it always was: it is what
                # `search` prints, and the structured version of the same
                # fact now rides on the DEPENDS_ON {kind:"inherits"} edges.
                "bases": ",".join(cls.bases) if cls.bases else "",
                "module": file_module,
                "is_public": cls.is_public,
                "search_text": _derive_search_text(
                    rel_file, cls.name, cls.source_code, cls.docstring
                ),
            }
            if include_source:
                class_properties["source_code"] = cls.source_code or ""
            nodes.append(
                NodeRecord(
                    id=class_id,
                    type="Class",
                    properties=class_properties,
                )
            )
            dependency_candidates.setdefault(cls.name, []).append(
                {
                    "id": class_id,
                    "node_type": "Class",
                    "name": cls.name,
                    "file": rel_file,
                    "module": file_module,
                    "parent_class": "",
                }
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

    if emit_dependencies:
        external_nodes: Dict[str, NodeRecord] = {}
        seen_imports: set = set()
        for result in results:
            rel_file = to_relative_path(result.file_path, project_root)
            file_module = file_modules.get(rel_file, "")

            for reference in file_dependency_references(
                result, project_root, file_module
            ):
                if reference["kind"] == KIND_IMPORTS:
                    edge = resolve_import_reference(reference, files_by_module)
                    if edge is not None and (edge.src_id, edge.dst_id) not in seen_imports:
                        seen_imports.add((edge.src_id, edge.dst_id))
                        edges.append(edge)
                    continue
                candidates = dependency_candidates.get(
                    reference["target_name"] or reference["called_name"], []
                )
                target, method, confidence = resolve_dependency_reference(
                    reference, candidates
                )
                if target is not None:
                    edges.append(
                        dependency_edge(
                            reference,
                            target["id"],
                            target["node_type"],
                            method,
                            confidence,
                        )
                    )
                    continue
                # Unresolved and attributable to a module we never parsed:
                # the same boundary CALLS_EXTERNAL already draws
                # (`pydantic.BaseModel`, `@app.route`). Reused rather than
                # inventing a second unresolved-target concept. Unresolved
                # with no module at all is dropped -- there is nothing to
                # name the node after.
                module = reference["target_module"]
                if not module or module in files_by_module:
                    continue
                symbol_id = external_symbol_id(module, reference["target_name"])
                if symbol_id not in external_nodes:
                    external_nodes[symbol_id] = NodeRecord(
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
        nodes.extend(external_nodes.values())

    return nodes, edges
