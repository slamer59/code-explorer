#!/usr/bin/env python3
"""
Export dependency graph to JSON format.

Analyzes Python files and exports dependencies as JSON with nodes and edges.
"""

import ast
import json
import sys
from pathlib import Path
from typing import Dict, List, Set


def extract_imports(file_path: Path, base_path: Path) -> Set[str]:
    """Extract import statements from a Python file.

    Args:
        file_path: Path to the Python file
        base_path: Base path for calculating relative imports

    Returns:
        Set of imported module paths
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(file_path))

        imports = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.level == 0:
                    # Absolute import
                    imports.add(node.module.split(".")[0])
                elif node.level > 0:
                    # Relative import - resolve to absolute path
                    current_package = file_path.parent
                    for _ in range(node.level - 1):
                        current_package = current_package.parent
                    if node.module:
                        target = current_package / node.module.replace(".", "/")
                    else:
                        target = current_package

                    try:
                        rel_target = target.relative_to(base_path)
                        imports.add(str(rel_target).replace("/", "."))
                    except ValueError:
                        pass

        return imports

    except (SyntaxError, UnicodeDecodeError, FileNotFoundError):
        return set()


def build_python_dependency_graph(
    root_dirs: List[Path], exclude_patterns: List[str] = None
) -> Dict:
    """Build dependency graph for Python files.

    Args:
        root_dirs: List of root directories to analyze
        exclude_patterns: Patterns to exclude (e.g., 'tests', '__pycache__')

    Returns:
        Dictionary with 'nodes' and 'edges' for the dependency graph
    """
    if exclude_patterns is None:
        exclude_patterns = [
            "__pycache__",
            "tests",
            ".pytest_cache",
            "htmlcov",
            "dist",
            "build",
        ]

    graph = {
        "nodes": [],
        "edges": [],
        "metadata": {
            "language": "python",
            "tool": "custom-ast-parser",
            "root_dirs": [str(d) for d in root_dirs],
        },
    }

    node_ids = set()

    for root_dir in root_dirs:
        if not root_dir.exists():
            print(f"Warning: {root_dir} does not exist", file=sys.stderr)
            continue

        for py_file in root_dir.rglob("*.py"):
            # Skip excluded patterns
            if any(pattern in str(py_file) for pattern in exclude_patterns):
                continue

            rel_path = str(py_file.relative_to(root_dir))
            node_id = f"{root_dir.name}/{rel_path}"

            # Add node
            if node_id not in node_ids:
                graph["nodes"].append({
                    "id": node_id,
                    "path": str(py_file),
                    "type": "file",
                    "language": "python",
                    "package": root_dir.name,
                })
                node_ids.add(node_id)

            # Extract imports and create edges
            imports = extract_imports(py_file, root_dir)

            for imp in imports:
                # Try to resolve import to a file in our codebase
                for check_root in root_dirs:
                    potential_file = check_root / imp.replace(".", "/") / "__init__.py"
                    potential_module = check_root / (imp.replace(".", "/") + ".py")

                    target_file = None
                    if potential_file.exists():
                        target_file = potential_file
                    elif potential_module.exists():
                        target_file = potential_module

                    if target_file:
                        try:
                            target_rel = str(target_file.relative_to(check_root))
                            target_id = f"{check_root.name}/{target_rel}"

                            # Add target node if not exists
                            if target_id not in node_ids:
                                graph["nodes"].append({
                                    "id": target_id,
                                    "path": str(target_file),
                                    "type": "file",
                                    "language": "python",
                                    "package": check_root.name,
                                })
                                node_ids.add(target_id)

                            # Add edge
                            graph["edges"].append({
                                "source": node_id,
                                "target": target_id,
                                "type": "import",
                            })
                            break
                        except ValueError:
                            continue

    return graph


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Export Python dependency graph to JSON"
    )
    parser.add_argument(
        "directories", nargs="+", type=Path, help="Directories to analyze"
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("dependencies.json"),
        help="Output JSON file (default: dependencies.json)",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        help="Patterns to exclude (can be specified multiple times)",
    )
    parser.add_argument(
        "--pretty", action="store_true", help="Pretty-print JSON output"
    )

    args = parser.parse_args()

    # Build dependency graph
    print(f"Analyzing {len(args.directories)} directories...", file=sys.stderr)
    graph = build_python_dependency_graph(
        args.directories, exclude_patterns=args.exclude
    )

    print(
        f"Found {len(graph['nodes'])} nodes and {len(graph['edges'])} edges",
        file=sys.stderr,
    )

    # Write to JSON
    with open(args.output, "w", encoding="utf-8") as f:
        if args.pretty:
            json.dump(graph, f, indent=2, ensure_ascii=False)
        else:
            json.dump(graph, f, ensure_ascii=False)

    print(f"Exported to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()

if __name__ == "__main__":
    main()
