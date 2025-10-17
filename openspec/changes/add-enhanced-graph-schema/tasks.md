# Implementation Tasks

## 1. Schema Extension
- [ ] 1.1 Add Import node table to graph.py `_create_schema()`
- [ ] 1.2 Add Decorator node table to graph.py `_create_schema()`
- [ ] 1.3 Add Attribute node table to graph.py `_create_schema()`
- [ ] 1.4 Add Exception node table to graph.py `_create_schema()`
- [ ] 1.5 Add Module node table to graph.py `_create_schema()`
- [ ] 1.6 Add HAS_IMPORT edge table (File → Import)
- [ ] 1.7 Add IMPORTS_FROM edge table (Import → Function|Class|Variable)
- [ ] 1.8 Add DECORATED_BY edge table (Function|Class → Decorator)
- [ ] 1.9 Add DECORATOR_RESOLVES_TO edge table (Decorator → Function)
- [ ] 1.10 Add HAS_ATTRIBUTE edge table (Class → Attribute)
- [ ] 1.11 Add ACCESSES edge table (Function → Attribute)
- [ ] 1.12 Add MODIFIES edge table (Function → Attribute)
- [ ] 1.13 Add RAISES edge table (Function → Exception)
- [ ] 1.14 Add CATCHES edge table (Function → Exception)
- [ ] 1.15 Add CONTAINS_MODULE edge table (Module → Module)
- [ ] 1.16 Add MODULE_OF edge table (File → Module)

## 2. Analyzer Enhancements
- [ ] 2.1 Add `_extract_imports_detailed()` method to analyzer.py using ast
- [ ] 2.2 Add `_extract_decorators()` method to analyzer.py using ast
- [ ] 2.3 Add `_extract_attributes()` method to analyzer.py using ast
- [ ] 2.4 Add `_extract_exceptions()` method to analyzer.py using ast
- [ ] 2.5 Add `_extract_module_info()` method to analyzer.py
- [ ] 2.6 Update FileAnalysis dataclass with new fields (imports_detailed, decorators, attributes, exceptions)
- [ ] 2.7 Update `analyze_file()` to call new extraction methods
- [ ] 2.8 Add attribute access detection in AST traversal
- [ ] 2.9 Add exception raise/catch detection in AST traversal
- [ ] 2.10 Handle decorator arguments parsing (JSON serialization)

## 3. Graph Methods
- [ ] 3.1 Add `add_import()` method to graph.py
- [ ] 3.2 Add `add_decorator()` method to graph.py
- [ ] 3.3 Add `add_attribute()` method to graph.py
- [ ] 3.4 Add `add_exception()` method to graph.py
- [ ] 3.5 Add `add_module()` method to graph.py
- [ ] 3.6 Add `get_imports_for_file()` query method
- [ ] 3.7 Add `get_decorators_for_function()` query method
- [ ] 3.8 Add `get_attributes_for_class()` query method
- [ ] 3.9 Add `get_functions_raising_exception()` query method
- [ ] 3.10 Add `get_module_hierarchy()` query method
- [ ] 3.11 Add `find_import_usages()` - find what imports a specific function/class
- [ ] 3.12 Add `find_attribute_modifiers()` - find what modifies an attribute
- [ ] 3.13 Update `_make_import_id()`, `_make_decorator_id()`, etc. ID generation methods
- [ ] 3.14 Update `delete_file_data()` to remove new node types
- [ ] 3.15 Update `get_statistics()` to include new node counts

## 4. CLI Integration
- [ ] 4.1 Update `analyze` command to populate Import nodes
- [ ] 4.2 Update `analyze` command to populate Decorator nodes
- [ ] 4.3 Update `analyze` command to populate Attribute nodes
- [ ] 4.4 Update `analyze` command to populate Exception nodes
- [ ] 4.5 Update `analyze` command to populate Module nodes
- [ ] 4.6 Update `stats` command to display new node counts
- [ ] 4.7 Add new query examples to CLI help text

## 5. Testing
- [ ] 5.1 Add unit tests for import extraction (test_analyzer.py)
- [ ] 5.2 Add unit tests for decorator extraction (test_analyzer.py)
- [ ] 5.3 Add unit tests for attribute extraction (test_analyzer.py)
- [ ] 5.4 Add unit tests for exception extraction (test_analyzer.py)
- [ ] 5.5 Add unit tests for module extraction (test_analyzer.py)
- [ ] 5.6 Add graph tests for Import node operations (test_graph.py)
- [ ] 5.7 Add graph tests for Decorator node operations (test_graph.py)
- [ ] 5.8 Add graph tests for Attribute node operations (test_graph.py)
- [ ] 5.9 Add graph tests for Exception node operations (test_graph.py)
- [ ] 5.10 Add graph tests for Module node operations (test_graph.py)
- [ ] 5.11 Add integration test: analyze file with decorators
- [ ] 5.12 Add integration test: query imports for renamed function
- [ ] 5.13 Add integration test: find attribute modification sites
- [ ] 5.14 Add integration test: trace exception propagation
- [ ] 5.15 Add performance test: analyze large codebase with new nodes

## 6. Documentation
- [ ] 6.1 Update README.md with new query capabilities
- [ ] 6.2 Add tutorial: Using import tracking to find rename impacts
- [ ] 6.3 Add tutorial: Analyzing decorator dependencies
- [ ] 6.4 Add tutorial: Tracking attribute modifications
- [ ] 6.5 Add reference doc: New node types and their properties
- [ ] 6.6 Update architecture.md with schema diagram
- [ ] 6.7 Add migration guide for existing users

## 7. Migration
- [ ] 7.1 Add schema version detection in graph.py
- [ ] 7.2 Add warning message if old schema detected
- [ ] 7.3 Update CLI to prompt for re-analysis if schema outdated
- [ ] 7.4 Document migration process (re-run analyze vs manual migration)
