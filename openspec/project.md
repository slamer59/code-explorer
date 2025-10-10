# Project Context

## Purpose
Code Explorer is a Python dependency analysis tool that provides fast, fine-grained impact analysis for codebases. The primary goal is to quickly answer: "If I change this line of code, which files and lines will be affected?" This enables developers to understand the ripple effects of their changes before making them.

## Tech Stack
- **Language**: Python 3.13+
- **Package Manager**: uv (modern Python package manager)
- **Graph Database**: KuzuDB (property graph database for storing dependencies)
- **Code Analysis**: PyRefly (fast AST parsing and call graph generation)
- **Build System**: Hatchling
- **Testing**: pytest (planned)

## Project Conventions

### Code Style
- PEP 8 compliant Python code
- Type hints for all function signatures
- Descriptive variable names following snake_case
- Classes follow PascalCase
- Maximum line length: 100 characters
- Use pathlib for file operations instead of os.path

### Architecture Patterns
- **Hybrid Analysis Architecture**: Combine PyRefly (fast initial analysis) with KuzuDB (efficient graph queries)
- **Fine-grained Dependency Tracking**: Track dependencies at line and statement level, not just module level
- **Parallel Processing**: Use ThreadPoolExecutor for analyzing multiple files concurrently
- **Incremental Updates**: Use content hashing to detect file changes and only re-analyze modified files
- **Separation of Concerns**:
  - Code analysis layer (PyRefly integration)
  - Graph storage layer (KuzuDB integration)
  - Query/Impact analysis layer
  - CLI interface layer

### Testing Strategy
- Unit tests for individual components (analyzers, graph operations)
- Integration tests for end-to-end dependency analysis
- Performance benchmarks for large codebases
- Test fixtures using real Python code samples
- Aim for >80% code coverage

### Git Workflow
- Main branch: `main`
- Feature branches: `feature/description`
- Commit messages: Conventional Commits format
- OpenSpec workflow for features and breaking changes
- Direct commits for bug fixes and minor improvements

## Domain Context

### Dependency Analysis Concepts
- **Impact Analysis**: Determining what code is affected by a change
- **Call Graph**: Directed graph of function calls
- **AST (Abstract Syntax Tree)**: Tree representation of code structure
- **Property Graph**: Graph with typed nodes and edges with properties
- **Fine-grained Dependencies**: Tracking at statement/line level vs module level
- **Centrality**: Graph metrics identifying important nodes (authority pages, hubs, bridges)

### Performance Goals
- Initial analysis: Seconds to minutes for large codebases (PyRefly provides speed)
- Impact queries: Sub-second response time (KuzuDB graph queries)
- Incremental updates: Only re-analyze changed files
- Memory efficient: Store graph in KuzuDB, not in RAM

## Important Constraints
- Must support Python 3.13+ (project requirement)
- Must be fast enough for large codebases (1000+ files)
- Must provide line-level precision for impact analysis
- Should minimize false positives in dependency detection
- Must support incremental analysis (not re-analyze everything on each run)

## External Dependencies
- **KuzuDB**: Property graph database for storing and querying dependencies
- **PyRefly**: Fast Python code analyzer for AST parsing and call graphs
- **AST module**: Python standard library for code parsing
- **pathlib**: Python standard library for file operations
- **concurrent.futures**: Python standard library for parallel processing
