"""
Query operations for the dependency graph.

Extracted from original graph.py lines 1531-2173.

Backend-agnostic (Phase 1 of the LatticeDB migration, see
docs/explanation/latticedb-migration.md): every method here goes through
CodeGraphBackend.query(cypher, params), which returns List[Dict[str, Any]]
(rows keyed by column name/expression) for both KuzuBackend and
LatticeBackend. LatticeDB's Cypher dialect was confirmed compatible with the
existing hand-written queries, with one exception: LatticeDB rejects
unaliased `COUNT(*)` ("Expected expression"), so every aggregate here is
written as `COUNT(<var>) AS <alias>` (works identically on both backends)
instead of Kuzu's `COUNT(*)` / `COUNT_STAR()` convention.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from rich.console import Console

from code_explorer.graph.backend import CodeGraphBackend
from code_explorer.graph.models import (
    AttributeNode,
    ClassNode,
    DecoratorNode,
    FunctionNode,
    ImportNode,
    ModuleNode,
)

console = Console()


class QueryOperations:
    """Handles query operations for the dependency graph."""

    def __init__(
        self,
        backend: CodeGraphBackend,
        project_root: Path,
        helper_methods: dict,
        schema_version: str,
    ):
        """Initialize query operations.

        Args:
            backend: CodeGraphBackend to run Cypher queries against
            project_root: Root directory for relative path calculations
            helper_methods: Dictionary containing helper methods from facade
            schema_version: Schema version ("v1" or "v2")
        """
        self.backend = backend
        self.project_root = project_root
        self.schema_version = schema_version
        self._to_relative_path = helper_methods["to_relative_path"]
        self._make_variable_id = helper_methods["make_variable_id"]

    def _resolve_function_id(self, rel_file: str, function: str) -> Optional[str]:
        """Resolve (file, name) to a single Function id.

        Function is only unique by (file, name, start_line), not (file, name)
        alone -- two distinct functions can share a name in the same file
        (e.g. same-named methods on different classes). Matching CALLS edges
        directly against Function {file, name} would silently conflate their
        callers/callees into one merged (and wrong) result set. Resolving to
        one specific id first (lowest start_line, deterministic) fixes that;
        it doesn't fully disambiguate from the CLI's (file, function) input,
        but it replaces "silently wrong for the ambiguous case" with
        "well-defined for the ambiguous case."
        """
        rows = self.backend.query(
            "MATCH (f:Function {file: $file, name: $name}) "
            "RETURN f.id AS id ORDER BY f.start_line ASC LIMIT 1",
            {"file": rel_file, "name": function},
        )
        return rows[0]["id"] if rows else None

    def get_callers(self, file: str, function: str) -> List[Tuple[str, str, int]]:
        """Get functions that call the specified function.

        Args:
            file: File where function is defined
            function: Function name

        Returns:
            List of (file, function_name, call_line) tuples
        """
        rel_file = self._to_relative_path(file)

        try:
            fn_id = self._resolve_function_id(rel_file, function)
            if fn_id is None:
                return []
            callers, _callees = self.backend.get_call_edges_with_lines(fn_id)
            return [(f, n, call_line) for f, n, call_line, _s, _e in callers]
        except Exception as e:
            console.print(
                f"[red]Error getting callers for {function} in {file}: {e}[/red]"
            )
            return []

    def get_callees(self, file: str, function: str) -> List[Tuple[str, str, int]]:
        """Get functions called by the specified function.

        Args:
            file: File where function is defined
            function: Function name

        Returns:
            List of (file, function_name, call_line) tuples
        """
        rel_file = self._to_relative_path(file)

        try:
            fn_id = self._resolve_function_id(rel_file, function)
            if fn_id is None:
                return []
            _callers, callees = self.backend.get_call_edges_with_lines(fn_id)
            return [(f, n, call_line) for f, n, call_line, _s, _e in callees]
        except Exception as e:
            console.print(
                f"[red]Error getting callees for {function} in {file}: {e}[/red]"
            )
            return []

    def get_callers_and_callees_with_lines(
        self, file: str, function: str
    ) -> Tuple[
        List[Tuple[str, str, int, int, int]], List[Tuple[str, str, int, int, int]]
    ]:
        """Like get_callers()+get_callees() combined, but resolves the
        function id once (shared) instead of twice, and returns each
        caller/callee's (start_line, end_line) directly from the same
        matched node instead of requiring a separate lookup per node.

        Built for context.py's ContextAssembler, which previously issued
        one query per caller/callee just to fetch line ranges -- 23 queries
        measured for one seed with 10 callers + 8 callees (see
        docs/explanation/latticedb-migration.md's Performance Findings).
        Returning start_line/end_line from the already-matched CALLS-edge
        node is also more correct than a fresh (file, name) lookup would
        be: it can't hit the same name-ambiguity class _resolve_function_id
        exists to guard against, since it's the exact node the edge points
        to, not a fresh name-based re-match.

        Returns:
            (callers, callees), each a list of
            (file, name, call_line, start_line, end_line) tuples.
        """
        rel_file = self._to_relative_path(file)
        try:
            fn_id = self._resolve_function_id(rel_file, function)
            if fn_id is None:
                return [], []
            return self.backend.get_call_edges_with_lines(fn_id)
        except Exception as e:
            console.print(
                f"[red]Error getting callers/callees with lines for {function} "
                f"in {file}: {e}[/red]"
            )
            return [], []

    def get_variable_usage(
        self, file: str, var_name: str, definition_line: int
    ) -> List[Tuple[str, str, int]]:
        """Get functions that use the specified variable.

        Args:
            file: File where variable is defined
            var_name: Variable name
            definition_line: Line where variable is defined

        Returns:
            List of (file, function_name, usage_line) tuples
        """
        var_id = self._make_variable_id(file, var_name, definition_line)

        try:
            rows = self.backend.query(
                """
                MATCH (func:Function)-[r:REFERENCES]->(var:Variable {id: $var_id})
                WHERE r.context = 'use'
                RETURN func.file AS file, func.name AS name, r.line_number AS line_number
            """,
                {"var_id": var_id},
            )
            return [(row["file"], row["name"], row["line_number"]) for row in rows]
        except Exception as e:
            console.print(
                f"[red]Error getting variable usage for {var_name} in {file}: {e}[/red]"
            )
            return []

    def get_function(self, file: str, name: str) -> Optional[FunctionNode]:
        """Get function node by file and name.

        Args:
            file: File path
            name: Function name

        Returns:
            FunctionNode if found, None otherwise
        """
        rel_file = self._to_relative_path(file)

        try:
            rows = self.backend.query(
                """
                MATCH (f:Function {file: $file, name: $name})
                RETURN f.name AS name, f.file AS file, f.start_line AS start_line,
                       f.end_line AS end_line, f.is_public AS is_public
            """,
                {"file": rel_file, "name": name},
            )
            if rows:
                row = rows[0]
                return FunctionNode(
                    name=row["name"],
                    file=row["file"],
                    start_line=row["start_line"],
                    end_line=row["end_line"],
                    is_public=row["is_public"],
                )
            return None
        except Exception as e:
            console.print(f"[red]Error getting function {name} in {file}: {e}[/red]")
            return None

    def get_all_functions_in_file(self, file: str) -> List[FunctionNode]:
        """Get all functions defined in a file.

        Args:
            file: File path

        Returns:
            List of FunctionNode objects
        """
        try:
            rows = self.backend.query(
                """
                MATCH (f:Function {file: $file})
                RETURN f.name AS name, f.file AS file, f.start_line AS start_line,
                       f.end_line AS end_line, f.is_public AS is_public
            """,
                {"file": file},
            )
            return [
                FunctionNode(
                    name=row["name"],
                    file=row["file"],
                    start_line=row["start_line"],
                    end_line=row["end_line"],
                    is_public=row["is_public"],
                )
                for row in rows
            ]
        except Exception as e:
            console.print(f"[red]Error getting functions in file {file}: {e}[/red]")
            return []

    def get_class(self, file: str, name: str) -> Optional[ClassNode]:
        """Get class node by file and name.

        Args:
            file: File path
            name: Class name

        Returns:
            ClassNode if found, None otherwise
        """
        rel_file = self._to_relative_path(file)

        try:
            rows = self.backend.query(
                """
                MATCH (c:Class {file: $file, name: $name})
                RETURN c.name AS name, c.file AS file, c.start_line AS start_line,
                       c.end_line AS end_line, c.bases AS bases, c.is_public AS is_public
            """,
                {"file": rel_file, "name": name},
            )
            if rows:
                row = rows[0]
                bases = json.loads(row["bases"]) if row["bases"] else []
                return ClassNode(
                    name=row["name"],
                    file=row["file"],
                    start_line=row["start_line"],
                    end_line=row["end_line"],
                    bases=bases,
                    is_public=row["is_public"],
                )
            return None
        except Exception as e:
            console.print(f"[red]Error getting class {name} in {file}: {e}[/red]")
            return None

    def get_all_classes_in_file(self, file: str) -> List[ClassNode]:
        """Get all classes defined in a file.

        Args:
            file: File path

        Returns:
            List of ClassNode objects
        """
        try:
            rows = self.backend.query(
                """
                MATCH (c:Class {file: $file})
                RETURN c.name AS name, c.file AS file, c.start_line AS start_line,
                       c.end_line AS end_line, c.bases AS bases, c.is_public AS is_public
            """,
                {"file": file},
            )
            classes = []
            for row in rows:
                bases = json.loads(row["bases"]) if row["bases"] else []
                classes.append(
                    ClassNode(
                        name=row["name"],
                        file=row["file"],
                        start_line=row["start_line"],
                        end_line=row["end_line"],
                        bases=bases,
                        is_public=row["is_public"],
                    )
                )
            return classes
        except Exception as e:
            console.print(f"[red]Error getting classes in file {file}: {e}[/red]")
            return []

    def get_functions_with_multiple_decorators(self) -> List[dict]:
        """Get functions that have multiple decorators applied.

        Returns:
            List of dicts with: name, file, decorator_count, decorators (list of decorator names)
        """
        try:
            rows = self.backend.query(
                """
                MATCH (func:Function)-[:DECORATED_BY]->(dec:Decorator)
                WITH func, COUNT(dec) as decorator_count, COLLECT(dec.name) as decorators
                WHERE decorator_count > 1
                RETURN
                    func.name as function_name,
                    func.file as file_path,
                    decorator_count,
                    decorators
                ORDER BY decorator_count DESC
            """
            )
            return [
                {
                    "name": row["function_name"],
                    "file": row["file_path"],
                    "decorator_count": row["decorator_count"],
                    "decorators": row["decorators"],
                }
                for row in rows
            ]
        except Exception as e:
            console.print(f"[red]Error getting functions with multiple decorators: {e}[/red]")
            return []

    def _count(self, label: str, var: str = "n") -> int:
        """Count nodes of a label. COUNT(*) is unaliasable and unsupported by
        LatticeDB, so this always counts a bound variable with an alias."""
        rows = self.backend.query(f"MATCH ({var}:{label}) RETURN COUNT({var}) AS count")
        return rows[0]["count"] if rows else 0

    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics about the graph.

        Returns:
            Dictionary with graph statistics
        """
        try:
            total_files = self._count("File", "f")
            total_functions = self._count("Function", "f")
            total_classes = self._count("Class", "c")
            total_variables = self._count("Variable", "v")

            # Count imports (only if v2 schema)
            total_imports = 0
            if self.schema_version == "v2":
                try:
                    total_imports = self._count("Import", "i")
                except Exception:
                    pass

            # Count decorators (only if v2 schema)
            total_decorators = 0
            if self.schema_version == "v2":
                try:
                    total_decorators = self._count("Decorator", "d")
                except Exception:
                    pass

            # Count attributes (only if v2 schema)
            total_attributes = 0
            if self.schema_version == "v2":
                try:
                    total_attributes = self._count("Attribute", "a")
                except Exception:
                    pass

            # Count exceptions (only if v2 schema)
            total_exceptions = 0
            if self.schema_version == "v2":
                try:
                    total_exceptions = self._count("Exception", "e")
                except Exception:
                    pass

            # Count modules (only if v2 schema)
            total_modules = 0
            if self.schema_version == "v2":
                try:
                    total_modules = self._count("Module", "m")
                except Exception:
                    pass

            # Count all relationship types
            edge_stats = {}
            edge_types = [
                "CONTAINS_FUNCTION",
                "CONTAINS_CLASS",
                "CONTAINS_VARIABLE",
                "METHOD_OF",
                "HAS_IMPORT",
                "HAS_ATTRIBUTE",
                "DECORATED_BY",
                "REFERENCES",
                "ACCESSES",
                "HANDLES_EXCEPTION",
                "CALLS",
                "INHERITS",
            ]

            total_edges = 0
            for edge_type in edge_types:
                try:
                    rows = self.backend.query(
                        f"MATCH ()-[r:{edge_type}]->() RETURN COUNT(r) AS count"
                    )
                    count = rows[0]["count"] if rows else 0
                    edge_stats[edge_type] = count
                    total_edges += count
                except Exception:
                    edge_stats[edge_type] = 0

            # Get most-called functions -- backend.get_most_called_functions()
            # instead of raw Cypher: on LatticeDB, this global aggregation
            # measured 23.9s via Cypher vs 1.25s via the imperative API on a
            # real 338K-edge graph (see CodeGraphBackend's docstring).
            most_called = [
                {"name": name, "file": file, "call_count": call_count}
                for name, file, call_count in self.backend.get_most_called_functions(limit=20)
            ]

            return {
                "total_files": total_files,
                "total_functions": total_functions,
                "total_classes": total_classes,
                "total_variables": total_variables,
                "total_imports": total_imports,
                "total_decorators": total_decorators,
                "total_attributes": total_attributes,
                "total_exceptions": total_exceptions,
                "total_modules": total_modules,
                "total_edges": total_edges,
                "edge_stats": edge_stats,
                "function_calls": edge_stats.get("CALLS", 0),
                "most_called_functions": most_called,
                "schema_version": self.schema_version,
            }
        except Exception as e:
            console.print(f"[red]Error getting statistics: {e}[/red]")
            return {
                "total_files": 0,
                "total_functions": 0,
                "total_classes": 0,
                "total_variables": 0,
                "total_imports": 0,
                "total_decorators": 0,
                "total_attributes": 0,
                "total_exceptions": 0,
                "total_modules": 0,
                "total_edges": 0,
                "edge_stats": {
                    "CONTAINS_FUNCTION": 0,
                    "CONTAINS_CLASS": 0,
                    "CONTAINS_VARIABLE": 0,
                    "METHOD_OF": 0,
                    "HAS_IMPORT": 0,
                    "HAS_ATTRIBUTE": 0,
                    "DECORATED_BY": 0,
                    "REFERENCES": 0,
                    "ACCESSES": 0,
                    "HANDLES_EXCEPTION": 0,
                    "CALLS": 0,
                    "INHERITS": 0,
                },
                "function_calls": 0,
                "most_called_functions": [],
                "schema_version": self.schema_version,
            }

    def get_imports_for_file(self, file_path: str) -> List[ImportNode]:
        """Get all imports in a file.

        Args:
            file_path: Path to file

        Returns:
            List of ImportNode objects
        """
        rel_file = self._to_relative_path(file_path)

        try:
            rows = self.backend.query(
                """
                MATCH (f:File {path: $file})-[:HAS_IMPORT]->(i:Import)
                RETURN i.imported_name AS imported_name, i.import_type AS import_type,
                       i.alias AS alias, i.line_number AS line_number,
                       i.is_relative AS is_relative, i.file AS file
            """,
                {"file": rel_file},
            )
            return [
                ImportNode(
                    imported_name=row["imported_name"],
                    import_type=row["import_type"],
                    alias=row["alias"] if row["alias"] else None,
                    line_number=row["line_number"],
                    is_relative=row["is_relative"],
                    file=row["file"],
                )
                for row in rows
            ]
        except Exception as e:
            console.print(f"[red]Error getting imports for file {file_path}: {e}[/red]")
            return []

    def get_decorators_for_function(
        self, file: str, function_name: str
    ) -> List[DecoratorNode]:
        """Get all decorators applied to a function.

        Args:
            file: File path where function is defined
            function_name: Function name

        Returns:
            List of DecoratorNode objects
        """
        rel_file = self._to_relative_path(file)

        try:
            rows = self.backend.query(
                """
                MATCH (f:Function {file: $file, name: $name})-[:DECORATED_BY]->(d:Decorator)
                RETURN d.name AS name, d.file AS file, d.line_number AS line_number,
                       d.arguments AS arguments
            """,
                {"file": rel_file, "name": function_name},
            )
            return [
                DecoratorNode(
                    name=row["name"],
                    file=row["file"],
                    line_number=row["line_number"],
                    arguments=row["arguments"],
                )
                for row in rows
            ]
        except Exception as e:
            console.print(
                f"[red]Error getting decorators for function {function_name} in {file}: {e}[/red]"
            )
            return []

    def get_attributes_for_class(
        self, file: str, class_name: str
    ) -> List[AttributeNode]:
        """Get all attributes of a class.

        Args:
            file: File path where class is defined
            class_name: Class name

        Returns:
            List of AttributeNode objects
        """
        rel_file = self._to_relative_path(file)

        try:
            rows = self.backend.query(
                """
                MATCH (c:Class {file: $file, name: $name})-[:HAS_ATTRIBUTE]->(a:Attribute)
                RETURN a.name AS name, a.class_name AS class_name, a.file AS file,
                       a.definition_line AS definition_line, a.type_hint AS type_hint,
                       a.is_class_attribute AS is_class_attribute
            """,
                {"file": rel_file, "name": class_name},
            )
            return [
                AttributeNode(
                    name=row["name"],
                    class_name=row["class_name"],
                    file=row["file"],
                    definition_line=row["definition_line"],
                    type_hint=row["type_hint"] if row["type_hint"] else None,
                    is_class_attribute=row["is_class_attribute"],
                )
                for row in rows
            ]
        except Exception as e:
            console.print(
                f"[red]Error getting attributes for class {class_name} in {file}: {e}[/red]"
            )
            return []

    def get_functions_raising_exception(
        self, exception_name: str
    ) -> List[Tuple[str, str]]:
        """Get all functions that raise a specific exception.

        Args:
            exception_name: Name of exception

        Returns:
            List of (file, function_name) tuples
        """
        try:
            rows = self.backend.query(
                """
                MATCH (f:Function)-[h:HANDLES_EXCEPTION]->(e:Exception {name: $exc_name})
                WHERE h.context = 'raise'
                RETURN DISTINCT f.file AS file, f.name AS name
            """,
                {"exc_name": exception_name},
            )
            return [(row["file"], row["name"]) for row in rows]
        except Exception as e:
            console.print(
                f"[red]Error getting functions raising {exception_name}: {e}[/red]"
            )
            return []

    def get_module_hierarchy(self) -> List[ModuleNode]:
        """Get all modules in the project.

        Returns:
            List of ModuleNode objects
        """
        try:
            rows = self.backend.query(
                """
                MATCH (m:Module)
                RETURN m.name AS name, m.path AS path, m.is_package AS is_package,
                       m.docstring AS docstring
            """
            )
            return [
                ModuleNode(
                    name=row["name"],
                    path=row["path"],
                    is_package=row["is_package"],
                    docstring=row["docstring"] if row["docstring"] else None,
                )
                for row in rows
            ]
        except Exception as e:
            console.print(f"[red]Error getting module hierarchy: {e}[/red]")
            return []

    def find_import_usages(self, function_or_class_name: str) -> List[Tuple[str, int]]:
        """Find which files import a specific function or class.

        Args:
            function_or_class_name: Name of function or class

        Returns:
            List of (file, line_number) tuples
        """
        try:
            rows = self.backend.query(
                """
                MATCH (i:Import {imported_name: $name})
                RETURN i.file AS file, i.line_number AS line_number
            """,
                {"name": function_or_class_name},
            )
            return [(row["file"], row["line_number"]) for row in rows]
        except Exception as e:
            console.print(
                f"[red]Error finding import usages for {function_or_class_name}: {e}[/red]"
            )
            return []

    def find_attribute_modifiers(
        self, class_name: str, attribute_name: str
    ) -> List[Tuple[str, str, int]]:
        """Find functions that modify a specific attribute.

        Args:
            class_name: Name of class owning the attribute
            attribute_name: Name of attribute

        Returns:
            List of (file, function_name, line_number) tuples
        """
        try:
            rows = self.backend.query(
                """
                MATCH (f:Function)-[a:ACCESSES]->(attr:Attribute {class_name: $class_name, name: $attr_name})
                WHERE a.access_type IN ['write', 'read_write']
                RETURN f.file AS file, f.name AS name, a.line_number AS line_number
            """,
                {"class_name": class_name, "attr_name": attribute_name},
            )
            return [(row["file"], row["name"], row["line_number"]) for row in rows]
        except Exception as e:
            console.print(
                f"[red]Error finding modifiers for {class_name}.{attribute_name}: {e}[/red]"
            )
            return []

    def file_exists(self, file_path: str, content_hash: str) -> bool:
        """Check if file with this hash exists in database.

        Args:
            file_path: Path to file
            content_hash: Hash of file contents

        Returns:
            True if file exists with same hash, False otherwise
        """
        try:
            rows = self.backend.query(
                """
                MATCH (f:File {path: $path})
                RETURN f.content_hash AS content_hash
            """,
                {"path": file_path},
            )
            if rows:
                return rows[0]["content_hash"] == content_hash
            return False
        except Exception as e:
            console.print(f"[red]Error checking file existence: {e}[/red]")
            return False
