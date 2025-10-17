# Enhanced Dependency Graph Schema

## Why

The current dependency graph schema captures basic code structure (functions, variables, classes) but misses critical dependency information that users need for comprehensive impact analysis:

- **Import granularity**: We track that File A imports File B, but not *what* was imported (specific functions, classes, or variables), making it impossible to answer "what breaks if I rename this function?"
- **Decorator dependencies**: Decorators like `@property`, `@cached`, `@dataclass` fundamentally change behavior and create implicit dependencies, but we don't track them
- **Attribute access**: Class attributes and object.attribute access patterns are invisible, preventing data flow analysis through object state
- **Exception propagation**: We can't answer "what functions might throw exceptions that I need to handle?"
- **Module hierarchy**: Package structure is lost, making module-level impact analysis impossible

## What Changes

Add five high-priority node types and supporting edges to the KuzuDB schema:

1. **Import Node** - Granular import tracking (what was imported, not just which files)
   - Properties: imported_name, import_type, alias, line_number, is_relative
   - Edges: HAS_IMPORT (File → Import), IMPORTS_FROM (Import → Function|Class|Variable)

2. **Decorator Node** - Track decorators and their effects
   - Properties: name, file, line_number, arguments (JSON)
   - Edges: DECORATED_BY (Function|Class → Decorator), DECORATOR_RESOLVES_TO (Decorator → Function)

3. **Attribute Node** - Class attributes and field access
   - Properties: name, class_name, file, definition_line, type_hint, is_class_attribute
   - Edges: HAS_ATTRIBUTE (Class → Attribute), ACCESSES (Function → Attribute), MODIFIES (Function → Attribute)

4. **Exception Node** - Exception raising and handling
   - Properties: name, file, line_number
   - Edges: RAISES (Function → Exception), CATCHES (Function → Exception)

5. **Module Node** - Package/module hierarchy
   - Properties: name, path, is_package, docstring
   - Edges: CONTAINS_MODULE (Module → Module), MODULE_OF (File → Module)

### Breaking Changes

**Schema Migration Required**:
- New node tables must be created in KuzuDB
- Existing databases will need migration or re-analysis
- CLI will detect schema version and prompt user to re-analyze or migrate

## Impact

### Affected Specs
- **dependency-analysis**: Five new ADDED requirements for each node type

### Affected Code
- `src/code_explorer/graph.py` (graph.py:99-206): Add new node tables and edge tables to `_create_schema()`
- `src/code_explorer/graph.py`: Add methods for each node type (add_*, get_*, query operations)
- `src/code_explorer/analyzer.py` (analyzer.py:139-173): Extract new information during AST analysis
- `src/code_explorer/analyzer.py`: Add extraction methods for decorators, imports, attributes, exceptions
- `src/code_explorer/cli.py` (cli.py:156-246): Update analyze command to populate new nodes
- `tests/`: New test files for each node type

### User Impact
- **Existing databases**: Users must re-run `code-explorer analyze` or use migration tool
- **New capabilities**: Enables answering previously impossible questions:
  - "What breaks if I rename this function?" (import tracking)
  - "What implicitly depends on this via decorators?" (decorator tracking)
  - "What modifies this class attribute?" (attribute tracking)
  - "What exceptions can this call chain raise?" (exception propagation)

### Performance Considerations
- Larger graph size (estimated +30-50% nodes for typical codebases)
- Slightly slower initial analysis (more AST traversal)
- Query performance should remain similar (indexed by node IDs)
