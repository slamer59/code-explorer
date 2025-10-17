"""
Data models for code analysis results.

Extracted from analyzer.py lines 32-170.
"""

from dataclasses import dataclass, field
from typing import List, Optional


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
    # Cached file content to avoid redundant reads (set by analyze_file)
    _source_content: Optional[str] = field(default=None, repr=False)
    _source_lines: Optional[List[str]] = field(default=None, repr=False)
