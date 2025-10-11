# Code Explorer Test Suite

Comprehensive pytest test suite for the code-explorer project.

## Test Summary

**Total Tests: 96**
- Unit Tests: 78 (including 4 new read-only mode tests)
- Integration Tests: 8
- Performance Tests: 10

**All tests passing ✓**

## Test Coverage by Module

### 1. test_analyzer.py (17 tests)
Tests for the code analysis module using AST and astroid:

- **Hash Computation**: Valid files, nonexistent files, content changes
- **Function Extraction**: Simple functions, class methods, visibility (public/private)
- **Function Calls**: Call detection, nested calls, method calls
- **Import Detection**: Absolute imports, relative imports, from-imports
- **Variable Detection**: Module-level variables, function-level variables, scope tracking
- **Error Handling**: Syntax errors, malformed files, Unicode errors
- **Directory Analysis**: Sequential processing, parallel processing, exclusion patterns
- **Edge Cases**: Empty directories, large files

### 2. test_graph.py (26 tests)
Tests for the KuzuDB-backed dependency graph:

- **Initialization**: Database creation, schema setup
- **Node Operations**: Add/update functions, add variables, add files
- **Edge Operations**: Function calls, variable usage, DEFINES relationships
- **Queries**: get_callers, get_callees, get_variable_usage, get_all_functions_in_file
- **File Management**: file_exists with hash, delete_file_data (incremental updates)
- **Statistics**: Graph statistics, most-called functions
- **Cross-file Dependencies**: Multi-file function calls
- **Persistence**: Database reopening, data persistence
- **Cleanup**: clear_all operation
- **Read-only Mode**: Initialization, write prevention, read allowance, flag attribute (4 new tests)

### 3. test_impact.py (15 tests)
Tests for impact analysis functionality:

- **Upstream Analysis**: Direct callers, multi-level transitive callers
- **Downstream Analysis**: Direct callees, transitive callees
- **Bidirectional**: Both upstream and downstream analysis
- **Depth Limiting**: max_depth parameter enforcement
- **Variable Impact**: Variable usage tracking across functions
- **Formatting**: Rich table formatting for CLI display
- **Edge Cases**: Empty results, isolated functions, circular dependencies
- **Cross-file Impact**: Dependencies spanning multiple files
- **Result Sorting**: Proper ordering by depth and name

### 4. test_visualizer.py (20 tests)
Tests for Mermaid diagram generation:

- **Function Graphs**: Simple graphs, multi-level dependencies
- **Highlighting**: CSS styling for focus/callers/callees
- **Module Graphs**: All functions in a file, internal vs external
- **Import Handling**: Including/excluding external imports
- **File Operations**: save_to_file, nested directories
- **Node ID Generation**: Sanitization, uniqueness
- **Label Formatting**: Human-readable labels with filenames
- **Traversal**: Upstream/downstream collection with max_depth
- **Edge Cases**: Empty modules, isolated functions, circular deps
- **Syntax Validation**: Valid Mermaid output

### 5. test_integration.py (8 tests)
End-to-end integration tests:

- **Full Workflow**: Analyze → Graph → Query pipeline
- **Incremental Updates**: Unchanged file detection, modified file re-analysis
- **Database Persistence**: Session management, data persistence
- **Impact Analysis**: Complete flow from analysis to impact results
- **Visualization**: Complete flow from analysis to diagram generation
- **Parallel vs Sequential**: Consistency between processing modes
- **Complex Dependencies**: Multi-file, multi-level dependency chains
- **Error Handling**: Mixed valid/invalid files, graceful degradation

### 6. test_performance.py (10 tests)
Performance benchmarks and stress tests:

- **Large-scale Analysis**: 100 files sequential, 100 files parallel
- **Large Files**: 100 functions in single file
- **Query Performance**: Bulk graph queries (< 1 second)
- **Incremental Updates**: Update speed vs full refresh (50% faster)
- **Deep Chains**: 100-level call chains (< 2 seconds)
- **Statistics**: Computation on 500 functions (< 1 second)
- **Hash Computation**: Speed for various file sizes
- **Parallel Speedup**: Verification of parallel performance gains
- **Delete Operations**: Large file deletion (< 1 second)

## Running Tests

### All tests
```bash
pytest tests/
```

### Unit tests only
```bash
pytest tests/ -m unit
```

### Integration tests only
```bash
pytest tests/ -m integration
```

### Performance tests only
```bash
pytest tests/ -m performance
```

### With coverage
```bash
pytest tests/ --cov=code_explorer --cov-report=html
```

### Verbose output
```bash
pytest tests/ -v
```

## Test Execution Time

- **Unit tests**: ~4.5 seconds
- **Integration tests**: ~3 seconds
- **Performance tests**: ~11 seconds
- **Total**: ~18.5 seconds

## Test Design Principles

### Functional Style
Tests are organized as functions, not classes, for better readability and isolation:

```python
@pytest.mark.unit
def test_analyze_simple_function(sample_python_file: Path) -> None:
    """Test analysis of a file with simple functions."""
    analyzer = CodeAnalyzer()
    result = analyzer.analyze_file(sample_python_file)
    assert len(result.functions) >= 3
```

### Fixtures for Isolation
Comprehensive fixtures in `conftest.py`:
- `temp_dir`: Temporary directory for test files
- `temp_db_path`: Temporary database path
- `sample_python_file`: Simple Python file fixture
- `complex_python_file`: Complex multi-function file
- `malformed_python_file`: Syntax error testing
- `sample_project`: Multi-file project structure

### Parametrized Tests
Where applicable, using `@pytest.mark.parametrize` for testing multiple scenarios

### Type Hints
All test functions include proper type hints for parameters and return values

### Docstrings
Every test has a clear docstring explaining what it validates

## Dependencies

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-cov>=4.0",
    "pytest-benchmark>=4.0",
]
```

## Continuous Integration Ready

The test suite is designed for CI/CD pipelines:
- Fast execution (< 20 seconds)
- No external dependencies (uses temporary databases)
- Clear test markers for selective execution
- Comprehensive coverage across all modules
- Performance benchmarks to detect regressions

## Issues Found During Testing

None - all modules working as designed!

The test suite helped validate:
- Proper hash-based incremental updates
- Correct AST/astroid fallback behavior
- Graph persistence across sessions
- Parallel processing correctness
- Error handling for malformed files
