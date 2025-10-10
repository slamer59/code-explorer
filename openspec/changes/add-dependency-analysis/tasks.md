# Implementation Tasks

## 1. Setup and Dependencies
- [x] 1.1 Add astroid dependency to pyproject.toml
- [x] 1.2 Add kuzu dependency to pyproject.toml
- [x] 1.3 Add click dependency for CLI to pyproject.toml
- [x] 1.4 Add rich dependency for terminal UI to pyproject.toml
- [x] 1.5 Create basic project structure (analyzer, graph, impact, cli, visualizer modules)

## 2. KuzuDB Graph Schema (Simplified)
- [x] 2.1 Design and document simplified graph schema (File, Function, Variable nodes)
- [x] 2.2 Implement graph.py with DependencyGraph class
- [x] 2.3 Create node tables (File, Function, Variable)
- [ ] 2.4 Create edge tables (CONTAINS, CALLS, DEFINES, USES, IMPORTS) - NOTE: In-memory implementation, not KuzuDB
- [x] 2.5 Add methods for inserting nodes and edges
- [x] 2.6 Add content hash tracking for incremental updates
- [x] 2.7 Add methods for querying nodes and edges

## 3. Code Analysis with ast + astroid
- [x] 3.1 Implement analyzer.py with CodeAnalyzer class
- [x] 3.2 Use ast module for basic parsing and structure extraction
- [x] 3.3 Use astroid for semantic analysis and name resolution
- [x] 3.4 Extract function definitions with line ranges
- [x] 3.5 Extract function calls and build call graph
- [x] 3.6 Extract variable definitions and usage
- [x] 3.7 Track import dependencies between modules
- [x] 3.8 Add parallel processing for analyzing multiple files (ThreadPoolExecutor)
- [x] 3.9 Implement content hashing for change detection (SHA-256)
- [x] 3.10 Handle parsing errors gracefully without stopping analysis

## 4. Impact Analysis Queries
- [x] 4.1 Implement impact.py with ImpactAnalyzer class
- [x] 4.2 Create query to find function by name and file
- [x] 4.3 Create query to find all callers of a function (upstream impact)
- [x] 4.4 Create query to find all callees of a function (downstream impact)
- [x] 4.5 Create transitive query with depth limit (default: 5 hops)
- [x] 4.6 Create query to find variable definitions
- [x] 4.7 Create query to find where variable is used
- [ ] 4.8 Add query result caching for repeated queries

## 5. CLI Interface
- [x] 5.1 Implement cli.py with Click commands
- [x] 5.2 Add `analyze` command to analyze a codebase
- [x] 5.3 Add `impact` command with function name parameter
- [x] 5.4 Add `trace` command for variable data flow tracking
- [x] 5.5 Add `visualize` command to generate dependency graphs
- [x] 5.6 Add `stats` command to show graph statistics
- [x] 5.7 Add progress indicators using rich library
- [x] 5.8 Add error handling and user-friendly messages
- [x] 5.9 Update __init__.py main() to invoke CLI

## 6. Visualization
- [x] 6.1 Implement visualizer.py with Mermaid diagram generation
- [x] 6.2 Generate function call graphs in Mermaid format
- [x] 6.3 Add highlighting for impacted nodes (different colors)
- [x] 6.4 Add filtering options (by file, by depth)
- [x] 6.5 Support exporting to .md files

## 7. Testing
- [ ] 7.1 Create test fixtures with sample Python code
- [ ] 7.2 Write unit tests for analyzer.py (ast + astroid parsing)
- [ ] 7.3 Write unit tests for graph.py (KuzuDB operations)
- [ ] 7.4 Write unit tests for impact.py (query logic)
- [ ] 7.5 Write integration tests for end-to-end analysis
- [ ] 7.6 Test incremental updates with content hashing
- [ ] 7.7 Add performance benchmarks for various codebase sizes

## 8. Documentation
- [ ] 8.1 Update README.md with installation instructions
- [ ] 8.2 Add usage examples for all CLI commands
- [ ] 8.3 Add inline code documentation and type hints
- [ ] 8.4 Create examples directory with sample analyses
- [ ] 8.5 Document graph schema and query patterns
- [ ] 8.6 Add troubleshooting guide for common issues
- [ ] 8.7 Document known limitations (dynamic imports, etc.)
