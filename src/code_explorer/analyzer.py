#!/usr/bin/env python3
"""
Code analysis module using ast and astroid.

Extracts functions, function calls, variables, and their dependencies from Python code.
"""

import ast
import hashlib
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

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

            # Extract classes using ast (after functions so we can link methods)
            self._extract_classes_ast(tree, result)

            # Extract imports using ast
            self._extract_imports_ast(tree, result)

            # Extract variables using ast
            self._extract_variables_ast(tree, result)

            # Extract new node types using ast
            self._extract_imports_detailed(tree, result)
            self._extract_decorators(tree, result)
            self._extract_attributes(tree, result)
            self._extract_exceptions(tree, result)
            self._extract_module_info(result)

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
        # Read file to extract source code
        source_lines = None
        try:
            with open(result.file_path, 'r', encoding='utf-8') as f:
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
                        func_lines = source_lines[node.lineno - 1:node.end_lineno]
                        source_code = ''.join(func_lines)
                    except Exception as e:
                        logger.warning(f"Could not extract source for {node.name}: {e}")

                func_info = FunctionInfo(
                    name=node.name,
                    file=result.file_path,
                    start_line=node.lineno,
                    end_line=node.end_lineno or node.lineno,
                    is_public=not node.name.startswith('_'),
                    source_code=source_code,
                    parent_class=None  # Will be updated by _extract_classes_ast
                )
                result.functions.append(func_info)

    def _extract_classes_ast(self, tree: ast.AST, result: FileAnalysis) -> None:
        """Extract class definitions using ast.

        Args:
            tree: AST tree
            result: FileAnalysis to populate
        """
        # Read file to extract source code
        source_lines = None
        try:
            with open(result.file_path, 'r', encoding='utf-8') as f:
                source_lines = f.readlines()
        except Exception as e:
            logger.warning(f"Could not read source for {result.file_path}: {e}")

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                # Extract base class names
                bases = []
                for base in node.bases:
                    if isinstance(base, ast.Name):
                        bases.append(base.id)
                    else:
                        # For complex base expressions, use unparse
                        try:
                            bases.append(ast.unparse(base))
                        except Exception:
                            bases.append("<complex>")

                # Extract method names
                methods = []
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        methods.append(item.name)
                        # Update the corresponding FunctionInfo with parent_class
                        for func_info in result.functions:
                            if (func_info.name == item.name and
                                func_info.start_line == item.lineno):
                                func_info.parent_class = node.name

                # Extract source code if available
                source_code = None
                if source_lines and node.lineno and node.end_lineno:
                    try:
                        # Extract lines (1-indexed to 0-indexed)
                        class_lines = source_lines[node.lineno - 1:node.end_lineno]
                        source_code = ''.join(class_lines)
                    except Exception as e:
                        logger.warning(f"Could not extract source for class {node.name}: {e}")

                class_info = ClassInfo(
                    name=node.name,
                    file=result.file_path,
                    start_line=node.lineno,
                    end_line=node.end_lineno or node.lineno,
                    bases=bases,
                    methods=methods,
                    is_public=not node.name.startswith('_'),
                    source_code=source_code
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
                        module=None
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
                        module=module_name if module_name else None
                    )
                    result.imports_detailed.append(import_info)

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
            for i, arg in enumerate(decorator_call.args):
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

            # Parse keyword arguments
            for keyword in decorator_call.keywords:
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
        except Exception as e:
            logger.warning(f"Error parsing decorator arguments: {e}")

        return args_dict

    def _extract_decorators(self, tree: ast.AST, result: FileAnalysis) -> None:
        """Extract decorator information using ast.

        Args:
            tree: AST tree
            result: FileAnalysis to populate
        """
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                target_name = node.name
                target_type = "function" if isinstance(node, ast.FunctionDef) else "class"

                for decorator in node.decorator_list:
                    # Get decorator name and arguments
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

                    decorator_info = DecoratorInfo(
                        name=decorator_name,
                        file=result.file_path,
                        line_number=decorator.lineno,
                        arguments=json.dumps(arguments),
                        target_name=target_name,
                        target_type=target_type
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

    def _extract_attributes(self, tree: ast.AST, result: FileAnalysis) -> None:
        """Extract class attribute information using ast.

        Args:
            tree: AST tree
            result: FileAnalysis to populate
        """
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                class_name = node.name

                # Extract class-level attributes
                for item in node.body:
                    if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                        # Type-annotated class attribute: name: type = value
                        attr_info = AttributeInfo(
                            name=item.target.id,
                            class_name=class_name,
                            file=result.file_path,
                            definition_line=item.lineno,
                            type_hint=self._extract_type_hint(item.annotation),
                            is_class_attribute=True
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
                                    is_class_attribute=True
                                )
                                result.attributes.append(attr_info)

                # Extract instance attributes from __init__
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                        for child in ast.walk(item):
                            if isinstance(child, ast.Assign):
                                for target in child.targets:
                                    # Look for self.attribute assignments
                                    if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                                        if target.value.id == "self":
                                            attr_info = AttributeInfo(
                                                name=target.attr,
                                                class_name=class_name,
                                                file=result.file_path,
                                                definition_line=child.lineno,
                                                type_hint=None,
                                                is_class_attribute=False
                                            )
                                            result.attributes.append(attr_info)
                            elif isinstance(child, ast.AnnAssign):
                                # Type-annotated instance attribute: self.name: type = value
                                if isinstance(child.target, ast.Attribute) and isinstance(child.target.value, ast.Name):
                                    if child.target.value.id == "self":
                                        attr_info = AttributeInfo(
                                            name=child.target.attr,
                                            class_name=class_name,
                                            file=result.file_path,
                                            definition_line=child.lineno,
                                            type_hint=self._extract_type_hint(child.annotation),
                                            is_class_attribute=False
                                        )
                                        result.attributes.append(attr_info)

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

                # Find raise statements
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
                                    function_name=func_name
                                )
                                result.exceptions.append(exc_info)
                        else:
                            # Bare raise (re-raise)
                            exc_info = ExceptionInfo(
                                name="<bare-raise>",
                                file=result.file_path,
                                line_number=node.lineno,
                                context="raise",
                                function_name=func_name
                            )
                            result.exceptions.append(exc_info)

                    # Find except handlers
                    elif isinstance(node, ast.ExceptHandler):
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
                                    function_name=func_name
                                )
                                result.exceptions.append(exc_info)
                        else:
                            # Bare except
                            exc_info = ExceptionInfo(
                                name="<bare-except>",
                                file=result.file_path,
                                line_number=node.lineno,
                                context="catch",
                                function_name=func_name
                            )
                            result.exceptions.append(exc_info)

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
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        tree = ast.parse(content)
                        docstring = ast.get_docstring(tree)
                except Exception as e:
                    logger.debug(f"Could not extract docstring from {file_path}: {e}")

                module_info = ModuleInfo(
                    name=module_name,
                    path=str(file_path),
                    is_package=is_package,
                    docstring=docstring
                )
                result.module_info = module_info
        except Exception as e:
            logger.warning(f"Error extracting module info for {result.file_path}: {e}")

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
