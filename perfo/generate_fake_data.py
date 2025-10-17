"""
Generate massive amounts of fake code graph data for performance testing.

SIMPLE pattern-based generation without faker library.
Uses loops and string formatting to create entity_{i} style names.

Usage:
    python generate_fake_data.py --scale small
    python generate_fake_data.py --scale medium --seed 42
    python generate_fake_data.py --scale large
"""

import argparse
import hashlib
import random
from datetime import datetime, timedelta
from pathlib import Path

import polars as pl
from codetiming import Timer
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

console = Console()

# Scale configurations
SCALE_CONFIGS = {
    "small": {
        "files": 100,
        "functions": 3000,
        "classes": 500,
        "variables": 2000,
        "imports": 1000,
        "decorators": 500,
        "attributes": 800,
        "exceptions": 300,
    },
    "medium": {
        "files": 1000,
        "functions": 30000,
        "classes": 5000,
        "variables": 20000,
        "imports": 10000,
        "decorators": 5000,
        "attributes": 8000,
        "exceptions": 3000,
    },
    "large": {
        "files": 10000,
        "functions": 300000,
        "classes": 50000,
        "variables": 200000,
        "imports": 100000,
        "decorators": 50000,
        "attributes": 80000,
        "exceptions": 30000,
    },
}


def hash_id(prefix: str, name: str, file: str = "", extra: str = "") -> str:
    """Generate hash-based ID with sufficient length to avoid collisions.

    Args:
        prefix: ID prefix (fn, cls, var, etc.)
        name: Entity name
        file: Optional file path
        extra: Optional extra data for uniqueness (e.g., line number, scope)

    Returns:
        Hash-based ID like 'fn_abc123456789abcd' (16 hex chars for uniqueness)
    """
    # Include all available info to maximize uniqueness
    parts = [name]
    if file:
        parts.append(file)
    if extra:
        parts.append(extra)

    content = ":".join(parts)
    # Use 16 hex characters (64 bits) instead of 8 to dramatically reduce collision probability
    # Birthday paradox: 8 hex chars (32 bits) has ~50% collision at 77k items
    #                   16 hex chars (64 bits) has ~50% collision at 5 billion items
    hash_hex = hashlib.md5(content.encode()).hexdigest()[:16]
    return f"{prefix}_{hash_hex}"


def generate_files(config: dict, seed: int) -> pl.DataFrame:
    """Generate File nodes using simple pattern-based names."""
    random.seed(seed)
    num_files = config["files"]

    base_dirs = ["src", "lib", "app", "services", "models", "utils", "core", "api"]
    subdirs = ["handlers", "controllers", "repositories", "entities", "views", "helpers"]

    files = []
    base_time = datetime.now() - timedelta(days=365)

    for i in range(num_files):
        base = base_dirs[i % len(base_dirs)]
        subdir = subdirs[(i // len(base_dirs)) % len(subdirs)]
        filename = f"module_{i}.py"
        path = f"{base}/{subdir}/{filename}"

        # Random timestamp in last year
        days_offset = random.randint(0, 365)
        last_modified = base_time + timedelta(days=days_offset)

        files.append({
            "path": path,
            "language": "python",
            "last_modified": last_modified,
            "content_hash": f"hash_{i:08x}",
        })

    return pl.DataFrame(files)


def generate_functions(config: dict, files_df: pl.DataFrame, seed: int) -> pl.DataFrame:
    """Generate Function nodes using simple pattern-based names."""
    random.seed(seed + 1)
    num_functions = config["functions"]
    file_paths = files_df["path"].to_list()

    prefixes = ["get", "set", "create", "update", "delete", "fetch", "process",
                "calculate", "validate", "parse", "handle", "build"]
    suffixes = ["data", "user", "result", "value", "item", "record", "config",
                "entity", "total", "summary", "list"]

    functions = []

    for i in range(num_functions):
        # Pattern-based name generation
        if i % 3 == 0:
            name = f"function_{i}"
        elif i % 3 == 1:
            prefix = prefixes[i % len(prefixes)]
            suffix = suffixes[(i // len(prefixes)) % len(suffixes)]
            name = f"{prefix}_{suffix}_{i % 100}"
        else:
            name = f"{prefixes[i % len(prefixes)]}_data_{i}"

        file = file_paths[i % len(file_paths)]
        start_line = 10 + (i % 500)
        # Include start line and index to ensure uniqueness
        func_id = hash_id("fn", name, file, f"{start_line}:{i}")
        end_line = start_line + 5 + (i % 50)
        is_public = not name.startswith("_")

        source_code = f'''def {name}(arg1, arg2):
    """Function {name}."""
    result = arg1 + arg2
    return result
'''

        functions.append({
            "id": func_id,
            "name": name,
            "file": file,
            "start_line": start_line,
            "end_line": end_line,
            "is_public": is_public,
            "source_code": source_code,
        })

    return pl.DataFrame(functions)


def generate_classes(config: dict, files_df: pl.DataFrame, seed: int) -> pl.DataFrame:
    """Generate Class nodes using simple pattern-based names."""
    random.seed(seed + 2)
    num_classes = config["classes"]
    file_paths = files_df["path"].to_list()

    suffixes = ["Service", "Manager", "Controller", "Handler", "Processor",
                "Repository", "Factory", "Builder", "Model", "Entity"]
    names = ["User", "Order", "Product", "Payment", "Account", "Report",
             "Config", "Data", "Message", "Task"]

    classes = []

    for i in range(num_classes):
        # Pattern-based name generation
        if i % 2 == 0:
            name = f"Class_{i}"
        else:
            base_name = names[i % len(names)]
            suffix = suffixes[(i // len(names)) % len(suffixes)]
            name = f"{base_name}{suffix}_{i % 100}"

        file = file_paths[i % len(file_paths)]
        start_line = 10 + (i % 500)
        end_line = start_line + 20 + (i % 100)
        # Include start line and index to ensure uniqueness
        class_id = hash_id("cls", name, file, f"{start_line}:{i}")

        # Some classes have bases
        bases = ""
        if i % 5 == 0:
            bases = "object"
        elif i % 7 == 0:
            bases = "BaseModel"

        source_code = f'''class {name}:
    """Class {name}."""

    def __init__(self):
        self.value = None
'''

        classes.append({
            "id": class_id,
            "name": name,
            "file": file,
            "start_line": start_line,
            "end_line": end_line,
            "bases": bases,
            "is_public": not name.startswith("_"),
            "source_code": source_code,
        })

    return pl.DataFrame(classes)


def generate_variables(config: dict, files_df: pl.DataFrame, seed: int) -> pl.DataFrame:
    """Generate Variable nodes using simple pattern-based names."""
    random.seed(seed + 3)
    num_variables = config["variables"]
    file_paths = files_df["path"].to_list()

    suffixes = ["id", "name", "value", "data", "config", "count", "list",
                "dict", "result", "status"]
    scopes = ["module", "function", "class"]

    variables = []

    for i in range(num_variables):
        # Pattern-based name generation
        if i % 2 == 0:
            name = f"var_{i}"
        else:
            suffix = suffixes[i % len(suffixes)]
            name = f"user_{suffix}_{i % 100}"

        file = file_paths[i % len(file_paths)]
        definition_line = 5 + (i % 500)
        scope = scopes[i % len(scopes)]
        # Include scope, line number, and index to ensure uniqueness (since line numbers repeat)
        var_id = hash_id("var", name, file, f"{scope}:{definition_line}:{i}")

        variables.append({
            "id": var_id,
            "name": name,
            "file": file,
            "definition_line": definition_line,
            "scope": scope,
        })

    return pl.DataFrame(variables)


def generate_imports(config: dict, files_df: pl.DataFrame, seed: int) -> pl.DataFrame:
    """Generate Import nodes using simple pattern-based names."""
    random.seed(seed + 4)
    num_imports = config["imports"]
    file_paths = files_df["path"].to_list()

    packages = ["pandas", "numpy", "requests", "flask", "django", "fastapi",
                "sqlalchemy", "pydantic", "pytest", "asyncio", "typing",
                "pathlib", "logging", "json", "datetime"]
    import_types = ["module", "class", "function", "constant"]

    imports = []

    for i in range(num_imports):
        imported_name = packages[i % len(packages)]
        if i % 3 == 0:
            imported_name = f"{imported_name}.core"

        file = file_paths[i % len(file_paths)]
        import_type = import_types[i % len(import_types)]
        line_number = 1 + (i % 20)
        # Include import type, line number, and index to ensure uniqueness
        import_id = hash_id("imp", imported_name, file, f"{import_type}:{line_number}:{i}")

        # 30% chance of alias
        alias = ""
        if i % 10 < 3:
            alias = f"alias_{i % 100}"

        imports.append({
            "id": import_id,
            "imported_name": imported_name,
            "import_type": import_type,
            "alias": alias,
            "line_number": line_number,
            "is_relative": (i % 5) == 0,  # 20% relative
            "file": file,
        })

    return pl.DataFrame(imports)


def generate_decorators(config: dict, files_df: pl.DataFrame, seed: int) -> pl.DataFrame:
    """Generate Decorator nodes using simple pattern-based names."""
    random.seed(seed + 5)
    num_decorators = config["decorators"]
    file_paths = files_df["path"].to_list()

    decorator_names = ["@property", "@staticmethod", "@classmethod",
                       "@cached_property", "@dataclass", "@lru_cache",
                       "@wraps", "@override", "@deprecated"]

    decorators = []

    for i in range(num_decorators):
        name = decorator_names[i % len(decorator_names)]
        file = file_paths[i % len(file_paths)]
        line_number = 10 + (i % 500)
        # Include line number and index to ensure uniqueness
        dec_id = hash_id("dec", name, file, f"{line_number}:{i}")

        # Some have arguments
        arguments = ""
        if i % 5 == 0 and name == "@lru_cache":
            arguments = f"maxsize={128 * (i % 8 + 1)}"

        decorators.append({
            "id": dec_id,
            "name": name,
            "file": file,
            "line_number": line_number,
            "arguments": arguments,
        })

    return pl.DataFrame(decorators)


def generate_attributes(config: dict, classes_df: pl.DataFrame, seed: int) -> pl.DataFrame:
    """Generate Attribute nodes using simple pattern-based names."""
    random.seed(seed + 6)
    num_attributes = config["attributes"]

    class_info = classes_df.select(["id", "name", "file"]).to_dicts()
    attr_names = ["id", "name", "value", "email", "created_at", "updated_at",
                  "status", "type", "data", "config", "count"]
    type_hints = ["str", "int", "float", "bool", "list", "dict",
                  "Optional[str]", "List[int]", "Dict[str, Any]"]

    attributes = []

    for i in range(num_attributes):
        class_data = class_info[i % len(class_info)]
        attr_name = attr_names[i % len(attr_names)]
        if i % 2 == 0:
            attr_name = f"{attr_name}_{i % 100}"

        definition_line = 15 + (i % 200)
        type_hint = type_hints[i % len(type_hints)]
        is_class_attribute = (i % 10) < 3  # 30% class attributes
        # Include class name, line number, and index to ensure uniqueness
        attr_id = hash_id("attr", attr_name, class_data["file"], f"{class_data['name']}:{definition_line}:{i}")

        attributes.append({
            "id": attr_id,
            "name": attr_name,
            "class_name": class_data["name"],
            "file": class_data["file"],
            "definition_line": definition_line,
            "type_hint": type_hint,
            "is_class_attribute": is_class_attribute,
        })

    return pl.DataFrame(attributes)


def generate_exceptions(config: dict, files_df: pl.DataFrame, seed: int) -> pl.DataFrame:
    """Generate Exception nodes using simple pattern-based names."""
    random.seed(seed + 7)
    num_exceptions = config["exceptions"]
    file_paths = files_df["path"].to_list()

    exception_names = ["ValueError", "TypeError", "KeyError", "IndexError",
                       "AttributeError", "FileNotFoundError", "IOError",
                       "ConnectionError", "TimeoutError", "ValidationError"]

    exceptions = []

    for i in range(num_exceptions):
        name = exception_names[i % len(exception_names)]
        file = file_paths[i % len(file_paths)]
        line_number = 20 + (i % 500)
        # Include line number and index to ensure uniqueness
        exc_id = hash_id("exc", name, file, f"{line_number}:{i}")

        exceptions.append({
            "id": exc_id,
            "name": name,
            "file": file,
            "line_number": line_number,
        })

    return pl.DataFrame(exceptions)


def generate_calls_edges(functions_df: pl.DataFrame, seed: int, ratio: float = 3.0) -> pl.DataFrame:
    """Generate CALLS edges (Function -> Function)."""
    random.seed(seed + 10)
    function_ids = functions_df["id"].to_list()
    num_edges = int(len(function_ids) * ratio)

    edges = []
    seen = set()

    for i in range(num_edges):
        from_idx = i % len(function_ids)
        to_idx = (i + 1 + (i % 37)) % len(function_ids)  # Pseudo-random but deterministic

        # Avoid self-calls
        if from_idx == to_idx:
            to_idx = (to_idx + 1) % len(function_ids)

        edge_key = (from_idx, to_idx)
        if edge_key not in seen:
            seen.add(edge_key)
            edges.append({
                "from": function_ids[from_idx],
                "to": function_ids[to_idx],
                "call_line": 10 + (i % 500),
            })

    return pl.DataFrame(edges)


def generate_contains_function_edges(files_df: pl.DataFrame, functions_df: pl.DataFrame) -> pl.DataFrame:
    """Generate CONTAINS_FUNCTION edges (File -> Function)."""
    return functions_df.select([
        pl.col("file").alias("from"),
        pl.col("id").alias("to"),
    ])


def generate_contains_class_edges(files_df: pl.DataFrame, classes_df: pl.DataFrame) -> pl.DataFrame:
    """Generate CONTAINS_CLASS edges (File -> Class)."""
    return classes_df.select([
        pl.col("file").alias("from"),
        pl.col("id").alias("to"),
    ])


def generate_contains_variable_edges(files_df: pl.DataFrame, variables_df: pl.DataFrame) -> pl.DataFrame:
    """Generate CONTAINS_VARIABLE edges (File -> Variable)."""
    return variables_df.select([
        pl.col("file").alias("from"),
        pl.col("id").alias("to"),
    ])


def generate_method_of_edges(functions_df: pl.DataFrame, classes_df: pl.DataFrame,
                             seed: int, ratio: float = 0.6) -> pl.DataFrame:
    """Generate METHOD_OF edges (Function -> Class)."""
    random.seed(seed + 11)
    function_ids = functions_df["id"].to_list()
    class_ids = classes_df["id"].to_list()
    num_edges = int(len(function_ids) * ratio)

    edges = []
    seen = set()

    for i in range(num_edges):
        func_idx = i % len(function_ids)
        class_idx = i % len(class_ids)

        edge_key = (func_idx, class_idx)
        if edge_key not in seen:
            seen.add(edge_key)
            edges.append({
                "from": function_ids[func_idx],
                "to": class_ids[class_idx],
            })

    return pl.DataFrame(edges)


def generate_inherits_edges(classes_df: pl.DataFrame, seed: int, ratio: float = 0.3) -> pl.DataFrame:
    """Generate INHERITS edges (Class -> Class) as DAG."""
    random.seed(seed + 12)
    class_ids = classes_df["id"].to_list()
    num_edges = int(len(class_ids) * ratio)

    edges = []
    seen = set()

    for i in range(num_edges):
        # Create DAG: child inherits from parent with lower index
        child_idx = min(i + 1, len(class_ids) - 1)
        parent_idx = i % child_idx if child_idx > 0 else 0

        edge_key = (child_idx, parent_idx)
        if edge_key not in seen and child_idx != parent_idx:
            seen.add(edge_key)
            edges.append({
                "from": class_ids[child_idx],
                "to": class_ids[parent_idx],
            })

    return pl.DataFrame(edges) if edges else pl.DataFrame({"from": [], "to": []})


def generate_has_import_edges(files_df: pl.DataFrame, imports_df: pl.DataFrame) -> pl.DataFrame:
    """Generate HAS_IMPORT edges (File -> Import)."""
    return imports_df.select([
        pl.col("file").alias("from"),
        pl.col("id").alias("to"),
    ])


def generate_decorated_by_edges(functions_df: pl.DataFrame, decorators_df: pl.DataFrame,
                                seed: int, ratio: float = 0.5) -> pl.DataFrame:
    """Generate DECORATED_BY edges (Function -> Decorator)."""
    random.seed(seed + 13)
    function_ids = functions_df["id"].to_list()
    decorator_ids = decorators_df["id"].to_list()
    num_edges = int(len(function_ids) * ratio)

    edges = []
    seen = set()

    for i in range(num_edges):
        func_idx = i % len(function_ids)
        dec_idx = i % len(decorator_ids)

        edge_key = (func_idx, dec_idx)
        if edge_key not in seen:
            seen.add(edge_key)
            edges.append({
                "from": function_ids[func_idx],
                "to": decorator_ids[dec_idx],
                "position": i % 4,
            })

    return pl.DataFrame(edges)


def generate_has_attribute_edges(classes_df: pl.DataFrame, attributes_df: pl.DataFrame) -> pl.DataFrame:
    """Generate HAS_ATTRIBUTE edges (Class -> Attribute)."""
    class_lookup = {row["name"]: row["id"] for row in classes_df.to_dicts()}

    edges = []
    for attr in attributes_df.to_dicts():
        class_name = attr["class_name"]
        if class_name in class_lookup:
            edges.append({
                "from": class_lookup[class_name],
                "to": attr["id"],
            })

    return pl.DataFrame(edges) if edges else pl.DataFrame({"from": [], "to": []})


def generate_references_edges(functions_df: pl.DataFrame, variables_df: pl.DataFrame,
                              seed: int, ratio: float = 2.0) -> pl.DataFrame:
    """Generate REFERENCES edges (Function -> Variable)."""
    random.seed(seed + 14)
    function_ids = functions_df["id"].to_list()
    variable_ids = variables_df["id"].to_list()
    num_edges = int(len(function_ids) * ratio)

    edges = []
    seen = set()
    contexts = ["read", "write"]

    for i in range(num_edges):
        func_idx = i % len(function_ids)
        var_idx = i % len(variable_ids)

        edge_key = (func_idx, var_idx)
        if edge_key not in seen:
            seen.add(edge_key)
            edges.append({
                "from": function_ids[func_idx],
                "to": variable_ids[var_idx],
                "line_number": 10 + (i % 500),
                "context": contexts[i % len(contexts)],
            })

    return pl.DataFrame(edges)


def generate_accesses_edges(functions_df: pl.DataFrame, attributes_df: pl.DataFrame,
                            seed: int, ratio: float = 1.5) -> pl.DataFrame:
    """Generate ACCESSES edges (Function -> Attribute)."""
    random.seed(seed + 15)
    function_ids = functions_df["id"].to_list()
    attribute_ids = attributes_df["id"].to_list()
    num_edges = int(len(function_ids) * ratio)

    edges = []
    seen = set()
    access_types = ["read", "write"]

    for i in range(num_edges):
        func_idx = i % len(function_ids)
        attr_idx = i % len(attribute_ids)

        edge_key = (func_idx, attr_idx)
        if edge_key not in seen:
            seen.add(edge_key)
            edges.append({
                "from": function_ids[func_idx],
                "to": attribute_ids[attr_idx],
                "line_number": 10 + (i % 500),
                "access_type": access_types[i % len(access_types)],
            })

    return pl.DataFrame(edges)


def generate_handles_exception_edges(functions_df: pl.DataFrame, exceptions_df: pl.DataFrame,
                                     seed: int, ratio: float = 0.3) -> pl.DataFrame:
    """Generate HANDLES_EXCEPTION edges (Function -> Exception)."""
    random.seed(seed + 16)
    function_ids = functions_df["id"].to_list()
    exception_ids = exceptions_df["id"].to_list()
    num_edges = int(len(function_ids) * ratio)

    edges = []
    seen = set()
    contexts = ["raises", "catches"]

    for i in range(num_edges):
        func_idx = i % len(function_ids)
        exc_idx = i % len(exception_ids)

        edge_key = (func_idx, exc_idx)
        if edge_key not in seen:
            seen.add(edge_key)
            edges.append({
                "from": function_ids[func_idx],
                "to": exception_ids[exc_idx],
                "line_number": 10 + (i % 500),
                "context": contexts[i % len(contexts)],
            })

    return pl.DataFrame(edges)


def validate_unique_ids(df: pl.DataFrame, entity_type: str, id_column: str = "id") -> None:
    """Validate that all IDs in a DataFrame are unique.

    Args:
        df: DataFrame to validate
        entity_type: Type of entity (for error messages)
        id_column: Name of the ID column (default: "id")

    Raises:
        ValueError: If duplicate IDs are found
    """
    if id_column not in df.columns:
        return  # No ID column to validate (e.g., File uses 'path' as primary key)

    total_ids = len(df)
    unique_ids = df[id_column].n_unique()

    if total_ids != unique_ids:
        duplicates_count = total_ids - unique_ids
        # Find example duplicates
        duplicate_ids = (
            df.group_by(id_column)
            .agg(pl.len().alias("count"))
            .filter(pl.col("count") > 1)
            .head(5)
        )
        examples = duplicate_ids[id_column].to_list()

        raise ValueError(
            f"{entity_type}: Found {duplicates_count} duplicate IDs!\n"
            f"Total: {total_ids}, Unique: {unique_ids}\n"
            f"Example duplicates: {examples[:5]}"
        )


def write_parquet(df: pl.DataFrame, path: Path, name: str, validate_ids: bool = True) -> None:
    """Write DataFrame to Parquet file with optional ID validation.

    Args:
        df: DataFrame to write
        path: Output file path
        name: Entity name (for display)
        validate_ids: Whether to validate ID uniqueness (default: True)
    """
    # Validate uniqueness before writing (if requested)
    if validate_ids:
        # Determine ID column name
        id_column = "id" if "id" in df.columns else "path"
        validate_unique_ids(df, name, id_column)

    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)

    size_bytes = path.stat().st_size
    if size_bytes < 1024 * 1024:
        size_str = f"{size_bytes / 1024:.1f} KB"
    else:
        size_str = f"{size_bytes / (1024 * 1024):.1f} MB"

    console.print(f"  ✓ {name}: {len(df):,} rows, {size_str}")


def display_summary(stats: dict, elapsed: float) -> None:
    """Display generation summary."""
    table = Table(title="Generation Summary", show_header=True, header_style="bold magenta")
    table.add_column("Category", style="cyan", width=20)
    table.add_column("Type", style="green", width=25)
    table.add_column("Count", style="yellow", justify="right")

    # Nodes
    for node_type, count in stats["nodes"].items():
        table.add_row("Nodes", node_type.capitalize(), f"{count:,}")

    table.add_row("", "", "", end_section=True)

    # Edges
    for edge_type, count in stats["edges"].items():
        table.add_row("Edges", edge_type.replace("_", " ").title(), f"{count:,}")

    table.add_row("", "", "", end_section=True)

    # Totals
    total_nodes = sum(stats["nodes"].values())
    total_edges = sum(stats["edges"].values())
    table.add_row("Total", "Nodes", f"{total_nodes:,}", style="bold")
    table.add_row("Total", "Edges", f"{total_edges:,}", style="bold")

    console.print()
    console.print(table)
    console.print()

    console.print(Panel(
        f"[green]✓ Generation completed in {elapsed:.2f} seconds[/green]\n"
        f"[cyan]Output directory: {stats['output_dir']}[/cyan]",
        title="Performance",
        border_style="green",
    ))


def main() -> None:
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description="Generate massive fake code graph data (SIMPLE, no faker)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python generate_fake_data.py --scale small
  python generate_fake_data.py --scale medium --seed 42
  python generate_fake_data.py --scale large
        """,
    )
    parser.add_argument(
        "--scale",
        choices=["small", "medium", "large"],
        default="small",
        help="Scale of data generation (default: small)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility (default: 42)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("perfo/data/output"),
        help="Output directory (default: perfo/data/output)",
    )

    args = parser.parse_args()

    config = SCALE_CONFIGS[args.scale]
    output_dir = Path(args.output)

    console.print()
    console.print(Panel(
        f"[bold cyan]Scale:[/bold cyan] {args.scale}\n"
        f"[bold cyan]Seed:[/bold cyan] {args.seed}\n"
        f"[bold cyan]Output:[/bold cyan] {output_dir}",
        title="Configuration",
        border_style="cyan",
    ))
    console.print()

    stats = {"nodes": {}, "edges": {}, "output_dir": str(output_dir)}

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        timer = Timer("total", logger=None)
        timer.start()

        # Generate nodes
        task = progress.add_task("[cyan]Generating nodes...", total=8)

        progress.update(task, description="[cyan]Generating files...")
        files_df = generate_files(config, args.seed)
        stats["nodes"]["files"] = len(files_df)
        progress.advance(task)

        progress.update(task, description="[cyan]Generating functions...")
        functions_df = generate_functions(config, files_df, args.seed)
        stats["nodes"]["functions"] = len(functions_df)
        progress.advance(task)

        progress.update(task, description="[cyan]Generating classes...")
        classes_df = generate_classes(config, files_df, args.seed)
        stats["nodes"]["classes"] = len(classes_df)
        progress.advance(task)

        progress.update(task, description="[cyan]Generating variables...")
        variables_df = generate_variables(config, files_df, args.seed)
        stats["nodes"]["variables"] = len(variables_df)
        progress.advance(task)

        progress.update(task, description="[cyan]Generating imports...")
        imports_df = generate_imports(config, files_df, args.seed)
        stats["nodes"]["imports"] = len(imports_df)
        progress.advance(task)

        progress.update(task, description="[cyan]Generating decorators...")
        decorators_df = generate_decorators(config, files_df, args.seed)
        stats["nodes"]["decorators"] = len(decorators_df)
        progress.advance(task)

        progress.update(task, description="[cyan]Generating attributes...")
        attributes_df = generate_attributes(config, classes_df, args.seed)
        stats["nodes"]["attributes"] = len(attributes_df)
        progress.advance(task)

        progress.update(task, description="[cyan]Generating exceptions...")
        exceptions_df = generate_exceptions(config, files_df, args.seed)
        stats["nodes"]["exceptions"] = len(exceptions_df)
        progress.advance(task)

        # Generate edges
        task2 = progress.add_task("[magenta]Generating edges...", total=10)

        progress.update(task2, description="[magenta]Generating calls edges...")
        calls_df = generate_calls_edges(functions_df, args.seed)
        stats["edges"]["calls"] = len(calls_df)
        progress.advance(task2)

        progress.update(task2, description="[magenta]Generating contains_function edges...")
        contains_function_df = generate_contains_function_edges(files_df, functions_df)
        stats["edges"]["contains_function"] = len(contains_function_df)
        progress.advance(task2)

        progress.update(task2, description="[magenta]Generating contains_class edges...")
        contains_class_df = generate_contains_class_edges(files_df, classes_df)
        stats["edges"]["contains_class"] = len(contains_class_df)
        progress.advance(task2)

        progress.update(task2, description="[magenta]Generating contains_variable edges...")
        contains_variable_df = generate_contains_variable_edges(files_df, variables_df)
        stats["edges"]["contains_variable"] = len(contains_variable_df)
        progress.advance(task2)

        progress.update(task2, description="[magenta]Generating method_of edges...")
        method_of_df = generate_method_of_edges(functions_df, classes_df, args.seed)
        stats["edges"]["method_of"] = len(method_of_df)
        progress.advance(task2)

        progress.update(task2, description="[magenta]Generating inherits edges...")
        inherits_df = generate_inherits_edges(classes_df, args.seed)
        stats["edges"]["inherits"] = len(inherits_df)
        progress.advance(task2)

        progress.update(task2, description="[magenta]Generating has_import edges...")
        has_import_df = generate_has_import_edges(files_df, imports_df)
        stats["edges"]["has_import"] = len(has_import_df)
        progress.advance(task2)

        progress.update(task2, description="[magenta]Generating decorated_by edges...")
        decorated_by_df = generate_decorated_by_edges(functions_df, decorators_df, args.seed)
        stats["edges"]["decorated_by"] = len(decorated_by_df)
        progress.advance(task2)

        progress.update(task2, description="[magenta]Generating has_attribute edges...")
        has_attribute_df = generate_has_attribute_edges(classes_df, attributes_df)
        stats["edges"]["has_attribute"] = len(has_attribute_df)
        progress.advance(task2)

        progress.update(task2, description="[magenta]Generating references edges...")
        references_df = generate_references_edges(functions_df, variables_df, args.seed)
        stats["edges"]["references"] = len(references_df)
        progress.advance(task2)

        # Additional edges
        accesses_df = generate_accesses_edges(functions_df, attributes_df, args.seed)
        stats["edges"]["accesses"] = len(accesses_df)

        handles_exception_df = generate_handles_exception_edges(functions_df, exceptions_df, args.seed)
        stats["edges"]["handles_exception"] = len(handles_exception_df)

    console.print()
    console.print("[bold green]Writing Parquet files...[/bold green]")
    console.print()

    # Write nodes
    console.print("[cyan]Nodes:[/cyan]")
    write_parquet(files_df, output_dir / "nodes" / "files.parquet", "Files")
    write_parquet(functions_df, output_dir / "nodes" / "functions.parquet", "Functions")
    write_parquet(classes_df, output_dir / "nodes" / "classes.parquet", "Classes")
    write_parquet(variables_df, output_dir / "nodes" / "variables.parquet", "Variables")
    write_parquet(imports_df, output_dir / "nodes" / "imports.parquet", "Imports")
    write_parquet(decorators_df, output_dir / "nodes" / "decorators.parquet", "Decorators")
    write_parquet(attributes_df, output_dir / "nodes" / "attributes.parquet", "Attributes")
    write_parquet(exceptions_df, output_dir / "nodes" / "exceptions.parquet", "Exceptions")

    console.print()
    console.print("[magenta]Edges:[/magenta]")
    write_parquet(calls_df, output_dir / "edges" / "calls.parquet", "Calls")
    write_parquet(contains_function_df, output_dir / "edges" / "contains_function.parquet", "Contains Function")
    write_parquet(contains_class_df, output_dir / "edges" / "contains_class.parquet", "Contains Class")
    write_parquet(contains_variable_df, output_dir / "edges" / "contains_variable.parquet", "Contains Variable")
    write_parquet(method_of_df, output_dir / "edges" / "method_of.parquet", "Method Of")
    write_parquet(inherits_df, output_dir / "edges" / "inherits.parquet", "Inherits")
    write_parquet(has_import_df, output_dir / "edges" / "has_import.parquet", "Has Import")
    write_parquet(decorated_by_df, output_dir / "edges" / "decorated_by.parquet", "Decorated By")
    write_parquet(has_attribute_df, output_dir / "edges" / "has_attribute.parquet", "Has Attribute")
    write_parquet(references_df, output_dir / "edges" / "references.parquet", "References")
    write_parquet(accesses_df, output_dir / "edges" / "accesses.parquet", "Accesses")
    write_parquet(handles_exception_df, output_dir / "edges" / "handles_exception.parquet", "Handles Exception")

    elapsed = timer.stop()
    display_summary(stats, elapsed)


if __name__ == "__main__":
    main()
