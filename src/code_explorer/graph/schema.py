"""
Database schema management for the dependency graph.

Extracted from original graph.py lines 151-430.
"""

import kuzu


class SchemaManager:
    """Manages KuzuDB schema creation and versioning."""

    def __init__(self, conn: kuzu.Connection):
        """Initialize schema manager.

        Args:
            conn: KuzuDB connection to use for schema operations
        """
        self.conn = conn

    def detect_schema_version(self) -> str:
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

    def create_schema(self) -> None:
        """Create KuzuDB schema with node and edge tables."""
        try:
            # Create File node table
            self.conn.execute("""
                CREATE NODE TABLE IF NOT EXISTS File(
                    path STRING,
                    language STRING,
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

            # Consolidated USES + DEFINES → REFERENCES with context property
            self.conn.execute("""
                CREATE REL TABLE IF NOT EXISTS REFERENCES(
                    FROM Function TO Variable,
                    line_number INT64,
                    context STRING
                )
            """)

            # CONTAINS now supports File -> Function, File -> Class, File -> Variable
            self.conn.execute("""
                CREATE REL TABLE IF NOT EXISTS CONTAINS_FUNCTION(
                    FROM File TO Function
                )
            """)

            self.conn.execute("""
                CREATE REL TABLE IF NOT EXISTS CONTAINS_CLASS(
                    FROM File TO Class
                )
            """)

            self.conn.execute("""
                CREATE REL TABLE IF NOT EXISTS CONTAINS_VARIABLE(
                    FROM File TO Variable
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

            # DEPENDS_ON edge: Class depends on Class (composition, dependency injection)
            self.conn.execute("""
                CREATE REL TABLE IF NOT EXISTS DEPENDS_ON(
                    FROM Class TO Class,
                    dependency_type STRING,
                    line_number INT64
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

            # DECORATOR_RESOLVES_TO removed - redundant with DECORATED_BY

            # Create HAS_ATTRIBUTE edge: Class has Attribute
            self.conn.execute("""
                CREATE REL TABLE IF NOT EXISTS HAS_ATTRIBUTE(
                    FROM Class TO Attribute
                )
            """)

            # Consolidated ACCESSES + MODIFIES → ACCESSES with access_type property
            self.conn.execute("""
                CREATE REL TABLE IF NOT EXISTS ACCESSES(
                    FROM Function TO Attribute,
                    line_number INT64,
                    access_type STRING
                )
            """)

            # Consolidated RAISES + CATCHES → HANDLES_EXCEPTION with context property
            self.conn.execute("""
                CREATE REL TABLE IF NOT EXISTS HANDLES_EXCEPTION(
                    FROM Function TO Exception,
                    line_number INT64,
                    context STRING
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
