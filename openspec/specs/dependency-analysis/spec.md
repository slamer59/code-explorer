# dependency-analysis Specification

## Purpose
TBD - created by archiving change add-dependency-analysis. Update Purpose after archive.
## Requirements
### Requirement: Code Analysis
The system SHALL analyze Python codebases using Python's built-in `ast` module and `astroid` library to extract dependency information including functions, variables, and their relationships.

#### Scenario: Analyze single Python file
- **WHEN** user runs `code-explorer analyze /path/to/file.py`
- **THEN** system extracts all functions, classes, and variables from the file
- **AND** stores them in the dependency graph with line number information
- **AND** reports analysis results to the user

#### Scenario: Analyze directory recursively
- **WHEN** user runs `code-explorer analyze /path/to/directory`
- **THEN** system discovers all Python files in the directory recursively
- **AND** analyzes each file in parallel
- **AND** stores combined dependency graph
- **AND** shows progress indicator during analysis

#### Scenario: Incremental analysis with content hashing
- **WHEN** user runs analysis on a previously analyzed codebase
- **THEN** system computes content hash for each file
- **AND** skips files with unchanged hashes
- **AND** only re-analyzes modified files
- **AND** reports number of changed files

### Requirement: Dependency Graph Storage
The system SHALL store dependency information in a KuzuDB property graph with simplified typed nodes and edges.

#### Scenario: Store file nodes
- **WHEN** analyzing a Python file
- **THEN** system creates a File node with path, language, last_modified, and content_hash properties
- **AND** File node serves as parent for all code elements in that file

#### Scenario: Store function nodes
- **WHEN** analyzing a function definition
- **THEN** system creates a Function node with name, file, start_line, end_line, and is_public properties
- **AND** creates CONTAINS edge from File to Function

#### Scenario: Store variable nodes
- **WHEN** analyzing a variable definition
- **THEN** system creates a Variable node with name, file, definition_line, and scope properties
- **AND** creates DEFINES edge from defining Function to Variable

#### Scenario: Store call relationships
- **WHEN** analyzing a function call
- **THEN** system creates CALLS edge from caller Function to callee Function
- **AND** stores call_line property indicating where the call occurs
- **AND** edge enables call graph traversal

#### Scenario: Store variable usage relationships
- **WHEN** analyzing variable usage in a function
- **THEN** system creates USES edge from Function to Variable
- **AND** stores usage_line property indicating where variable is used
- **AND** edge enables data dependency tracking

#### Scenario: Store import relationships
- **WHEN** analyzing import statements
- **THEN** system creates IMPORTS edge from File to imported File
- **AND** stores import line number and directness (direct vs indirect)

### Requirement: Impact Analysis Queries
The system SHALL provide queries to determine which files and lines are affected when code is changed.

#### Scenario: Find impacted functions (upstream)
- **WHEN** user queries `code-explorer impact file.py:function_name`
- **THEN** system finds the specified function
- **AND** traverses CALLS edges in reverse to find all callers (upstream)
- **AND** returns list of functions and files that call the specified function
- **AND** completes query in under 1 second for codebases up to 10,000 files

#### Scenario: Find downstream dependencies
- **WHEN** user queries `code-explorer impact file.py:function_name --downstream`
- **THEN** system finds the specified function
- **AND** traverses CALLS edges forward to find all callees (downstream)
- **AND** returns list of functions that are called by the specified function
- **AND** sorts results by file path

#### Scenario: Find variable usage chain
- **WHEN** user queries `code-explorer trace file.py:42 --variable var_name`
- **THEN** system finds the variable defined at line 42
- **AND** traverses USES edges to find all functions that use the variable
- **AND** returns list of (file, function, line) tuples where variable is used

#### Scenario: Depth-limited transitive queries
- **WHEN** user queries with `--max-depth N` flag
- **THEN** system limits graph traversal to N hops
- **AND** prevents excessively long query times
- **AND** reports if depth limit was reached

### Requirement: Call Graph Extraction
The system SHALL use Python's `ast` module and `astroid` library to extract call graphs from Python code.

#### Scenario: Extract direct function calls
- **WHEN** analyzing a function body using ast
- **THEN** system identifies all direct function calls
- **AND** uses astroid to resolve function names across modules
- **AND** creates CALLS edges for each resolved call
- **AND** handles method calls on objects

#### Scenario: Handle built-in functions
- **WHEN** code calls built-in functions (e.g., `print`, `len`)
- **THEN** system recognizes them as built-ins using astroid
- **AND** optionally excludes them from graph (configurable)
- **AND** avoids creating nodes for external standard library functions

#### Scenario: Handle unresolved calls
- **WHEN** astroid cannot resolve a function name (e.g., dynamic imports)
- **THEN** system logs the unresolved call for debugging
- **AND** optionally creates CALLS edge with best-guess target
- **AND** marks edge as "unresolved" for user awareness

### Requirement: Parallel Processing
The system SHALL analyze multiple files concurrently to improve performance on large codebases.

#### Scenario: Parallel file analysis
- **WHEN** analyzing a directory with many files
- **THEN** system uses ThreadPoolExecutor with 4-8 workers
- **AND** distributes files across workers
- **AND** analyzes files in parallel
- **AND** combines results into single graph

#### Scenario: Progress reporting during parallel analysis
- **WHEN** parallel analysis is running
- **THEN** system displays progress bar showing completed/total files
- **AND** updates progress as each file completes
- **AND** shows estimated time remaining

### Requirement: Command-Line Interface
The system SHALL provide a CLI using Click for interacting with dependency analysis features.

#### Scenario: Analyze command
- **WHEN** user runs `code-explorer analyze <path>`
- **THEN** system analyzes the codebase at the given path
- **AND** stores results in `.code-explorer/` directory
- **AND** displays summary statistics (files analyzed, functions found, etc.)

#### Scenario: Impact command
- **WHEN** user runs `code-explorer impact <file>:<line>`
- **THEN** system queries the dependency graph for impact
- **AND** displays list of impacted files and lines
- **AND** formats output in a readable table

#### Scenario: Visualize command
- **WHEN** user runs `code-explorer visualize <file> --output graph.md`
- **THEN** system generates a Mermaid diagram of dependencies
- **AND** saves to specified output file
- **AND** supports filtering by depth and file patterns

#### Scenario: Stats command
- **WHEN** user runs `code-explorer stats`
- **THEN** system displays graph statistics (node counts, edge counts, etc.)
- **AND** shows largest functions by complexity
- **AND** shows most-called functions

#### Scenario: Error handling
- **WHEN** user provides invalid path or line number
- **THEN** system displays clear error message
- **AND** suggests correct usage
- **AND** exits with non-zero status code

### Requirement: Dependency Graph Visualization
The system SHALL generate visual representations of dependency graphs using Mermaid diagrams.

#### Scenario: Generate function call graph
- **WHEN** user runs `code-explorer visualize --type calls --file module.py`
- **THEN** system generates Mermaid graph showing function calls
- **AND** includes all functions in the specified file
- **AND** shows CALLS edges between functions
- **AND** labels nodes with function names

#### Scenario: Highlight impacted nodes
- **WHEN** user visualizes with `--highlight-impact file.py:42`
- **THEN** system highlights nodes affected by changing line 42
- **AND** uses different colors for direct vs transitive dependencies
- **AND** shows depth level of each impacted node

#### Scenario: Filter by depth
- **WHEN** user visualizes with `--max-depth 2`
- **THEN** system includes only nodes within 2 hops of selected nodes
- **AND** prevents overly complex diagrams
- **AND** indicates if more nodes exist beyond depth limit

#### Scenario: Export to different formats
- **WHEN** user specifies `--format svg` or `--format png`
- **THEN** system generates Mermaid diagram
- **AND** optionally converts to specified format if tools available
- **AND** falls back to Mermaid text if conversion fails

### Requirement: Incremental Updates
The system SHALL support incremental analysis by tracking file changes using content hashing.

#### Scenario: Detect unchanged files
- **WHEN** running analysis on previously analyzed codebase
- **THEN** system compares SHA-256 hashes of each file
- **AND** skips analysis for files with matching hashes
- **AND** preserves existing graph data for unchanged files

#### Scenario: Update changed files
- **WHEN** file content has changed since last analysis
- **THEN** system removes old nodes and edges for that file
- **AND** re-analyzes the file completely
- **AND** inserts new nodes and edges into graph
- **AND** updates content_hash in File node

#### Scenario: Handle deleted files
- **WHEN** file exists in graph but not on filesystem
- **THEN** system removes File node and all related nodes/edges
- **AND** cleans up orphaned references
- **AND** reports deleted files in summary

### Requirement: Error Handling and Robustness
The system SHALL handle analysis errors gracefully without stopping the entire analysis.

#### Scenario: Handle syntax errors in Python files
- **WHEN** encountering a Python file with syntax errors
- **THEN** system logs the error with file path
- **AND** skips analysis for that file
- **AND** continues analyzing remaining files
- **AND** includes error count in final summary

#### Scenario: Handle unsupported Python syntax
- **WHEN** ast or astroid cannot parse certain Python syntax
- **THEN** system logs the parsing error with file path and line number
- **AND** skips the problematic file or function
- **AND** continues analysis with remaining code

#### Scenario: Handle circular dependencies
- **WHEN** analyzing codebases with circular imports or calls
- **THEN** system detects cycles during graph traversal
- **AND** prevents infinite loops in queries
- **AND** optionally reports circular dependencies to user

#### Scenario: Handle database connection errors
- **WHEN** unable to connect to or create KuzuDB database
- **THEN** system displays clear error message with database path
- **AND** suggests common fixes (permissions, disk space, etc.)
- **AND** exits gracefully with non-zero status

### Requirement: Performance Benchmarks
The system SHALL meet performance targets for analysis and query operations.

#### Scenario: Analysis performance target
- **WHEN** analyzing a codebase with 1000 Python files
- **THEN** initial analysis completes in under 5 minutes
- **AND** incremental analysis (10% changed) completes in under 1 minute
- **AND** system uses less than 2GB of RAM during analysis

#### Scenario: Query performance target
- **WHEN** executing impact analysis query
- **THEN** query completes in under 1 second for depth ≤ 5
- **AND** query completes in under 5 seconds for depth ≤ 10
- **AND** system supports concurrent queries

#### Scenario: Graph size limits
- **WHEN** graph contains up to 100,000 nodes
- **THEN** all operations remain performant
- **AND** query response time remains under 2 seconds
- **AND** database size remains reasonable (< 500MB for 100k nodes)

