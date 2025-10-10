#!/usr/bin/env python3
"""
Code analysis module using ast and astroid.

Extracts functions, function calls, variables, and their dependencies from Python code.
"""

import ast
import hashlib
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Set, Tuple

import astroid
from astroid.nodes import Module, FunctionDef, Call, Name, Attribute
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn

logger = logging.getLogger(__name__)


@dataclass
class FunctionInfo:
    """Information about a function."""
    name: str
    file: str
    start_line: int
    end_line: int
    is_public: bool


@dataclass
class FunctionCall:
    """Information about a function call."""
    caller_function: str
    called_name: str
    call_line: int


@dataclass
class VariableInfo:
    """Information about a variable."""
    name: str
    file: str
    definition_line: int
    scope: str  # "module" or "function:func_name"


@dataclass
class VariableUsage:
    """Information about variable usage."""
    variable_name: str
    function_name: str
    usage_line: int


@dataclass
class ImportInfo:
    """Information about an import."""
    module: str
    line_number: int
    is_relative: bool


@dataclass
class FileAnalysis:
    """Complete analysis result for a single file."""
    file_path: str
    content_hash: str
    functions: List[FunctionInfo] = field(default_factory=list)
    function_calls: List[FunctionCall] = field(default_factory=list)
    variables: List[VariableInfo] = field(default_factory=list)
    variable_usage: List[VariableUsage] = field(default_factory=list)
    imports: List[ImportInfo] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class CodeAnalyzer:
    """Analyzes Python code to extract dependencies."""

    def __init__(self):
        """Initialize the code analyzer."""
        pass

    def compute_hash(self, file_path: Path) -> str:
        """Compute SHA-256 hash of file contents.

        Args:
            file_path: Path to the file

        Returns:
            Hexadecimal hash string
        """
        try:
            with open(file_path, 'rb') as f:
                return hashlib.sha256(f.read()).hexdigest()
        except Exception as e:
            logger.error(f"Error computing hash for {file_path}: {e}")
            return ""

    def analyze_file(self, file_path: Path) -> FileAnalysis:
        """Analyze a single Python file using ast and astroid.

        Args:
            file_path: Path to the Python file

        Returns:
            FileAnalysis containing all extracted information
        """
        result = FileAnalysis(
            file_path=str(file_path),
            content_hash=self.compute_hash(file_path)
        )

        try:
            # Read file content
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Parse with ast for basic structure
            try:
                tree = ast.parse(content, filename=str(file_path))
            except SyntaxError as e:
                result.errors.append(f"Syntax error: {e}")
                return result

            # Extract functions using ast
            self._extract_functions_ast(tree, result)

            # Extract imports using ast
            self._extract_imports_ast(tree, result)

            # Extract variables using ast
            self._extract_variables_ast(tree, result)

            # Try astroid for better name resolution
            try:
                astroid_module = astroid.parse(content, module_name=file_path.stem)
                self._extract_function_calls_astroid(astroid_module, result)
                self._extract_variable_usage_astroid(astroid_module, result)
            except Exception as e:
                logger.warning(f"Astroid analysis failed for {file_path}, falling back to ast: {e}")
                # Fallback to simpler ast-based call extraction
                self._extract_function_calls_ast(tree, result)
                self._extract_variable_usage_ast(tree, result)

        except UnicodeDecodeError as e:
            result.errors.append(f"Encoding error: {e}")
        except Exception as e:
            result.errors.append(f"Unexpected error: {e}")
            logger.exception(f"Error analyzing {file_path}")

        return result

    def _extract_functions_ast(self, tree: ast.AST, result: FileAnalysis) -> None:
        """Extract function definitions using ast.

        Args:
            tree: AST tree
            result: FileAnalysis to populate
        """
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                func_info = FunctionInfo(
                    name=node.name,
                    file=result.file_path,
                    start_line=node.lineno,
                    end_line=node.end_lineno or node.lineno,
                    is_public=not node.name.startswith('_')
                )
                result.functions.append(func_info)

    def _extract_imports_ast(self, tree: ast.AST, result: FileAnalysis) -> None:
        """Extract import statements using ast.

        Args:
            tree: AST tree
            result: FileAnalysis to populate
        """
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    import_info = ImportInfo(
                        module=alias.name,
                        line_number=node.lineno,
                        is_relative=False
                    )
                    result.imports.append(import_info)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    import_info = ImportInfo(
                        module=node.module,
                        line_number=node.lineno,
                        is_relative=node.level > 0
                    )
                    result.imports.append(import_info)

    def _extract_function_calls_ast(self, tree: ast.AST, result: FileAnalysis) -> None:
        """Extract function calls using simple ast traversal.

        This is a fallback when astroid fails. It's less precise but more robust.

        Args:
            tree: AST tree
            result: FileAnalysis to populate
        """
        # Build a map of function nodes to their names
        function_nodes = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                function_nodes[id(node)] = node.name

        # Find calls within each function
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                caller_name = node.name
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        called_name = self._get_call_name(child.func)
                        if called_name:
                            call_info = FunctionCall(
                                caller_function=caller_name,
                                called_name=called_name,
                                call_line=child.lineno
                            )
                            result.function_calls.append(call_info)

    def _get_call_name(self, node: ast.AST) -> Optional[str]:
        """Extract function name from a call node.

        Args:
            node: AST node representing the called function

        Returns:
            Function name or None
        """
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            # For method calls like obj.method(), just return 'method'
            return node.attr
        return None

    def _extract_function_calls_astroid(self, module: Module, result: FileAnalysis) -> None:
        """Extract function calls using astroid for better name resolution.

        Args:
            module: Astroid module
            result: FileAnalysis to populate
        """
        # Find all function definitions
        for node in module.nodes_of_class(FunctionDef):
            caller_name = node.name

            # Find all calls within this function
            for call_node in node.nodes_of_class(Call):
                called_name = None

                if isinstance(call_node.func, Name):
                    called_name = call_node.func.name
                elif isinstance(call_node.func, Attribute):
                    called_name = call_node.func.attrname

                if called_name:
                    call_info = FunctionCall(
                        caller_function=caller_name,
                        called_name=called_name,
                        call_line=call_node.lineno
                    )
                    result.function_calls.append(call_info)

    def _extract_variables_ast(self, tree: ast.AST, result: FileAnalysis) -> None:
        """Extract variable definitions using ast.

        Args:
            tree: AST tree
            result: FileAnalysis to populate
        """
        # Extract module-level variables
        if isinstance(tree, ast.Module):
            for node in tree.body:
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        var_names = self._get_assignment_targets(target)
                        for var_name in var_names:
                            var_info = VariableInfo(
                                name=var_name,
                                file=result.file_path,
                                definition_line=node.lineno,
                                scope="module"
                            )
                            result.variables.append(var_info)

        # Extract function-level variables
        for func_node in ast.walk(tree):
            if isinstance(func_node, ast.FunctionDef):
                for node in ast.walk(func_node):
                    if isinstance(node, ast.Assign):
                        for target in node.targets:
                            var_names = self._get_assignment_targets(target)
                            for var_name in var_names:
                                var_info = VariableInfo(
                                    name=var_name,
                                    file=result.file_path,
                                    definition_line=node.lineno,
                                    scope=f"function:{func_node.name}"
                                )
                                result.variables.append(var_info)

    def _get_assignment_targets(self, node: ast.AST) -> List[str]:
        """Extract variable names from assignment targets.

        Args:
            node: AST node representing assignment target

        Returns:
            List of variable names
        """
        names = []
        if isinstance(node, ast.Name):
            names.append(node.id)
        elif isinstance(node, ast.Tuple) or isinstance(node, ast.List):
            for elt in node.elts:
                names.extend(self._get_assignment_targets(elt))
        return names

    def _extract_variable_usage_ast(self, tree: ast.AST, result: FileAnalysis) -> None:
        """Extract variable usage using ast.

        Args:
            tree: AST tree
            result: FileAnalysis to populate
        """
        # Find variable usage within each function
        for func_node in ast.walk(tree):
            if isinstance(func_node, ast.FunctionDef):
                func_name = func_node.name
                for node in ast.walk(func_node):
                    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                        # This is a variable being read (not assigned)
                        usage_info = VariableUsage(
                            variable_name=node.id,
                            function_name=func_name,
                            usage_line=node.lineno
                        )
                        result.variable_usage.append(usage_info)

    def _extract_variable_usage_astroid(self, module: Module, result: FileAnalysis) -> None:
        """Extract variable usage using astroid.

        Args:
            module: Astroid module
            result: FileAnalysis to populate
        """
        # Find all function definitions
        for func_node in module.nodes_of_class(FunctionDef):
            func_name = func_node.name

            # Find all name references within this function
            for name_node in func_node.nodes_of_class(Name):
                # Check if it's a load context (reading, not assigning)
                try:
                    # astroid uses different context types; check if it's a load
                    if hasattr(name_node, 'ctx') and str(type(name_node.ctx).__name__) == 'Load':
                        usage_info = VariableUsage(
                            variable_name=name_node.name,
                            function_name=func_name,
                            usage_line=name_node.lineno
                        )
                        result.variable_usage.append(usage_info)
                except AttributeError:
                    # Some nodes might not have ctx
                    pass

    def analyze_directory(
        self,
        root_path: Path,
        parallel: bool = True,
        exclude_patterns: Optional[List[str]] = None
    ) -> List[FileAnalysis]:
        """Analyze all Python files in a directory recursively.

        Args:
            root_path: Root directory to analyze
            parallel: Whether to use parallel processing
            exclude_patterns: Patterns to exclude (e.g., '__pycache__', 'tests')

        Returns:
            List of FileAnalysis results
        """
        if exclude_patterns is None:
            exclude_patterns = [
                '__pycache__',
                '.pytest_cache',
                'htmlcov',
                'dist',
                'build',
                '.git',
                '.venv',
                'venv',
            ]

        # Find all Python files
        python_files = []
        for py_file in root_path.rglob('*.py'):
            # Skip excluded patterns
            if any(pattern in str(py_file) for pattern in exclude_patterns):
                continue
            python_files.append(py_file)

        if not python_files:
            logger.warning(f"No Python files found in {root_path}")
            return []

        results = []

        if parallel:
            # Use ThreadPoolExecutor for parallel analysis
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TimeElapsedColumn(),
            ) as progress:
                task = progress.add_task(
                    f"Analyzing {len(python_files)} files...",
                    total=len(python_files)
                )

                with ThreadPoolExecutor(max_workers=8) as executor:
                    # Submit all files for analysis
                    future_to_file = {
                        executor.submit(self.analyze_file, py_file): py_file
                        for py_file in python_files
                    }

                    # Collect results as they complete
                    for future in as_completed(future_to_file):
                        py_file = future_to_file[future]
                        try:
                            result = future.result()
                            results.append(result)
                        except Exception as e:
                            logger.error(f"Failed to analyze {py_file}: {e}")
                        finally:
                            progress.update(task, advance=1)
        else:
            # Sequential analysis
            for py_file in python_files:
                result = self.analyze_file(py_file)
                results.append(result)

        return results


def main():
    """Simple test of the analyzer."""
    import sys

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s: %(message)s'
    )

    if len(sys.argv) < 2:
        print("Usage: python analyzer.py <file_or_directory>")
        sys.exit(1)

    path = Path(sys.argv[1])
    analyzer = CodeAnalyzer()

    if path.is_file():
        # Analyze single file
        result = analyzer.analyze_file(path)
        print(f"\n=== Analysis of {result.file_path} ===")
        print(f"Hash: {result.content_hash}")
        print(f"\nFunctions ({len(result.functions)}):")
        for func in result.functions:
            visibility = "public" if func.is_public else "private"
            print(f"  - {func.name} (lines {func.start_line}-{func.end_line}, {visibility})")

        print(f"\nFunction calls ({len(result.function_calls)}):")
        for call in result.function_calls:
            print(f"  - {call.caller_function} calls {call.called_name} at line {call.call_line}")

        print(f"\nImports ({len(result.imports)}):")
        for imp in result.imports:
            imp_type = "relative" if imp.is_relative else "absolute"
            print(f"  - {imp.module} (line {imp.line_number}, {imp_type})")

        print(f"\nVariables ({len(result.variables)}):")
        for var in result.variables[:20]:  # Limit to first 20
            print(f"  - {var.name} (line {var.definition_line}, scope: {var.scope})")
        if len(result.variables) > 20:
            print(f"  ... and {len(result.variables) - 20} more")

        print(f"\nVariable usage ({len(result.variable_usage)}):")
        usage_summary = {}
        for usage in result.variable_usage:
            key = usage.variable_name
            usage_summary[key] = usage_summary.get(key, 0) + 1
        for var_name, count in sorted(usage_summary.items(), key=lambda x: x[1], reverse=True)[:10]:
            print(f"  - {var_name}: used {count} times")

        if result.errors:
            print(f"\nErrors ({len(result.errors)}):")
            for error in result.errors:
                print(f"  - {error}")

    elif path.is_dir():
        # Analyze directory
        results = analyzer.analyze_directory(path, parallel=True)
        print(f"\n=== Analyzed {len(results)} files ===")

        total_functions = sum(len(r.functions) for r in results)
        total_calls = sum(len(r.function_calls) for r in results)
        total_errors = sum(len(r.errors) for r in results)

        print(f"Total functions: {total_functions}")
        print(f"Total function calls: {total_calls}")
        print(f"Files with errors: {total_errors}")

        # Show files with most functions
        results_sorted = sorted(results, key=lambda r: len(r.functions), reverse=True)
        print("\nTop 10 files by function count:")
        for result in results_sorted[:10]:
            print(f"  - {Path(result.file_path).name}: {len(result.functions)} functions")

    else:
        print(f"Error: {path} is not a file or directory")
        sys.exit(1)


if __name__ == "__main__":
    main()
