"""
Backward compatibility redirect.
Import from the new modular structure.
"""

from code_explorer.analyzer.base_analyzer import CodeAnalyzer
from code_explorer.analyzer.models import (
    AttributeInfo,
    ClassInfo,
    DecoratorInfo,
    ExceptionInfo,
    FileAnalysis,
    FunctionCall,
    FunctionInfo,
    ImportDetailedInfo,
    ImportInfo,
    ModuleInfo,
    VariableInfo,
    VariableUsage,
)

__all__ = [
    "CodeAnalyzer",
    "FileAnalysis",
    "FunctionInfo",
    "ClassInfo",
    "FunctionCall",
    "VariableInfo",
    "VariableUsage",
    "ImportInfo",
    "ImportDetailedInfo",
    "DecoratorInfo",
    "AttributeInfo",
    "ExceptionInfo",
    "ModuleInfo",
]
