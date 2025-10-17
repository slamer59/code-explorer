"""
Main facade for the dependency graph.

Delegates to specialized operation classes while maintaining backward compatibility.
"""

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import kuzu
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
from code_explorer.graph.schema import SchemaManager
from code_explorer.graph.node_operations import NodeOperations
from code_explorer.graph.edge_operations import EdgeOperations
from code_explorer.graph.queries import QueryOperations

console = Console()


class DependencyGraph:
    """KuzuDB-backed dependency graph with persistent storage.

    Stores functions, variables, and their relationships in a property graph
    database that persists to disk. Supports incremental updates and efficient queries.
    """

    def __init__(
        self,
        db_path: Optional[Path] = None,
        read_only: bool = False,
        project_root: Optional[Path] = None,
    ):
        """Initialize KuzuDB connection and create schema if needed.

        Args:
            db_path: Path to KuzuDB database directory.
                    Defaults to .code-explorer/graph.db
            read_only: If True, opens database in read-only mode for safe parallel
                      reads without risk of accidental writes. Default is False.
                      In read-only mode, schema creation is skipped and all write
                      methods will raise exceptions if called.
            project_root: Root directory for relative paths. Defaults to current working directory.
        """
        if db_path is None:
            db_path = Path.cwd() / ".code-explorer" / "graph.db"

        # Ensure parent directory exists (only in read-write mode)
        if not read_only:
            db_path.parent.mkdir(parents=True, exist_ok=True)

        self.db_path = db_path
        self.read_only = read_only
        self.project_root = project_root if project_root else Path.cwd()
        self.db = kuzu.Database(str(db_path), read_only=read_only)
        self.conn = kuzu.Connection(self.db)

        # Create schema manager and initialize schema
        self.schema_manager = SchemaManager(self.conn)

        # Create schema if tables don't exist (only in read-write mode)
        if not self.read_only:
            self.schema_manager.create_schema()

        # Detect schema version (after schema creation)
        self.schema_version = self.schema_manager.detect_schema_version()

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
            self.conn, self.project_root, helper_methods, self.schema_version
        )
        # Batch operations will be initialized when needed to avoid pandas import overhead

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
            # Delete all edges first
            self.conn.execute("MATCH ()-[r:CALLS]->() DELETE r")
            self.conn.execute("MATCH ()-[r:REFERENCES]->() DELETE r")
            self.conn.execute("MATCH ()-[r:CONTAINS_FUNCTION]->() DELETE r")
            self.conn.execute("MATCH ()-[r:CONTAINS_CLASS]->() DELETE r")
            self.conn.execute("MATCH ()-[r:CONTAINS_VARIABLE]->() DELETE r")
            self.conn.execute("MATCH ()-[r:IMPORTS]->() DELETE r")
            self.conn.execute("MATCH ()-[r:INHERITS]->() DELETE r")
            self.conn.execute("MATCH ()-[r:DEPENDS_ON]->() DELETE r")
            self.conn.execute("MATCH ()-[r:METHOD_OF]->() DELETE r")

            # Delete new edges (v2 schema)
            if self.schema_version == "v2":
                try:
                    self.conn.execute("MATCH ()-[r:HAS_IMPORT]->() DELETE r")
                    self.conn.execute("MATCH ()-[r:IMPORTS_FROM]->() DELETE r")
                    self.conn.execute("MATCH ()-[r:DECORATED_BY]->() DELETE r")
                    self.conn.execute("MATCH ()-[r:HAS_ATTRIBUTE]->() DELETE r")
                    self.conn.execute("MATCH ()-[r:ACCESSES]->() DELETE r")
                    self.conn.execute("MATCH ()-[r:HANDLES_EXCEPTION]->() DELETE r")
                    self.conn.execute("MATCH ()-[r:CONTAINS_MODULE]->() DELETE r")
                    self.conn.execute("MATCH ()-[r:MODULE_OF]->() DELETE r")
                except Exception:
                    pass

            # Delete all nodes
            self.conn.execute("MATCH (f:Function) DELETE f")
            self.conn.execute("MATCH (c:Class) DELETE c")
            self.conn.execute("MATCH (v:Variable) DELETE v")
            self.conn.execute("MATCH (f:File) DELETE f")

            # Delete new nodes (v2 schema)
            if self.schema_version == "v2":
                try:
                    self.conn.execute("MATCH (i:Import) DELETE i")
                    self.conn.execute("MATCH (d:Decorator) DELETE i")
                    self.conn.execute("MATCH (a:Attribute) DELETE a")
                    self.conn.execute("MATCH (e:Exception) DELETE e")
                    self.conn.execute("MATCH (m:Module) DELETE m")
                except Exception:
                    pass

        except Exception as e:
            console.print(f"[red]Error clearing database: {e}[/red]")

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

    # Batch operations - lazy import to avoid pandas overhead
    def batch_add_all_from_results(self, results, chunk_size: int = None) -> None:
        """Batch add all nodes from multiple FileAnalysis results AT ONCE.

        This MUST process ALL files in a single batch operation.
        Chunking causes segmentation faults with KuzuDB!

        Args:
            results: List of FileAnalysis objects
            chunk_size: Ignored (kept for API compatibility)

        Raises:
            RuntimeError: If database is in read-only mode
        """
        self._check_read_only()
        # Lazy import batch operations
        from code_explorer.graph.batch_operations import BatchOperations

        if not hasattr(self, '_batch_ops'):
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
            self._batch_ops = BatchOperations(
                self.conn, self.read_only, self.project_root, helper_methods,
                db_path=self.db_path, db=self.db
            )

        return self._batch_ops.batch_add_all_from_results(results, chunk_size)

    def batch_add_all_edges_from_results(self, results, chunk_size: int = None) -> None:
        """Batch add all edges from FileAnalysis results AT ONCE.

        This MUST process ALL files in a single batch operation.
        Chunking causes segmentation faults with KuzuDB!
        Must be called AFTER batch_add_all_from_results().

        Args:
            results: List of FileAnalysis objects
            chunk_size: Ignored (kept for API compatibility)

        Raises:
            RuntimeError: If database is in read-only mode
        """
        self._check_read_only()
        # Lazy import batch operations
        from code_explorer.graph.batch_operations import BatchOperations

        if not hasattr(self, '_batch_ops'):
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
            self._batch_ops = BatchOperations(
                self.conn, self.read_only, self.project_root, helper_methods,
                db_path=self.db_path, db=self.db
            )

        return self._batch_ops.batch_add_all_edges_from_results(results, chunk_size)

    def batch_insert_call_edges(self, all_matched_calls, chunk_size: int = 1000) -> None:
        """Batch insert function call edges in chunks.

        Args:
            all_matched_calls: List of dicts with call edge data
            chunk_size: Number of edges per chunk (default: 1000)

        Raises:
            RuntimeError: If database is in read-only mode
        """
        self._check_read_only()
        # Lazy import batch operations
        from code_explorer.graph.batch_operations import BatchOperations

        if not hasattr(self, '_batch_ops'):
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
            self._batch_ops = BatchOperations(
                self.conn, self.read_only, self.project_root, helper_methods,
                db_path=self.db_path, db=self.db
            )

        return self._batch_ops.batch_insert_call_edges(all_matched_calls, chunk_size)
