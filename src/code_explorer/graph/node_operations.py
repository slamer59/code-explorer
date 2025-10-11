"""
Node CRUD operations for the dependency graph.

Extracted from original graph.py lines 579-1278 and 2175-2318.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import kuzu
from rich.console import Console

console = Console()


class NodeOperations:
    """Handles CRUD operations for all node types in the dependency graph."""

    def __init__(
        self,
        conn: kuzu.Connection,
        read_only: bool,
        project_root: Path,
        helper_methods: dict,
    ):
        """Initialize node operations.

        Args:
            conn: KuzuDB connection to use for operations
            read_only: Whether database is in read-only mode
            project_root: Root directory for relative path calculations
            helper_methods: Dictionary containing helper methods from facade
        """
        self.conn = conn
        self.read_only = read_only
        self.project_root = project_root
        self._to_relative_path = helper_methods["to_relative_path"]
        self._make_function_id = helper_methods["make_function_id"]
        self._make_variable_id = helper_methods["make_variable_id"]
        self._make_class_id = helper_methods["make_class_id"]
        self._make_import_id = helper_methods["make_import_id"]
        self._make_decorator_id = helper_methods["make_decorator_id"]
        self._make_attribute_id = helper_methods["make_attribute_id"]
        self._make_exception_id = helper_methods["make_exception_id"]
        self._make_module_id = helper_methods["make_module_id"]

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

    def add_function(
        self,
        name: str,
        file: str,
        start_line: int,
        end_line: int,
        is_public: bool = True,
        source_code: Optional[str] = None,
        parent_class: Optional[str] = None,
    ) -> None:
        """Add a function to the graph.

        Args:
            name: Function name
            file: File path where function is defined
            start_line: Starting line number
            end_line: Ending line number
            is_public: Whether function is public (not starting with _)
            source_code: Source code of the function (optional)
            parent_class: Name of parent class if this is a method (optional)

        Raises:
            RuntimeError: If database is in read-only mode
        """
        self._check_read_only()
        func_id = self._make_function_id(file, name, start_line)
        rel_file = self._to_relative_path(file)

        try:
            # Check if function already exists
            result = self.conn.execute(
                """
                MATCH (f:Function {id: $id})
                RETURN f.id
            """,
                {"id": func_id},
            )

            if result.has_next():
                # Update existing function
                self.conn.execute(
                    """
                    MATCH (f:Function {id: $id})
                    SET f.name = $name,
                        f.file = $file,
                        f.start_line = $start_line,
                        f.end_line = $end_line,
                        f.is_public = $is_public,
                        f.source_code = $source_code
                """,
                    {
                        "id": func_id,
                        "name": name,
                        "file": rel_file,
                        "start_line": start_line,
                        "end_line": end_line,
                        "is_public": is_public,
                        "source_code": source_code or "",
                    },
                )
            else:
                # Create new function
                self.conn.execute(
                    """
                    CREATE (f:Function {
                        id: $id,
                        name: $name,
                        file: $file,
                        start_line: $start_line,
                        end_line: $end_line,
                        is_public: $is_public,
                        source_code: $source_code
                    })
                """,
                    {
                        "id": func_id,
                        "name": name,
                        "file": rel_file,
                        "start_line": start_line,
                        "end_line": end_line,
                        "is_public": is_public,
                        "source_code": source_code or "",
                    },
                )

                # Add CONTAINS_FUNCTION edge from file to function if file exists
                self.conn.execute(
                    """
                    MATCH (file:File {path: $file}), (func:Function {id: $func_id})
                    CREATE (file)-[:CONTAINS_FUNCTION]->(func)
                """,
                    {"file": rel_file, "func_id": func_id},
                )

            # If parent_class provided, create METHOD_OF edge
            if parent_class:
                self.conn.execute(
                    """
                    MATCH (func:Function {id: $func_id}), (cls:Class {file: $file, name: $class_name})
                    CREATE (func)-[:METHOD_OF]->(cls)
                """,
                    {"func_id": func_id, "file": rel_file, "class_name": parent_class},
                )

        except Exception as e:
            console.print(f"[red]Error adding function {name} in {file}: {e}[/red]")

    def add_variable(
        self, name: str, file: str, definition_line: int, scope: str
    ) -> None:
        """Add a variable to the graph.

        Args:
            name: Variable name
            file: File path where variable is defined
            definition_line: Line number where variable is defined
            scope: Scope of the variable (e.g., "module", "function:func_name")

        Raises:
            RuntimeError: If database is in read-only mode
        """
        self._check_read_only()
        var_id = self._make_variable_id(file, name, definition_line)
        rel_file = self._to_relative_path(file)

        try:
            # Check if variable already exists
            result = self.conn.execute(
                """
                MATCH (v:Variable {id: $id})
                RETURN v.id
            """,
                {"id": var_id},
            )

            if result.has_next():
                # Update existing variable
                self.conn.execute(
                    """
                    MATCH (v:Variable {id: $id})
                    SET v.name = $name,
                        v.file = $file,
                        v.definition_line = $def_line,
                        v.scope = $scope
                """,
                    {
                        "id": var_id,
                        "name": name,
                        "file": rel_file,
                        "def_line": definition_line,
                        "scope": scope,
                    },
                )
            else:
                # Create new variable
                self.conn.execute(
                    """
                    CREATE (v:Variable {
                        id: $id,
                        name: $name,
                        file: $file,
                        definition_line: $def_line,
                        scope: $scope
                    })
                """,
                    {
                        "id": var_id,
                        "name": name,
                        "file": rel_file,
                        "def_line": definition_line,
                        "scope": scope,
                    },
                )

            # Add CONTAINS_VARIABLE edge from file for module-level variables (after node creation)
            if scope == "module":
                try:
                    self.conn.execute(
                        """
                        MATCH (file:File {path: $file}), (var:Variable {id: $var_id})
                        MERGE (file)-[:CONTAINS_VARIABLE]->(var)
                    """,
                        {"file": rel_file, "var_id": var_id},
                    )
                except Exception as e:
                    # File might not exist yet
                    pass

        except Exception as e:
            console.print(f"[red]Error adding variable {name} in {file}: {e}[/red]")

    def add_class(
        self,
        name: str,
        file: str,
        start_line: int,
        end_line: int,
        bases: List[str],
        is_public: bool = True,
        source_code: Optional[str] = None,
    ) -> None:
        """Add a class to the graph.

        Args:
            name: Class name
            file: File path where class is defined
            start_line: Starting line number
            end_line: Ending line number
            bases: List of base class names
            is_public: Whether class is public (not starting with _)
            source_code: Source code of the class (optional)

        Raises:
            RuntimeError: If database is in read-only mode
        """
        self._check_read_only()
        class_id = self._make_class_id(file, name, start_line)
        rel_file = self._to_relative_path(file)
        bases_json = json.dumps(bases)

        try:
            # Check if class already exists
            result = self.conn.execute(
                """
                MATCH (c:Class {id: $id})
                RETURN c.id
            """,
                {"id": class_id},
            )

            if result.has_next():
                # Update existing class
                self.conn.execute(
                    """
                    MATCH (c:Class {id: $id})
                    SET c.name = $name,
                        c.file = $file,
                        c.start_line = $start_line,
                        c.end_line = $end_line,
                        c.bases = $bases,
                        c.is_public = $is_public,
                        c.source_code = $source_code
                """,
                    {
                        "id": class_id,
                        "name": name,
                        "file": rel_file,
                        "start_line": start_line,
                        "end_line": end_line,
                        "bases": bases_json,
                        "is_public": is_public,
                        "source_code": source_code or "",
                    },
                )
            else:
                # Create new class
                self.conn.execute(
                    """
                    CREATE (c:Class {
                        id: $id,
                        name: $name,
                        file: $file,
                        start_line: $start_line,
                        end_line: $end_line,
                        bases: $bases,
                        is_public: $is_public,
                        source_code: $source_code
                    })
                """,
                    {
                        "id": class_id,
                        "name": name,
                        "file": rel_file,
                        "start_line": start_line,
                        "end_line": end_line,
                        "bases": bases_json,
                        "is_public": is_public,
                        "source_code": source_code or "",
                    },
                )

                # Add CONTAINS_CLASS edge from file to class if file exists
                self.conn.execute(
                    """
                    MATCH (file:File {path: $file}), (cls:Class {id: $class_id})
                    CREATE (file)-[:CONTAINS_CLASS]->(cls)
                """,
                    {"file": rel_file, "class_id": class_id},
                )

            # Create INHERITS edges for each base class
            for base_name in bases:
                # Try to find base class in the same file first, then in other files
                self.conn.execute(
                    """
                    MATCH (child:Class {id: $child_id}), (parent:Class {name: $base_name})
                    CREATE (child)-[:INHERITS]->(parent)
                """,
                    {"child_id": class_id, "base_name": base_name},
                )

        except Exception as e:
            console.print(f"[red]Error adding class {name} in {file}: {e}[/red]")

    def add_import(
        self,
        imported_name: str,
        import_type: str,
        file: str,
        line_number: int,
        alias: Optional[str] = None,
        is_relative: bool = False,
    ) -> None:
        """Add an import to the graph.

        Args:
            imported_name: Name of imported entity
            import_type: Type of import ("module", "function", "class", "variable", "*")
            file: File path where import occurs
            line_number: Line number of import statement
            alias: Import alias (e.g., "np" for "import numpy as np")
            is_relative: Whether this is a relative import

        Raises:
            RuntimeError: If database is in read-only mode
        """
        self._check_read_only()
        import_id = self._make_import_id(file, imported_name, line_number)
        rel_file = self._to_relative_path(file)

        try:
            # Check if import already exists
            result = self.conn.execute(
                """
                MATCH (i:Import {id: $id})
                RETURN i.id
            """,
                {"id": import_id},
            )

            if result.has_next():
                # Update existing import
                self.conn.execute(
                    """
                    MATCH (i:Import {id: $id})
                    SET i.imported_name = $imported_name,
                        i.import_type = $import_type,
                        i.alias = $alias,
                        i.line_number = $line_number,
                        i.is_relative = $is_relative,
                        i.file = $file
                """,
                    {
                        "id": import_id,
                        "imported_name": imported_name,
                        "import_type": import_type,
                        "alias": alias or "",
                        "line_number": line_number,
                        "is_relative": is_relative,
                        "file": rel_file,
                    },
                )
            else:
                # Create new import
                self.conn.execute(
                    """
                    CREATE (i:Import {
                        id: $id,
                        imported_name: $imported_name,
                        import_type: $import_type,
                        alias: $alias,
                        line_number: $line_number,
                        is_relative: $is_relative,
                        file: $file
                    })
                """,
                    {
                        "id": import_id,
                        "imported_name": imported_name,
                        "import_type": import_type,
                        "alias": alias or "",
                        "line_number": line_number,
                        "is_relative": is_relative,
                        "file": rel_file,
                    },
                )

                # Add HAS_IMPORT edge from file to import
                self.conn.execute(
                    """
                    MATCH (file:File {path: $file}), (imp:Import {id: $import_id})
                    CREATE (file)-[:HAS_IMPORT]->(imp)
                """,
                    {"file": rel_file, "import_id": import_id},
                )

        except Exception as e:
            console.print(
                f"[red]Error adding import {imported_name} in {file}: {e}[/red]"
            )

    def add_decorator(
        self, name: str, file: str, line_number: int, arguments: str = "{}"
    ) -> None:
        """Add a decorator to the graph.

        Args:
            name: Decorator name
            file: File path where decorator is applied
            line_number: Line number of decorator application
            arguments: JSON-serialized decorator arguments

        Raises:
            RuntimeError: If database is in read-only mode
        """
        self._check_read_only()
        decorator_id = self._make_decorator_id(file, name, line_number)
        rel_file = self._to_relative_path(file)

        try:
            # Check if decorator already exists
            result = self.conn.execute(
                """
                MATCH (d:Decorator {id: $id})
                RETURN d.id
            """,
                {"id": decorator_id},
            )

            if result.has_next():
                # Update existing decorator
                self.conn.execute(
                    """
                    MATCH (d:Decorator {id: $id})
                    SET d.name = $name,
                        d.file = $file,
                        d.line_number = $line_number,
                        d.arguments = $arguments
                """,
                    {
                        "id": decorator_id,
                        "name": name,
                        "file": rel_file,
                        "line_number": line_number,
                        "arguments": arguments,
                    },
                )
            else:
                # Create new decorator
                self.conn.execute(
                    """
                    CREATE (d:Decorator {
                        id: $id,
                        name: $name,
                        file: $file,
                        line_number: $line_number,
                        arguments: $arguments
                    })
                """,
                    {
                        "id": decorator_id,
                        "name": name,
                        "file": rel_file,
                        "line_number": line_number,
                        "arguments": arguments,
                    },
                )

        except Exception as e:
            console.print(f"[red]Error adding decorator {name} in {file}: {e}[/red]")

    def add_attribute(
        self,
        name: str,
        class_name: str,
        file: str,
        definition_line: int,
        type_hint: Optional[str] = None,
        is_class_attribute: bool = False,
    ) -> None:
        """Add an attribute to the graph.

        Args:
            name: Attribute name
            class_name: Name of class owning the attribute
            file: File path where attribute is defined
            definition_line: Line number where attribute is defined
            type_hint: Type hint string (if any)
            is_class_attribute: True for class variables, False for instance variables

        Raises:
            RuntimeError: If database is in read-only mode
        """
        self._check_read_only()
        attr_id = self._make_attribute_id(file, class_name, name, definition_line)
        rel_file = self._to_relative_path(file)

        try:
            # Check if attribute already exists
            result = self.conn.execute(
                """
                MATCH (a:Attribute {id: $id})
                RETURN a.id
            """,
                {"id": attr_id},
            )

            if result.has_next():
                # Update existing attribute
                self.conn.execute(
                    """
                    MATCH (a:Attribute {id: $id})
                    SET a.name = $name,
                        a.class_name = $class_name,
                        a.file = $file,
                        a.definition_line = $definition_line,
                        a.type_hint = $type_hint,
                        a.is_class_attribute = $is_class_attribute
                """,
                    {
                        "id": attr_id,
                        "name": name,
                        "class_name": class_name,
                        "file": rel_file,
                        "definition_line": definition_line,
                        "type_hint": type_hint or "",
                        "is_class_attribute": is_class_attribute,
                    },
                )
            else:
                # Create new attribute
                self.conn.execute(
                    """
                    CREATE (a:Attribute {
                        id: $id,
                        name: $name,
                        class_name: $class_name,
                        file: $file,
                        definition_line: $definition_line,
                        type_hint: $type_hint,
                        is_class_attribute: $is_class_attribute
                    })
                """,
                    {
                        "id": attr_id,
                        "name": name,
                        "class_name": class_name,
                        "file": rel_file,
                        "definition_line": definition_line,
                        "type_hint": type_hint or "",
                        "is_class_attribute": is_class_attribute,
                    },
                )

                # Add HAS_ATTRIBUTE edge from class to attribute
                self.conn.execute(
                    """
                    MATCH (cls:Class {file: $file, name: $class_name}), (attr:Attribute {id: $attr_id})
                    CREATE (cls)-[:HAS_ATTRIBUTE]->(attr)
                """,
                    {"file": rel_file, "class_name": class_name, "attr_id": attr_id},
                )

        except Exception as e:
            console.print(
                f"[red]Error adding attribute {name} to class {class_name} in {file}: {e}[/red]"
            )

    def add_exception(self, name: str, file: str, line_number: int) -> None:
        """Add an exception to the graph.

        Args:
            name: Exception name
            file: File path where exception is raised/caught
            line_number: Line number where exception appears

        Raises:
            RuntimeError: If database is in read-only mode
        """
        self._check_read_only()
        exc_id = self._make_exception_id(file, name, line_number)
        rel_file = self._to_relative_path(file)

        try:
            # Check if exception already exists
            result = self.conn.execute(
                """
                MATCH (e:Exception {id: $id})
                RETURN e.id
            """,
                {"id": exc_id},
            )

            if result.has_next():
                # Update existing exception
                self.conn.execute(
                    """
                    MATCH (e:Exception {id: $id})
                    SET e.name = $name,
                        e.file = $file,
                        e.line_number = $line_number
                """,
                    {
                        "id": exc_id,
                        "name": name,
                        "file": rel_file,
                        "line_number": line_number,
                    },
                )
            else:
                # Create new exception
                self.conn.execute(
                    """
                    CREATE (e:Exception {
                        id: $id,
                        name: $name,
                        file: $file,
                        line_number: $line_number
                    })
                """,
                    {
                        "id": exc_id,
                        "name": name,
                        "file": rel_file,
                        "line_number": line_number,
                    },
                )

        except Exception as e:
            console.print(f"[red]Error adding exception {name} in {file}: {e}[/red]")

    def add_module(
        self, name: str, path: str, is_package: bool, docstring: Optional[str] = None
    ) -> None:
        """Add a module to the graph.

        Args:
            name: Module name (e.g., "utils.helpers")
            path: File path or directory path
            is_package: True if __init__.py, False for regular module
            docstring: Module-level docstring

        Raises:
            RuntimeError: If database is in read-only mode
        """
        self._check_read_only()
        module_id = self._make_module_id(name)
        rel_path = self._to_relative_path(path)

        try:
            # Check if module already exists
            result = self.conn.execute(
                """
                MATCH (m:Module {id: $id})
                RETURN m.id
            """,
                {"id": module_id},
            )

            if result.has_next():
                # Update existing module
                self.conn.execute(
                    """
                    MATCH (m:Module {id: $id})
                    SET m.name = $name,
                        m.path = $path,
                        m.is_package = $is_package,
                        m.docstring = $docstring
                """,
                    {
                        "id": module_id,
                        "name": name,
                        "path": rel_path,
                        "is_package": is_package,
                        "docstring": docstring or "",
                    },
                )
            else:
                # Create new module
                self.conn.execute(
                    """
                    CREATE (m:Module {
                        id: $id,
                        name: $name,
                        path: $path,
                        is_package: $is_package,
                        docstring: $docstring
                    })
                """,
                    {
                        "id": module_id,
                        "name": name,
                        "path": rel_path,
                        "is_package": is_package,
                        "docstring": docstring or "",
                    },
                )

        except Exception as e:
            console.print(f"[red]Error adding module {name}: {e}[/red]")

    def add_file(self, file_path: str, language: str, content_hash: str) -> None:
        """Add or update file node in database.

        Args:
            file_path: Path to file
            language: Programming language
            content_hash: Hash of file contents

        Raises:
            RuntimeError: If database is in read-only mode
        """
        self._check_read_only()
        try:
            # Check if file exists
            result = self.conn.execute(
                """
                MATCH (f:File {path: $path})
                RETURN f.path
            """,
                {"path": file_path},
            )

            if result.has_next():
                # Update existing file
                self.conn.execute(
                    """
                    MATCH (f:File {path: $path})
                    SET f.language = $language,
                        f.last_modified = $timestamp,
                        f.content_hash = $hash
                """,
                    {
                        "path": file_path,
                        "language": language,
                        "timestamp": datetime.now(),
                        "hash": content_hash,
                    },
                )
            else:
                # Create new file
                self.conn.execute(
                    """
                    CREATE (f:File {
                        path: $path,
                        language: $language,
                        last_modified: $timestamp,
                        content_hash: $hash
                    })
                """,
                    {
                        "path": file_path,
                        "language": language,
                        "timestamp": datetime.now(),
                        "hash": content_hash,
                    },
                )
        except Exception as e:
            console.print(f"[red]Error adding file {file_path}: {e}[/red]")

    def delete_file_data(self, file_path: str) -> None:
        """Delete all nodes and edges for a file.

        Args:
            file_path: Path to file

        Raises:
            RuntimeError: If database is in read-only mode
        """
        self._check_read_only()
        try:
            # Delete functions from this file
            self.conn.execute(
                """
                MATCH (f:Function {file: $path})
                DETACH DELETE f
            """,
                {"path": file_path},
            )

            # Delete classes from this file
            self.conn.execute(
                """
                MATCH (c:Class {file: $path})
                DETACH DELETE c
            """,
                {"path": file_path},
            )

            # Delete variables from this file
            self.conn.execute(
                """
                MATCH (v:Variable {file: $path})
                DETACH DELETE v
            """,
                {"path": file_path},
            )

            # Delete imports from this file
            self.conn.execute(
                """
                MATCH (i:Import {file: $path})
                DETACH DELETE i
            """,
                {"path": file_path},
            )

            # Delete decorators from this file
            self.conn.execute(
                """
                MATCH (d:Decorator {file: $path})
                DETACH DELETE d
            """,
                {"path": file_path},
            )

            # Delete attributes from this file
            self.conn.execute(
                """
                MATCH (a:Attribute {file: $path})
                DETACH DELETE a
            """,
                {"path": file_path},
            )

            # Delete exceptions from this file
            self.conn.execute(
                """
                MATCH (e:Exception {file: $path})
                DETACH DELETE e
            """,
                {"path": file_path},
            )

            # Delete file node
            self.conn.execute(
                """
                MATCH (f:File {path: $path})
                DELETE f
            """,
                {"path": file_path},
            )

        except Exception as e:
            console.print(f"[red]Error deleting file data for {file_path}: {e}[/red]")
