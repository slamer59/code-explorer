"""
Query operations for the dependency graph.

Extracted from original graph.py lines 1531-2173.
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import kuzu
from rich.console import Console

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
        conn: kuzu.Connection,
        project_root: Path,
        helper_methods: dict,
        schema_version: str,
    ):
        """Initialize query operations.

        Args:
            conn: KuzuDB connection to use for operations
            project_root: Root directory for relative path calculations
            helper_methods: Dictionary containing helper methods from facade
            schema_version: Schema version ("v1" or "v2")
        """
        self.conn = conn
        self.project_root = project_root
        self.schema_version = schema_version
        self._to_relative_path = helper_methods["to_relative_path"]
        self._make_variable_id = helper_methods["make_variable_id"]

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
            result = self.conn.execute(
                """
                MATCH (caller:Function)-[c:CALLS]->(callee:Function {file: $file, name: $name})
                RETURN caller.file, caller.name, c.call_line
            """,
                {"file": rel_file, "name": function},
            )

            callers = []
            while result.has_next():
                row = result.get_next()
                callers.append((row[0], row[1], row[2]))

            return callers
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
            result = self.conn.execute(
                """
                MATCH (caller:Function {file: $file, name: $name})-[c:CALLS]->(callee:Function)
                RETURN callee.file, callee.name, c.call_line
            """,
                {"file": rel_file, "name": function},
            )

            callees = []
            while result.has_next():
                row = result.get_next()
                callees.append((row[0], row[1], row[2]))

            return callees
        except Exception as e:
            console.print(
                f"[red]Error getting callees for {function} in {file}: {e}[/red]"
            )
            return []

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
            result = self.conn.execute(
                """
                MATCH (func:Function)-[r:REFERENCES]->(var:Variable {id: $var_id})
                WHERE r.context = 'use'
                RETURN func.file, func.name, r.line_number
            """,
                {"var_id": var_id},
            )

            usages = []
            while result.has_next():
                row = result.get_next()
                usages.append((row[0], row[1], row[2]))

            return usages
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
            result = self.conn.execute(
                """
                MATCH (f:Function {file: $file, name: $name})
                RETURN f.name, f.file, f.start_line, f.end_line, f.is_public
            """,
                {"file": rel_file, "name": name},
            )

            if result.has_next():
                row = result.get_next()
                return FunctionNode(
                    name=row[0],
                    file=row[1],
                    start_line=row[2],
                    end_line=row[3],
                    is_public=row[4],
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
            result = self.conn.execute(
                """
                MATCH (f:Function {file: $file})
                RETURN f.name, f.file, f.start_line, f.end_line, f.is_public
            """,
                {"file": file},
            )

            functions = []
            while result.has_next():
                row = result.get_next()
                functions.append(
                    FunctionNode(
                        name=row[0],
                        file=row[1],
                        start_line=row[2],
                        end_line=row[3],
                        is_public=row[4],
                    )
                )

            return functions
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
            result = self.conn.execute(
                """
                MATCH (c:Class {file: $file, name: $name})
                RETURN c.name, c.file, c.start_line, c.end_line, c.bases, c.is_public
            """,
                {"file": rel_file, "name": name},
            )

            if result.has_next():
                row = result.get_next()
                bases = json.loads(row[4]) if row[4] else []
                return ClassNode(
                    name=row[0],
                    file=row[1],
                    start_line=row[2],
                    end_line=row[3],
                    bases=bases,
                    is_public=row[5],
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
            result = self.conn.execute(
                """
                MATCH (c:Class {file: $file})
                RETURN c.name, c.file, c.start_line, c.end_line, c.bases, c.is_public
            """,
                {"file": file},
            )

            classes = []
            while result.has_next():
                row = result.get_next()
                bases = json.loads(row[4]) if row[4] else []
                classes.append(
                    ClassNode(
                        name=row[0],
                        file=row[1],
                        start_line=row[2],
                        end_line=row[3],
                        bases=bases,
                        is_public=row[5],
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
            result = self.conn.execute("""
                MATCH (func:Function)-[:DECORATED_BY]->(dec:Decorator)
                WITH func, COUNT(*) as decorator_count, COLLECT(dec.name) as decorators
                WHERE decorator_count > 1
                RETURN
                    func.name as function_name,
                    func.file as file_path,
                    decorator_count,
                    decorators
                ORDER BY decorator_count DESC
            """)

            functions = []
            while result.has_next():
                row = result.get_next()
                functions.append({
                    "name": row[0],
                    "file": row[1],
                    "decorator_count": row[2],
                    "decorators": row[3],
                })

            return functions
        except Exception as e:
            console.print(f"[red]Error getting functions with multiple decorators: {e}[/red]")
            return []

    def get_statistics(self) -> Dict[str, any]:
        """Get statistics about the graph.

        Returns:
            Dictionary with graph statistics
        """
        try:
            # Count files
            result = self.conn.execute("MATCH (f:File) RETURN COUNT(*)")
            total_files = result.get_next()[0] if result.has_next() else 0

            # Count functions
            result = self.conn.execute("MATCH (f:Function) RETURN COUNT(*)")
            total_functions = result.get_next()[0] if result.has_next() else 0

            # Count classes
            result = self.conn.execute("MATCH (c:Class) RETURN COUNT(*)")
            total_classes = result.get_next()[0] if result.has_next() else 0

            # Count variables
            result = self.conn.execute("MATCH (v:Variable) RETURN COUNT(*)")
            total_variables = result.get_next()[0] if result.has_next() else 0

            # Count imports (only if v2 schema)
            total_imports = 0
            if self.schema_version == "v2":
                try:
                    result = self.conn.execute("MATCH (i:Import) RETURN COUNT(*)")
                    total_imports = result.get_next()[0] if result.has_next() else 0
                except Exception:
                    pass

            # Count decorators (only if v2 schema)
            total_decorators = 0
            if self.schema_version == "v2":
                try:
                    result = self.conn.execute("MATCH (d:Decorator) RETURN COUNT(*)")
                    total_decorators = result.get_next()[0] if result.has_next() else 0
                except Exception:
                    pass

            # Count attributes (only if v2 schema)
            total_attributes = 0
            if self.schema_version == "v2":
                try:
                    result = self.conn.execute("MATCH (a:Attribute) RETURN COUNT(*)")
                    total_attributes = result.get_next()[0] if result.has_next() else 0
                except Exception:
                    pass

            # Count exceptions (only if v2 schema)
            total_exceptions = 0
            if self.schema_version == "v2":
                try:
                    result = self.conn.execute("MATCH (e:Exception) RETURN COUNT(*)")
                    total_exceptions = result.get_next()[0] if result.has_next() else 0
                except Exception:
                    pass

            # Count modules (only if v2 schema)
            total_modules = 0
            if self.schema_version == "v2":
                try:
                    result = self.conn.execute("MATCH (m:Module) RETURN COUNT(*)")
                    total_modules = result.get_next()[0] if result.has_next() else 0
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
                    result = self.conn.execute(f"MATCH ()-[r:{edge_type}]->() RETURN COUNT(*)")
                    count = result.get_next()[0] if result.has_next() else 0
                    edge_stats[edge_type] = count
                    total_edges += count
                except Exception:
                    edge_stats[edge_type] = 0

            # Get most-called functions
            result = self.conn.execute("""
                MATCH (caller:Function)-[:CALLS]->(callee:Function)
                RETURN callee.name, callee.file, COUNT(*) as call_count
                ORDER BY call_count DESC
                LIMIT 20
            """)

            most_called = []
            while result.has_next():
                row = result.get_next()
                most_called.append(
                    {"name": row[0], "file": row[1], "call_count": row[2]}
                )

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
            result = self.conn.execute(
                """
                MATCH (f:File {path: $file})-[:HAS_IMPORT]->(i:Import)
                RETURN i.imported_name, i.import_type, i.alias, i.line_number, i.is_relative, i.file
            """,
                {"file": rel_file},
            )

            imports = []
            while result.has_next():
                row = result.get_next()
                imports.append(
                    ImportNode(
                        imported_name=row[0],
                        import_type=row[1],
                        alias=row[2] if row[2] else None,
                        line_number=row[3],
                        is_relative=row[4],
                        file=row[5],
                    )
                )

            return imports
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
            result = self.conn.execute(
                """
                MATCH (f:Function {file: $file, name: $name})-[:DECORATED_BY]->(d:Decorator)
                RETURN d.name, d.file, d.line_number, d.arguments
            """,
                {"file": rel_file, "name": function_name},
            )

            decorators = []
            while result.has_next():
                row = result.get_next()
                decorators.append(
                    DecoratorNode(
                        name=row[0], file=row[1], line_number=row[2], arguments=row[3]
                    )
                )

            return decorators
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
            result = self.conn.execute(
                """
                MATCH (c:Class {file: $file, name: $name})-[:HAS_ATTRIBUTE]->(a:Attribute)
                RETURN a.name, a.class_name, a.file, a.definition_line, a.type_hint, a.is_class_attribute
            """,
                {"file": rel_file, "name": class_name},
            )

            attributes = []
            while result.has_next():
                row = result.get_next()
                attributes.append(
                    AttributeNode(
                        name=row[0],
                        class_name=row[1],
                        file=row[2],
                        definition_line=row[3],
                        type_hint=row[4] if row[4] else None,
                        is_class_attribute=row[5],
                    )
                )

            return attributes
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
            result = self.conn.execute(
                """
                MATCH (f:Function)-[h:HANDLES_EXCEPTION]->(e:Exception {name: $exc_name})
                WHERE h.context = 'raise'
                RETURN DISTINCT f.file, f.name
            """,
                {"exc_name": exception_name},
            )

            functions = []
            while result.has_next():
                row = result.get_next()
                functions.append((row[0], row[1]))

            return functions
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
            result = self.conn.execute("""
                MATCH (m:Module)
                RETURN m.name, m.path, m.is_package, m.docstring
            """)

            modules = []
            while result.has_next():
                row = result.get_next()
                modules.append(
                    ModuleNode(
                        name=row[0],
                        path=row[1],
                        is_package=row[2],
                        docstring=row[3] if row[3] else None,
                    )
                )

            return modules
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
            result = self.conn.execute(
                """
                MATCH (i:Import {imported_name: $name})
                RETURN i.file, i.line_number
            """,
                {"name": function_or_class_name},
            )

            usages = []
            while result.has_next():
                row = result.get_next()
                usages.append((row[0], row[1]))

            return usages
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
            result = self.conn.execute(
                """
                MATCH (f:Function)-[a:ACCESSES]->(attr:Attribute {class_name: $class_name, name: $attr_name})
                WHERE a.access_type IN ['write', 'read_write']
                RETURN f.file, f.name, a.line_number
            """,
                {"class_name": class_name, "attr_name": attribute_name},
            )

            modifiers = []
            while result.has_next():
                row = result.get_next()
                modifiers.append((row[0], row[1], row[2]))

            return modifiers
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
            result = self.conn.execute(
                """
                MATCH (f:File {path: $path})
                RETURN f.content_hash
            """,
                {"path": file_path},
            )

            if result.has_next():
                row = result.get_next()
                return row[0] == content_hash
            return False
        except Exception as e:
            console.print(f"[red]Error checking file existence: {e}[/red]")
            return False
