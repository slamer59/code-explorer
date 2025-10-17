"""
Analyzer module for Python code analysis.

This module provides a refactored structure for code analysis:
- models: Data classes for analysis results
- base_analyzer: Main CodeAnalyzer orchestrator
- extractors: Specialized extraction classes
- call_resolver: Fast function call resolution using Polars
"""

# Backward compatibility: Export everything
from code_explorer.analyzer.base_analyzer import CodeAnalyzer
from code_explorer.analyzer.call_resolver import CallResolver
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
    "CallResolver",
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
