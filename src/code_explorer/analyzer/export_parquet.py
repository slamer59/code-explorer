"""
Export FileAnalysis results to Parquet format for KuzuDB bulk loading.

This module converts FileAnalysis objects into Parquet files that can be
efficiently loaded into KuzuDB using COPY FROM operations.
"""

import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import polars as pl

from code_explorer.analyzer.models import FileAnalysis
from code_explorer.utils.timer import Timer


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


@lru_cache(maxsize=100_000)
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


@lru_cache(maxsize=100_000)
def make_variable_id(
    file: str, name: str, line: int, scope: str, project_root: Path
) -> str:
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


@lru_cache(maxsize=100_000)
def make_import_id(
    file: str, imported_name: str, line_number: int, project_root: Path
) -> str:
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


@lru_cache(maxsize=100_000)
def make_decorator_id(
    file: str, name: str, line_number: int, project_root: Path
) -> str:
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
    project_root: Path,
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


def _process_batch(
    batch_results: List[FileAnalysis],
    project_root: Path,
) -> Dict[str, Any]:
    """Process a batch of FileAnalysis objects and return extracted data.

    Args:
        batch_results: List of FileAnalysis objects in this batch
        project_root: Root directory for computing relative paths

    Returns:
        Dictionary containing all extracted data structures for this batch
    """
    # Initialize data structures for this batch
    batch_data = {
        "files_data": [],
        "functions_data": [],
        "classes_data": [],
        "variables_data": [],
        "imports_data": [],
        "decorators_data": [],
        "attributes_data": [],
        "exceptions_data": [],
        "contains_function_data": [],
        "contains_class_data": [],
        "contains_variable_data": [],
        "has_import_data": [],
        "deferred_method_of": [],
        "deferred_references": [],
        "deferred_decorated_by": [],
        "deferred_has_attribute": [],
        "deferred_handles_exception": [],
    }

    # Process each FileAnalysis result in the batch
    for result in batch_results:
        file_path = result.file_path
        rel_file_path = to_relative_path(file_path, project_root)

        # File node
        batch_data["files_data"].append(
            {
                "path": rel_file_path,
                "language": "python",
                "content_hash": result.content_hash,
            }
        )

        # Function nodes and edges
        seen_funcs = set()
        for func in result.functions:
            func_key = (file_path, func.name, func.start_line)
            if func_key in seen_funcs:
                continue
            seen_funcs.add(func_key)

            func_id = make_function_id(
                file_path, func.name, func.start_line, project_root
            )
            batch_data["functions_data"].append(
                {
                    "id": func_id,
                    "name": func.name,
                    "file": rel_file_path,
                    "start_line": func.start_line,
                    "end_line": func.end_line,
                    "is_public": func.is_public,
                    "source_code": func.source_code or "",
                }
            )

            batch_data["contains_function_data"].append(
                {
                    "from": rel_file_path,
                    "to": func_id,
                }
            )

            if func.parent_class:
                batch_data["deferred_method_of"].append(
                    (rel_file_path, func.name, func.start_line, func.parent_class)
                )

        # Class nodes and edges
        seen_classes = set()
        for cls in result.classes:
            cls_key = (file_path, cls.name, cls.start_line)
            if cls_key in seen_classes:
                continue
            seen_classes.add(cls_key)

            class_id = make_class_id(file_path, cls.name, cls.start_line, project_root)
            bases_str = ",".join(cls.bases) if cls.bases else ""

            batch_data["classes_data"].append(
                {
                    "id": class_id,
                    "name": cls.name,
                    "file": rel_file_path,
                    "start_line": cls.start_line,
                    "end_line": cls.end_line,
                    "bases": bases_str,
                    "is_public": cls.is_public,
                    "source_code": cls.source_code or "",
                }
            )

            batch_data["contains_class_data"].append(
                {
                    "from": rel_file_path,
                    "to": class_id,
                }
            )

        # Variable nodes and edges
        seen_vars = set()
        for var in result.variables:
            var_key = (file_path, var.name, var.definition_line, var.scope)
            if var_key in seen_vars:
                continue
            seen_vars.add(var_key)

            var_id = make_variable_id(
                file_path, var.name, var.definition_line, var.scope, project_root
            )
            batch_data["variables_data"].append(
                {
                    "id": var_id,
                    "name": var.name,
                    "file": rel_file_path,
                    "definition_line": var.definition_line,
                    "scope": var.scope,
                }
            )

            batch_data["contains_variable_data"].append(
                {
                    "from": rel_file_path,
                    "to": var_id,
                }
            )

        # Defer REFERENCES edge creation
        for usage in result.variable_usage:
            batch_data["deferred_references"].append(
                (rel_file_path, usage.function_name, usage.variable_name, usage.usage_line)
            )

        # Import nodes and edges
        seen_imps = set()
        for imp in result.imports_detailed:
            imp_key = (file_path, imp.imported_name, imp.line_number)
            if imp_key in seen_imps:
                continue
            seen_imps.add(imp_key)

            imp_id = make_import_id(
                file_path, imp.imported_name, imp.line_number, project_root
            )
            batch_data["imports_data"].append(
                {
                    "id": imp_id,
                    "imported_name": imp.imported_name,
                    "import_type": imp.import_type,
                    "alias": imp.alias or "",
                    "line_number": imp.line_number,
                    "is_relative": imp.is_relative,
                    "file": rel_file_path,
                }
            )

            batch_data["has_import_data"].append(
                {
                    "from": rel_file_path,
                    "to": imp_id,
                }
            )

        # Decorator nodes
        seen_decs = set()
        for dec in result.decorators:
            dec_key = (file_path, dec.name, dec.line_number)
            if dec_key in seen_decs:
                continue
            seen_decs.add(dec_key)

            dec_id = make_decorator_id(
                file_path, dec.name, dec.line_number, project_root
            )
            batch_data["decorators_data"].append(
                {
                    "id": dec_id,
                    "name": dec.name,
                    "file": rel_file_path,
                    "line_number": dec.line_number,
                    "arguments": dec.arguments or "",
                }
            )

            if dec.target_type == "function":
                batch_data["deferred_decorated_by"].append(
                    (rel_file_path, dec.target_name, dec.name, dec.line_number)
                )

        # Attribute nodes
        seen_attrs = set()
        for attr in result.attributes:
            attr_key = (file_path, attr.class_name, attr.name, attr.definition_line)
            if attr_key in seen_attrs:
                continue
            seen_attrs.add(attr_key)

            attr_id = make_attribute_id(
                file_path,
                attr.class_name,
                attr.name,
                attr.definition_line,
                project_root,
            )
            batch_data["attributes_data"].append(
                {
                    "id": attr_id,
                    "name": attr.name,
                    "class_name": attr.class_name,
                    "file": rel_file_path,
                    "definition_line": attr.definition_line,
                    "type_hint": attr.type_hint or "",
                    "is_class_attribute": attr.is_class_attribute,
                }
            )

            batch_data["deferred_has_attribute"].append(
                (rel_file_path, attr.class_name, attr.name, attr.definition_line)
            )

        # Exception nodes
        seen_excs = set()
        for exc in result.exceptions:
            exc_key = (
                file_path,
                exc.name,
                exc.line_number,
                exc.context,
                exc.function_name or "",
            )
            if exc_key in seen_excs:
                continue
            seen_excs.add(exc_key)

            exc_id = make_exception_id(
                file_path,
                exc.name,
                exc.line_number,
                exc.context,
                exc.function_name,
                project_root,
            )
            batch_data["exceptions_data"].append(
                {
                    "id": exc_id,
                    "name": exc.name,
                    "file": rel_file_path,
                    "line_number": exc.line_number,
                }
            )

            if exc.function_name:
                batch_data["deferred_handles_exception"].append(
                    (
                        rel_file_path,
                        exc.function_name,
                        exc.name,
                        exc.line_number,
                        exc.context,
                    )
                )

    return batch_data


def export_to_parquet(
    results: List[FileAnalysis],
    output_dir: Path,
    project_root: Path,
    resolved_calls: Optional[List[dict]] = None,
    batch_size: int = 100,
    max_workers: Optional[int] = None,
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
        batch_size: Number of files to process in each parallel batch (default: 100)
        max_workers: Maximum number of worker threads (default: None = auto-detect)

    Note:
        - INHERITS edges are skipped (not implemented)
        - REFERENCES context always uses empty string ""
        - DECORATED_BY generates target IDs from file + target_name + line
        - Empty DataFrames create Parquet files with 0 rows but correct schema

    Performance:
        - Optimized to avoid O(n²) complexity by building global lookups ONCE after processing all files
        - Edge creation happens after the main loop using O(1) hash table lookups
        - Parallel processing with ThreadPoolExecutor for I/O bound operations
    """
    # Create output directories
    nodes_dir = output_dir / "nodes"
    edges_dir = output_dir / "edges"
    nodes_dir.mkdir(parents=True, exist_ok=True)
    edges_dir.mkdir(parents=True, exist_ok=True)

    # Collect all node data
    files_data = []
    functions_data = []
    classes_data = []
    variables_data = []
    imports_data = []
    decorators_data = []
    attributes_data = []
    exceptions_data = []

    # Collect basic edge data (edges that don't need lookups)
    contains_function_data = []
    contains_class_data = []
    contains_variable_data = []
    has_import_data = []

    # Defer complex edge data that requires lookups (built after main loop)
    method_of_data = []
    decorated_by_data = []
    has_attribute_data = []
    references_data = []
    accesses_data = []
    handles_exception_data = []

    # Store raw edge data from FileAnalysis for deferred processing
    # This avoids the O(n²) lookup problem by deferring edge creation
    deferred_method_of = []  # (file_path, func.name, func.parent_class)
    deferred_references = []  # (file_path, usage.function_name, usage.variable_name, usage.usage_line)
    deferred_decorated_by = []  # (file_path, dec.target_name, dec.name, dec.line_number)
    deferred_has_attribute = []  # (file_path, attr.class_name, attr.name, attr.definition_line)
    deferred_handles_exception = []  # (file_path, exc.function_name, exc.name, exc.line_number, exc.context)

    # PARALLEL OPTIMIZATION: Split results into batches and process in parallel
    with Timer("parallel_batch_processing", silent=True) as processing_timer:
        # Split results into batches
        batches = []
        for i in range(0, len(results), batch_size):
            batch = results[i : i + batch_size]
            batches.append(batch)

        # Process batches in parallel using ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all batch processing jobs
            future_to_batch = {
                executor.submit(_process_batch, batch, project_root): batch
                for batch in batches
            }

            # Collect results as they complete
            batch_results = []
            for future in as_completed(future_to_batch):
                try:
                    batch_data = future.result()
                    batch_results.append(batch_data)
                except Exception as exc:
                    batch = future_to_batch[future]
                    print(
                        f"Batch processing failed for batch of {len(batch)} files: {exc}"
                    )
                    # Continue processing other batches, but log the error
                    continue

        # Combine results from all batches
        with Timer("combine_batch_results", silent=True) as combine_timer:
            for batch_data in batch_results:
                files_data.extend(batch_data["files_data"])
                functions_data.extend(batch_data["functions_data"])
                classes_data.extend(batch_data["classes_data"])
                variables_data.extend(batch_data["variables_data"])
                imports_data.extend(batch_data["imports_data"])
                decorators_data.extend(batch_data["decorators_data"])
                attributes_data.extend(batch_data["attributes_data"])
                exceptions_data.extend(batch_data["exceptions_data"])

                contains_function_data.extend(batch_data["contains_function_data"])
                contains_class_data.extend(batch_data["contains_class_data"])
                contains_variable_data.extend(batch_data["contains_variable_data"])
                has_import_data.extend(batch_data["has_import_data"])

                deferred_method_of.extend(batch_data["deferred_method_of"])
                deferred_references.extend(batch_data["deferred_references"])
                deferred_decorated_by.extend(batch_data["deferred_decorated_by"])
                deferred_has_attribute.extend(batch_data["deferred_has_attribute"])
                deferred_handles_exception.extend(
                    batch_data["deferred_handles_exception"]
                )

    print(
        f"⏱️  Parallel batch processing: {processing_timer.elapsed:.3f}s ({len(batches)} batches, {len(results)} files)"
    )
    print(f"⏱️  Result combination: {combine_timer.elapsed:.3f}s")

    # OPTIMIZATION: Build global lookup dictionaries ONCE after all files are processed.
    # This eliminates the O(n²) complexity from the original implementation.
    # Each lookup is O(1) instead of O(n) scan through all accumulated data.
    with Timer("build_lookup_dictionaries", silent=True) as lookup_timer:
        # Build lookup: (file, name, start_line) -> function data
        func_lookup = {}
        for func_data in functions_data:
            key = (func_data["file"], func_data["name"], func_data["start_line"])
            func_lookup[key] = func_data

        # Build lookup: (file, name, start_line) -> class data
        class_lookup = {}
        for cls_data in classes_data:
            key = (cls_data["file"], cls_data["name"], cls_data["start_line"])
            class_lookup[key] = cls_data

        # Build lookup: (file, name) -> class data (for simple name-based lookups)
        class_by_name = {}
        for cls_data in classes_data:
            key = (cls_data["file"], cls_data["name"])
            # Keep first occurrence (handles duplicates)
            if key not in class_by_name:
                class_by_name[key] = cls_data

        # Build lookup: (file, name) -> variable data (for simple name-based lookups)
        var_by_name = {}
        for var_data in variables_data:
            key = (var_data["file"], var_data["name"])
            # Keep first occurrence (handles duplicates)
            if key not in var_by_name:
                var_by_name[key] = var_data

        # Build lookup: (file, name) -> function data (for simple name-based lookups)
        func_by_name = {}
        for func_data in functions_data:
            key = (func_data["file"], func_data["name"])
            # Keep first occurrence (handles duplicates)
            if key not in func_by_name:
                func_by_name[key] = func_data

        # Build lookup: (file, name, line_number) -> decorator data
        decorator_lookup = {}
        for dec_data in decorators_data:
            key = (dec_data["file"], dec_data["name"], dec_data["line_number"])
            decorator_lookup[key] = dec_data

        # Build lookup: (file, class_name, name, definition_line) -> attribute data
        attribute_lookup = {}
        for attr_data in attributes_data:
            key = (
                attr_data["file"],
                attr_data["class_name"],
                attr_data["name"],
                attr_data["definition_line"],
            )
            attribute_lookup[key] = attr_data

        # Build lookup: (file, name, line_number) -> exception data
        exception_lookup = {}
        for exc_data in exceptions_data:
            key = (exc_data["file"], exc_data["name"], exc_data["line_number"])
            exception_lookup[key] = exc_data

        # OPTIMIZATION: Create edges using global lookups (O(1) per edge instead of O(n))

        # Create METHOD_OF edges
        for rel_file_path, func_name, func_start_line, parent_class in deferred_method_of:
            func_key = (rel_file_path, func_name, func_start_line)
            class_key = (rel_file_path, parent_class)

            if func_key in func_lookup and class_key in class_by_name:
                func_id = func_lookup[func_key]["id"]
                class_id = class_by_name[class_key]["id"]
                method_of_data.append(
                    {
                        "from": func_id,
                        "to": class_id,
                    }
                )

        # Create REFERENCES edges
        for rel_file_path, func_name, var_name, usage_line in deferred_references:
            func_key = (rel_file_path, func_name)
            var_key = (rel_file_path, var_name)

            if func_key in func_by_name and var_key in var_by_name:
                func_id = func_by_name[func_key]["id"]
                var_id = var_by_name[var_key]["id"]
                references_data.append(
                    {
                        "from": func_id,
                        "to": var_id,
                        "line_number": usage_line,
                        "context": "",
                    }
                )

        # Create DECORATED_BY edges
        for rel_file_path, target_name, dec_name, dec_line in deferred_decorated_by:
            func_key = (rel_file_path, target_name)
            dec_key = (rel_file_path, dec_name, dec_line)

            if func_key in func_by_name and dec_key in decorator_lookup:
                func_id = func_by_name[func_key]["id"]
                dec_id = decorator_lookup[dec_key]["id"]
                decorated_by_data.append(
                    {
                        "from": func_id,
                        "to": dec_id,
                        "position": 0,
                    }
                )

        # Create HAS_ATTRIBUTE edges
        for rel_file_path, class_name, attr_name, attr_line in deferred_has_attribute:
            class_key = (rel_file_path, class_name)
            attr_key = (rel_file_path, class_name, attr_name, attr_line)

            if class_key in class_by_name and attr_key in attribute_lookup:
                class_id = class_by_name[class_key]["id"]
                attr_id = attribute_lookup[attr_key]["id"]
                has_attribute_data.append(
                    {
                        "from": class_id,
                        "to": attr_id,
                    }
                )

        # Create HANDLES_EXCEPTION edges
        for (
            rel_file_path,
            func_name,
            exc_name,
            exc_line,
            exc_context,
        ) in deferred_handles_exception:
            func_key = (rel_file_path, func_name)
            exc_key = (rel_file_path, exc_name, exc_line)

            if func_key in func_by_name and exc_key in exception_lookup:
                func_id = func_by_name[func_key]["id"]
                exc_id = exception_lookup[exc_key]["id"]
                handles_exception_data.append(
                    {
                        "from": func_id,
                        "to": exc_id,
                        "line_number": exc_line,
                        "context": exc_context,
                    }
                )
    print(
        f"⏱️  Lookup dictionary building and edge creation: {lookup_timer.elapsed:.3f}s"
    )
    # Process resolved CALLS edges if provided
    with Timer("process_calls_edges", silent=True) as calls_timer:
        calls_data = []
        if resolved_calls:
            for call in resolved_calls:
                # Generate caller and callee IDs
                caller_id = make_function_id(
                    call["caller_file"],
                    call["caller_function"],
                    call["caller_start_line"],
                    project_root,
                )
                callee_id = make_function_id(
                    call["callee_file"],
                    call["callee_function"],
                    call["callee_start_line"],
                    project_root,
                )

                calls_data.append(
                    {
                        "from": caller_id,
                        "to": callee_id,
                        "line_number": call["call_line"],
                    }
                )
    print(f"⏱️  CALLS edge processing: {calls_timer.elapsed:.3f}s")
    # Create Polars DataFrames and write to Parquet
    with Timer("write_parquet_files", silent=True) as write_timer:
        # Node tables
        _write_node_table(
            files_data,
            ["path", "language", "content_hash"],
            nodes_dir / "files.parquet",
        )

        _write_node_table(
            functions_data,
            [
                "id",
                "name",
                "file",
                "start_line",
                "end_line",
                "is_public",
                "source_code",
            ],
            nodes_dir / "functions.parquet",
        )

        _write_node_table(
            classes_data,
            [
                "id",
                "name",
                "file",
                "start_line",
                "end_line",
                "bases",
                "is_public",
                "source_code",
            ],
            nodes_dir / "classes.parquet",
        )

        _write_node_table(
            variables_data,
            ["id", "name", "file", "definition_line", "scope"],
            nodes_dir / "variables.parquet",
        )

        _write_node_table(
            imports_data,
            [
                "id",
                "imported_name",
                "import_type",
                "alias",
                "line_number",
                "is_relative",
                "file",
            ],
            nodes_dir / "imports.parquet",
        )

        _write_node_table(
            decorators_data,
            ["id", "name", "file", "line_number", "arguments"],
            nodes_dir / "decorators.parquet",
        )

        _write_node_table(
            attributes_data,
            [
                "id",
                "name",
                "class_name",
                "file",
                "definition_line",
                "type_hint",
                "is_class_attribute",
            ],
            nodes_dir / "attributes.parquet",
        )

        _write_node_table(
            exceptions_data,
            ["id", "name", "file", "line_number"],
            nodes_dir / "exceptions.parquet",
        )

        # Edge tables
        _write_edge_table(
            contains_function_data,
            ["from", "to"],
            edges_dir / "contains_function.parquet",
        )

        _write_edge_table(
            contains_class_data, ["from", "to"], edges_dir / "contains_class.parquet"
        )

        _write_edge_table(
            contains_variable_data,
            ["from", "to"],
            edges_dir / "contains_variable.parquet",
        )

        _write_edge_table(
            method_of_data, ["from", "to"], edges_dir / "method_of.parquet"
        )

        _write_edge_table(
            has_import_data, ["from", "to"], edges_dir / "has_import.parquet"
        )

        _write_edge_table(
            decorated_by_data,
            ["from", "to", "position"],
            edges_dir / "decorated_by.parquet",
        )

        _write_edge_table(
            has_attribute_data, ["from", "to"], edges_dir / "has_attribute.parquet"
        )

        _write_edge_table(
            references_data,
            ["from", "to", "line_number", "context"],
            edges_dir / "references.parquet",
        )

        _write_edge_table(
            accesses_data,
            ["from", "to", "line_number", "access_type"],
            edges_dir / "accesses.parquet",
        )

        _write_edge_table(
            handles_exception_data,
            ["from", "to", "line_number", "context"],
            edges_dir / "handles_exception.parquet",
        )

        _write_edge_table(
            calls_data, ["from", "to", "line_number"], edges_dir / "calls.parquet"
        )
    print(f"⏱️  Parquet file writing: {write_timer.elapsed:.3f}s")


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
    return {col: type_map.get(col, pl.Utf8) for col in columns}
    return {col: type_map.get(col, pl.Utf8) for col in columns}
