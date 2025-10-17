"""
Main CodeAnalyzer orchestrator.

Refactored from analyzer.py to use extractor-based architecture.
"""

import ast
import hashlib
import logging
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import List, Optional

import astroid
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

    def _run_extractions(self, tree: ast.AST, result: FileAnalysis) -> None:
        """Run extraction methods sequentially using extractor instances.

        Refactored from analyzer.py lines 196-248.

        Args:
            tree: AST tree
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
            # Read file content
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            # if sub_task_id is not None:
            #     file_name = Path(file_path).name
            #     progress.update(
            #         sub_task_id,
            #         completed=10,
            #         description=f"  └─ {file_name}: Parsing AST...",
            #     )

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
                    self.function_extractor.extract_function_calls_astroid(
                        astroid_module, result
                    )
                except Exception as e:
                    logger.error(f"Astroid function call extraction failed: {e}")

                try:
                    self.variable_extractor.extract_variable_usage_astroid(
                        astroid_module, result
                    )
                except Exception as e:
                    logger.error(f"Astroid variable usage extraction failed: {e}")
            except Exception as e:
                logger.warning(
                    f"Astroid analysis failed for {file_path}, falling back to ast: {e}"
                )
                # Fallback to simpler ast-based call extraction
                try:
                    self.function_extractor.extract_function_calls_ast(tree, result)
                except Exception as e:
                    logger.error(f"Fallback function call extraction failed: {e}")

                try:
                    self.variable_extractor.extract_variable_usage_ast(tree, result)
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

        Extracted from analyzer.py lines 1193-1301.

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
