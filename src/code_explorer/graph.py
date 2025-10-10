"""
Dependency graph data structure with KuzuDB persistent storage.

This module provides a graph database for storing and querying Python code
dependencies. Data persists to disk using KuzuDB for fast incremental analysis.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import kuzu


@dataclass
class FunctionNode:
    """Represents a function in the dependency graph."""

    name: str
    file: str
    start_line: int
    end_line: int
    is_public: bool = True


@dataclass
class VariableNode:
    """Represents a variable in the dependency graph."""

    name: str
    file: str
    definition_line: int
    scope: str


@dataclass
class ClassNode:
    """Represents a class in the dependency graph."""

    name: str
    file: str
    start_line: int
    end_line: int
    bases: List[str]
    is_public: bool = True


@dataclass
class ImportNode:
    """Represents an import statement in the dependency graph."""

    imported_name: str
    import_type: str  # "module", "function", "class", "variable", "*"
    alias: Optional[str]
    line_number: int
    is_relative: bool
    file: str


@dataclass
class DecoratorNode:
    """Represents a decorator application in the dependency graph."""

    name: str
    file: str
    line_number: int
    arguments: str  # JSON-serialized decorator arguments


@dataclass
class AttributeNode:
    """Represents a class attribute in the dependency graph."""

    name: str
    class_name: str
    file: str
    definition_line: int
    type_hint: Optional[str]
    is_class_attribute: bool


@dataclass
class ExceptionNode:
    """Represents an exception in the dependency graph."""

    name: str
    file: str
    line_number: int


@dataclass
class ModuleNode:
    """Represents a module in the dependency graph."""

    name: str
    path: str
    is_package: bool
    docstring: Optional[str]


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

        # Create schema if tables don't exist (only in read-write mode)
        if not self.read_only:
            self._create_schema()

        # Detect schema version (after schema creation)
        self.schema_version = self._detect_schema_version()

    def _detect_schema_version(self) -> str:
        """Detect schema version by checking if new tables exist.

        Returns:
            "v1" for old schema (only File, Function, Variable, Class)
            "v2" for new schema (with Import, Decorator, Attribute, Exception, Module)
        """
        try:
            # Check if Import table exists (part of v2 schema)
            result = self.conn.execute("MATCH (i:Import) RETURN COUNT(*) LIMIT 1")
            result.get_next()
            return "v2"
        except Exception:
            # Import table doesn't exist, must be v1
            return "v1"

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

    def _create_schema(self) -> None:
        """Create KuzuDB schema with node and edge tables."""
        try:
            # Create File node table
            self.conn.execute("""
                CREATE NODE TABLE IF NOT EXISTS File(
                    path STRING,
                    language STRING,
                    last_modified TIMESTAMP,
                    content_hash STRING,
                    PRIMARY KEY(path)
                )
            """)

            # Create Function node table
            self.conn.execute("""
                CREATE NODE TABLE IF NOT EXISTS Function(
                    id STRING,
                    name STRING,
                    file STRING,
                    start_line INT64,
                    end_line INT64,
                    is_public BOOLEAN,
                    source_code STRING,
                    PRIMARY KEY(id)
                )
            """)

            # Create Variable node table
            self.conn.execute("""
                CREATE NODE TABLE IF NOT EXISTS Variable(
                    id STRING,
                    name STRING,
                    file STRING,
                    definition_line INT64,
                    scope STRING,
                    PRIMARY KEY(id)
                )
            """)

            # Create Class node table
            self.conn.execute("""
                CREATE NODE TABLE IF NOT EXISTS Class(
                    id STRING,
                    name STRING,
                    file STRING,
                    start_line INT64,
                    end_line INT64,
                    bases STRING,
                    is_public BOOLEAN,
                    source_code STRING,
                    PRIMARY KEY(id)
                )
            """)

            # Create edge tables
            self.conn.execute("""
                CREATE REL TABLE IF NOT EXISTS CALLS(
                    FROM Function TO Function,
                    call_line INT64
                )
            """)

            self.conn.execute("""
                CREATE REL TABLE IF NOT EXISTS USES(
                    FROM Function TO Variable,
                    usage_line INT64
                )
            """)

            self.conn.execute("""
                CREATE REL TABLE IF NOT EXISTS CONTAINS(
                    FROM File TO Function
                )
            """)

            self.conn.execute("""
                CREATE REL TABLE IF NOT EXISTS DEFINES(
                    FROM Function TO Variable
                )
            """)

            self.conn.execute("""
                CREATE REL TABLE IF NOT EXISTS IMPORTS(
                    FROM File TO File,
                    line_number INT64,
                    is_direct BOOLEAN
                )
            """)

            # INHERITS edge: Class inherits from Class
            self.conn.execute("""
                CREATE REL TABLE IF NOT EXISTS INHERITS(
                    FROM Class TO Class
                )
            """)

            # METHOD_OF edge: Function is method of Class
            self.conn.execute("""
                CREATE REL TABLE IF NOT EXISTS METHOD_OF(
                    FROM Function TO Class
                )
            """)

            # Create Import node table
            self.conn.execute("""
                CREATE NODE TABLE IF NOT EXISTS Import(
                    id STRING,
                    imported_name STRING,
                    import_type STRING,
                    alias STRING,
                    line_number INT64,
                    is_relative BOOLEAN,
                    file STRING,
                    PRIMARY KEY(id)
                )
            """)

            # Create Decorator node table
            self.conn.execute("""
                CREATE NODE TABLE IF NOT EXISTS Decorator(
                    id STRING,
                    name STRING,
                    file STRING,
                    line_number INT64,
                    arguments STRING,
                    PRIMARY KEY(id)
                )
            """)

            # Create Attribute node table
            self.conn.execute("""
                CREATE NODE TABLE IF NOT EXISTS Attribute(
                    id STRING,
                    name STRING,
                    class_name STRING,
                    file STRING,
                    definition_line INT64,
                    type_hint STRING,
                    is_class_attribute BOOLEAN,
                    PRIMARY KEY(id)
                )
            """)

            # Create Exception node table
            self.conn.execute("""
                CREATE NODE TABLE IF NOT EXISTS Exception(
                    id STRING,
                    name STRING,
                    file STRING,
                    line_number INT64,
                    PRIMARY KEY(id)
                )
            """)

            # Create Module node table
            self.conn.execute("""
                CREATE NODE TABLE IF NOT EXISTS Module(
                    id STRING,
                    name STRING,
                    path STRING,
                    is_package BOOLEAN,
                    docstring STRING,
                    PRIMARY KEY(id)
                )
            """)

            # Create HAS_IMPORT edge: File has Import
            self.conn.execute("""
                CREATE REL TABLE IF NOT EXISTS HAS_IMPORT(
                    FROM File TO Import
                )
            """)

            # Create IMPORTS_FROM edge: Import imports from Function|Class|Variable|Module
            # Note: KuzuDB supports union types in FROM/TO
            self.conn.execute("""
                CREATE REL TABLE IF NOT EXISTS IMPORTS_FROM(
                    FROM Import TO Function
                )
            """)

            # Create DECORATED_BY edge: Function|Class decorated by Decorator
            self.conn.execute("""
                CREATE REL TABLE IF NOT EXISTS DECORATED_BY(
                    FROM Function TO Decorator,
                    position INT64
                )
            """)

            # Create DECORATOR_RESOLVES_TO edge: Decorator resolves to Function
            self.conn.execute("""
                CREATE REL TABLE IF NOT EXISTS DECORATOR_RESOLVES_TO(
                    FROM Decorator TO Function
                )
            """)

            # Create HAS_ATTRIBUTE edge: Class has Attribute
            self.conn.execute("""
                CREATE REL TABLE IF NOT EXISTS HAS_ATTRIBUTE(
                    FROM Class TO Attribute
                )
            """)

            # Create ACCESSES edge: Function accesses Attribute
            self.conn.execute("""
                CREATE REL TABLE IF NOT EXISTS ACCESSES(
                    FROM Function TO Attribute,
                    line_number INT64
                )
            """)

            # Create MODIFIES edge: Function modifies Attribute
            self.conn.execute("""
                CREATE REL TABLE IF NOT EXISTS MODIFIES(
                    FROM Function TO Attribute,
                    line_number INT64
                )
            """)

            # Create RAISES edge: Function raises Exception
            self.conn.execute("""
                CREATE REL TABLE IF NOT EXISTS RAISES(
                    FROM Function TO Exception,
                    line_number INT64
                )
            """)

            # Create CATCHES edge: Function catches Exception
            self.conn.execute("""
                CREATE REL TABLE IF NOT EXISTS CATCHES(
                    FROM Function TO Exception,
                    line_number INT64
                )
            """)

            # Create CONTAINS_MODULE edge: Module contains Module
            self.conn.execute("""
                CREATE REL TABLE IF NOT EXISTS CONTAINS_MODULE(
                    FROM Module TO Module
                )
            """)

            # Create MODULE_OF edge: File has Module
            self.conn.execute("""
                CREATE REL TABLE IF NOT EXISTS MODULE_OF(
                    FROM File TO Module
                )
            """)

        except Exception as e:
            # Tables may already exist, which is fine
            pass

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

                # Add CONTAINS edge from file to function if file exists
                self.conn.execute(
                    """
                    MATCH (file:File {path: $file}), (func:Function {id: $func_id})
                    CREATE (file)-[:CONTAINS]->(func)
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
            print(f"Error adding function {name} in {file}: {e}")

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

        except Exception as e:
            print(f"Error adding variable {name} in {file}: {e}")

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
            print(f"Error adding class {name} in {file}: {e}")

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
            print(f"Error adding import {imported_name} in {file}: {e}")

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
            print(f"Error adding decorator {name} in {file}: {e}")

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
            print(f"Error adding attribute {name} to class {class_name} in {file}: {e}")

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
            print(f"Error adding exception {name} in {file}: {e}")

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
            print(f"Error adding module {name}: {e}")

    def add_call(
        self,
        caller_file: str,
        caller_function: str,
        caller_start_line: int,
        callee_file: str,
        callee_function: str,
        callee_start_line: int,
        call_line: int,
    ) -> None:
        """Add a function call edge.

        Args:
            caller_file: File where caller is defined
            caller_function: Name of calling function
            caller_start_line: Starting line of caller function
            callee_file: File where callee is defined
            callee_function: Name of called function
            callee_start_line: Starting line of callee function
            call_line: Line number where call occurs

        Raises:
            RuntimeError: If database is in read-only mode
        """
        self._check_read_only()
        caller_id = self._make_function_id(
            caller_file, caller_function, caller_start_line
        )
        callee_id = self._make_function_id(
            callee_file, callee_function, callee_start_line
        )

        try:
            # Create CALLS edge (KuzuDB handles duplicates automatically)
            self.conn.execute(
                """
                MATCH (caller:Function {id: $caller_id}), (callee:Function {id: $callee_id})
                CREATE (caller)-[:CALLS {call_line: $call_line}]->(callee)
            """,
                {
                    "caller_id": caller_id,
                    "callee_id": callee_id,
                    "call_line": call_line,
                },
            )
        except Exception as e:
            # Functions may not exist yet, which is fine for incremental builds
            pass

    def add_variable_usage(
        self,
        function_file: str,
        function_name: str,
        function_start_line: int,
        var_name: str,
        var_file: str,
        var_definition_line: int,
        usage_line: int,
        is_definition: bool = False,
    ) -> None:
        """Add variable usage edge.

        Args:
            function_file: File where function is defined
            function_name: Name of function using the variable
            function_start_line: Starting line of function
            var_name: Variable name
            var_file: File where variable is defined
            var_definition_line: Line where variable is defined
            usage_line: Line where variable is used
            is_definition: True if function defines the variable

        Raises:
            RuntimeError: If database is in read-only mode
        """
        self._check_read_only()
        func_id = self._make_function_id(
            function_file, function_name, function_start_line
        )
        var_id = self._make_variable_id(var_file, var_name, var_definition_line)

        try:
            if is_definition:
                # Create DEFINES edge
                self.conn.execute(
                    """
                    MATCH (func:Function {id: $func_id}), (var:Variable {id: $var_id})
                    CREATE (func)-[:DEFINES]->(var)
                """,
                    {"func_id": func_id, "var_id": var_id},
                )
            else:
                # Create USES edge
                self.conn.execute(
                    """
                    MATCH (func:Function {id: $func_id}), (var:Variable {id: $var_id})
                    CREATE (func)-[:USES {usage_line: $usage_line}]->(var)
                """,
                    {"func_id": func_id, "var_id": var_id, "usage_line": usage_line},
                )
        except Exception as e:
            # Nodes may not exist yet
            pass

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
            print(f"Error getting callers for {function} in {file}: {e}")
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
            print(f"Error getting callees for {function} in {file}: {e}")
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
                MATCH (func:Function)-[u:USES]->(var:Variable {id: $var_id})
                RETURN func.file, func.name, u.usage_line
            """,
                {"var_id": var_id},
            )

            usages = []
            while result.has_next():
                row = result.get_next()
                usages.append((row[0], row[1], row[2]))

            return usages
        except Exception as e:
            print(f"Error getting variable usage for {var_name} in {file}: {e}")
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
            print(f"Error getting function {name} in {file}: {e}")
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
            print(f"Error getting functions in file {file}: {e}")
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
            print(f"Error getting class {name} in {file}: {e}")
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
            print(f"Error getting classes in file {file}: {e}")
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

            # Count call edges
            result = self.conn.execute("MATCH ()-[c:CALLS]->() RETURN COUNT(*)")
            total_call_edges = result.get_next()[0] if result.has_next() else 0

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
                "total_edges": total_call_edges,
                "function_calls": total_call_edges,
                "most_called_functions": most_called,
                "schema_version": self.schema_version,
            }
        except Exception as e:
            print(f"Error getting statistics: {e}")
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
            print(f"Error getting imports for file {file_path}: {e}")
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
            print(
                f"Error getting decorators for function {function_name} in {file}: {e}"
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
            print(f"Error getting attributes for class {class_name} in {file}: {e}")
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
                MATCH (f:Function)-[:RAISES]->(e:Exception {name: $exc_name})
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
            print(f"Error getting functions raising {exception_name}: {e}")
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
            print(f"Error getting module hierarchy: {e}")
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
            print(f"Error finding import usages for {function_or_class_name}: {e}")
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
                MATCH (f:Function)-[m:MODIFIES]->(a:Attribute {class_name: $class_name, name: $attr_name})
                RETURN f.file, f.name, m.line_number
            """,
                {"class_name": class_name, "attr_name": attribute_name},
            )

            modifiers = []
            while result.has_next():
                row = result.get_next()
                modifiers.append((row[0], row[1], row[2]))

            return modifiers
        except Exception as e:
            print(f"Error finding modifiers for {class_name}.{attribute_name}: {e}")
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
            print(f"Error checking file existence: {e}")
            return False

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
            print(f"Error adding file {file_path}: {e}")

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
            print(f"Error deleting file data for {file_path}: {e}")

    def clear_all(self) -> None:
        """Clear all data from the database.

        Raises:
            RuntimeError: If database is in read-only mode
        """
        self._check_read_only()
        try:
            # Delete all edges first
            self.conn.execute("MATCH ()-[r:CALLS]->() DELETE r")
            self.conn.execute("MATCH ()-[r:USES]->() DELETE r")
            self.conn.execute("MATCH ()-[r:CONTAINS]->() DELETE r")
            self.conn.execute("MATCH ()-[r:DEFINES]->() DELETE r")
            self.conn.execute("MATCH ()-[r:IMPORTS]->() DELETE r")
            self.conn.execute("MATCH ()-[r:INHERITS]->() DELETE r")
            self.conn.execute("MATCH ()-[r:METHOD_OF]->() DELETE r")

            # Delete new edges (v2 schema)
            if self.schema_version == "v2":
                try:
                    self.conn.execute("MATCH ()-[r:HAS_IMPORT]->() DELETE r")
                    self.conn.execute("MATCH ()-[r:IMPORTS_FROM]->() DELETE r")
                    self.conn.execute("MATCH ()-[r:DECORATED_BY]->() DELETE r")
                    self.conn.execute("MATCH ()-[r:DECORATOR_RESOLVES_TO]->() DELETE r")
                    self.conn.execute("MATCH ()-[r:HAS_ATTRIBUTE]->() DELETE r")
                    self.conn.execute("MATCH ()-[r:ACCESSES]->() DELETE r")
                    self.conn.execute("MATCH ()-[r:MODIFIES]->() DELETE r")
                    self.conn.execute("MATCH ()-[r:RAISES]->() DELETE r")
                    self.conn.execute("MATCH ()-[r:CATCHES]->() DELETE r")
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
                    self.conn.execute("MATCH (d:Decorator) DELETE d")
                    self.conn.execute("MATCH (a:Attribute) DELETE a")
                    self.conn.execute("MATCH (e:Exception) DELETE e")
                    self.conn.execute("MATCH (m:Module) DELETE m")
                except Exception:
                    pass

        except Exception as e:
            print(f"Error clearing database: {e}")

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
