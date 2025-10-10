"""
Dependency graph data structure with KuzuDB persistent storage.

This module provides a graph database for storing and querying Python code
dependencies. Data persists to disk using KuzuDB for fast incremental analysis.
"""

import hashlib
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


class DependencyGraph:
    """KuzuDB-backed dependency graph with persistent storage.

    Stores functions, variables, and their relationships in a property graph
    database that persists to disk. Supports incremental updates and efficient queries.
    """

    def __init__(self, db_path: Optional[Path] = None, read_only: bool = False):
        """Initialize KuzuDB connection and create schema if needed.

        Args:
            db_path: Path to KuzuDB database directory.
                    Defaults to .code-explorer/graph.db
            read_only: If True, opens database in read-only mode for safe parallel
                      reads without risk of accidental writes. Default is False.
                      In read-only mode, schema creation is skipped and all write
                      methods will raise exceptions if called.
        """
        if db_path is None:
            db_path = Path.cwd() / ".code-explorer" / "graph.db"

        # Ensure parent directory exists (only in read-write mode)
        if not read_only:
            db_path.parent.mkdir(parents=True, exist_ok=True)

        self.db_path = db_path
        self.read_only = read_only
        self.db = kuzu.Database(str(db_path), read_only=read_only)
        self.conn = kuzu.Connection(self.db)

        # Create schema if tables don't exist (only in read-write mode)
        if not self.read_only:
            self._create_schema()

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

        except Exception as e:
            # Tables may already exist, which is fine
            pass

    def _make_function_id(self, file: str, name: str) -> str:
        """Create unique ID for a function."""
        return f"{file}::{name}"

    def _make_variable_id(self, file: str, name: str, line: int) -> str:
        """Create unique ID for a variable."""
        return f"{file}::{name}::{line}"

    def add_function(
        self,
        name: str,
        file: str,
        start_line: int,
        end_line: int,
        is_public: bool = True
    ) -> None:
        """Add a function to the graph.

        Args:
            name: Function name
            file: File path where function is defined
            start_line: Starting line number
            end_line: Ending line number
            is_public: Whether function is public (not starting with _)

        Raises:
            RuntimeError: If database is in read-only mode
        """
        self._check_read_only()
        func_id = self._make_function_id(file, name)

        try:
            # Check if function already exists
            result = self.conn.execute("""
                MATCH (f:Function {id: $id})
                RETURN f.id
            """, {"id": func_id})

            if result.has_next():
                # Update existing function
                self.conn.execute("""
                    MATCH (f:Function {id: $id})
                    SET f.name = $name,
                        f.file = $file,
                        f.start_line = $start_line,
                        f.end_line = $end_line,
                        f.is_public = $is_public
                """, {
                    "id": func_id,
                    "name": name,
                    "file": file,
                    "start_line": start_line,
                    "end_line": end_line,
                    "is_public": is_public
                })
            else:
                # Create new function
                self.conn.execute("""
                    CREATE (f:Function {
                        id: $id,
                        name: $name,
                        file: $file,
                        start_line: $start_line,
                        end_line: $end_line,
                        is_public: $is_public
                    })
                """, {
                    "id": func_id,
                    "name": name,
                    "file": file,
                    "start_line": start_line,
                    "end_line": end_line,
                    "is_public": is_public
                })

                # Add CONTAINS edge from file to function if file exists
                self.conn.execute("""
                    MATCH (file:File {path: $file}), (func:Function {id: $func_id})
                    CREATE (file)-[:CONTAINS]->(func)
                """, {"file": file, "func_id": func_id})

        except Exception as e:
            print(f"Error adding function {name} in {file}: {e}")

    def add_variable(
        self,
        name: str,
        file: str,
        definition_line: int,
        scope: str
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

        try:
            # Check if variable already exists
            result = self.conn.execute("""
                MATCH (v:Variable {id: $id})
                RETURN v.id
            """, {"id": var_id})

            if result.has_next():
                # Update existing variable
                self.conn.execute("""
                    MATCH (v:Variable {id: $id})
                    SET v.name = $name,
                        v.file = $file,
                        v.definition_line = $def_line,
                        v.scope = $scope
                """, {
                    "id": var_id,
                    "name": name,
                    "file": file,
                    "def_line": definition_line,
                    "scope": scope
                })
            else:
                # Create new variable
                self.conn.execute("""
                    CREATE (v:Variable {
                        id: $id,
                        name: $name,
                        file: $file,
                        definition_line: $def_line,
                        scope: $scope
                    })
                """, {
                    "id": var_id,
                    "name": name,
                    "file": file,
                    "def_line": definition_line,
                    "scope": scope
                })

        except Exception as e:
            print(f"Error adding variable {name} in {file}: {e}")

    def add_call(
        self,
        caller_file: str,
        caller_function: str,
        callee_file: str,
        callee_function: str,
        call_line: int
    ) -> None:
        """Add a function call edge.

        Args:
            caller_file: File where caller is defined
            caller_function: Name of calling function
            callee_file: File where callee is defined
            callee_function: Name of called function
            call_line: Line number where call occurs

        Raises:
            RuntimeError: If database is in read-only mode
        """
        self._check_read_only()
        caller_id = self._make_function_id(caller_file, caller_function)
        callee_id = self._make_function_id(callee_file, callee_function)

        try:
            # Create CALLS edge (KuzuDB handles duplicates automatically)
            self.conn.execute("""
                MATCH (caller:Function {id: $caller_id}), (callee:Function {id: $callee_id})
                CREATE (caller)-[:CALLS {call_line: $call_line}]->(callee)
            """, {
                "caller_id": caller_id,
                "callee_id": callee_id,
                "call_line": call_line
            })
        except Exception as e:
            # Functions may not exist yet, which is fine for incremental builds
            pass

    def add_variable_usage(
        self,
        function_file: str,
        function_name: str,
        var_name: str,
        var_file: str,
        var_definition_line: int,
        usage_line: int,
        is_definition: bool = False
    ) -> None:
        """Add variable usage edge.

        Args:
            function_file: File where function is defined
            function_name: Name of function using the variable
            var_name: Variable name
            var_file: File where variable is defined
            var_definition_line: Line where variable is defined
            usage_line: Line where variable is used
            is_definition: True if function defines the variable

        Raises:
            RuntimeError: If database is in read-only mode
        """
        self._check_read_only()
        func_id = self._make_function_id(function_file, function_name)
        var_id = self._make_variable_id(var_file, var_name, var_definition_line)

        try:
            if is_definition:
                # Create DEFINES edge
                self.conn.execute("""
                    MATCH (func:Function {id: $func_id}), (var:Variable {id: $var_id})
                    CREATE (func)-[:DEFINES]->(var)
                """, {"func_id": func_id, "var_id": var_id})
            else:
                # Create USES edge
                self.conn.execute("""
                    MATCH (func:Function {id: $func_id}), (var:Variable {id: $var_id})
                    CREATE (func)-[:USES {usage_line: $usage_line}]->(var)
                """, {"func_id": func_id, "var_id": var_id, "usage_line": usage_line})
        except Exception as e:
            # Nodes may not exist yet
            pass

    def get_callers(
        self,
        file: str,
        function: str
    ) -> List[Tuple[str, str, int]]:
        """Get functions that call the specified function.

        Args:
            file: File where function is defined
            function: Function name

        Returns:
            List of (file, function_name, call_line) tuples
        """
        func_id = self._make_function_id(file, function)

        try:
            result = self.conn.execute("""
                MATCH (caller:Function)-[c:CALLS]->(callee:Function {id: $func_id})
                RETURN caller.file, caller.name, c.call_line
            """, {"func_id": func_id})

            callers = []
            while result.has_next():
                row = result.get_next()
                callers.append((row[0], row[1], row[2]))

            return callers
        except Exception as e:
            print(f"Error getting callers for {function} in {file}: {e}")
            return []

    def get_callees(
        self,
        file: str,
        function: str
    ) -> List[Tuple[str, str, int]]:
        """Get functions called by the specified function.

        Args:
            file: File where function is defined
            function: Function name

        Returns:
            List of (file, function_name, call_line) tuples
        """
        func_id = self._make_function_id(file, function)

        try:
            result = self.conn.execute("""
                MATCH (caller:Function {id: $func_id})-[c:CALLS]->(callee:Function)
                RETURN callee.file, callee.name, c.call_line
            """, {"func_id": func_id})

            callees = []
            while result.has_next():
                row = result.get_next()
                callees.append((row[0], row[1], row[2]))

            return callees
        except Exception as e:
            print(f"Error getting callees for {function} in {file}: {e}")
            return []

    def get_variable_usage(
        self,
        file: str,
        var_name: str,
        definition_line: int
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
            result = self.conn.execute("""
                MATCH (func:Function)-[u:USES]->(var:Variable {id: $var_id})
                RETURN func.file, func.name, u.usage_line
            """, {"var_id": var_id})

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
        func_id = self._make_function_id(file, name)

        try:
            result = self.conn.execute("""
                MATCH (f:Function {id: $func_id})
                RETURN f.name, f.file, f.start_line, f.end_line, f.is_public
            """, {"func_id": func_id})

            if result.has_next():
                row = result.get_next()
                return FunctionNode(
                    name=row[0],
                    file=row[1],
                    start_line=row[2],
                    end_line=row[3],
                    is_public=row[4]
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
            result = self.conn.execute("""
                MATCH (f:Function {file: $file})
                RETURN f.name, f.file, f.start_line, f.end_line, f.is_public
            """, {"file": file})

            functions = []
            while result.has_next():
                row = result.get_next()
                functions.append(FunctionNode(
                    name=row[0],
                    file=row[1],
                    start_line=row[2],
                    end_line=row[3],
                    is_public=row[4]
                ))

            return functions
        except Exception as e:
            print(f"Error getting functions in file {file}: {e}")
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

            # Count variables
            result = self.conn.execute("MATCH (v:Variable) RETURN COUNT(*)")
            total_variables = result.get_next()[0] if result.has_next() else 0

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
                most_called.append({
                    "name": row[0],
                    "file": row[1],
                    "call_count": row[2]
                })

            return {
                "total_files": total_files,
                "total_functions": total_functions,
                "total_variables": total_variables,
                "total_edges": total_call_edges,
                "function_calls": total_call_edges,
                "most_called_functions": most_called,
            }
        except Exception as e:
            print(f"Error getting statistics: {e}")
            return {
                "total_files": 0,
                "total_functions": 0,
                "total_variables": 0,
                "total_edges": 0,
                "function_calls": 0,
                "most_called_functions": [],
            }

    def file_exists(self, file_path: str, content_hash: str) -> bool:
        """Check if file with this hash exists in database.

        Args:
            file_path: Path to file
            content_hash: Hash of file contents

        Returns:
            True if file exists with same hash, False otherwise
        """
        try:
            result = self.conn.execute("""
                MATCH (f:File {path: $path})
                RETURN f.content_hash
            """, {"path": file_path})

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
            result = self.conn.execute("""
                MATCH (f:File {path: $path})
                RETURN f.path
            """, {"path": file_path})

            if result.has_next():
                # Update existing file
                self.conn.execute("""
                    MATCH (f:File {path: $path})
                    SET f.language = $language,
                        f.last_modified = $timestamp,
                        f.content_hash = $hash
                """, {
                    "path": file_path,
                    "language": language,
                    "timestamp": datetime.now(),
                    "hash": content_hash
                })
            else:
                # Create new file
                self.conn.execute("""
                    CREATE (f:File {
                        path: $path,
                        language: $language,
                        last_modified: $timestamp,
                        content_hash: $hash
                    })
                """, {
                    "path": file_path,
                    "language": language,
                    "timestamp": datetime.now(),
                    "hash": content_hash
                })
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
            self.conn.execute("""
                MATCH (f:Function {file: $path})
                DETACH DELETE f
            """, {"path": file_path})

            # Delete variables from this file
            self.conn.execute("""
                MATCH (v:Variable {file: $path})
                DETACH DELETE v
            """, {"path": file_path})

            # Delete file node
            self.conn.execute("""
                MATCH (f:File {path: $path})
                DELETE f
            """, {"path": file_path})

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

            # Delete all nodes
            self.conn.execute("MATCH (f:Function) DELETE f")
            self.conn.execute("MATCH (v:Variable) DELETE v")
            self.conn.execute("MATCH (f:File) DELETE f")

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
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                hasher.update(chunk)
        return hasher.hexdigest()
