#!/usr/bin/env python3
"""
Code analysis module using ast and astroid.

Extracts functions, function calls, variables, and their dependencies from Python code.
"""

import ast
import hashlib
import json
import logging
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import astroid
from astroid.nodes import Attribute, Call, FunctionDef, Module, Name
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

logger = logging.getLogger(__name__)


@dataclass
class FunctionInfo:
    """Information about a function."""

    name: str
    file: str
    start_line: int
    end_line: int
    is_public: bool
    source_code: Optional[str] = None
    parent_class: Optional[str] = None


@dataclass
class ClassInfo:
    """Information about a class."""

    name: str
    file: str
    start_line: int
    end_line: int
    bases: List[str]  # Base class names
    methods: List[str]  # Method names
    is_public: bool
    source_code: Optional[str] = None


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
class ImportDetailedInfo:
    """Detailed information about an import statement."""

    imported_name: str
    import_type: str  # "module", "function", "class", "variable", "*"
    alias: Optional[str]
    line_number: int
    is_relative: bool
    module: Optional[str]  # For "from X import Y", this is X


@dataclass
class DecoratorInfo:
    """Information about a decorator."""

    name: str
    file: str
    line_number: int
    arguments: str  # JSON-serialized decorator arguments
    target_name: str  # Name of decorated function/class
    target_type: str  # "function" or "class"


@dataclass
class AttributeInfo:
    """Information about a class attribute."""

    name: str
    class_name: str
    file: str
    definition_line: int
    type_hint: Optional[str]
    is_class_attribute: bool


@dataclass
class ExceptionInfo:
    """Information about an exception."""

    name: str
    file: str
    line_number: int
    context: str  # "raise" or "catch"
    function_name: Optional[str]  # Function where exception appears


@dataclass
class ModuleInfo:
    """Information about module hierarchy."""

    name: str
    path: str
    is_package: bool
    docstring: Optional[str]


@dataclass
class FileAnalysis:
    """Complete analysis result for a single file."""

    file_path: str
    content_hash: str
    functions: List[FunctionInfo] = field(default_factory=list)
    classes: List[ClassInfo] = field(default_factory=list)
    function_calls: List[FunctionCall] = field(default_factory=list)
    variables: List[VariableInfo] = field(default_factory=list)
    variable_usage: List[VariableUsage] = field(default_factory=list)
    imports: List[ImportInfo] = field(default_factory=list)
    imports_detailed: List[ImportDetailedInfo] = field(default_factory=list)
    decorators: List[DecoratorInfo] = field(default_factory=list)
    attributes: List[AttributeInfo] = field(default_factory=list)
    exceptions: List[ExceptionInfo] = field(default_factory=list)
    module_info: Optional[ModuleInfo] = None
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
            with open(file_path, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()
        except Exception as e:
            logger.error(f"Error computing hash for {file_path}: {e}")
            return ""

    def _run_extractions(self, tree: ast.AST, result: FileAnalysis) -> None:
        """Run extraction methods sequentially.

        Args:
            tree: AST tree
            result: FileAnalysis to populate
        """
        # Run extractions sequentially (faster due to no thread pool overhead)
        try:
            self._extract_functions_ast(tree, result)
        except Exception as e:
            logger.error(f"Function extraction failed: {e}")

        try:
            self._extract_imports_ast(tree, result)
        except Exception as e:
            logger.error(f"Import extraction failed: {e}")

        try:
            self._extract_variables_ast(tree, result)
        except Exception as e:
            logger.error(f"Variable extraction failed: {e}")

        try:
            self._extract_imports_detailed(tree, result)
        except Exception as e:
            logger.error(f"Detailed import extraction failed: {e}")

        try:
            self._extract_decorators(tree, result)
        except Exception as e:
            logger.error(f"Decorator extraction failed: {e}")

        try:
            self._extract_exceptions(tree, result)
        except Exception as e:
            logger.error(f"Exception extraction failed: {e}")

        try:
            self._extract_attributes(tree, result)
        except Exception as e:
            logger.error(f"Attribute extraction failed: {e}")

        try:
            self._extract_module_info(result)
        except Exception as e:
            logger.error(f"Module info extraction failed: {e}")

        # Extract classes (depends on functions being extracted first)
        try:
            self._extract_classes_ast(tree, result)
        except Exception as e:
            logger.error(f"Class extraction failed: {e}")

    def analyze_file(
        self,
        file_path: Path,
        progress: Optional[Progress] = None,
        parent_task_id: Optional[object] = None,
    ) -> FileAnalysis:
        """Analyze a single Python file using ast and astroid.

        Args:
            file_path: Path to the Python file
            progress: Optional Progress instance for nested progress display
            parent_task_id: Optional parent task ID for nested progress

        Returns:
            FileAnalysis containing all extracted information
        """
        result = FileAnalysis(
            file_path=str(file_path), content_hash=self.compute_hash(file_path)
        )

        # Create sub-task for this file if progress tracking enabled
        sub_task_id = None
        if progress is not None:
            file_name = Path(file_path).name
            sub_task_id = progress.add_task(
                f"  └─ {file_name}: Starting...", total=100, visible=True
            )

        try:
            # Read file content
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            if sub_task_id is not None:
                file_name = Path(file_path).name
                progress.update(
                    sub_task_id,
                    completed=10,
                    description=f"  └─ {file_name}: Parsing AST...",
                )

            # Parse with ast for basic structure
            try:
                tree = ast.parse(content, filename=str(file_path))
            except SyntaxError as e:
                result.errors.append(f"Syntax error: {e}")
                if sub_task_id is not None:
                    file_name = Path(file_path).name
                    progress.update(
                        sub_task_id, description=f"  └─ {file_name}: Failed ✗"
                    )
                return result

            if sub_task_id is not None:
                file_name = Path(file_path).name
                progress.update(
                    sub_task_id,
                    completed=30,
                    description=f"  └─ {file_name}: Running extractions...",
                )

            # Run all AST extractions sequentially
            self._run_extractions(tree, result)

            if sub_task_id is not None:
                file_name = Path(file_path).name
                progress.update(
                    sub_task_id,
                    completed=70,
                    description=f"  └─ {file_name}: Astroid analysis...",
                )

            # Try astroid for better name resolution
            try:
                astroid_module = astroid.parse(content, module_name=file_path.stem)

                # Run astroid extractions sequentially
                try:
                    self._extract_function_calls_astroid(astroid_module, result)
                except Exception as e:
                    logger.error(f"Astroid function call extraction failed: {e}")

                try:
                    self._extract_variable_usage_astroid(astroid_module, result)
                except Exception as e:
                    logger.error(f"Astroid variable usage extraction failed: {e}")
            except Exception as e:
                logger.warning(
                    f"Astroid analysis failed for {file_path}, falling back to ast: {e}"
                )
                # Fallback to simpler ast-based call extraction
                try:
                    self._extract_function_calls_ast(tree, result)
                except Exception as e:
                    logger.error(f"Fallback function call extraction failed: {e}")

                try:
                    self._extract_variable_usage_ast(tree, result)
                except Exception as e:
                    logger.error(f"Fallback variable usage extraction failed: {e}")

            if sub_task_id is not None:
                file_name = Path(file_path).name
                progress.update(
                    sub_task_id,
                    completed=100,
                    description=f"  └─ {file_name}: Complete ✓",
                )

        except UnicodeDecodeError as e:
            result.errors.append(f"Encoding error: {e}")
            if sub_task_id is not None:
                file_name = Path(file_path).name
                progress.update(sub_task_id, description=f"  └─ {file_name}: Failed ✗")
        except Exception as e:
            result.errors.append(f"Unexpected error: {e}")
            logger.exception(f"Error analyzing {file_path}")
            if sub_task_id is not None:
                file_name = Path(file_path).name
                progress.update(sub_task_id, description=f"  └─ {file_name}: Failed ✗")

        return result

    def _extract_functions_ast(self, tree: ast.AST, result: FileAnalysis) -> None:
        """Extract function definitions using ast.

        Args:
            tree: AST tree
            result: FileAnalysis to populate
        """
        # Read file to extract source code
        source_lines = None
        try:
            with open(result.file_path, "r", encoding="utf-8") as f:
                source_lines = f.readlines()
        except Exception as e:
            logger.warning(f"Could not read source for {result.file_path}: {e}")

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                # Extract source code if available
                source_code = None
                if source_lines and node.lineno and node.end_lineno:
                    try:
                        # Extract lines (1-indexed to 0-indexed)
                        func_lines = source_lines[node.lineno - 1 : node.end_lineno]
                        source_code = "".join(func_lines)
                    except Exception as e:
                        logger.warning(f"Could not extract source for {node.name}: {e}")

                func_info = FunctionInfo(
                    name=node.name,
                    file=result.file_path,
                    start_line=node.lineno,
                    end_line=node.end_lineno or node.lineno,
                    is_public=not node.name.startswith("_"),
                    source_code=source_code,
                    parent_class=None,  # Will be updated by _extract_classes_ast
                )
                result.functions.append(func_info)

    def _parse_base_class(self, base: ast.expr) -> str:
        """Parse a base class expression to extract its name.

        Args:
            base: AST expression node representing a base class

        Returns:
            String representation of the base class name
        """
        if isinstance(base, ast.Name):
            return base.id
        else:
            # For complex base expressions, use unparse
            try:
                return ast.unparse(base)
            except Exception:
                return "<complex>"

    def _link_methods_to_class(
        self, methods: List[Tuple[str, int]], class_name: str, result: FileAnalysis
    ) -> None:
        """Link method names to their parent class in FunctionInfo objects.

        Args:
            methods: List of tuples containing (method_name, line_number)
            class_name: Name of the parent class
            result: FileAnalysis object to update
        """
        for method_name, method_line in methods:
            for func_info in result.functions:
                if (
                    func_info.name == method_name
                    and func_info.start_line == method_line
                ):
                    func_info.parent_class = class_name
                    break

    def _extract_classes_ast(self, tree: ast.AST, result: FileAnalysis) -> None:
        """Extract class definitions using ast.

        Args:
            tree: AST tree
            result: FileAnalysis to populate
        """
        # Read file to extract source code
        source_lines = None
        try:
            with open(result.file_path, "r", encoding="utf-8") as f:
                source_lines = f.readlines()
        except Exception as e:
            logger.warning(f"Could not read source for {result.file_path}: {e}")

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                # Extract base class names using helper
                bases = [self._parse_base_class(base) for base in node.bases]

                # Extract method names and their line numbers
                method_info = [
                    (item.name, item.lineno)
                    for item in node.body
                    if isinstance(item, ast.FunctionDef)
                ]
                methods = [name for name, _ in method_info]

                # Link methods to this class using helper
                self._link_methods_to_class(method_info, node.name, result)

                # Extract source code if available
                source_code = None
                if source_lines and node.lineno and node.end_lineno:
                    try:
                        # Extract lines (1-indexed to 0-indexed)
                        class_lines = source_lines[node.lineno - 1 : node.end_lineno]
                        source_code = "".join(class_lines)
                    except Exception as e:
                        logger.warning(
                            f"Could not extract source for class {node.name}: {e}"
                        )

                class_info = ClassInfo(
                    name=node.name,
                    file=result.file_path,
                    start_line=node.lineno,
                    end_line=node.end_lineno or node.lineno,
                    bases=bases,
                    methods=methods,
                    is_public=not node.name.startswith("_"),
                    source_code=source_code,
                )
                result.classes.append(class_info)

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
                        module=alias.name, line_number=node.lineno, is_relative=False
                    )
                    result.imports.append(import_info)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    import_info = ImportInfo(
                        module=node.module,
                        line_number=node.lineno,
                        is_relative=node.level > 0,
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
                        # Skip if lineno is None
                        if child.lineno is None:
                            continue
                        called_name = self._get_call_name(child.func)
                        if called_name:
                            call_info = FunctionCall(
                                caller_function=caller_name,
                                called_name=called_name,
                                call_line=child.lineno,
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

    def _extract_function_calls_astroid(
        self, module: Module, result: FileAnalysis
    ) -> None:
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

                # Skip if lineno is None (type safety)
                if called_name and call_node.lineno is not None:
                    call_info = FunctionCall(
                        caller_function=caller_name,
                        called_name=called_name,
                        call_line=call_node.lineno,
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
                                scope="module",
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
                                    scope=f"function:{func_node.name}",
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
                            usage_line=node.lineno,
                        )
                        result.variable_usage.append(usage_info)

    def _extract_variable_usage_astroid(
        self, module: Module, result: FileAnalysis
    ) -> None:
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
                # Skip if lineno is None (type safety)
                if name_node.lineno is None:
                    continue

                # Check if it's a load context (reading, not assigning)
                try:
                    # astroid uses different context types; check if it's a load
                    # Note: astroid Name nodes may not have ctx attribute
                    if hasattr(name_node, "ctx"):
                        ctx_name = str(type(name_node.ctx).__name__)
                        if ctx_name == "Load":
                            usage_info = VariableUsage(
                                variable_name=name_node.name,
                                function_name=func_name,
                                usage_line=name_node.lineno,
                            )
                            result.variable_usage.append(usage_info)
                except (AttributeError, TypeError):
                    # Some nodes might not have ctx or it might be None
                    pass

    def _extract_imports_detailed(self, tree: ast.AST, result: FileAnalysis) -> None:
        """Extract detailed import information using ast.

        Args:
            tree: AST tree
            result: FileAnalysis to populate
        """
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                # Handle: import module [as alias]
                for alias in node.names:
                    import_info = ImportDetailedInfo(
                        imported_name=alias.name,
                        import_type="module",
                        alias=alias.asname,
                        line_number=node.lineno,
                        is_relative=False,
                        module=None,
                    )
                    result.imports_detailed.append(import_info)
            elif isinstance(node, ast.ImportFrom):
                # Handle: from module import name [as alias]
                module_name = node.module or ""
                is_relative = node.level > 0

                for alias in node.names:
                    # Determine import type based on name
                    import_type = "unknown"
                    if alias.name == "*":
                        import_type = "*"
                    else:
                        # We'll try to infer type later, default to "unknown"
                        import_type = "unknown"

                    import_info = ImportDetailedInfo(
                        imported_name=alias.name,
                        import_type=import_type,
                        alias=alias.asname,
                        line_number=node.lineno,
                        is_relative=is_relative,
                        module=module_name if module_name else None,
                    )
                    result.imports_detailed.append(import_info)

    def _parse_positional_args(self, args: list) -> Dict[str, Any]:
        """Parse positional arguments from decorator call.

        Args:
            args: List of positional argument nodes

        Returns:
            Dictionary of positional arguments
        """
        args_dict = {}
        for i, arg in enumerate(args):
            try:
                # Try to evaluate simple literals
                value = ast.literal_eval(arg)
                args_dict[f"arg_{i}"] = value
            except (ValueError, TypeError):
                # Fall back to unparsing complex expressions
                try:
                    args_dict[f"arg_{i}"] = ast.unparse(arg)
                except Exception:
                    args_dict[f"arg_{i}"] = "<complex>"
        return args_dict

    def _parse_keyword_args(self, keywords: list) -> Dict[str, Any]:
        """Parse keyword arguments from decorator call.

        Args:
            keywords: List of keyword argument nodes

        Returns:
            Dictionary of keyword arguments
        """
        args_dict = {}
        for keyword in keywords:
            try:
                # Try to evaluate simple literals
                value = ast.literal_eval(keyword.value)
                args_dict[keyword.arg or "**kwargs"] = value
            except (ValueError, TypeError):
                # Fall back to unparsing
                try:
                    args_dict[keyword.arg or "**kwargs"] = ast.unparse(keyword.value)
                except Exception:
                    args_dict[keyword.arg or "**kwargs"] = "<complex>"
        return args_dict

    def _parse_decorator_args(self, decorator_call: ast.Call) -> Dict[str, Any]:
        """Parse decorator arguments to a dictionary.

        Args:
            decorator_call: AST Call node representing decorator with arguments

        Returns:
            Dictionary of argument names to values
        """
        args_dict = {}

        try:
            # Parse positional arguments
            positional = self._parse_positional_args(decorator_call.args)
            args_dict.update(positional)

            # Parse keyword arguments
            keywords = self._parse_keyword_args(decorator_call.keywords)
            args_dict.update(keywords)
        except Exception as e:
            logger.warning(f"Error parsing decorator arguments: {e}")

        return args_dict

    def _resolve_decorator_name(self, decorator: ast.expr) -> tuple:
        """Resolve decorator name and arguments from decorator expression.

        Args:
            decorator: AST expression node representing a decorator

        Returns:
            Tuple of (decorator_name, arguments_dict)
        """
        decorator_name = ""
        arguments = {}

        if isinstance(decorator, ast.Name):
            # Simple decorator: @property
            decorator_name = decorator.id
        elif isinstance(decorator, ast.Call):
            # Decorator with arguments: @lru_cache(maxsize=128)
            if isinstance(decorator.func, ast.Name):
                decorator_name = decorator.func.id
            elif isinstance(decorator.func, ast.Attribute):
                # Decorated with attribute access: @dataclasses.dataclass
                try:
                    decorator_name = ast.unparse(decorator.func)
                except Exception:
                    decorator_name = decorator.func.attr
            arguments = self._parse_decorator_args(decorator)
        elif isinstance(decorator, ast.Attribute):
            # Decorator as attribute: @staticmethod
            try:
                decorator_name = ast.unparse(decorator)
            except Exception:
                decorator_name = decorator.attr
        else:
            # Complex decorator expression
            try:
                decorator_name = ast.unparse(decorator)
            except Exception:
                decorator_name = "<complex>"

        return decorator_name, arguments

    def _extract_decorators(self, tree: ast.AST, result: FileAnalysis) -> None:
        """Extract decorator information using ast.

        Args:
            tree: AST tree
            result: FileAnalysis to populate
        """
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                target_name = node.name
                target_type = (
                    "function" if isinstance(node, ast.FunctionDef) else "class"
                )

                for decorator in node.decorator_list:
                    # Get decorator name and arguments using helper
                    decorator_name, arguments = self._resolve_decorator_name(decorator)

                    decorator_info = DecoratorInfo(
                        name=decorator_name,
                        file=result.file_path,
                        line_number=decorator.lineno,
                        arguments=json.dumps(arguments),
                        target_name=target_name,
                        target_type=target_type,
                    )
                    result.decorators.append(decorator_info)

    def _extract_type_hint(self, annotation: Optional[ast.AST]) -> Optional[str]:
        """Extract type hint from annotation node.

        Args:
            annotation: AST annotation node

        Returns:
            String representation of type hint or None
        """
        if annotation is None:
            return None

        try:
            return ast.unparse(annotation)
        except Exception:
            return None

    def _extract_class_level_attributes(
        self, class_node: ast.ClassDef, class_name: str, result: FileAnalysis
    ) -> None:
        """Extract class-level attributes from a class definition.

        Args:
            class_node: AST ClassDef node
            class_name: Name of the class
            result: FileAnalysis object to populate
        """
        for item in class_node.body:
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                # Type-annotated class attribute: name: type = value
                attr_info = AttributeInfo(
                    name=item.target.id,
                    class_name=class_name,
                    file=result.file_path,
                    definition_line=item.lineno,
                    type_hint=self._extract_type_hint(item.annotation),
                    is_class_attribute=True,
                )
                result.attributes.append(attr_info)
            elif isinstance(item, ast.Assign):
                # Regular class attribute: name = value
                for target in item.targets:
                    if isinstance(target, ast.Name):
                        attr_info = AttributeInfo(
                            name=target.id,
                            class_name=class_name,
                            file=result.file_path,
                            definition_line=item.lineno,
                            type_hint=None,
                            is_class_attribute=True,
                        )
                        result.attributes.append(attr_info)

    def _extract_instance_attributes(
        self, init_node: ast.FunctionDef, class_name: str, result: FileAnalysis
    ) -> None:
        """Extract instance attributes from __init__ method.

        Args:
            init_node: AST FunctionDef node for __init__ method
            class_name: Name of the parent class
            result: FileAnalysis object to populate
        """
        for child in ast.walk(init_node):
            if isinstance(child, ast.Assign):
                for target in child.targets:
                    # Look for self.attribute assignments
                    if isinstance(target, ast.Attribute) and isinstance(
                        target.value, ast.Name
                    ):
                        if target.value.id == "self":
                            attr_info = AttributeInfo(
                                name=target.attr,
                                class_name=class_name,
                                file=result.file_path,
                                definition_line=child.lineno,
                                type_hint=None,
                                is_class_attribute=False,
                            )
                            result.attributes.append(attr_info)
            elif isinstance(child, ast.AnnAssign):
                # Type-annotated instance attribute: self.name: type = value
                if isinstance(child.target, ast.Attribute) and isinstance(
                    child.target.value, ast.Name
                ):
                    if child.target.value.id == "self":
                        attr_info = AttributeInfo(
                            name=child.target.attr,
                            class_name=class_name,
                            file=result.file_path,
                            definition_line=child.lineno,
                            type_hint=self._extract_type_hint(child.annotation),
                            is_class_attribute=False,
                        )
                        result.attributes.append(attr_info)

    def _extract_attributes(self, tree: ast.AST, result: FileAnalysis) -> None:
        """Extract class attribute information using ast.

        Args:
            tree: AST tree
            result: FileAnalysis to populate
        """
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                class_name = node.name

                # Extract class-level attributes using helper
                self._extract_class_level_attributes(node, class_name, result)

                # Extract instance attributes from __init__ using helper
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                        self._extract_instance_attributes(item, class_name, result)
                        break  # Only process the first __init__ found

    def _get_exception_name(self, exc_node: ast.AST) -> Optional[str]:
        """Extract exception name from exception node.

        Args:
            exc_node: AST node representing exception

        Returns:
            Exception name or None
        """
        if isinstance(exc_node, ast.Name):
            return exc_node.id
        elif isinstance(exc_node, ast.Call) and isinstance(exc_node.func, ast.Name):
            return exc_node.func.id
        elif isinstance(exc_node, ast.Attribute):
            try:
                return ast.unparse(exc_node)
            except Exception:
                return exc_node.attr
        else:
            try:
                return ast.unparse(exc_node)
            except Exception:
                return None

    def _extract_raise_statements(
        self, func_node: ast.FunctionDef, func_name: str, result: FileAnalysis
    ) -> None:
        """Extract raise statements from a function node.

        Args:
            func_node: Function AST node
            func_name: Name of the function
            result: FileAnalysis to populate
        """
        for node in ast.walk(func_node):
            if isinstance(node, ast.Raise):
                if node.exc:
                    exc_name = self._get_exception_name(node.exc)
                    if exc_name:
                        exc_info = ExceptionInfo(
                            name=exc_name,
                            file=result.file_path,
                            line_number=node.lineno,
                            context="raise",
                            function_name=func_name,
                        )
                        result.exceptions.append(exc_info)
                else:
                    # Bare raise (re-raise)
                    exc_info = ExceptionInfo(
                        name="<bare-raise>",
                        file=result.file_path,
                        line_number=node.lineno,
                        context="raise",
                        function_name=func_name,
                    )
                    result.exceptions.append(exc_info)

    def _extract_except_handlers(
        self, func_node: ast.FunctionDef, func_name: str, result: FileAnalysis
    ) -> None:
        """Extract except handlers from a function node.

        Args:
            func_node: Function AST node
            func_name: Name of the function
            result: FileAnalysis to populate
        """
        for node in ast.walk(func_node):
            if isinstance(node, ast.ExceptHandler):
                if node.type:
                    # Handle multiple exception types in tuple
                    exc_names = []
                    if isinstance(node.type, ast.Tuple):
                        for elt in node.type.elts:
                            exc_name = self._get_exception_name(elt)
                            if exc_name:
                                exc_names.append(exc_name)
                    else:
                        exc_name = self._get_exception_name(node.type)
                        if exc_name:
                            exc_names.append(exc_name)

                    for exc_name in exc_names:
                        exc_info = ExceptionInfo(
                            name=exc_name,
                            file=result.file_path,
                            line_number=node.lineno,
                            context="catch",
                            function_name=func_name,
                        )
                        result.exceptions.append(exc_info)
                else:
                    # Bare except
                    exc_info = ExceptionInfo(
                        name="<bare-except>",
                        file=result.file_path,
                        line_number=node.lineno,
                        context="catch",
                        function_name=func_name,
                    )
                    result.exceptions.append(exc_info)

    def _extract_exceptions(self, tree: ast.AST, result: FileAnalysis) -> None:
        """Extract exception raising and handling information using ast.

        Args:
            tree: AST tree
            result: FileAnalysis to populate
        """
        # Find exceptions in functions
        for func_node in ast.walk(tree):
            if isinstance(func_node, ast.FunctionDef):
                func_name = func_node.name
                self._extract_raise_statements(func_node, func_name, result)
                self._extract_except_handlers(func_node, func_name, result)

    def _extract_module_info(self, result: FileAnalysis) -> None:
        """Extract module information from file path.

        Args:
            result: FileAnalysis to populate
        """
        try:
            file_path = Path(result.file_path)

            # Determine if this is a package (__init__.py)
            is_package = file_path.name == "__init__.py"

            # Build module name from path
            # Remove .py extension
            if file_path.suffix == ".py":
                parts = []

                # Walk up the directory tree to build module path
                current = file_path
                if is_package:
                    # For __init__.py, the package name is the directory name
                    current = current.parent
                else:
                    # For regular files, use the stem (filename without extension)
                    parts.insert(0, current.stem)
                    current = current.parent

                # Add parent directories as module parts
                # Stop when we hit a directory without __init__.py
                while current != current.parent:
                    init_file = current / "__init__.py"
                    if init_file.exists():
                        parts.insert(0, current.name)
                        current = current.parent
                    else:
                        break

                module_name = ".".join(parts) if parts else file_path.stem

                # Extract docstring
                docstring = None
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = f.read()
                        tree = ast.parse(content)
                        docstring = ast.get_docstring(tree)
                except Exception as e:
                    logger.debug(f"Could not extract docstring from {file_path}: {e}")

                module_info = ModuleInfo(
                    name=module_name,
                    path=str(file_path),
                    is_package=is_package,
                    docstring=docstring,
                )
                result.module_info = module_info
        except Exception as e:
            logger.warning(f"Error extracting module info for {result.file_path}: {e}")

    def analyze_directory(
        self,
        root_path: Path,
        parallel: bool = True,
        exclude_patterns: Optional[List[str]] = None,
        verbose_progress: bool = False,
    ) -> List[FileAnalysis]:
        """Analyze all Python files in a directory recursively.

        Args:
            root_path: Root directory to analyze
            parallel: Whether to use parallel processing
            exclude_patterns: Patterns to exclude (e.g., '__pycache__', 'tests')
            verbose_progress: Show detailed nested progress for each file (default: False)

        Returns:
            List of FileAnalysis results
        """
        if exclude_patterns is None:
            exclude_patterns = [
                "__pycache__",
                ".pytest_cache",
                "htmlcov",
                "dist",
                "build",
                ".git",
                ".venv",
                "venv",
            ]

        # Find all Python files
        python_files = []
        for py_file in root_path.rglob("*.py"):
            # Skip excluded patterns
            if any(pattern in str(py_file) for pattern in exclude_patterns):
                continue
            python_files.append(py_file)

        if not python_files:
            logger.warning(f"No Python files found in {root_path}")
            return []

        results = []

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            expand=verbose_progress,
        ) as progress:
            task = progress.add_task(
                f"Analyzing {len(python_files)} files...", total=len(python_files)
            )

            if parallel:
                # Use ProcessPoolExecutor for true parallel CPU-bound processing
                with ProcessPoolExecutor(max_workers=os.cpu_count() or 8) as executor:
                    # Submit all files for analysis
                    future_to_file = {
                        executor.submit(
                            self.analyze_file,
                            py_file,
                            progress if verbose_progress else None,
                            task,
                        ): py_file
                        for py_file in python_files
                    }

                    # Collect results as they complete
                    for future in as_completed(future_to_file):
                        py_file = future_to_file[future]
                        try:
                            result = future.result()
                            results.append(result)
                            if not verbose_progress:
                                # Show which file just completed
                                progress.update(
                                    task,
                                    description="Analyzing files...",
                                )
                        except Exception as e:
                            logger.error(f"Failed to analyze {py_file}: {e}")
                        finally:
                            progress.update(task, advance=1)
            else:
                # Sequential analysis
                for py_file in python_files:
                    try:
                        result = self.analyze_file(
                            py_file,
                            progress if verbose_progress else None,
                            task,
                        )
                        results.append(result)
                        if not verbose_progress:
                            # Show which file just completed
                            progress.update(
                                task,
                                description="Analyzing files...",
                            )
                    except Exception as e:
                        logger.error(f"Failed to analyze {py_file}: {e}")
                    finally:
                        progress.update(task, advance=1)

        return results


def _display_file_analysis(result: FileAnalysis) -> None:
    """Display analysis results for a single file.

    Args:
        result: FileAnalysis object to display
    """
    print(f"\n=== Analysis of {result.file_path} ===")
    print(f"Hash: {result.content_hash}")
    print(f"\nFunctions ({len(result.functions)}):")
    for func in result.functions:
        visibility = "public" if func.is_public else "private"
        print(
            f"  - {func.name} (lines {func.start_line}-{func.end_line}, {visibility})"
        )

    print(f"\nFunction calls ({len(result.function_calls)}):")
    for call in result.function_calls:
        print(
            f"  - {call.caller_function} calls {call.called_name} at line {call.call_line}"
        )

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
    for var_name, count in sorted(
        usage_summary.items(), key=lambda x: x[1], reverse=True
    )[:10]:
        print(f"  - {var_name}: used {count} times")

    if result.errors:
        print(f"\nErrors ({len(result.errors)}):")
        for error in result.errors:
            print(f"  - {error}")


def _display_directory_analysis(results: List[FileAnalysis]) -> None:
    """Display analysis results for a directory.

    Args:
        results: List of FileAnalysis objects to display
    """
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


def main():
    """Simple test of the analyzer."""
    import argparse
    import sys

    # Configure logging
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # Create argument parser
    parser = argparse.ArgumentParser(
        description="Analyze Python code to extract functions, classes, and dependencies"
    )
    parser.add_argument("path", type=Path, help="File or directory to analyze")
    parser.add_argument(
        "--parallel",
        action="store_true",
        default=True,
        help="Use parallel processing for directory analysis (default: True)",
    )
    parser.add_argument(
        "--no-parallel",
        dest="parallel",
        action="store_false",
        help="Disable parallel processing",
    )
    parser.add_argument(
        "--verbose-progress",
        action="store_true",
        default=False,
        help="Show detailed nested progress bars for each file being analyzed",
    )

    args = parser.parse_args()

    analyzer = CodeAnalyzer()

    if args.path.is_file():
        result = analyzer.analyze_file(args.path)
        _display_file_analysis(result)
    elif args.path.is_dir():
        results = analyzer.analyze_directory(
            args.path,
            parallel=args.parallel,
            verbose_progress=args.verbose_progress,  # Pass the new flag
        )
        _display_directory_analysis(results)
    else:
        print(f"Error: {args.path} is not a file or directory", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
