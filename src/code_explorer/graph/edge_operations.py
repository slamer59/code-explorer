"""
Edge CRUD operations for the dependency graph.

Extracted from original graph.py lines 1280-1529.
"""

from pathlib import Path

import kuzu


class EdgeOperations:
    """Handles CRUD operations for all edge types in the dependency graph."""

    def __init__(
        self,
        conn: kuzu.Connection,
        read_only: bool,
        project_root: Path,
        helper_methods: dict,
    ):
        """Initialize edge operations.

        Args:
            conn: KuzuDB connection to use for operations
            read_only: Whether database is in read-only mode
            project_root: Root directory for relative path calculations
            helper_methods: Dictionary containing helper methods from facade
        """
        self.conn = conn
        self.read_only = read_only
        self.project_root = project_root
        self._make_function_id = helper_methods["make_function_id"]
        self._make_attribute_id = helper_methods["make_attribute_id"]
        self._make_exception_id = helper_methods["make_exception_id"]
        self._make_variable_id = helper_methods["make_variable_id"]
        self._make_class_id = helper_methods["make_class_id"]

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

    def add_exception_handling(
        self,
        function_file: str,
        function_name: str,
        function_start_line: int,
        exception_name: str,
        exception_file: str,
        exception_line: int,
        context: str,
    ) -> None:
        """Add exception handling edge (raise or catch).

        Args:
            function_file: File where function is defined
            function_name: Name of function
            function_start_line: Starting line of function
            exception_name: Name of exception
            exception_file: File where exception is raised/caught
            exception_line: Line number where exception appears
            context: "raise" or "catch"

        Raises:
            RuntimeError: If database is in read-only mode
        """
        self._check_read_only()
        func_id = self._make_function_id(
            function_file, function_name, function_start_line
        )
        exc_id = self._make_exception_id(exception_file, exception_name, exception_line)

        try:
            self.conn.execute(
                """
                MATCH (func:Function {id: $func_id}), (exc:Exception {id: $exc_id})
                CREATE (func)-[:HANDLES_EXCEPTION {line_number: $line_number, context: $context}]->(exc)
            """,
                {
                    "func_id": func_id,
                    "exc_id": exc_id,
                    "line_number": exception_line,
                    "context": context,
                },
            )
        except Exception as e:
            # Nodes may not exist yet
            pass

    def add_attribute_access(
        self,
        function_file: str,
        function_name: str,
        function_start_line: int,
        class_name: str,
        attribute_name: str,
        attribute_file: str,
        attribute_line: int,
        access_type: str,
        access_line: int,
    ) -> None:
        """Add attribute access edge.

        Args:
            function_file: File where function is defined
            function_name: Name of function accessing attribute
            function_start_line: Starting line of function
            class_name: Name of class owning the attribute
            attribute_name: Name of attribute
            attribute_file: File where attribute is defined
            attribute_line: Line where attribute is defined
            access_type: "read", "write", or "read_write"
            access_line: Line where access occurs

        Raises:
            RuntimeError: If database is in read-only mode
        """
        self._check_read_only()
        func_id = self._make_function_id(
            function_file, function_name, function_start_line
        )
        attr_id = self._make_attribute_id(
            attribute_file, class_name, attribute_name, attribute_line
        )

        try:
            self.conn.execute(
                """
                MATCH (func:Function {id: $func_id}), (attr:Attribute {id: $attr_id})
                CREATE (func)-[:ACCESSES {line_number: $line_number, access_type: $access_type}]->(attr)
            """,
                {
                    "func_id": func_id,
                    "attr_id": attr_id,
                    "line_number": access_line,
                    "access_type": access_type,
                },
            )
        except Exception as e:
            # Nodes may not exist yet
            pass

    def add_class_dependency(
        self,
        dependent_class_file: str,
        dependent_class_name: str,
        dependent_class_start_line: int,
        dependency_class_file: str,
        dependency_class_name: str,
        dependency_class_start_line: int,
        dependency_type: str,
        line_number: int,
    ) -> None:
        """Add class dependency edge (composition, dependency injection).

        Args:
            dependent_class_file: File where dependent class is defined
            dependent_class_name: Name of class that depends
            dependent_class_start_line: Starting line of dependent class
            dependency_class_file: File where dependency class is defined
            dependency_class_name: Name of class that is depended upon
            dependency_class_start_line: Starting line of dependency class
            dependency_type: "composition", "injection", or "inheritance"
            line_number: Line where dependency is declared

        Raises:
            RuntimeError: If database is in read-only mode
        """
        self._check_read_only()
        dependent_id = self._make_class_id(
            dependent_class_file, dependent_class_name, dependent_class_start_line
        )
        dependency_id = self._make_class_id(
            dependency_class_file, dependency_class_name, dependency_class_start_line
        )

        try:
            self.conn.execute(
                """
                MATCH (dependent:Class {id: $dependent_id}), (dependency:Class {id: $dependency_id})
                CREATE (dependent)-[:DEPENDS_ON {dependency_type: $dep_type, line_number: $line_number}]->(dependency)
            """,
                {
                    "dependent_id": dependent_id,
                    "dependency_id": dependency_id,
                    "dep_type": dependency_type,
                    "line_number": line_number,
                },
            )
        except Exception as e:
            # Classes may not exist yet
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
            # Create REFERENCES edge with context ("define" or "use")
            context = "define" if is_definition else "use"
            self.conn.execute(
                """
                MATCH (func:Function {id: $func_id}), (var:Variable {id: $var_id})
                CREATE (func)-[:REFERENCES {line_number: $line_number, context: $context}]->(var)
            """,
                {
                    "func_id": func_id,
                    "var_id": var_id,
                    "line_number": usage_line,
                    "context": context,
                },
            )
        except Exception as e:
            # Nodes may not exist yet
            pass
