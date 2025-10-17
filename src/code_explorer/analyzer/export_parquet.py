"""
Export FileAnalysis results to Parquet format for KuzuDB bulk loading.

This module converts FileAnalysis objects into Parquet files that can be
efficiently loaded into KuzuDB using COPY FROM operations.
"""

import hashlib
from pathlib import Path
from typing import List, Optional

import polars as pl

from code_explorer.analyzer.models import FileAnalysis


def to_relative_path(file_path: str, project_root: Path) -> str:
    """Convert absolute path to relative path from project root.

    Args:
        file_path: Absolute or relative file path
        project_root: Root directory for relative paths

    Returns:
        Relative path from project root
    """
    try:
        path = Path(file_path)
        if path.is_absolute():
            return str(path.relative_to(project_root))
        return file_path
    except ValueError:
        # Path is not relative to project_root, return as-is
        return file_path


def make_function_id(file: str, name: str, start_line: int, project_root: Path) -> str:
    """Create stable hash-based ID for a function.

    Args:
        file: File path
        name: Function name
        start_line: Starting line number
        project_root: Root directory for relative paths

    Returns:
        Hash-based identifier (e.g., 'fn_a1b2c3d4e5f6')
    """
    rel_path = to_relative_path(file, project_root)
    content = f"{rel_path}::{name}::{start_line}"
    hash_digest = hashlib.sha256(content.encode()).hexdigest()[:12]
    return f"fn_{hash_digest}"


def make_class_id(file: str, name: str, start_line: int, project_root: Path) -> str:
    """Create stable hash-based ID for a class.

    Args:
        file: File path
        name: Class name
        start_line: Starting line number
        project_root: Root directory for relative paths

    Returns:
        Hash-based identifier (e.g., 'cls_a1b2c3d4e5f6')
    """
    rel_path = to_relative_path(file, project_root)
    content = f"{rel_path}::{name}::{start_line}"
    hash_digest = hashlib.sha256(content.encode()).hexdigest()[:12]
    return f"cls_{hash_digest}"


def make_variable_id(file: str, name: str, line: int, scope: str, project_root: Path) -> str:
    """Create stable hash-based ID for a variable.

    Args:
        file: File path
        name: Variable name
        line: Definition line number
        scope: Variable scope (e.g., "module" or "function:func_name")
        project_root: Root directory for relative paths

    Returns:
        Hash-based identifier (e.g., 'var_a1b2c3d4e5f6')
    """
    rel_path = to_relative_path(file, project_root)
    content = f"{rel_path}::{name}::{line}::{scope}"
    hash_digest = hashlib.sha256(content.encode()).hexdigest()[:12]
    return f"var_{hash_digest}"


def make_import_id(file: str, imported_name: str, line_number: int, project_root: Path) -> str:
    """Create stable hash-based ID for an import.

    Args:
        file: File path
        imported_name: Name of imported entity
        line_number: Line number of import
        project_root: Root directory for relative paths

    Returns:
        Hash-based identifier (e.g., 'imp_a1b2c3d4e5f6')
    """
    rel_path = to_relative_path(file, project_root)
    content = f"{rel_path}::{imported_name}::{line_number}"
    hash_digest = hashlib.sha256(content.encode()).hexdigest()[:12]
    return f"imp_{hash_digest}"


def make_decorator_id(file: str, name: str, line_number: int, project_root: Path) -> str:
    """Create stable hash-based ID for a decorator.

    Args:
        file: File path
        name: Decorator name
        line_number: Line number of decorator application
        project_root: Root directory for relative paths

    Returns:
        Hash-based identifier (e.g., 'dec_a1b2c3d4e5f6')
    """
    rel_path = to_relative_path(file, project_root)
    content = f"{rel_path}::{name}::{line_number}"
    hash_digest = hashlib.sha256(content.encode()).hexdigest()[:12]
    return f"dec_{hash_digest}"


def make_attribute_id(
    file: str, class_name: str, name: str, line: int, project_root: Path
) -> str:
    """Create stable hash-based ID for an attribute.

    Args:
        file: File path
        class_name: Name of class owning the attribute
        name: Attribute name
        line: Definition line number
        project_root: Root directory for relative paths

    Returns:
        Hash-based identifier (e.g., 'attr_a1b2c3d4e5f6')
    """
    rel_path = to_relative_path(file, project_root)
    content = f"{rel_path}::{class_name}::{name}::{line}"
    hash_digest = hashlib.sha256(content.encode()).hexdigest()[:12]
    return f"attr_{hash_digest}"


def make_exception_id(
    file: str,
    name: str,
    line_number: int,
    context: str,
    function_name: Optional[str],
    project_root: Path
) -> str:
    """Create stable hash-based ID for an exception.

    Args:
        file: File path
        name: Exception name
        line_number: Line number where exception is raised/caught
        context: Exception context ("raise" or "catch")
        function_name: Optional function name where exception appears
        project_root: Root directory for relative paths

    Returns:
        Hash-based identifier (e.g., 'exc_a1b2c3d4e5f6')
    """
    rel_path = to_relative_path(file, project_root)
    func_part = f"::{function_name}" if function_name else ""
    content = f"{rel_path}::{name}::{line_number}::{context}{func_part}"
    hash_digest = hashlib.sha256(content.encode()).hexdigest()[:12]
    return f"exc_{hash_digest}"


def export_to_parquet(
    results: List[FileAnalysis],
    output_dir: Path,
    project_root: Path,
    resolved_calls: Optional[List[dict]] = None,
) -> None:
    """Export FileAnalysis results to Parquet files for bulk loading.

    Creates node and edge Parquet files in the output directory structure:
    - nodes/: files.parquet, functions.parquet, classes.parquet, etc.
    - edges/: contains_function.parquet, calls.parquet, etc.

    Args:
        results: List of FileAnalysis objects to export
        output_dir: Directory where Parquet files will be written
        project_root: Root directory for computing relative paths
        resolved_calls: Optional list of resolved call data from CallResolver.resolve_all_calls()

    Note:
        - INHERITS edges are skipped (not implemented)
        - REFERENCES context always uses empty string ""
        - DECORATED_BY generates target IDs from file + target_name + line
        - Empty DataFrames create Parquet files with 0 rows but correct schema
    """
    # Create output directories
    nodes_dir = output_dir / "nodes"
    edges_dir = output_dir / "edges"
    nodes_dir.mkdir(parents=True, exist_ok=True)
    edges_dir.mkdir(parents=True, exist_ok=True)

    # Collect all data
    files_data = []
    functions_data = []
    classes_data = []
    variables_data = []
    imports_data = []
    decorators_data = []
    attributes_data = []
    exceptions_data = []

    contains_function_data = []
    contains_class_data = []
    contains_variable_data = []
    method_of_data = []
    has_import_data = []
    decorated_by_data = []
    has_attribute_data = []
    references_data = []
    accesses_data = []
    handles_exception_data = []

    # Process each FileAnalysis result
    for result in results:
        file_path = result.file_path
        rel_file_path = to_relative_path(file_path, project_root)

        # File node
        files_data.append({
            "path": rel_file_path,
            "language": "python",
            "content_hash": result.content_hash,
        })

        # Function nodes and edges
        # Deduplicate functions by unique key to prevent ID collisions
        seen_funcs = set()
        for func in result.functions:
            func_key = (file_path, func.name, func.start_line)
            if func_key in seen_funcs:
                continue  # Skip duplicate
            seen_funcs.add(func_key)

            func_id = make_function_id(file_path, func.name, func.start_line, project_root)
            functions_data.append({
                "id": func_id,
                "name": func.name,
                "file": rel_file_path,
                "start_line": func.start_line,
                "end_line": func.end_line,
                "is_public": func.is_public,
                "source_code": func.source_code or "",
            })

            # CONTAINS_FUNCTION edge
            contains_function_data.append({
                "from": rel_file_path,
                "to": func_id,
            })

            # METHOD_OF edge (if parent_class exists)
            if func.parent_class:
                # Find class ID by matching class name
                for cls in result.classes:
                    if cls.name == func.parent_class:
                        class_id = make_class_id(file_path, cls.name, cls.start_line, project_root)
                        method_of_data.append({
                            "from": func_id,
                            "to": class_id,
                        })
                        break

        # Class nodes and edges
        # Deduplicate classes by unique key to prevent ID collisions
        seen_classes = set()
        for cls in result.classes:
            cls_key = (file_path, cls.name, cls.start_line)
            if cls_key in seen_classes:
                continue  # Skip duplicate
            seen_classes.add(cls_key)

            class_id = make_class_id(file_path, cls.name, cls.start_line, project_root)

            # Convert bases list to comma-separated string or empty string
            bases_str = ",".join(cls.bases) if cls.bases else ""

            classes_data.append({
                "id": class_id,
                "name": cls.name,
                "file": rel_file_path,
                "start_line": cls.start_line,
                "end_line": cls.end_line,
                "bases": bases_str,
                "is_public": cls.is_public,
                "source_code": cls.source_code or "",
            })

            # CONTAINS_CLASS edge
            contains_class_data.append({
                "from": rel_file_path,
                "to": class_id,
            })

        # Variable nodes and edges
        # Deduplicate variables by unique key to prevent ID collisions
        seen_vars = set()
        for var in result.variables:
            var_key = (file_path, var.name, var.definition_line, var.scope)
            if var_key in seen_vars:
                continue  # Skip duplicate
            seen_vars.add(var_key)

            var_id = make_variable_id(file_path, var.name, var.definition_line, var.scope, project_root)
            variables_data.append({
                "id": var_id,
                "name": var.name,
                "file": rel_file_path,
                "definition_line": var.definition_line,
                "scope": var.scope,
            })

            # CONTAINS_VARIABLE edge
            contains_variable_data.append({
                "from": rel_file_path,
                "to": var_id,
            })

        # Variable usage -> REFERENCES edges
        for usage in result.variable_usage:
            # Find function ID
            for func in result.functions:
                if func.name == usage.function_name:
                    func_id = make_function_id(file_path, func.name, func.start_line, project_root)

                    # Find variable ID
                    for var in result.variables:
                        if var.name == usage.variable_name:
                            var_id = make_variable_id(file_path, var.name, var.definition_line, var.scope, project_root)
                            references_data.append({
                                "from": func_id,
                                "to": var_id,
                                "line_number": usage.usage_line,
                                "context": "",  # Use empty string as approved
                            })
                            break
                    break

        # Import nodes and edges
        # Deduplicate imports by unique key to prevent ID collisions
        seen_imps = set()
        for imp in result.imports_detailed:
            imp_key = (file_path, imp.imported_name, imp.line_number)
            if imp_key in seen_imps:
                continue  # Skip duplicate
            seen_imps.add(imp_key)

            imp_id = make_import_id(file_path, imp.imported_name, imp.line_number, project_root)
            imports_data.append({
                "id": imp_id,
                "imported_name": imp.imported_name,
                "import_type": imp.import_type,
                "alias": imp.alias or "",
                "line_number": imp.line_number,
                "is_relative": imp.is_relative,
                "file": rel_file_path,
            })

            # HAS_IMPORT edge
            has_import_data.append({
                "from": rel_file_path,
                "to": imp_id,
            })

        # Decorator nodes and edges
        # Deduplicate decorators by unique key to prevent ID collisions
        seen_decs = set()
        for dec in result.decorators:
            dec_key = (file_path, dec.name, dec.line_number)
            if dec_key in seen_decs:
                continue  # Skip duplicate
            seen_decs.add(dec_key)

            dec_id = make_decorator_id(file_path, dec.name, dec.line_number, project_root)
            decorators_data.append({
                "id": dec_id,
                "name": dec.name,
                "file": rel_file_path,
                "line_number": dec.line_number,
                "arguments": dec.arguments or "",
            })

            # DECORATED_BY edge - generate target ID
            if dec.target_type == "function":
                # Find function by name
                for func in result.functions:
                    if func.name == dec.target_name:
                        target_id = make_function_id(file_path, func.name, func.start_line, project_root)
                        decorated_by_data.append({
                            "from": target_id,
                            "to": dec_id,
                            "position": 0,  # Default position
                        })
                        break
            elif dec.target_type == "class":
                # Find class by name
                for cls in result.classes:
                    if cls.name == dec.target_name:
                        target_id = make_class_id(file_path, cls.name, cls.start_line, project_root)
                        decorated_by_data.append({
                            "from": target_id,
                            "to": dec_id,
                            "position": 0,  # Default position
                        })
                        break

        # Attribute nodes and edges
        # Deduplicate attributes by unique key to prevent ID collisions
        seen_attrs = set()
        for attr in result.attributes:
            attr_key = (file_path, attr.class_name, attr.name, attr.definition_line)
            if attr_key in seen_attrs:
                continue  # Skip duplicate
            seen_attrs.add(attr_key)

            attr_id = make_attribute_id(
                file_path, attr.class_name, attr.name, attr.definition_line, project_root
            )
            attributes_data.append({
                "id": attr_id,
                "name": attr.name,
                "class_name": attr.class_name,
                "file": rel_file_path,
                "definition_line": attr.definition_line,
                "type_hint": attr.type_hint or "",
                "is_class_attribute": attr.is_class_attribute,
            })

            # HAS_ATTRIBUTE edge
            # Find class ID by matching class name
            for cls in result.classes:
                if cls.name == attr.class_name:
                    class_id = make_class_id(file_path, cls.name, cls.start_line, project_root)
                    has_attribute_data.append({
                        "from": class_id,
                        "to": attr_id,
                    })
                    break

        # Exception nodes and edges
        # Deduplicate exceptions by unique key to prevent ID collisions
        seen_excs = set()
        for exc in result.exceptions:
            exc_key = (file_path, exc.name, exc.line_number, exc.context, exc.function_name or "")
            if exc_key in seen_excs:
                continue  # Skip duplicate
            seen_excs.add(exc_key)

            exc_id = make_exception_id(file_path, exc.name, exc.line_number, exc.context, exc.function_name, project_root)
            exceptions_data.append({
                "id": exc_id,
                "name": exc.name,
                "file": rel_file_path,
                "line_number": exc.line_number,
            })

            # HANDLES_EXCEPTION edge
            if exc.function_name:
                # Find function ID
                for func in result.functions:
                    if func.name == exc.function_name:
                        func_id = make_function_id(file_path, func.name, func.start_line, project_root)
                        handles_exception_data.append({
                            "from": func_id,
                            "to": exc_id,
                            "line_number": exc.line_number,
                            "context": exc.context,  # "raise" or "catch"
                        })
                        break

        # Note: ACCESSES edges are not directly available in FileAnalysis
        # They would need to be extracted from function bodies or added to the analyzer

    # Build efficient lookup dictionaries for edge creation (O(1) instead of O(n²))
    func_by_name = {}  # name -> (id, start_line)
    for func_data in functions_data:
        if func_data["name"] not in func_by_name:
            func_by_name[func_data["name"]] = (func_data["id"], func_data["start_line"])

    class_by_name = {}  # name -> (id, start_line)
    for cls_data in classes_data:
        if cls_data["name"] not in class_by_name:
            class_by_name[cls_data["name"]] = (cls_data["id"], cls_data["start_line"])

    var_by_name_scope = {}  # (name, scope) -> id
    for var_data in variables_data:
        key = (var_data["name"], var_data["scope"])
        if key not in var_by_name_scope:
            var_by_name_scope[key] = var_data["id"]

    # Process resolved CALLS edges if provided
    calls_data = []
    if resolved_calls:
        for call in resolved_calls:
            # Generate caller and callee IDs
            caller_id = make_function_id(
                call["caller_file"],
                call["caller_function"],
                call["caller_start_line"],
                project_root
            )
            callee_id = make_function_id(
                call["callee_file"],
                call["callee_function"],
                call["callee_start_line"],
                project_root
            )

            calls_data.append({
                "from": caller_id,
                "to": callee_id,
                "line_number": call["call_line"],
            })

    # Create Polars DataFrames and write to Parquet
    # Node tables
    _write_node_table(
        files_data,
        ["path", "language", "content_hash"],
        nodes_dir / "files.parquet"
    )

    _write_node_table(
        functions_data,
        ["id", "name", "file", "start_line", "end_line", "is_public", "source_code"],
        nodes_dir / "functions.parquet"
    )

    _write_node_table(
        classes_data,
        ["id", "name", "file", "start_line", "end_line", "bases", "is_public", "source_code"],
        nodes_dir / "classes.parquet"
    )

    _write_node_table(
        variables_data,
        ["id", "name", "file", "definition_line", "scope"],
        nodes_dir / "variables.parquet"
    )

    _write_node_table(
        imports_data,
        ["id", "imported_name", "import_type", "alias", "line_number", "is_relative", "file"],
        nodes_dir / "imports.parquet"
    )

    _write_node_table(
        decorators_data,
        ["id", "name", "file", "line_number", "arguments"],
        nodes_dir / "decorators.parquet"
    )

    _write_node_table(
        attributes_data,
        ["id", "name", "class_name", "file", "definition_line", "type_hint", "is_class_attribute"],
        nodes_dir / "attributes.parquet"
    )

    _write_node_table(
        exceptions_data,
        ["id", "name", "file", "line_number"],
        nodes_dir / "exceptions.parquet"
    )

    # Edge tables
    _write_edge_table(
        contains_function_data,
        ["from", "to"],
        edges_dir / "contains_function.parquet"
    )

    _write_edge_table(
        contains_class_data,
        ["from", "to"],
        edges_dir / "contains_class.parquet"
    )

    _write_edge_table(
        contains_variable_data,
        ["from", "to"],
        edges_dir / "contains_variable.parquet"
    )

    _write_edge_table(
        method_of_data,
        ["from", "to"],
        edges_dir / "method_of.parquet"
    )

    _write_edge_table(
        has_import_data,
        ["from", "to"],
        edges_dir / "has_import.parquet"
    )

    _write_edge_table(
        decorated_by_data,
        ["from", "to", "position"],
        edges_dir / "decorated_by.parquet"
    )

    _write_edge_table(
        has_attribute_data,
        ["from", "to"],
        edges_dir / "has_attribute.parquet"
    )

    _write_edge_table(
        references_data,
        ["from", "to", "line_number", "context"],
        edges_dir / "references.parquet"
    )

    _write_edge_table(
        accesses_data,
        ["from", "to", "line_number", "access_type"],
        edges_dir / "accesses.parquet"
    )

    _write_edge_table(
        handles_exception_data,
        ["from", "to", "line_number", "context"],
        edges_dir / "handles_exception.parquet"
    )

    _write_edge_table(
        calls_data,
        ["from", "to", "line_number"],
        edges_dir / "calls.parquet"
    )


def _write_node_table(data: List[dict], columns: List[str], output_path: Path) -> None:
    """Write node data to Parquet file with proper schema.

    Args:
        data: List of dictionaries containing node data
        columns: Expected column names (for schema validation)
        output_path: Path to write Parquet file
    """
    if data:
        df = pl.DataFrame(data)
    else:
        # Create empty DataFrame with correct schema
        schema = _get_schema_for_columns(columns)
        df = pl.DataFrame(schema=schema)

    df.write_parquet(output_path)


def _write_edge_table(data: List[dict], columns: List[str], output_path: Path) -> None:
    """Write edge data to Parquet file with proper schema.

    Args:
        data: List of dictionaries containing edge data
        columns: Expected column names (for schema validation)
        output_path: Path to write Parquet file
    """
    if data:
        df = pl.DataFrame(data)
    else:
        # Create empty DataFrame with correct schema
        schema = _get_schema_for_columns(columns)
        df = pl.DataFrame(schema=schema)

    df.write_parquet(output_path)


def _get_schema_for_columns(columns: List[str]) -> dict:
    """Get Polars schema for given column names.

    Args:
        columns: List of column names

    Returns:
        Dictionary mapping column names to Polars data types
    """
    # Define type mappings
    type_map = {
        "id": pl.Utf8,
        "path": pl.Utf8,
        "name": pl.Utf8,
        "file": pl.Utf8,
        "language": pl.Utf8,
        "content_hash": pl.Utf8,
        "imported_name": pl.Utf8,
        "import_type": pl.Utf8,
        "alias": pl.Utf8,
        "arguments": pl.Utf8,
        "class_name": pl.Utf8,
        "type_hint": pl.Utf8,
        "scope": pl.Utf8,
        "bases": pl.Utf8,
        "source_code": pl.Utf8,
        "context": pl.Utf8,
        "access_type": pl.Utf8,
        "from": pl.Utf8,
        "to": pl.Utf8,
        "start_line": pl.Int64,
        "end_line": pl.Int64,
        "definition_line": pl.Int64,
        "line_number": pl.Int64,
        "call_line": pl.Int64,
        "position": pl.Int64,
        "is_public": pl.Boolean,
        "is_relative": pl.Boolean,
        "is_class_attribute": pl.Boolean,
    }

    return {col: type_map.get(col, pl.Utf8) for col in columns}
