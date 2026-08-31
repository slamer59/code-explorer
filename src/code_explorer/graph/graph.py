"""
Main facade for the dependency graph.

Delegates to specialized operation classes while maintaining backward compatibility.
"""

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

from rich.console import Console

from code_explorer.graph.models import (
    AttributeNode,
    ClassNode,
    DecoratorNode,
    ExceptionNode,
    FunctionNode,
    ImportNode,
    ModuleNode,
    VariableNode,
)
from code_explorer.graph.backend import CodeGraphBackend
from code_explorer.graph.backends.kuzu_backend import KuzuBackend
from code_explorer.graph.node_operations import NodeOperations
from code_explorer.graph.edge_operations import EdgeOperations
from code_explorer.graph.queries import QueryOperations

console = Console()


class DependencyGraph:
    """KuzuDB-backed dependency graph with persistent storage.

    Stores functions, variables, and their relationships in a property graph
    database that persists to disk. Supports incremental updates and efficient queries.

    For bulk loading, use the Parquet workflow:
    1. Export: _export_results_to_parquet(results, parquet_dir)
    2. Load: load_from_parquet(parquet_dir) - 23x faster, 99% less memory

    The old pandas-based batch operations have been removed.
    """

    def __init__(
        self,
        db_path: Optional[Path] = None,
        read_only: bool = False,
        project_root: Optional[Path] = None,
        backend: Optional[CodeGraphBackend] = None,
    ):
        """Initialize the graph backend and create schema if needed.

        Args:
            db_path: Path to the database directory.
                    Defaults to .code-explorer/graph.db
            read_only: If True, opens database in read-only mode for safe parallel
                      reads without risk of accidental writes. Default is False.
                      In read-only mode, schema creation is skipped and all write
                      methods will raise exceptions if called.
            project_root: Root directory for relative paths. Defaults to current working directory.
            backend: CodeGraphBackend instance to use. Defaults to a KuzuBackend
                    opened at db_path. Pass an already-open backend to reuse a
                    connection or to use a different backend implementation.
        """
        if db_path is None:
            db_path = Path.cwd() / ".code-explorer" / "graph.db"

        self.db_path = db_path
        self.read_only = read_only
        self.project_root = project_root if project_root else Path.cwd()

        self.backend = backend if backend is not None else KuzuBackend(
            db_path, read_only=read_only
        )
        self.backend.open()

        # Backward-compat attributes: NodeOperations/EdgeOperations (and a
        # handful of raw Cypher calls in this facade) still take a
        # kuzu.Connection directly and only work with KuzuBackend (Phase 0 of
        # the LatticeDB migration keeps this unchanged; see
        # docs/explanation/latticedb-migration.md). Non-Kuzu backends (e.g.
        # LatticeBackend) don't have these attributes -- construction must
        # still succeed for such backends, since ingest_results/backend.query
        # work without them; add_function/add_class/etc. simply aren't usable
        # until NodeOperations/EdgeOperations are made backend-agnostic too.
        self.db = getattr(self.backend, "db", None)
        self.conn = getattr(self.backend, "conn", None)
        self.schema_manager = getattr(self.backend, "schema_manager", None)

        # Create schema if tables don't exist (only in read-write mode)
        if not self.read_only:
            self.backend.initialize_schema()

        # Detect schema version (after schema creation)
        self.schema_version = self.backend.detect_schema_version()

        # Build helper methods dictionary for operation classes
        helper_methods = {
            "to_relative_path": self._to_relative_path,
            "make_function_id": self._make_function_id,
            "make_variable_id": self._make_variable_id,
            "make_class_id": self._make_class_id,
            "make_import_id": self._make_import_id,
            "make_decorator_id": self._make_decorator_id,
            "make_attribute_id": self._make_attribute_id,
            "make_exception_id": self._make_exception_id,
            "make_module_id": self._make_module_id,
        }

        # Initialize operation classes
        self.node_ops = NodeOperations(
            self.conn, self.read_only, self.project_root, helper_methods
        )
        self.edge_ops = EdgeOperations(
            self.conn, self.read_only, self.project_root, helper_methods
        )
        self.queries = QueryOperations(
            self.backend, self.project_root, helper_methods, self.schema_version
        )

    def _check_read_only(self) -> None:
        """Raise exception if database is in read-only mode.

        Raises:
            RuntimeError: If database is in read-only mode
        """
        if self.read_only:
            raise RuntimeError(
                "Cannot perform write operation: database is in read-only mode. "
                "Create a new DependencyGraph instance with read_only=False to enable writes."
            )

    # Helper methods for ID generation
    def _to_relative_path(self, file_path: str) -> str:
        """Convert absolute path to relative path from project root.

        Args:
            file_path: Absolute or relative file path

        Returns:
            Relative path from project root
        """
        try:
            path = Path(file_path)
            if path.is_absolute():
                return str(path.relative_to(self.project_root))
            return file_path
        except ValueError:
            # Path is not relative to project_root, return as-is
            return file_path

    def _make_function_id(self, file: str, name: str, start_line: int) -> str:
        """Create stable hash-based ID for a function.

        Args:
            file: File path
            name: Function name
            start_line: Starting line number

        Returns:
            Hash-based identifier (e.g., 'fn_a1b2c3d4e5f6')
        """
        # Use relative path for stability
        rel_path = self._to_relative_path(file)
        content = f"{rel_path}::{name}::{start_line}"
        hash_digest = hashlib.sha256(content.encode()).hexdigest()[:12]
        return f"fn_{hash_digest}"

    def _make_variable_id(self, file: str, name: str, line: int) -> str:
        """Create stable hash-based ID for a variable.

        Args:
            file: File path
            name: Variable name
            line: Definition line number

        Returns:
            Hash-based identifier (e.g., 'var_a1b2c3d4e5f6')
        """
        rel_path = self._to_relative_path(file)
        content = f"{rel_path}::{name}::{line}"
        hash_digest = hashlib.sha256(content.encode()).hexdigest()[:12]
        return f"var_{hash_digest}"

    def _make_class_id(self, file: str, name: str, start_line: int) -> str:
        """Create stable hash-based ID for a class.

        Args:
            file: File path
            name: Class name
            start_line: Starting line number

        Returns:
            Hash-based identifier (e.g., 'cls_a1b2c3d4e5f6')
        """
        # Use relative path for stability
        rel_path = self._to_relative_path(file)
        content = f"{rel_path}::{name}::{start_line}"
        hash_digest = hashlib.sha256(content.encode()).hexdigest()[:12]
        return f"cls_{hash_digest}"

    def _make_import_id(self, file: str, imported_name: str, line_number: int) -> str:
        """Create stable hash-based ID for an import.

        Args:
            file: File path
            imported_name: Name of imported entity
            line_number: Line number of import

        Returns:
            Hash-based identifier (e.g., 'imp_a1b2c3d4e5f6')
        """
        rel_path = self._to_relative_path(file)
        content = f"{rel_path}::{imported_name}::{line_number}"
        hash_digest = hashlib.sha256(content.encode()).hexdigest()[:12]
        return f"imp_{hash_digest}"

    def _make_decorator_id(self, file: str, name: str, line_number: int) -> str:
        """Create stable hash-based ID for a decorator.

        Args:
            file: File path
            name: Decorator name
            line_number: Line number of decorator application

        Returns:
            Hash-based identifier (e.g., 'dec_a1b2c3d4e5f6')
        """
        rel_path = self._to_relative_path(file)
        content = f"{rel_path}::{name}::{line_number}"
        hash_digest = hashlib.sha256(content.encode()).hexdigest()[:12]
        return f"dec_{hash_digest}"

    def _make_attribute_id(
        self, file: str, class_name: str, name: str, line: int
    ) -> str:
        """Create stable hash-based ID for an attribute.

        Args:
            file: File path
            class_name: Name of class owning the attribute
            name: Attribute name
            line: Definition line number

        Returns:
            Hash-based identifier (e.g., 'attr_a1b2c3d4e5f6')
        """
        rel_path = self._to_relative_path(file)
        content = f"{rel_path}::{class_name}::{name}::{line}"
        hash_digest = hashlib.sha256(content.encode()).hexdigest()[:12]
        return f"attr_{hash_digest}"

    def _make_exception_id(self, file: str, name: str, line_number: int) -> str:
        """Create stable hash-based ID for an exception.

        Args:
            file: File path
            name: Exception name
            line_number: Line number where exception is raised/caught

        Returns:
            Hash-based identifier (e.g., 'exc_a1b2c3d4e5f6')
        """
        rel_path = self._to_relative_path(file)
        content = f"{rel_path}::{name}::{line_number}"
        hash_digest = hashlib.sha256(content.encode()).hexdigest()[:12]
        return f"exc_{hash_digest}"

    def _make_module_id(self, name: str) -> str:
        """Create stable hash-based ID for a module.

        Args:
            name: Module name (e.g., 'utils.helpers')

        Returns:
            Hash-based identifier (e.g., 'mod_a1b2c3d4e5f6')
        """
        hash_digest = hashlib.sha256(name.encode()).hexdigest()[:12]
        return f"mod_{hash_digest}"

    # Delegate node operations
    def add_function(self, *args, **kwargs) -> None:
        """Add a function to the graph."""
        return self.node_ops.add_function(*args, **kwargs)

    def add_variable(self, *args, **kwargs) -> None:
        """Add a variable to the graph."""
        return self.node_ops.add_variable(*args, **kwargs)

    def add_class(self, *args, **kwargs) -> None:
        """Add a class to the graph."""
        return self.node_ops.add_class(*args, **kwargs)

    def add_import(self, *args, **kwargs) -> None:
        """Add an import to the graph."""
        return self.node_ops.add_import(*args, **kwargs)

    def add_decorator(self, *args, **kwargs) -> None:
        """Add a decorator to the graph."""
        return self.node_ops.add_decorator(*args, **kwargs)

    def add_attribute(self, *args, **kwargs) -> None:
        """Add an attribute to the graph."""
        return self.node_ops.add_attribute(*args, **kwargs)

    def add_exception(self, *args, **kwargs) -> None:
        """Add an exception to the graph."""
        return self.node_ops.add_exception(*args, **kwargs)

    def add_module(self, *args, **kwargs) -> None:
        """Add a module to the graph."""
        return self.node_ops.add_module(*args, **kwargs)

    def add_file(self, *args, **kwargs) -> None:
        """Add or update file node in database."""
        return self.node_ops.add_file(*args, **kwargs)

    def delete_file_data(self, *args, **kwargs) -> None:
        """Delete all nodes and edges for a file."""
        return self.node_ops.delete_file_data(*args, **kwargs)

    # Delegate edge operations
    def add_call(self, *args, **kwargs) -> None:
        """Add a function call edge."""
        return self.edge_ops.add_call(*args, **kwargs)

    def add_exception_handling(self, *args, **kwargs) -> None:
        """Add exception handling edge (raise or catch)."""
        return self.edge_ops.add_exception_handling(*args, **kwargs)

    def add_attribute_access(self, *args, **kwargs) -> None:
        """Add attribute access edge."""
        return self.edge_ops.add_attribute_access(*args, **kwargs)

    def add_class_dependency(self, *args, **kwargs) -> None:
        """Add class dependency edge (composition, dependency injection)."""
        return self.edge_ops.add_class_dependency(*args, **kwargs)

    def add_variable_usage(self, *args, **kwargs) -> None:
        """Add variable usage edge."""
        return self.edge_ops.add_variable_usage(*args, **kwargs)

    # Delegate query operations
    def get_callers(self, *args, **kwargs) -> List[Tuple[str, str, int]]:
        """Get functions that call the specified function."""
        return self.queries.get_callers(*args, **kwargs)

    def get_callees(self, *args, **kwargs) -> List[Tuple[str, str, int]]:
        """Get functions called by the specified function."""
        return self.queries.get_callees(*args, **kwargs)

    def get_callers_and_callees_with_lines(self, *args, **kwargs):
        """Combined get_callers()+get_callees(), sharing one function-id
        resolution and returning each result's (start_line, end_line) too
        -- see QueryOperations.get_callers_and_callees_with_lines."""
        return self.queries.get_callers_and_callees_with_lines(*args, **kwargs)

    def get_variable_usage(self, *args, **kwargs) -> List[Tuple[str, str, int]]:
        """Get functions that use the specified variable."""
        return self.queries.get_variable_usage(*args, **kwargs)

    def get_function(self, *args, **kwargs) -> Optional[FunctionNode]:
        """Get function node by file and name."""
        return self.queries.get_function(*args, **kwargs)

    def get_all_functions_in_file(self, *args, **kwargs) -> List[FunctionNode]:
        """Get all functions defined in a file."""
        return self.queries.get_all_functions_in_file(*args, **kwargs)

    def get_class(self, *args, **kwargs) -> Optional[ClassNode]:
        """Get class node by file and name."""
        return self.queries.get_class(*args, **kwargs)

    def get_all_classes_in_file(self, *args, **kwargs) -> List[ClassNode]:
        """Get all classes defined in a file."""
        return self.queries.get_all_classes_in_file(*args, **kwargs)

    def get_statistics(self, *args, **kwargs) -> Dict[str, any]:
        """Get statistics about the graph."""
        return self.queries.get_statistics(*args, **kwargs)

    def get_functions_with_multiple_decorators(self, *args, **kwargs) -> List[dict]:
        """Get functions that have multiple decorators applied."""
        return self.queries.get_functions_with_multiple_decorators(*args, **kwargs)

    def build_inheritance_edges(self) -> int:
        """Build INHERITS edges from Class bases field.

        Returns:
            Number of INHERITS edges created
        """
        return self.edge_ops.build_inheritance_edges()

    def get_imports_for_file(self, *args, **kwargs) -> List[ImportNode]:
        """Get all imports in a file."""
        return self.queries.get_imports_for_file(*args, **kwargs)

    def get_decorators_for_function(self, *args, **kwargs) -> List[DecoratorNode]:
        """Get all decorators applied to a function."""
        return self.queries.get_decorators_for_function(*args, **kwargs)

    def get_attributes_for_class(self, *args, **kwargs) -> List[AttributeNode]:
        """Get all attributes of a class."""
        return self.queries.get_attributes_for_class(*args, **kwargs)

    def get_functions_raising_exception(self, *args, **kwargs) -> List[Tuple[str, str]]:
        """Get all functions that raise a specific exception."""
        return self.queries.get_functions_raising_exception(*args, **kwargs)

    def get_module_hierarchy(self, *args, **kwargs) -> List[ModuleNode]:
        """Get all modules in the project."""
        return self.queries.get_module_hierarchy(*args, **kwargs)

    def find_import_usages(self, *args, **kwargs) -> List[Tuple[str, int]]:
        """Find which files import a specific function or class."""
        return self.queries.find_import_usages(*args, **kwargs)

    def find_attribute_modifiers(self, *args, **kwargs) -> List[Tuple[str, str, int]]:
        """Find functions that modify a specific attribute."""
        return self.queries.find_attribute_modifiers(*args, **kwargs)

    def file_exists(self, *args, **kwargs) -> bool:
        """Check if file with this hash exists in database."""
        return self.queries.file_exists(*args, **kwargs)

    # Utility methods
    def clear_all(self) -> None:
        """Clear all data from the database.

        Raises:
            RuntimeError: If database is in read-only mode
        """
        self._check_read_only()
        try:
            self.backend.clear_all()
        except Exception as e:
            console.print(f"[red]Error clearing database: {e}[/red]")

    def load_from_parquet(self, parquet_dir: Path) -> dict:
        """Load graph data from Parquet files using COPY FROM.

        This is 23x faster and uses 99% less memory than old batch operations.

        Args:
            parquet_dir: Directory containing nodes/ and edges/ Parquet files

        Returns:
            Statistics dict:
            {
                'total_nodes': int,
                'total_edges': int,
                'total_time': float,
                'node_times': Dict[str, Tuple[float, int]],
                'edge_times': Dict[str, Tuple[float, int]]
            }

        Raises:
            RuntimeError: If database is in read-only mode

        Example:
            >>> graph = DependencyGraph()
            >>> stats = graph.load_from_parquet(Path('.code-explorer/parquet'))
            >>> print(f"Loaded {stats['total_nodes']} nodes in {stats['total_time']:.2f}s")
        """
        self._check_read_only()

        from code_explorer.graph.bulk_loader import load_from_parquet_sync

        return load_from_parquet_sync(self.db_path, parquet_dir)

    def _export_results_to_parquet(
        self,
        results: List,
        output_dir: Path,
        resolved_calls: Optional[List[dict]] = None
    ) -> None:
        """Internal helper to export FileAnalysis results to Parquet.

        Args:
            results: List of FileAnalysis objects
            output_dir: Directory to write Parquet files
            resolved_calls: Optional resolved CALLS edges from CallResolver
        """
        from code_explorer.analyzer.export_parquet import export_to_parquet

        export_to_parquet(results, output_dir, self.project_root, resolved_calls)

    def ingest_results(
        self,
        results: List,
        resolved_calls: Optional[List[dict]] = None,
        include_source: bool = False,
        on_node_progress: Optional[Callable[[], None]] = None,
        on_edge_progress: Optional[Callable[[], None]] = None,
        assume_new: bool = False,
    ) -> dict:
        """Ingest FileAnalysis results via the generic NodeRecord/EdgeRecord
        backend interface (backend.upsert_nodes/upsert_edges).

        Works with any CodeGraphBackend, including KuzuBackend, but is
        intended for backends without a bulk-loader equivalent to Kuzu's
        Parquet/COPY-FROM path (see load_from_parquet) -- e.g. LatticeBackend.
        Only covers File, Function, Class nodes and their containment/CALLS
        edges; see graph/ingest.py for the exact scope.

        Args:
            results: List of FileAnalysis objects
            resolved_calls: Optional resolved CALLS edges from CallResolver
            include_source: If True, also store each function/class's full
                source_code as a graph property (opt-in, default off -- see
                graph/ingest.py's file_analyses_to_records for why).
            assume_new: Skip the existing-node lookup during upsert (see
                CodeGraphBackend.upsert_nodes) -- only correct when the
                backend has no pre-existing data for these nodes yet, e.g.
                indexing into a just-created, empty database.

        Returns:
            Statistics dict: {'total_nodes': int, 'total_edges': int}

        Raises:
            RuntimeError: If database is in read-only mode
        """
        self._check_read_only()

        from code_explorer.graph.ingest import file_analyses_to_records

        nodes, edges = file_analyses_to_records(
            results, self.project_root, resolved_calls, include_source=include_source
        )
        node_id_map = self.backend.upsert_nodes(
            nodes, on_progress=on_node_progress, assume_new=assume_new
        )
        self.backend.upsert_edges(
            edges, on_progress=on_edge_progress, node_id_map=node_id_map
        )
        return {"total_nodes": len(nodes), "total_edges": len(edges)}

    def ingest_incremental(self, target: Path) -> dict:
        """Re-index `target` incrementally: hash every current .py file,
        skip ones whose content is unchanged, and for changed/new/deleted
        files, invalidate and update only what's needed (Phase 3 of
        docs/explanation/latticedb-migration.md, "Incremental Updates").

        Unlike ingest_results (which ingests a pre-parsed List[FileAnalysis]
        the caller already has), this does its own file discovery + parsing
        internally, since it needs to decide per-file whether to parse at
        all -- parsing is exactly the cost incremental re-indexing exists to
        avoid for unchanged files.

        CALLS-edge limitation, real and worth knowing, not silently
        papered over: CALLS edges are resolved by function name across the
        whole repo (see analyzer/call_resolver.py -- a plain name join, no
        import resolution), so a changed file's own outgoing calls are
        correctly re-resolved against the full current function set here.
        But if an UNCHANGED file calls into a function that just moved,
        was renamed, or was deleted in a changed file, that unchanged
        file's CALLS edges are not re-examined by this method and can go
        stale until that caller file is also reprocessed (e.g. via a full
        `--reindex`). This is a real gap of per-file incremental updates
        without a full call-graph re-resolution, not a bug to silently
        hide.

        Args:
            target: Directory to re-index (same directory that was
                originally indexed via ingest_results/analyze_directory).

        Returns:
            {'unchanged': int, 'reprocessed': int, 'deleted': int,
            'changed_node_ids': List[int]} -- file counts for the caller to
            report to the user, plus the internal ids of Function/Class
            nodes that were created/updated (for a LatticeBackend caller
            that also maintains a vector index -- e.g. `code-explorer
            search --semantic` -- to re-embed just those nodes via
            backend.build_vector_index(node_ids=...) instead of a full
            rebuild; always [] for KuzuBackend).

        Raises:
            RuntimeError: If database is in read-only mode
        """
        self._check_read_only()

        from code_explorer.analyzer.base_analyzer import (
            CodeAnalyzer,
            discover_python_files,
        )
        from code_explorer.analyzer.export_parquet import to_relative_path
        from code_explorer.graph.ingest import file_analyses_to_records
        from code_explorer.settings import settings

        default_exclude_patterns = settings.default_exclude_patterns
        current_files = {
            to_relative_path(str(py_file), target): py_file
            for py_file in discover_python_files(target, default_exclude_patterns)
        }

        existing_files = {
            row["path"]: row["hash"]
            for row in self.backend.query(
                "MATCH (f:File) RETURN f.path AS path, f.content_hash AS hash"
            )
        }

        deleted = 0
        for rel_path in set(existing_files) - set(current_files):
            self.backend.delete_file(rel_path)
            deleted += 1

        unchanged = 0
        changed_results = []
        for rel_path, abs_path in current_files.items():
            current_hash = self.compute_file_hash(abs_path)
            if existing_files.get(rel_path) == current_hash:
                unchanged += 1
                continue
            if rel_path in existing_files:
                self.backend.delete_file(rel_path)
            changed_results.append(CodeAnalyzer().analyze_file(abs_path))

        changed_node_ids: List[int] = []
        if changed_results:
            nodes, edges = file_analyses_to_records(changed_results, target)
            node_id_map = self.backend.upsert_nodes(nodes, assume_new=True)
            if edges:
                self.backend.upsert_edges(edges, node_id_map=node_id_map)
            # Function/Class ids only -- these are what search_vector actually
            # indexes (see LatticeBackend.SEARCHABLE_TEXT_FIELDS); File ids
            # have no search_text/embedding and would just be wasted Ollama
            # calls if included. Empty for KuzuBackend (upsert_nodes returns
            # {} there -- fine, semantic search is LatticeDB-only anyway).
            changed_node_ids = [
                internal_id
                for (node_type, _canonical_id), internal_id in node_id_map.items()
                if node_type in ("Function", "Class")
            ]

            # Re-resolve CALLS for the changed files' own outgoing calls
            # against the full current function set (now includes the
            # changed files' freshly-upserted functions too) -- see the
            # CALLS-edge limitation note above for what this doesn't cover.
            all_functions = self.backend.query(
                "MATCH (f:Function) RETURN f.name AS name, f.file AS file, "
                "f.start_line AS start_line"
            )
            functions_by_name: Dict[str, List[Tuple[str, int]]] = {}
            for row in all_functions:
                functions_by_name.setdefault(row["name"], []).append(
                    (row["file"], row["start_line"])
                )

            resolved_calls = []
            for result in changed_results:
                rel_file = to_relative_path(result.file_path, target)
                caller_start_lines = {fn.name: fn.start_line for fn in result.functions}
                for call in result.function_calls:
                    caller_start_line = caller_start_lines.get(call.caller_function)
                    if caller_start_line is None:
                        continue
                    for callee_file, callee_start_line in functions_by_name.get(
                        call.called_name, []
                    ):
                        resolved_calls.append(
                            {
                                "caller_file": rel_file,
                                "caller_function": call.caller_function,
                                "caller_start_line": caller_start_line,
                                "callee_file": callee_file,
                                "callee_function": call.called_name,
                                "callee_start_line": callee_start_line,
                                "call_line": call.call_line,
                            }
                        )

            if resolved_calls:
                _, call_edges = file_analyses_to_records(
                    [], target, resolved_calls=resolved_calls
                )
                self.backend.upsert_edges(call_edges)

        return {
            "unchanged": unchanged,
            "reprocessed": len(changed_results),
            "deleted": deleted,
            "changed_node_ids": changed_node_ids,
        }

    def compute_file_hash(self, file_path: Path) -> str:
        """Compute SHA256 hash of file contents.

        Args:
            file_path: Path to file

        Returns:
            Hex digest of file contents
        """
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
