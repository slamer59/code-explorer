# Rich Nested Progress Bars - Implementation Guide

## Overview

This document describes how to implement nested progress bars using Rich to provide better visibility into parallel extraction operations within the code analyzer.

## Current Implementation

Currently, the analyzer uses a single progress bar in `analyze_directory()` that shows:
- Main progress: "Analyzing X files..."
- Overall completion percentage across all files

## Proposed Enhancement

Add nested progress bars to show:
1. **Main progress**: Overall file analysis progress
2. **Sub-progress**: Extraction progress within the currently processing file(s)

### Visual Example

```
Analyzing 50 files...                                    [████████████░░░░] 60% 00:45
  └─ analyzer.py: Parallel extractions                   [██████████████░░] 80% 00:01
     ├─ Functions extraction                             [████████████████] 100% ✓
     ├─ Imports extraction                               [████████████████] 100% ✓
     ├─ Variables extraction                             [████████████████] 100% ✓
     ├─ Decorators extraction                            [████████████████] 100% ✓
     ├─ Exceptions extraction                            [████████████████] 100% ✓
     └─ Detailed imports extraction                      [████████████░░░░] 75%
```

## Implementation Requirements

### 1. Signature Changes

**Current**:
```python
def analyze_file(self, file_path: Path) -> FileAnalysis:
    ...
```

**Proposed**:
```python
def analyze_file(
    self,
    file_path: Path,
    progress: Optional[Progress] = None,
    parent_task: Optional[int] = None
) -> FileAnalysis:
    ...
```

### 2. Modified `_run_parallel_extractions()` Method

```python
def _run_parallel_extractions(
    self,
    tree: ast.AST,
    result: FileAnalysis,
    progress: Optional[Progress] = None,
    parent_task: Optional[int] = None
) -> None:
    """Run independent extraction methods in parallel for better performance.

    Args:
        tree: AST tree
        result: FileAnalysis to populate
        progress: Optional Rich Progress instance for nested progress tracking
        parent_task: Optional parent task ID for nested progress
    """
    # Define extraction functions that can run in parallel
    extraction_names = [
        "Functions extraction",
        "Imports extraction",
        "Variables extraction",
        "Detailed imports extraction",
        "Decorators extraction",
        "Exceptions extraction",
    ]

    independent_extractions: List[Tuple[Callable, Tuple]] = [
        (self._extract_functions_ast, (tree, result)),
        (self._extract_imports_ast, (tree, result)),
        (self._extract_variables_ast, (tree, result)),
        (self._extract_imports_detailed, (tree, result)),
        (self._extract_decorators, (tree, result)),
        (self._extract_exceptions, (tree, result)),
    ]

    # Create sub-tasks if progress tracking is enabled
    sub_tasks = []
    if progress and parent_task is not None:
        for name in extraction_names:
            task_id = progress.add_task(
                f"  └─ {name}",
                total=1,
                visible=True
            )
            sub_tasks.append(task_id)

    # Run independent extractions in parallel
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [
            executor.submit(func, *args)
            for func, args in independent_extractions
        ]

        # Wait for all to complete and update progress
        for idx, future in enumerate(futures):
            try:
                future.result()
                if progress and sub_tasks:
                    progress.update(sub_tasks[idx], completed=1)
            except Exception as e:
                logger.error(f"Extraction failed: {e}")
                if progress and sub_tasks:
                    progress.update(
                        sub_tasks[idx],
                        description=f"  └─ {extraction_names[idx]} ✗"
                    )

    # Run dependent extractions sequentially
    # ...existing code...
```

### 3. Modified `analyze_directory()` Method

```python
def analyze_directory(
    self,
    root_path: Path,
    parallel: bool = True,
    exclude_patterns: Optional[List[str]] = None,
    show_detailed_progress: bool = False,  # New parameter
) -> List[FileAnalysis]:
    """Analyze all Python files in a directory recursively.

    Args:
        root_path: Root directory to analyze
        parallel: Whether to use parallel processing
        exclude_patterns: Patterns to exclude
        show_detailed_progress: Whether to show nested progress bars

    Returns:
        List of FileAnalysis results
    """
    # ...existing file discovery code...

    results = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        # Add this for nested progress
        expand=True if show_detailed_progress else False,
    ) as progress:
        main_task = progress.add_task(
            f"Analyzing {len(python_files)} files...",
            total=len(python_files)
        )

        if parallel:
            with ThreadPoolExecutor(max_workers=8) as executor:
                future_to_file = {
                    executor.submit(
                        self.analyze_file,
                        py_file,
                        progress if show_detailed_progress else None,
                        main_task if show_detailed_progress else None
                    ): py_file
                    for py_file in python_files
                }

                for future in as_completed(future_to_file):
                    py_file = future_to_file[future]
                    try:
                        result = future.result()
                        results.append(result)
                    except Exception as e:
                        logger.error(f"Failed to analyze {py_file}: {e}")
                    finally:
                        progress.update(main_task, advance=1)
        # ...rest of the code...
```

## Challenges & Considerations

### 1. Thread Safety
- Rich Progress is thread-safe, but care must be taken when updating tasks from multiple threads
- Each file analysis creates its own set of sub-tasks to avoid conflicts

### 2. Performance Impact
- Creating many sub-tasks may slow down the progress display
- Consider only showing nested progress for the "currently active" files (e.g., max 3-5 concurrent file sub-progress bars)

### 3. Visual Clutter
- With 8 parallel workers, showing all nested progress could be overwhelming
- Solution: Add `show_detailed_progress` flag (default: False) to opt-in

### 4. Task Lifecycle Management
- Sub-tasks need to be properly removed/hidden after completion
- Consider using task groups or automatic cleanup

## Alternative Simpler Implementation

Instead of showing all extraction sub-tasks, show a simpler nested view:

```
Analyzing 50 files...                                    [████████████░░░░] 60%
  ├─ analyzer.py: Running 6 parallel extractions...     [████████████████] 100%
  ├─ database.py: Running 6 parallel extractions...     [███████████░░░░░] 65%
  └─ utils.py: Running 6 parallel extractions...        [█░░░░░░░░░░░░░░░] 10%
```

This could be implemented with minimal changes:

```python
def analyze_file(
    self,
    file_path: Path,
    progress: Optional[Progress] = None,
) -> FileAnalysis:
    """Analyze a single Python file using ast and astroid."""
    result = FileAnalysis(...)

    # Create a sub-task if progress is provided
    sub_task = None
    if progress:
        sub_task = progress.add_task(
            f"  └─ {file_path.name}: Extracting...",
            total=100,
            visible=True
        )

    try:
        # Read file content
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        if sub_task:
            progress.update(sub_task, completed=10)

        # Parse with ast
        tree = ast.parse(content, filename=str(file_path))

        if sub_task:
            progress.update(sub_task, completed=30)

        # Run parallel extractions
        self._run_parallel_extractions(tree, result)

        if sub_task:
            progress.update(sub_task, completed=80)

        # Try astroid
        # ...existing code...

        if sub_task:
            progress.update(sub_task, completed=100)
            # Remove or hide the task after a brief moment
            progress.remove_task(sub_task)

    except Exception as e:
        if sub_task:
            progress.update(
                sub_task,
                description=f"  └─ {file_path.name}: Failed ✗"
            )

    return result
```

## Recommendation

Given the complexity and potential visual clutter, I recommend starting with the **simpler implementation** that shows:
- Main progress bar for overall file analysis
- One sub-progress bar per currently-processing file (auto-removed when done)
- Optional flag to enable/disable nested progress

This provides better visibility without overwhelming the user interface.

## Next Steps

1. Implement the simpler nested progress approach first
2. Test with different numbers of parallel workers
3. Gather user feedback
4. If needed, iterate to add more detailed extraction-level progress

## References

- Rich Progress documentation: https://rich.readthedocs.io/en/stable/progress.html
- Rich Progress Advanced: https://rich.readthedocs.io/en/stable/progress.html#advanced-usage
