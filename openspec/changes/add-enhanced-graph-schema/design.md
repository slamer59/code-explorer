# Design Document: Enhanced Dependency Graph Schema

## Context

The current dependency graph schema uses KuzuDB to store basic code structure (Files, Functions, Variables, Classes) and their relationships. While this enables function-level call graph analysis, users frequently ask questions that require more detailed dependency tracking:

- "What will break if I rename this function?" - Requires import tracking
- "What depends on this decorator?" - Requires decorator tracking
- "What modifies this class attribute?" - Requires attribute access tracking
- "What exceptions can this function raise?" - Requires exception flow analysis

This proposal adds five new node types to address these gaps while maintaining KuzuDB performance characteristics.

## Goals / Non-Goals

### Goals
- Enable granular import tracking (what was imported, not just which files)
- Track decorator dependencies (including arguments and resolution)
- Separate class attributes from regular variables
- Track exception raising and handling for propagation analysis
- Represent Python module/package hierarchy in the graph
- Maintain query performance (<1s for typical queries)
- Support incremental updates (only re-analyze changed files)

### Non-Goals
- Type inference or static typing analysis (use mypy/pyright for that)
- Cross-language support (Python only for now)
- Runtime behavior analysis (static analysis only)
- Tracking all possible attribute access (dynamic/runtime attributes out of scope)

## Decisions

### Decision 1: Use separate node types instead of properties
**What**: Create dedicated node tables (Import, Decorator, Attribute, Exception, Module) instead of adding properties to existing nodes.

**Why**:
- Better normalization (one Import node can be referenced by multiple files)
- Easier querying (Cypher patterns like `MATCH (f:Function)-[:DECORATED_BY]->(d:Decorator {name: "cached"})`)
- Flexible schema evolution (can add properties to nodes without migration)
- Follows property graph best practices

**Alternatives considered**:
- Adding `decorators` JSON array to Function nodes - rejected due to poor query performance
- Storing everything in File properties - rejected due to denormalization and update complexity

### Decision 2: Use AST-only extraction (no additional static analysis)
**What**: Extract new information using Python's built-in `ast` module, with optional astroid fallback for name resolution.

**Why**:
- Consistency with existing analyzer architecture
- Fast and reliable (ast is battle-tested)
- No new dependencies required
- Good enough for 95% of use cases

**Alternatives considered**:
- Using mypy for type inference - rejected due to complexity and speed overhead
- Using rope for refactoring support - rejected due to additional dependency

**Trade-offs**:
- Won't resolve all dynamic imports (acceptable - mark as unresolved)
- Won't infer decorator side effects (acceptable - track application, not effects)

### Decision 3: Store decorator arguments as JSON strings
**What**: Serialize decorator arguments to JSON for storage in Decorator nodes.

**Why**:
- KuzuDB doesn't support complex nested structures natively
- JSON is human-readable for debugging
- Enables future querying by argument values
- Lightweight serialization

**Limitations**:
- Complex non-literal arguments stored as string representations
- Querying by argument values requires JSON parsing
- Acceptable trade-off for current use cases

### Decision 4: Module hierarchy derived from filesystem
**What**: Construct module names from file paths relative to project root (e.g., `src/utils/helpers.py` → `utils.helpers`).

**Why**:
- Deterministic and reliable
- No need to parse __init__.py imports
- Matches Python's module resolution

**Edge cases**:
- Packages without __init__.py (namespace packages) - handle by checking directory structure
- Non-standard project layouts - user can configure project_root

### Decision 5: Schema migration via re-analysis (no live migration)
**What**: Require users to re-run `code-explorer analyze` after upgrading to new schema.

**Why**:
- Simpler implementation (no migration logic)
- Faster for users (full analysis takes <5 min for 1000 files)
- Avoids complex data migration bugs
- KuzuDB doesn't have built-in migration tools

**User experience**:
- CLI detects old schema and prompts user
- Clear error message with migration instructions
- Option to delete old DB or backup

## Schema Design

### Node Tables

```cypher
# Import nodes - granular import tracking
CREATE NODE TABLE Import(
    id STRING PRIMARY KEY,
    imported_name STRING,      # "calculate" or "numpy"
    import_type STRING,        # "module", "function", "class", "variable", "*"
    alias STRING,              # "np" for "import numpy as np", null otherwise
    line_number INT64,
    is_relative BOOLEAN,
    file STRING                # Source file doing the import
)

# Decorator nodes - decorator applications
CREATE NODE TABLE Decorator(
    id STRING PRIMARY KEY,
    name STRING,               # "property", "lru_cache", "dataclass"
    file STRING,
    line_number INT64,
    arguments STRING           # JSON-serialized decorator arguments
)

# Attribute nodes - class attributes and fields
CREATE NODE TABLE Attribute(
    id STRING PRIMARY KEY,
    name STRING,               # "count", "value"
    class_name STRING,         # Which class owns this attribute
    file STRING,
    definition_line INT64,
    type_hint STRING,          # "int", "List[str]", etc.
    is_class_attribute BOOLEAN # True for class vars, False for instance vars
)

# Exception nodes - raised/caught exceptions
CREATE NODE TABLE Exception(
    id STRING PRIMARY KEY,
    name STRING,               # "ValueError", "CustomException"
    file STRING,
    line_number INT64
)

# Module nodes - package/module hierarchy
CREATE NODE TABLE Module(
    id STRING PRIMARY KEY,
    name STRING,               # "utils.helpers", "myapp.services"
    path STRING,               # File path or directory path
    is_package BOOLEAN,        # True if __init__.py, False for regular module
    docstring STRING           # Module-level docstring
)
```

### Edge Tables

```cypher
# Import edges
CREATE REL TABLE HAS_IMPORT(FROM File TO Import)
CREATE REL TABLE IMPORTS_FROM(FROM Import TO Function|Class|Variable|Module)

# Decorator edges
CREATE REL TABLE DECORATED_BY(FROM Function|Class TO Decorator, position INT64)
CREATE REL TABLE DECORATOR_RESOLVES_TO(FROM Decorator TO Function)

# Attribute edges
CREATE REL TABLE HAS_ATTRIBUTE(FROM Class TO Attribute)
CREATE REL TABLE ACCESSES(FROM Function TO Attribute, line_number INT64)
CREATE REL TABLE MODIFIES(FROM Function TO Attribute, line_number INT64)

# Exception edges
CREATE REL TABLE RAISES(FROM Function TO Exception, line_number INT64)
CREATE REL TABLE CATCHES(FROM Function TO Exception, line_number INT64)

# Module edges
CREATE REL TABLE CONTAINS_MODULE(FROM Module TO Module)
CREATE REL TABLE MODULE_OF(FROM File TO Module)
```

## Implementation Strategy

### Phase 1: Schema and Core Methods (Week 1)
1. Add node tables to graph.py `_create_schema()`
2. Add edge tables to graph.py
3. Implement `add_import()`, `add_decorator()`, etc. methods
4. Implement ID generation methods (`_make_import_id()`, etc.)
5. Add basic unit tests for graph operations

### Phase 2: Analyzer Integration (Week 2)
1. Add extraction methods to analyzer.py (`_extract_imports_detailed()`, etc.)
2. Update FileAnalysis dataclass
3. Update `analyze_file()` to call new extractors
4. Add unit tests for extraction methods

### Phase 3: CLI and Queries (Week 3)
1. Update CLI `analyze` command to populate new nodes
2. Add query methods to graph.py (`get_imports_for_file()`, etc.)
3. Update `stats` command
4. Add integration tests

### Phase 4: Documentation and Polish (Week 4)
1. Update README and tutorials
2. Add migration guide
3. Performance testing and optimization
4. Schema version detection

## Risks / Trade-offs

### Risk: Performance degradation with larger graphs
**Impact**: Medium - graph size increases 30-50%
**Mitigation**:
- KuzuDB is designed for larger graphs (tested to millions of nodes)
- Query patterns remain similar (indexed lookups)
- Performance tests in Phase 4 will validate

### Risk: Incomplete decorator argument parsing
**Impact**: Low - some complex decorators won't have arguments
**Mitigation**:
- Use ast.literal_eval for literal arguments
- Store repr() for complex arguments
- Mark as "unparseable" if needed

### Risk: Dynamic imports not captured
**Impact**: Low - affects <5% of typical codebases
**Mitigation**:
- Document limitation
- Mark unresolved imports explicitly
- Future: add runtime analysis mode (out of scope)

### Trade-off: Schema migration complexity
**Impact**: Medium - users must re-analyze
**Mitigation**:
- Clear error messages
- Fast re-analysis (<5 min for typical projects)
- Incremental updates still work after migration

## Migration Plan

### For Users

1. **Detect old schema**:
   ```python
   # In graph.py, add schema version check
   def _check_schema_version(self):
       try:
           result = self.conn.execute("MATCH (i:Import) RETURN COUNT(*) LIMIT 1")
           return "v2"
       except:
           return "v1"
   ```

2. **Prompt for migration**:
   ```bash
   $ code-explorer analyze ./src
   Error: Database schema outdated (found v1, need v2)

   To migrate, run:
     code-explorer analyze ./src --refresh

   This will re-analyze your codebase (typically <5 min for 1000 files).
   ```

3. **Re-analyze**:
   ```bash
   $ code-explorer analyze ./src --refresh
   ```

### Rollback Plan

If issues arise:
1. User can delete `.code-explorer/` directory
2. Downgrade to previous version
3. Re-run analysis with old schema

## Open Questions

1. **Q**: Should we track method calls vs function calls separately?
   **A**: No - treat uniformly as CALLS edges. Distinction available via parent_class property.

2. **Q**: Should attribute access track object provenance (which object)?
   **A**: No - too complex for static analysis. Track class attribute only.

3. **Q**: Should we support custom decorator effect annotations?
   **A**: Not in v1 - focus on tracking application, not side effects.

4. **Q**: How to handle star imports (`from module import *`)?
   **A**: Create Import node with import_type="*", don't create IMPORTS_FROM edges (ambiguous).

5. **Q**: Should Module nodes include external packages (numpy, etc.)?
   **A**: Future enhancement - for now, only track local modules. Mark as "external" in Import nodes.
