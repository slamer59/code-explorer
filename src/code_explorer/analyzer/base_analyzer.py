"""
Main CodeAnalyzer orchestrator.

Refactored from analyzer.py to use extractor-based architecture.
"""

import hashlib
import logging
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, List, Optional

from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from code_explorer.analyzer.extractors.attributes import AttributeExtractor
from code_explorer.analyzer.extractors.classes import ClassExtractor
from code_explorer.analyzer.extractors.decorators import DecoratorExtractor
from code_explorer.analyzer.extractors.exceptions import ExceptionExtractor
from code_explorer.analyzer.extractors.functions import FunctionExtractor
from code_explorer.analyzer.extractors.imports import ImportExtractor
from code_explorer.analyzer.extractors.variables import VariableExtractor
from code_explorer.analyzer.models import FileAnalysis, ModuleInfo
from code_explorer.analyzer.parser import parse_python_file, get_parser_type, ParseError

logger = logging.getLogger(__name__)


class CodeAnalyzer:
    """
    Orchestrates code analysis using specialized extractors.

    Delegates extraction to specialized extractor classes for better organization
    and maintainability.
    """

    def __init__(self):
        """Initialize analyzer with all extractors."""
        self.function_extractor = FunctionExtractor()
        self.class_extractor = ClassExtractor()
        self.import_extractor = ImportExtractor()
        self.variable_extractor = VariableExtractor()
        self.decorator_extractor = DecoratorExtractor()
        self.attribute_extractor = AttributeExtractor()
        self.exception_extractor = ExceptionExtractor()

    def compute_hash(self, file_path: Path) -> str:
        """Compute SHA-256 hash of file contents.

        Extracted from analyzer.py lines 180-194.

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

    def _run_extractions(self, tree: Any, result: FileAnalysis) -> None:
        """Run extraction methods sequentially using extractor instances.

        Refactored from analyzer.py lines 196-248.
        Enhanced to support both AST and Tree-sitter parsing.

        Args:
            tree: Parsed tree (ast.AST or Tree-sitter node)
            result: FileAnalysis to populate
        """
        # Run extractions sequentially (faster due to no thread pool overhead)
        try:
            self.function_extractor.extract(tree, result)
        except Exception as e:
            logger.error(f"Function extraction failed: {e}")

        try:
            self.import_extractor.extract(tree, result)
        except Exception as e:
            logger.error(f"Import extraction failed: {e}")

        try:
            self.variable_extractor.extract(tree, result)
        except Exception as e:
            logger.error(f"Variable extraction failed: {e}")

        try:
            self.decorator_extractor.extract(tree, result)
        except Exception as e:
            logger.error(f"Decorator extraction failed: {e}")

        try:
            self.exception_extractor.extract(tree, result)
        except Exception as e:
            logger.error(f"Exception extraction failed: {e}")

        try:
            self.attribute_extractor.extract(tree, result)
        except Exception as e:
            logger.error(f"Attribute extraction failed: {e}")

        try:
            self._extract_module_info(result)
        except Exception as e:
            logger.error(f"Module info extraction failed: {e}")

        # Extract classes (depends on functions being extracted first)
        try:
            self.class_extractor.extract(tree, result)
        except Exception as e:
            logger.error(f"Class extraction failed: {e}")

    def analyze_file(
        self,
        file_path: Path,
        progress: Optional[Progress] = None,
        parent_task_id: Optional[object] = None,
    ) -> FileAnalysis:
        """Analyze a single Python file using ast and astroid.

        Refactored from analyzer.py lines 250-371.

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
            # Read file content once and cache it
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Cache both content and source lines to avoid redundant reads
            result._source_content = content
            result._source_lines = content.splitlines(keepends=True)

            # if sub_task_id is not None:
            #     file_name = Path(file_path).name
            #     progress.update(
            #         sub_task_id,
            #         completed=10,
            #         description=f"  └─ {file_name}: Parsing AST...",
            #     )

            # Parse with Tree-sitter (with AST fallback)
            try:
                tree = parse_python_file(content, filename=str(file_path))
            except ParseError as e:
                result.errors.append(f"Parse error: {e}")
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

            # Run all Tree-sitter extractions sequentially
            self._run_extractions(tree, result)

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

    def _extract_module_info(self, result: FileAnalysis) -> None:
        """Extract module information from file path.

        Extracted from analyzer.py lines 1134-1191.

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

                # Extract docstring using Tree-sitter (use cached content)
                docstring = None
                try:
                    content = result._source_content
                    if content is None:
                        # Fallback: read if not cached
                        with open(file_path, "r", encoding="utf-8") as f:
                            content = f.read()

                    # Parse using Tree-sitter to extract module docstring
                    from code_explorer.analyzer.parser import parse_python_file
                    tree = parse_python_file(content, filename=str(file_path))
                    # Check for module-level string literal (docstring)
                    for child in tree.children:
                        if hasattr(child, "type") and child.type == "expression_statement":
                            # Check if the expression is a string
                            expr = child.child_by_field_name("expression") if hasattr(child, "child_by_field_name") else None
                            if expr and hasattr(expr, "type") and expr.type == "string":
                                docstring = expr.text.decode("utf-8") if isinstance(expr.text, bytes) else expr.text
                                # Remove quotes
                                docstring = docstring.strip("\"'")
                                break
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
        max_workers: Optional[int] = None,
    ) -> List[FileAnalysis]:
        """Analyze all Python files in a directory recursively.

        Extracted from analyzer.py lines 1193-1301.

        Args:
            root_path: Root directory to analyze
            parallel: Whether to use parallel processing
            exclude_patterns: Patterns to exclude (e.g., '__pycache__', 'tests')
            verbose_progress: Show detailed nested progress for each file (default: False)
            max_workers: Number of worker threads (default: None, uses os.cpu_count())

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
                # Use ProcessPoolExecutor for CPU-bound parsing operations.
                # Tree-sitter AST parsing is CPU-intensive and benefits from true parallelism.
                # Threads are blocked by Python's GIL, making them ineffective for CPU-bound work.
                # max_workers defaults to None which uses os.cpu_count()
                with ProcessPoolExecutor(max_workers=max_workers) as executor:
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
