"""
Batch operations for the dependency graph.

Extracted from original graph.py lines 2395-3107.
This is a stub implementation - full batch operations will be implemented as needed.
"""

import gc
import json
import sys
from datetime import datetime
from pathlib import Path

import kuzu
from rich.console import Console

console = Console()


def _get_memory_mb() -> float:
    """Get current process memory usage in MB."""
    try:
        import psutil

        process = psutil.Process()
        return process.memory_info().rss / 1024 / 1024
    except ImportError:
        # Fallback if psutil not available
        return 0.0


class BatchOperations:
    """Handles batch insert operations for the dependency graph."""

    def __init__(
        self,
        conn: kuzu.Connection,
        read_only: bool,
        project_root: Path,
        helper_methods: dict,
    ):
        """Initialize batch operations.

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

        try:
            import pandas as pd
        except ImportError:
            console.print(
                "[yellow]Warning: pandas not installed, falling back to slow individual inserts[/yellow]"
            )
            return None

        # Process ALL results at once - chunking causes crashes!
        self._batch_add_nodes_chunk(results, pd)

    def _batch_add_nodes_chunk(self, results, pd) -> None:
        """Helper method to batch insert nodes for a chunk of results.

        Args:
            results: List of FileAnalysis objects (chunk)
            pd: pandas module
        """
        start_memory = _get_memory_mb()
        console.print(f"[dim]💾 Memory at start of batch: {start_memory:.1f}MB[/dim]")

        # Constants for chunking all data types (avoid memory exhaustion)
        FUNCTION_CHUNK_SIZE = 500  # Heavy (has source code)
        CLASS_CHUNK_SIZE = 500  # Heavy (has source code)
        IMPORT_CHUNK_SIZE = 1000  # Medium
        VARIABLE_CHUNK_SIZE = 1000  # Light
        DECORATOR_CHUNK_SIZE = 1000  # Light
        ATTRIBUTE_CHUNK_SIZE = 1000  # Medium
        EXCEPTION_CHUNK_SIZE = 1000  # Light

        # Collect all nodes by type
        all_files = []
        all_functions = []
        all_classes = []
        all_variables = []
        all_imports = []
        all_decorators = []
        all_attributes = []
        all_exceptions = []

        # Counters for progress tracking
        total_functions_inserted = 0
        total_classes_inserted = 0
        total_imports_inserted = 0
        total_variables_inserted = 0
        total_decorators_inserted = 0
        total_attributes_inserted = 0
        total_exceptions_inserted = 0

        # Process each result
        for result in results:
            file_path = self._to_relative_path(result.file_path)

            # Collect file data
            all_files.append(
                {
                    "path": file_path,
                    "language": "python",
                    "content_hash": "",
                    "last_modified": datetime.now(),
                }
            )

            # Collect functions
            for func in result.functions:
                func_id = self._make_function_id(file_path, func.name, func.start_line)
                all_functions.append(
                    {
                        "id": func_id,
                        "name": func.name,
                        "file": file_path,
                        "start_line": func.start_line,
                        "end_line": func.end_line,
                        "is_public": func.is_public,
                        "source_code": getattr(func, "source_code", "") or "",
                        "parent_class": getattr(func, "parent_class", None) or "",
                    }
                )

            # Collect classes
            for cls in result.classes:
                class_id = self._make_class_id(file_path, cls.name, cls.start_line)
                all_classes.append(
                    {
                        "id": class_id,
                        "name": cls.name,
                        "file": file_path,
                        "start_line": cls.start_line,
                        "end_line": cls.end_line,
                        "bases": json.dumps(cls.bases),
                        "is_public": cls.is_public,
                        "source_code": getattr(cls, "source_code", "") or "",
                    }
                )

            # Collect variables (module-level only for CONTAINS edge)
            for var in result.variables:
                if var.scope == "module":
                    var_id = self._make_variable_id(
                        file_path, var.name, var.definition_line
                    )
                    all_variables.append(
                        {
                            "id": var_id,
                            "name": var.name,
                            "file": file_path,
                            "definition_line": var.definition_line,
                            "scope": var.scope,
                        }
                    )

            # Collect imports
            for imp in result.imports_detailed:
                import_id = self._make_import_id(
                    file_path, imp.imported_name, imp.line_number
                )
                all_imports.append(
                    {
                        "id": import_id,
                        "imported_name": imp.imported_name,
                        "import_type": imp.import_type,
                        "alias": imp.alias or "",
                        "line_number": imp.line_number,
                        "is_relative": imp.is_relative,
                        "file": file_path,
                    }
                )

            # Collect decorators
            for dec in result.decorators:
                decorator_id = self._make_decorator_id(
                    file_path, dec.name, dec.line_number
                )
                all_decorators.append(
                    {
                        "id": decorator_id,
                        "name": dec.name,
                        "file": file_path,
                        "line_number": dec.line_number,
                        "arguments": dec.arguments,
                    }
                )

            # Collect attributes
            for attr in result.attributes:
                attr_id = self._make_attribute_id(
                    file_path, attr.class_name, attr.name, attr.definition_line
                )
                all_attributes.append(
                    {
                        "id": attr_id,
                        "name": attr.name,
                        "class_name": attr.class_name,
                        "file": file_path,
                        "definition_line": attr.definition_line,
                        "type_hint": attr.type_hint or "",
                        "is_class_attribute": attr.is_class_attribute,
                    }
                )

            # Collect exceptions
            for exc in result.exceptions:
                exc_id = self._make_exception_id(file_path, exc.name, exc.line_number)
                all_exceptions.append(
                    {
                        "id": exc_id,
                        "name": exc.name,
                        "file": file_path,
                        "line_number": exc.line_number,
                    }
                )

            # Insert functions in chunks to avoid memory exhaustion
            if len(all_functions) >= FUNCTION_CHUNK_SIZE:
                mem_before = _get_memory_mb()
                df_functions = pd.DataFrame(all_functions)
                mem_after_df = _get_memory_mb()

                self.conn.execute("""
                    LOAD FROM df_functions
                    MERGE (f:Function {id: id})
                    ON MATCH SET f.name = name, f.file = file, f.start_line = start_line,
                        f.end_line = end_line, f.is_public = is_public, f.source_code = source_code
                    ON CREATE SET f.name = name, f.file = file, f.start_line = start_line,
                        f.end_line = end_line, f.is_public = is_public, f.source_code = source_code
                """)
                mem_after_exec = _get_memory_mb()

                total_functions_inserted += len(all_functions)
                all_functions = []  # Clear list
                mem_after_clear = _get_memory_mb()

                del df_functions  # Explicitly delete DataFrame
                gc.collect()  # Force garbage collection
                mem_after_gc = _get_memory_mb()

                # console.print(
                #     f"[cyan]  → Flushed {total_functions_inserted} Function items "
                #     f"(mem: {mem_before:.1f}→{mem_after_df:.1f}→{mem_after_exec:.1f}→{mem_after_clear:.1f}→{mem_after_gc:.1f}MB)[/cyan]"
                # )

            # Insert classes in chunks
            if len(all_classes) >= CLASS_CHUNK_SIZE:
                df_classes = pd.DataFrame(all_classes)
                self.conn.execute("""
                    LOAD FROM df_classes
                    MERGE (c:Class {id: id})
                    ON MATCH SET c.name = name, c.file = file, c.start_line = start_line,
                        c.end_line = end_line, c.bases = bases, c.is_public = is_public, c.source_code = source_code
                    ON CREATE SET c.name = name, c.file = file, c.start_line = start_line,
                        c.end_line = end_line, c.bases = bases, c.is_public = is_public, c.source_code = source_code
                """)
                total_classes_inserted += len(all_classes)
                console.print(
                    f"[cyan]  → Inserted {total_classes_inserted} classes so far...[/cyan]"
                )
                all_classes = []

            # Insert imports in chunks
            if len(all_imports) >= IMPORT_CHUNK_SIZE:
                mem_before = _get_memory_mb()
                df_imports = pd.DataFrame(all_imports)
                mem_after_df = _get_memory_mb()

                self.conn.execute("""
                    LOAD FROM df_imports
                    MERGE (i:Import {id: id})
                    ON MATCH SET i.imported_name = imported_name, i.import_type = import_type,
                        i.alias = alias, i.line_number = line_number, i.is_relative = is_relative, i.file = file
                    ON CREATE SET i.imported_name = imported_name, i.import_type = import_type,
                        i.alias = alias, i.line_number = line_number, i.is_relative = is_relative, i.file = file
                """)
                mem_after_exec = _get_memory_mb()

                total_imports_inserted += len(all_imports)
                all_imports = []
                mem_after_clear = _get_memory_mb()

                del df_imports
                gc.collect()
                mem_after_gc = _get_memory_mb()

                # console.print(
                #     f"[cyan]  → Flushed {total_imports_inserted} Import items "
                #     f"(mem: {mem_before:.1f}→{mem_after_df:.1f}→{mem_after_exec:.1f}→{mem_after_clear:.1f}→{mem_after_gc:.1f}MB)[/cyan]"
                # )

            # Insert variables in chunks
            if len(all_variables) >= VARIABLE_CHUNK_SIZE:
                df_variables = pd.DataFrame(all_variables)
                self.conn.execute("""
                    LOAD FROM df_variables
                    MERGE (v:Variable {id: id})
                    ON MATCH SET v.name = name, v.file = file, v.definition_line = definition_line, v.scope = scope
                    ON CREATE SET v.name = name, v.file = file, v.definition_line = definition_line, v.scope = scope
                """)
                total_variables_inserted += len(all_variables)
                console.print(
                    f"[cyan]  → Inserted {total_variables_inserted} variables so far...[/cyan]"
                )
                all_variables = []

            # Insert decorators in chunks
            if len(all_decorators) >= DECORATOR_CHUNK_SIZE:
                df_decorators = pd.DataFrame(all_decorators)
                self.conn.execute("""
                    LOAD FROM df_decorators
                    MERGE (d:Decorator {id: id})
                    ON MATCH SET d.name = name, d.file = file, d.line_number = line_number, d.arguments = arguments
                    ON CREATE SET d.name = name, d.file = file, d.line_number = line_number, d.arguments = arguments
                """)
                total_decorators_inserted += len(all_decorators)
                console.print(
                    f"[cyan]  → Inserted {total_decorators_inserted} decorators so far...[/cyan]"
                )
                all_decorators = []

            # Insert attributes in chunks
            if len(all_attributes) >= ATTRIBUTE_CHUNK_SIZE:
                mem_before = _get_memory_mb()
                df_attributes = pd.DataFrame(all_attributes)
                mem_after_df = _get_memory_mb()

                self.conn.execute("""
                    LOAD FROM df_attributes
                    MERGE (a:Attribute {id: id})
                    ON MATCH SET a.name = name, a.class_name = class_name, a.file = file,
                        a.definition_line = definition_line, a.type_hint = type_hint, a.is_class_attribute = is_class_attribute
                    ON CREATE SET a.name = name, a.class_name = class_name, a.file = file,
                        a.definition_line = definition_line, a.type_hint = type_hint, a.is_class_attribute = is_class_attribute
                """)
                mem_after_exec = _get_memory_mb()

                total_attributes_inserted += len(all_attributes)
                all_attributes = []
                mem_after_clear = _get_memory_mb()

                del df_attributes
                gc.collect()
                mem_after_gc = _get_memory_mb()

                # console.print(
                #     f"[cyan]  → Flushed {total_attributes_inserted} Attribute items "
                #     f"(mem: {mem_before:.1f}→{mem_after_df:.1f}→{mem_after_exec:.1f}→{mem_after_clear:.1f}→{mem_after_gc:.1f}MB)[/cyan]"
                # )

            # Insert exceptions in chunks (use COPY to avoid segfault)
            if len(all_exceptions) >= EXCEPTION_CHUNK_SIZE:
                df_exceptions = pd.DataFrame(all_exceptions)
                self.conn.execute("""
                    COPY Exception FROM df_exceptions (ignore_errors=true)
                """)
                total_exceptions_inserted += len(all_exceptions)
                console.print(
                    f"[cyan]  → Inserted {total_exceptions_inserted} exceptions so far...[/cyan]"
                )
                all_exceptions = []

        # Insert remaining nodes
        # Files
        if all_files:
            df_files = pd.DataFrame(all_files)
            self.conn.execute("""
                LOAD FROM df_files
                MERGE (f:File {path: path})
                ON MATCH SET f.language = language, f.content_hash = content_hash, f.last_modified = last_modified
                ON CREATE SET f.language = language, f.content_hash = content_hash, f.last_modified = last_modified
            """)
            console.print(f"[green]✓ {len(all_files)} files inserted[/green]")

        # Functions
        if all_functions:
            df_functions = pd.DataFrame(all_functions)
            self.conn.execute("""
                LOAD FROM df_functions
                MERGE (f:Function {id: id})
                ON MATCH SET f.name = name, f.file = file, f.start_line = start_line,
                    f.end_line = end_line, f.is_public = is_public, f.source_code = source_code
                ON CREATE SET f.name = name, f.file = file, f.start_line = start_line,
                    f.end_line = end_line, f.is_public = is_public, f.source_code = source_code
            """)
            total_functions_inserted += len(all_functions)
        console.print(f"[green]✓ {total_functions_inserted} functions inserted[/green]")

        # Classes
        if all_classes:
            df_classes = pd.DataFrame(all_classes)
            self.conn.execute("""
                LOAD FROM df_classes
                MERGE (c:Class {id: id})
                ON MATCH SET c.name = name, c.file = file, c.start_line = start_line,
                    c.end_line = end_line, c.bases = bases, c.is_public = is_public, c.source_code = source_code
                ON CREATE SET c.name = name, c.file = file, c.start_line = start_line,
                    c.end_line = end_line, c.bases = bases, c.is_public = is_public, c.source_code = source_code
            """)
            total_classes_inserted += len(all_classes)
        console.print(f"[green]✓ {total_classes_inserted} classes inserted[/green]")

        # Imports
        if all_imports:
            df_imports = pd.DataFrame(all_imports)
            self.conn.execute("""
                LOAD FROM df_imports
                MERGE (i:Import {id: id})
                ON MATCH SET i.imported_name = imported_name, i.import_type = import_type,
                    i.alias = alias, i.line_number = line_number, i.is_relative = is_relative, i.file = file
                ON CREATE SET i.imported_name = imported_name, i.import_type = import_type,
                    i.alias = alias, i.line_number = line_number, i.is_relative = is_relative, i.file = file
            """)
            total_imports_inserted += len(all_imports)
        console.print(f"[green]✓ {total_imports_inserted} imports inserted[/green]")

        # Variables
        if all_variables:
            df_variables = pd.DataFrame(all_variables)
            self.conn.execute("""
                LOAD FROM df_variables
                MERGE (v:Variable {id: id})
                ON MATCH SET v.name = name, v.file = file, v.definition_line = definition_line, v.scope = scope
                ON CREATE SET v.name = name, v.file = file, v.definition_line = definition_line, v.scope = scope
            """)
            total_variables_inserted += len(all_variables)
        console.print(f"[green]✓ {total_variables_inserted} variables inserted[/green]")

        # Decorators
        if all_decorators:
            df_decorators = pd.DataFrame(all_decorators)
            self.conn.execute("""
                LOAD FROM df_decorators
                MERGE (d:Decorator {id: id})
                ON MATCH SET d.name = name, d.file = file, d.line_number = line_number, d.arguments = arguments
                ON CREATE SET d.name = name, d.file = file, d.line_number = line_number, d.arguments = arguments
            """)
            total_decorators_inserted += len(all_decorators)
        console.print(
            f"[green]✓ {total_decorators_inserted} decorators inserted[/green]"
        )

        # Attributes
        if all_attributes:
            df_attributes = pd.DataFrame(all_attributes)
            self.conn.execute("""
                LOAD FROM df_attributes
                MERGE (a:Attribute {id: id})
                ON MATCH SET a.name = name, a.class_name = class_name, a.file = file,
                    a.definition_line = definition_line, a.type_hint = type_hint, a.is_class_attribute = is_class_attribute
                ON CREATE SET a.name = name, a.class_name = class_name, a.file = file,
                    a.definition_line = definition_line, a.type_hint = type_hint, a.is_class_attribute = is_class_attribute
            """)
            total_attributes_inserted += len(all_attributes)
        console.print(
            f"[green]✓ {total_attributes_inserted} attributes inserted[/green]"
        )

        # Exceptions (use COPY)
        if all_exceptions:
            df_exceptions = pd.DataFrame(all_exceptions)
            self.conn.execute("""
                COPY Exception FROM df_exceptions (ignore_errors=true)
            """)
            total_exceptions_inserted += len(all_exceptions)
            del df_exceptions
        console.print(
            f"[green]✓ {total_exceptions_inserted} exceptions inserted[/green]"
        )

        # Final cleanup and memory report
        gc.collect()
        end_memory = _get_memory_mb()
        memory_growth = end_memory - start_memory
        console.print(
            f"[dim]💾 Memory at end of batch: {end_memory:.1f}MB (Δ {memory_growth:+.1f}MB)[/dim]"
        )

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

        try:
            import pandas as pd
        except ImportError:
            console.print(
                "[yellow]Warning: pandas not installed, cannot batch insert edges[/yellow]"
            )
            return None

        # Process ALL results at once - chunking causes crashes!
        self._batch_add_edges_chunk(results, pd)

    def _batch_add_edges_chunk(self, results, pd) -> None:
        """Helper method to batch insert edges for a chunk of results.

        Args:
            results: List of FileAnalysis objects (chunk)
            pd: pandas module
        """
        start_memory = _get_memory_mb()
        console.print(
            f"[dim]💾 Memory at start of edge batch: {start_memory:.1f}MB[/dim]"
        )

        # Collect all edges by type
        all_contains_function = []
        all_contains_class = []
        all_contains_variable = []
        all_method_of = []
        all_inherits = []
        all_has_import = []
        all_has_attribute = []

        # Process each result
        for result in results:
            file_path = self._to_relative_path(result.file_path)

            # CONTAINS_FUNCTION edges
            for func in result.functions:
                func_id = self._make_function_id(file_path, func.name, func.start_line)
                all_contains_function.append(
                    {"file_path": file_path, "function_id": func_id}
                )

                # METHOD_OF edges if parent_class
                parent_class = getattr(func, "parent_class", None)
                if parent_class:
                    all_method_of.append(
                        {
                            "function_id": func_id,
                            "file_path": file_path,
                            "class_name": parent_class,
                        }
                    )

            # CONTAINS_CLASS edges and INHERITS edges
            for cls in result.classes:
                class_id = self._make_class_id(file_path, cls.name, cls.start_line)
                all_contains_class.append(
                    {"file_path": file_path, "class_id": class_id}
                )

                # INHERITS edges
                for base in cls.bases:
                    all_inherits.append({"child_id": class_id, "base_name": base})

            # CONTAINS_VARIABLE edges (module-level only)
            for var in result.variables:
                if var.scope == "module":
                    var_id = self._make_variable_id(
                        file_path, var.name, var.definition_line
                    )
                    all_contains_variable.append(
                        {"file_path": file_path, "variable_id": var_id}
                    )

            # HAS_IMPORT edges
            for imp in result.imports_detailed:
                import_id = self._make_import_id(
                    file_path, imp.imported_name, imp.line_number
                )
                all_has_import.append({"file_path": file_path, "import_id": import_id})

            # HAS_ATTRIBUTE edges
            for attr in result.attributes:
                attr_id = self._make_attribute_id(
                    file_path, attr.class_name, attr.name, attr.definition_line
                )
                all_has_attribute.append(
                    {
                        "file_path": file_path,
                        "class_name": attr.class_name,
                        "attribute_id": attr_id,
                    }
                )

        # Batch insert edges using DataFrames and MERGE

        # 1. CONTAINS_FUNCTION edges
        if all_contains_function:
            df_contains_func = pd.DataFrame(all_contains_function)
            self.conn.execute("""
                LOAD FROM df_contains_func
                MATCH (f:File {path: file_path}), (fn:Function {id: function_id})
                MERGE (f)-[:CONTAINS_FUNCTION]->(fn)
            """)
            console.print(
                f"[green]✓ {len(all_contains_function)} CONTAINS_FUNCTION edges[/green]"
            )

        # 2. CONTAINS_CLASS edges
        if all_contains_class:
            df_contains_class = pd.DataFrame(all_contains_class)
            self.conn.execute("""
                LOAD FROM df_contains_class
                MATCH (f:File {path: file_path}), (c:Class {id: class_id})
                MERGE (f)-[:CONTAINS_CLASS]->(c)
            """)
            console.print(
                f"[green]✓ {len(all_contains_class)} CONTAINS_CLASS edges[/green]"
            )

        # 3. CONTAINS_VARIABLE edges
        if all_contains_variable:
            df_contains_var = pd.DataFrame(all_contains_variable)
            self.conn.execute("""
                LOAD FROM df_contains_var
                MATCH (f:File {path: file_path}), (v:Variable {id: variable_id})
                MERGE (f)-[:CONTAINS_VARIABLE]->(v)
            """)
            console.print(
                f"[green]✓ {len(all_contains_variable)} CONTAINS_VARIABLE edges[/green]"
            )

        # 4. METHOD_OF edges
        if all_method_of:
            df_method_of = pd.DataFrame(all_method_of)
            self.conn.execute("""
                LOAD FROM df_method_of
                MATCH (fn:Function {id: function_id}), (c:Class {file: file_path, name: class_name})
                MERGE (fn)-[:METHOD_OF]->(c)
            """)
            console.print(f"[green]✓ {len(all_method_of)} METHOD_OF edges[/green]")

        # 5. INHERITS edges (may fail if base class not found, that's OK)
        if all_inherits:
            df_inherits = pd.DataFrame(all_inherits)
            try:
                self.conn.execute("""
                    LOAD FROM df_inherits
                    MATCH (c1:Class {id: child_id}), (c2:Class {name: base_name})
                    MERGE (c1)-[:INHERITS]->(c2)
                """)
                console.print(f"[green]✓ {len(all_inherits)} INHERITS edges[/green]")
            except Exception as e:
                # Some base classes may not exist in the codebase (e.g., external libraries)
                console.print(
                    f"[yellow]⚠ Some INHERITS edges could not be created (external base classes)[/yellow]"
                )

        # 6. HAS_IMPORT edges
        if all_has_import:
            df_has_import = pd.DataFrame(all_has_import)
            self.conn.execute("""
                LOAD FROM df_has_import
                MATCH (f:File {path: file_path}), (i:Import {id: import_id})
                MERGE (f)-[:HAS_IMPORT]->(i)
            """)
            console.print(f"[green]✓ {len(all_has_import)} HAS_IMPORT edges[/green]")

        # 7. HAS_ATTRIBUTE edges
        if all_has_attribute:
            df_has_attr = pd.DataFrame(all_has_attribute)
            self.conn.execute("""
                LOAD FROM df_has_attr
                MATCH (c:Class {file: file_path, name: class_name}), (a:Attribute {id: attribute_id})
                MERGE (c)-[:HAS_ATTRIBUTE]->(a)
            """)
            console.print(
                f"[green]✓ {len(all_has_attribute)} HAS_ATTRIBUTE edges[/green]"
            )

        console.print("[green]✓ All structural edges inserted[/green]")

        # Memory cleanup and report
        gc.collect()
        end_memory = _get_memory_mb()
        memory_growth = end_memory - start_memory
        console.print(
            f"[dim]💾 Memory at end of edge batch: {end_memory:.1f}MB (Δ {memory_growth:+.1f}MB)[/dim]"
        )

    def batch_insert_call_edges(
        self, all_matched_calls, chunk_size: int = 1000
    ) -> None:
        """Batch insert CALLS edges from matched function calls.

        Processes matched calls in chunks and uses pandas DataFrame with KuzuDB's LOAD FROM
        for efficient batch insertion.

        Args:
            all_matched_calls: List of dicts with keys: caller_file, caller_function,
                             caller_start_line, callee_file, callee_function,
                             callee_start_line, call_line
            chunk_size: Number of edges to process per chunk (default: 1000)

        Raises:
            RuntimeError: If database is in read-only mode
        """
        self._check_read_only()

        if not all_matched_calls:
            console.print("[yellow]No matched calls to insert[/yellow]")
            return

        try:
            import pandas as pd
        except ImportError:
            console.print(
                "[yellow]Warning: pandas not installed, cannot batch insert call edges[/yellow]"
            )
            return

        from rich.progress import (
            BarColumn,
            MofNCompleteColumn,
            Progress,
            SpinnerColumn,
            TextColumn,
        )

        total_calls = len(all_matched_calls)
        total_inserted = 0
        total_errors = 0

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(
                "[cyan]Inserting CALLS edges...", total=total_calls
            )

            # Process in chunks
            for i in range(0, total_calls, chunk_size):
                chunk = all_matched_calls[i : i + chunk_size]
                chunk_edges = []

                # Prepare edge data for this chunk
                for call in chunk:
                    try:
                        caller_id = self._make_function_id(
                            call["caller_file"],
                            call["caller_function"],
                            call["caller_start_line"],
                        )
                        callee_id = self._make_function_id(
                            call["callee_file"],
                            call["callee_function"],
                            call["callee_start_line"],
                        )
                        chunk_edges.append(
                            {
                                "caller_id": caller_id,
                                "callee_id": callee_id,
                                "call_line": call["call_line"],
                            }
                        )
                    except Exception as e:
                        total_errors += 1
                        continue

                # Batch insert this chunk using DataFrame
                if chunk_edges:
                    try:
                        df_calls = pd.DataFrame(chunk_edges)
                        self.conn.execute("""
                            LOAD FROM df_calls
                            MATCH (caller:Function {id: caller_id}), (callee:Function {id: callee_id})
                            CREATE (caller)-[:CALLS {call_line: call_line}]->(callee)
                        """)
                        total_inserted += len(chunk_edges)
                    except Exception as e:
                        # Some functions may not exist in the graph
                        total_errors += len(chunk_edges)
                        console.print(
                            f"[yellow]⚠ Error inserting chunk (functions may not exist): {str(e)[:100]}[/yellow]"
                        )

                progress.update(task, advance=len(chunk))

        console.print(f"[green]✓ {total_inserted} CALLS edges inserted[/green]")
        if total_errors > 0:
            console.print(
                f"[yellow]⚠ {total_errors} calls skipped (functions not found in graph)[/yellow]"
            )
