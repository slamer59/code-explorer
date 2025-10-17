# KuzuDB Cypher Queries for Code Impact Analysis

**NOTE**: Schema updated to include CALLS edges! Your database now has:
- ✅ Nodes: File, Function, Class, Variable, Import, Decorator, Attribute, Exception
- ✅ Edges: CONTAINS_FUNCTION, METHOD_OF, HAS_ATTRIBUTE, DECORATED_BY, HAS_IMPORT, HANDLES_EXCEPTION, **CALLS** ← NEW!

Raw Cypher queries optimized for KuzuDB Python API. Use with: `conn.execute(query, params)`

---

## NEW: Function Call Analysis Queries Now Available! 🎉

The CALLS edges are now fully supported! You can now:
- ✅ Direct function call tracing (who calls whom)
- ✅ Upstream/downstream dependency analysis
- ✅ Call chain traversal

**To enable CALLS edges in your existing database:**
1. Run `code-explorer analyze . --refresh` to rebuild with latest schema
2. All subsequent analyses will include function call relationships

---

## 1. FILE & FUNCTION QUERIES

### 1.1 Get All Functions in a File
```cypher
MATCH (f:File {path: $file_path})-[:CONTAINS_FUNCTION]->(func:Function)
RETURN
    func.name as function_name,
    func.file as file_path,
    func.start_line as start_line,
    func.end_line as end_line,
    func.source_code as source_code,
    func.is_public as is_public
ORDER BY func.start_line
```

**Usage:**
```python
result = conn.execute("""
MATCH (f:File {path: $file_path})-[:CONTAINS_FUNCTION]->(func:Function)
RETURN func.name, func.file, func.start_line, func.end_line, func.is_public
""", {"file_path": "module.py"})

while result.has_next():
    row = result.get_next()
    print(f"{row[0]} at {row[1]}:{row[2]}")
```

---

### 1.2 Get All Functions in Multiple Files
```cypher
MATCH (f:File)-[:CONTAINS_FUNCTION]->(func:Function)
WHERE f.path IN $file_paths
RETURN
    f.path as file_path,
    func.name as function_name,
    func.start_line as start_line,
    func.end_line as end_line,
    func.source_code as source_code
ORDER BY f.path, func.start_line
```

**Usage:**
```python
result = conn.execute(query, {
    "file_paths": ["module.py", "utils.py", "helpers.py"]
})
```

---

### 1.3 Get All Files
```cypher
MATCH (f:File)
RETURN
    f.path as file_path,
    f.language as language,
    f.content_hash as content_hash
ORDER BY f.path
```

---

### 1.4 Search Functions by Name
```cypher
MATCH (f:Function)
WHERE f.name CONTAINS $name_pattern
RETURN
    f.name as function_name,
    f.file as file_path,
    f.start_line as start_line,
    f.end_line as end_line,
    f.is_public as is_public
ORDER BY f.file, f.start_line
```

**Usage:**
```python
result = conn.execute(query, {"name_pattern": "process"})
```

---

## 1.5 FUNCTION CALL ANALYSIS (NEW! 🎉)

### 1.5.1 Find All Upstream Callers (Who Calls This Function?)
```cypher
MATCH (caller:Function)-[:CALLS*1..5]->(target:Function {file: $file, name: $func_name})
WITH DISTINCT caller, LENGTH(0) as depth
RETURN
    caller.name as caller_function,
    caller.file as caller_file,
    caller.start_line as start_line,
    caller.end_line as end_line,
    caller.source_code as source_code
ORDER BY caller.file, caller.start_line
```

**Usage:**
```python
result = conn.execute(query, {
    "file": "module.py",
    "func_name": "my_function"
})
```

---

### 1.5.2 Find All Downstream Callees (What Functions Does This Call?)
```cypher
MATCH (source:Function {file: $file, name: $func_name})-[:CALLS*1..5]->(callee:Function)
RETURN DISTINCT
    callee.name as callee_function,
    callee.file as callee_file,
    callee.start_line as start_line,
    callee.end_line as end_line,
    callee.source_code as source_code
ORDER BY callee.file, callee.start_line
```

---

### 1.5.3 Direct Function Calls (With Call Line Numbers)
```cypher
MATCH (caller:Function)-[c:CALLS]->(target:Function {file: $file, name: $func_name})
RETURN
    caller.name as caller_function,
    caller.file as caller_file,
    caller.source_code as caller_source,
    caller.start_line as caller_start,
    caller.end_line as caller_end,
    c.call_line as call_line_number,
    target.name as target_function
ORDER BY caller.file, c.call_line
```

---

### 1.5.4 Call Chain Depth (Transitive Closure)
```cypher
MATCH path = (root:Function {file: $file, name: $func_name})-[:CALLS*0..10]->(descendant:Function)
WITH descendant, MIN(LENGTH(path)) as min_depth
WHERE min_depth > 0
RETURN
    descendant.name as function_name,
    descendant.file as file_path,
    descendant.source_code as source_code,
    min_depth as call_depth
ORDER BY min_depth, descendant.file, descendant.start_line
```

---

### 1.5.5 Most-Called Functions (In-Degree Centrality)
```cypher
MATCH (callee:Function)<-[:CALLS]-(caller:Function)
WITH callee, COUNT(DISTINCT caller) as num_callers
WHERE num_callers > 0
RETURN
    callee.name as function_name,
    callee.file as file_path,
    callee.source_code as source_code,
    num_callers as caller_count
ORDER BY caller_count DESC
LIMIT 20
```

---

### 1.5.6 Dead Code (Never Called Functions)
```cypher
MATCH (f:Function)
WHERE NOT EXISTS((caller:Function)-[:CALLS]->(f))
RETURN
    f.name as function_name,
    f.file as file_path,
    f.is_public as is_public,
    f.source_code as source_code,
    f.start_line as start_line
ORDER BY f.file, f.start_line
```

---

## 2. CLASS & ATTRIBUTE QUERIES

### 2.1 Get All Classes in a File
```cypher
MATCH (f:File {path: $file_path})-[:CONTAINS_CLASS]->(cls:Class)
RETURN
    cls.name as class_name,
    cls.file as file_path,
    cls.start_line as start_line,
    cls.end_line as end_line,
    cls.bases as base_classes,
    cls.is_public as is_public,
    cls.source_code as source_code
ORDER BY cls.start_line
```

---

### 2.2 Get All Methods of a Class
```cypher
MATCH (cls:Class {file: $file, name: $class_name})<-[:METHOD_OF]-(method:Function)
RETURN
    method.name as method_name,
    method.source_code as method_source,
    method.start_line as start_line,
    method.end_line as end_line,
    method.is_public as is_public
ORDER BY method.start_line
```

---

### 2.3 Get All Attributes of a Class
```cypher
MATCH (cls:Class {file: $file, name: $class_name})-[:HAS_ATTRIBUTE]->(attr:Attribute)
RETURN
    attr.name as attribute_name,
    attr.type_hint as type_hint,
    attr.is_class_attribute as is_class_attribute,
    attr.definition_line as definition_line
ORDER BY attr.definition_line
```

---

### 2.4 Get Class Base Classes (Inheritance Info)
```cypher
MATCH (cls:Class {file: $file, name: $class_name})
RETURN
    cls.name as class_name,
    cls.bases as base_classes,
    cls.start_line as start_line,
    cls.end_line as end_line
```

**Note:** The `bases` field contains JSON-encoded list of parent class names. The INHERITS edge type is not currently tracked in the schema.

---

### 2.5 Find Classes and Their Methods
```cypher
MATCH (cls:Class {file: $file, name: $class_name})<-[:METHOD_OF]-(method:Function)
RETURN
    cls.name as class_name,
    COLLECT(method.name) as methods,
    COUNT(*) as method_count
```

---

## 3. DECORATOR & ANNOTATION QUERIES

### 3.1 Get All Functions With a Specific Decorator
```cypher
MATCH (func:Function)-[:DECORATED_BY]->(dec:Decorator {name: $decorator_name})
RETURN
    func.name as function_name,
    func.file as file_path,
    func.start_line as start_line,
    func.end_line as end_line,
    func.source_code as source_code,
    dec.arguments as decorator_args,
    dec.line_number as decorator_line
ORDER BY func.file, func.start_line
```

**Usage:**
```python
result = conn.execute(query, {"decorator_name": "property"})
```

---

### 3.2 Get All Classes With a Specific Decorator
```cypher
MATCH (cls:Class)-[:DECORATED_BY]->(dec:Decorator {name: $decorator_name})
RETURN
    cls.name as class_name,
    cls.file as file_path,
    cls.start_line as start_line,
    dec.arguments as decorator_args
ORDER BY cls.file
```

---

### 3.3 Get All Decorators Used in a File
```cypher
MATCH (f:File {path: $file_path})-[:CONTAINS_FUNCTION]->(func:Function)-[:DECORATED_BY]->(dec:Decorator)
RETURN DISTINCT
    dec.name as decorator_name,
    COLLECT(DISTINCT func.name) as functions_using_it
```

---

## 4. EXCEPTION & ERROR HANDLING QUERIES

### 4.1 Get Functions That Raise a Specific Exception
```cypher
MATCH (func:Function)-[he:HANDLES_EXCEPTION {context: 'raise'}]->(exc:Exception {name: $exception_name})
RETURN
    func.name as function_name,
    func.file as file_path,
    func.source_code as source_code,
    func.start_line as start_line,
    he.line_number as raise_line
ORDER BY func.file, he.line_number
```

**Usage:**
```python
result = conn.execute(query, {"exception_name": "ValueError"})
```

---

### 4.2 Get Functions That Catch a Specific Exception
```cypher
MATCH (func:Function)-[he:HANDLES_EXCEPTION {context: 'catch'}]->(exc:Exception {name: $exception_name})
RETURN
    func.name as function_name,
    func.file as file_path,
    func.start_line as start_line,
    he.line_number as catch_line
ORDER BY func.file
```

---

### 4.3 Get All Exceptions in a File
```cypher
MATCH (f:File {path: $file_path})-[:CONTAINS_FUNCTION]->(func:Function)-[:HANDLES_EXCEPTION]->(exc:Exception)
RETURN DISTINCT
    exc.name as exception_name,
    COLLECT(DISTINCT func.name) as functions_handling_it
```

---

### 4.4 Get All Exception Types Handled by a Function
```cypher
MATCH (func:Function {file: $file, name: $func_name})-[he:HANDLES_EXCEPTION]->(exc:Exception)
RETURN
    exc.name as exception_name,
    he.context as context,
    he.line_number as line_number
ORDER BY he.line_number
```

---

## 5. IMPORT & DEPENDENCY QUERIES

### 5.1 Get All Imports in a File
```cypher
MATCH (f:File {path: $file_path})-[:HAS_IMPORT]->(imp:Import)
RETURN
    imp.imported_name as imported_name,
    imp.import_type as import_type,
    imp.alias as alias,
    imp.line_number as line_number,
    imp.is_relative as is_relative
ORDER BY imp.line_number
```

---

### 5.2 Find Which Files Import a Specific Module
```cypher
MATCH (f:File)-[:HAS_IMPORT]->(imp:Import {imported_name: $module_name})
RETURN
    f.path as file_path,
    imp.import_type as import_type,
    imp.alias as alias,
    imp.line_number as line_number
ORDER BY f.path
```

**Usage:**
```python
result = conn.execute(query, {"module_name": "pandas"})
```

---

### 5.3 Get Import Statistics
```cypher
MATCH (f:File)-[:HAS_IMPORT]->(imp:Import)
RETURN
    COUNT(DISTINCT f) as files_with_imports,
    COUNT(DISTINCT imp.imported_name) as unique_imports,
    COUNT(*) as total_imports
```

---

## 6. VARIABLE QUERIES

### 6.1 Get All Variables in a File
```cypher
MATCH (f:File {path: $file_path})-[:CONTAINS_VARIABLE]->(var:Variable)
RETURN
    var.name as variable_name,
    var.file as file_path,
    var.definition_line as definition_line,
    var.scope as scope
ORDER BY var.definition_line
```

---

### 6.2 Find Variables by Name Pattern
```cypher
MATCH (var:Variable)
WHERE var.name CONTAINS $name_pattern
RETURN
    var.name as variable_name,
    var.file as file_path,
    var.definition_line as definition_line,
    var.scope as scope
ORDER BY var.file, var.definition_line
```

---

### 6.3 Get All Global Variables
```cypher
MATCH (var:Variable {scope: 'module'})
RETURN
    var.name as variable_name,
    var.file as file_path,
    var.definition_line as definition_line
ORDER BY var.file, var.definition_line
```

---

## 7. BULK STATISTICS & ANALYSIS

### 7.1 Overall Codebase Statistics
```cypher
MATCH (f:File)
WITH COUNT(*) as total_files
MATCH (fn:Function)
WITH total_files, COUNT(*) as total_functions
MATCH (c:Class)
WITH total_files, total_functions, COUNT(*) as total_classes
MATCH (v:Variable)
WITH total_files, total_functions, total_classes, COUNT(*) as total_variables
MATCH (i:Import)
WITH total_files, total_functions, total_classes, total_variables, COUNT(*) as total_imports
MATCH (d:Decorator)
WITH total_files, total_functions, total_classes, total_variables, total_imports, COUNT(*) as total_decorators
MATCH (e:Exception)
WITH total_files, total_functions, total_classes, total_variables, total_imports, total_decorators, COUNT(*) as total_exceptions
RETURN
    total_files as files,
    total_functions as functions,
    total_classes as classes,
    total_variables as variables,
    total_imports as imports,
    total_decorators as decorators,
    total_exceptions as exceptions
```

---

### 7.2 Functions Per File Statistics
```cypher
MATCH (f:File)-[:CONTAINS_FUNCTION]->(func:Function)
RETURN
    f.path as file_path,
    COUNT(*) as function_count
ORDER BY function_count DESC
LIMIT 20
```

---

### 7.3 Most Decorated Functions
```cypher
MATCH (func:Function)-[:DECORATED_BY]->(dec:Decorator)
RETURN
    func.name as function_name,
    func.file as file_path,
    COUNT(*) as decorator_count,
    COLLECT(DISTINCT dec.name) as decorators
ORDER BY decorator_count DESC
LIMIT 20
```

---

### 7.4 Classes Per File
```cypher
MATCH (f:File)-[:CONTAINS_CLASS]->(cls:Class)
RETURN
    f.path as file_path,
    COUNT(*) as class_count,
    COLLECT(DISTINCT cls.name) as class_names
ORDER BY class_count DESC
```

---

### 7.5 Largest Classes (Most Methods)
```cypher
MATCH (cls:Class)<-[:METHOD_OF]-(method:Function)
RETURN
    cls.name as class_name,
    cls.file as file_path,
    COUNT(*) as method_count,
    COLLECT(DISTINCT method.name) as methods
ORDER BY method_count DESC
LIMIT 20
```

---

### 7.6 Most Used Decorators
```cypher
MATCH (entity)-[:DECORATED_BY]->(dec:Decorator)
RETURN
    dec.name as decorator_name,
    COUNT(*) as usage_count
ORDER BY usage_count DESC
```

---

### 7.7 Exception Coverage
```cypher
MATCH (func:Function)-[:HANDLES_EXCEPTION]->(exc:Exception)
RETURN
    exc.name as exception_name,
    COUNT(DISTINCT func) as functions_handling_it
ORDER BY functions_handling_it DESC
LIMIT 20
```

---

## 8. COMPLEX ANALYSIS QUERIES

### 8.1 Functions With Multiple Decorators
```cypher
MATCH (func:Function)-[:DECORATED_BY]->(dec:Decorator)
WITH func, COUNT(*) as decorator_count, COLLECT(dec.name) as decorators
WHERE decorator_count > 1
RETURN
    func.name as function_name,
    func.file as file_path,
    decorator_count,
    decorators
ORDER BY decorator_count DESC
```

---

### 8.2 Find Unused Methods (Private Methods Not In Any Exception Handlers)
```cypher
MATCH (cls:Class)<-[:METHOD_OF]-(method:Function {is_public: false})
WHERE NOT EXISTS((method)-[:HANDLES_EXCEPTION]->())
RETURN
    cls.name as class_name,
    method.name as method_name,
    cls.file as file_path,
    method.start_line as start_line
ORDER BY cls.file, method.start_line
```

---

### 8.3 Complex Classes (Many Methods + Attributes)
```cypher
MATCH (cls:Class)<-[:METHOD_OF]-(method:Function)
MATCH (cls)-[:HAS_ATTRIBUTE]->(attr:Attribute)
WITH cls, COUNT(DISTINCT method) as method_count, COUNT(DISTINCT attr) as attr_count
WHERE method_count + attr_count > 10
RETURN
    cls.name as class_name,
    cls.file as file_path,
    method_count,
    attr_count,
    method_count + attr_count as complexity_score
ORDER BY complexity_score DESC
```

---

### 8.4 Classes With Most Methods
```cypher
MATCH (cls:Class)<-[:METHOD_OF]-(method:Function)
WITH cls, COUNT(DISTINCT method) as method_count
WHERE method_count > 0
RETURN
    cls.name as class_name,
    cls.file as file_path,
    cls.bases as parent_classes,
    method_count
ORDER BY method_count DESC
LIMIT 20
```

**Note:** The `bases` field contains parent class information. Direct inheritance tracking via INHERITS edge is not currently supported.

---

### 8.5 Files With Most Imports
```cypher
MATCH (f:File)-[:HAS_IMPORT]->(imp:Import)
RETURN
    f.path as file_path,
    COUNT(DISTINCT imp.imported_name) as unique_imports,
    COUNT(*) as total_import_statements
ORDER BY unique_imports DESC
LIMIT 20
```

---

### 8.6 Public API Surface (Public Functions and Classes)
```cypher
MATCH (f:File {path: $file_path})-[:CONTAINS_FUNCTION]->(func:Function {is_public: true})
OPTIONAL MATCH (f)-[:CONTAINS_CLASS]->(cls:Class {is_public: true})
RETURN
    COLLECT(DISTINCT func.name) as public_functions,
    COLLECT(DISTINCT cls.name) as public_classes
```

---

## 9. TESTING QUERIES

### 9.1 Test Connection
```cypher
MATCH (f:File)
RETURN COUNT(*) as file_count
LIMIT 1
```

**Python Test:**
```python
import kuzu

db = kuzu.Database(".code-explorer/graph.db", read_only=True)
conn = kuzu.Connection(db)

try:
    result = conn.execute("MATCH (f:File) RETURN COUNT(*) as count")
    if result.has_next():
        count = result.get_next()[0]
        print(f"✓ Database connected. Found {count:,} files")
except Exception as e:
    print(f"✗ Error: {e}")
finally:
    db.close()
```

---

### 9.2 List All Tables
```python
import kuzu

db = kuzu.Database(".code-explorer/graph.db", read_only=True)
conn = kuzu.Connection(db)

result = conn.execute("CALL show_tables() RETURN *;")
print("Available tables:")
while result.has_next():
    print(f"  - {result.get_next()[0]}")

db.close()
```

---

### 9.3 Get Codebase Statistics Summary
```cypher
MATCH (f:File)
WITH COUNT(*) as total_files
MATCH (fn:Function)
WITH total_files, COUNT(*) as total_functions
MATCH (c:Class)
WITH total_files, total_functions, COUNT(*) as total_classes
MATCH (v:Variable)
WITH total_files, total_functions, total_classes, COUNT(*) as total_variables
MATCH (i:Import)
WITH total_files, total_functions, total_classes, total_variables, COUNT(*) as total_imports
MATCH (d:Decorator)
WITH total_files, total_functions, total_classes, total_variables, total_imports, COUNT(*) as total_decorators
MATCH (a:Attribute)
WITH total_files, total_functions, total_classes, total_variables, total_imports, total_decorators, COUNT(*) as total_attributes
MATCH (e:Exception)
WITH total_files, total_functions, total_classes, total_variables, total_imports, total_decorators, total_attributes, COUNT(*) as total_exceptions
RETURN
    total_files as "Total Files",
    total_functions as "Total Functions",
    total_classes as "Total Classes",
    total_variables as "Total Variables",
    total_imports as "Total Imports",
    total_decorators as "Total Decorators",
    total_attributes as "Total Attributes",
    total_exceptions as "Total Exceptions"
```

**Sample Results:**
```
Total Files:        1,606
Total Functions:    7,678
Total Classes:      1,076
Total Variables:   24,480
Total Imports:        840
Total Decorators:   2,801
Total Attributes:   1,493
Total Exceptions:   1,141
```

---

### 9.3b Get All Relationship/Edge Statistics
```cypher
MATCH ()-[contains_func:CONTAINS_FUNCTION]->() WITH COUNT(*) as contains_function
MATCH ()-[contains_cls:CONTAINS_CLASS]->() WITH contains_function, COUNT(*) as contains_class
MATCH ()-[contains_var:CONTAINS_VARIABLE]->() WITH contains_function, contains_class, COUNT(*) as contains_variable
MATCH ()-[method_of:METHOD_OF]->() WITH contains_function, contains_class, contains_variable, COUNT(*) as method_of
MATCH ()-[has_import:HAS_IMPORT]->() WITH contains_function, contains_class, contains_variable, method_of, COUNT(*) as has_import
MATCH ()-[has_attr:HAS_ATTRIBUTE]->() WITH contains_function, contains_class, contains_variable, method_of, has_import, COUNT(*) as has_attribute
MATCH ()-[decorated_by:DECORATED_BY]->() WITH contains_function, contains_class, contains_variable, method_of, has_import, has_attribute, COUNT(*) as decorated_by
MATCH ()-[references:REFERENCES]->() WITH contains_function, contains_class, contains_variable, method_of, has_import, has_attribute, decorated_by, COUNT(*) as references
MATCH ()-[accesses:ACCESSES]->() WITH contains_function, contains_class, contains_variable, method_of, has_import, has_attribute, decorated_by, references, COUNT(*) as accesses
MATCH ()-[handles_exc:HANDLES_EXCEPTION]->() WITH contains_function, contains_class, contains_variable, method_of, has_import, has_attribute, decorated_by, references, accesses, COUNT(*) as handles_exception
MATCH ()-[calls:CALLS]->() WITH contains_function, contains_class, contains_variable, method_of, has_import, has_attribute, decorated_by, references, accesses, handles_exception, COUNT(*) as calls
RETURN
    contains_function as "CONTAINS_FUNCTION",
    contains_class as "CONTAINS_CLASS",
    contains_variable as "CONTAINS_VARIABLE",
    method_of as "METHOD_OF",
    has_import as "HAS_IMPORT",
    has_attribute as "HAS_ATTRIBUTE",
    decorated_by as "DECORATED_BY",
    references as "REFERENCES",
    accesses as "ACCESSES",
    handles_exception as "HANDLES_EXCEPTION",
    calls as "CALLS",
    (contains_function + contains_class + contains_variable + method_of + has_import + has_attribute + decorated_by + references + accesses + handles_exception + calls) as "TOTAL_EDGES"
```

**Sample Results:**
```
CONTAINS_FUNCTION:    7,678  (File -> Function)
CONTAINS_CLASS:       1,076  (File -> Class)
CONTAINS_VARIABLE:   24,412  (File -> Variable)
METHOD_OF:            2,614  (Function -> Class)
HAS_IMPORT:             840  (File -> Import)
HAS_ATTRIBUTE:        1,493  (Class -> Attribute)
DECORATED_BY:         2,760  (Function -> Decorator)
REFERENCES:               0  (Function -> Variable)
ACCESSES:                 0  (Function -> Attribute)
HANDLES_EXCEPTION:      569  (Function -> Exception)
CALLS:            [pending]  (Function -> Function) ← Will be populated after refresh
─────────────────────────────
TOTAL_EDGES:         41,442
```

---

### 9.3c Relationship Statistics with Percentages
```cypher
MATCH ()-[e]->()
WITH labels(startNode(e))[0] as from_type, labels(endNode(e))[0] as to_type, type(e) as edge_type, COUNT(*) as edge_count
MATCH ()-[all_edges]->()
WITH from_type, to_type, edge_type, edge_count, COUNT(*) as total_edges
RETURN
    edge_type as "Relationship Type",
    edge_count as "Count",
    ROUND(100.0 * edge_count / total_edges, 2) as "% of Total",
    from_type + " → " + to_type as "Direction"
ORDER BY edge_count DESC
```

---

### 9.4 Check Available Nodes and Edges
```python
import kuzu

db = kuzu.Database(".code-explorer/graph.db", read_only=True)
conn = kuzu.Connection(db)

node_types = ["File", "Function", "Class", "Variable", "Import", "Decorator", "Attribute", "Exception", "Module"]
edge_types = ["CONTAINS_FUNCTION", "CONTAINS_CLASS", "CONTAINS_VARIABLE", "HAS_IMPORT", "METHOD_OF",
              "DECORATED_BY", "HAS_ATTRIBUTE", "HANDLES_EXCEPTION", "CALLS", "REFERENCES", "ACCESSES"]

print("\n=== NODES ===")
for node in node_types:
    try:
        result = conn.execute(f"MATCH (n:{node}) RETURN COUNT(*) as count LIMIT 1")
        if result.has_next():
            count = result.get_next()[0]
            if count > 0:
                print(f"  {node}: {count:,}")
    except:
        pass

print("\n=== EDGES ===")
for edge in edge_types:
    try:
        result = conn.execute(f"MATCH ()-[r:{edge}]->() RETURN COUNT(*) as count LIMIT 1")
        if result.has_next():
            count = result.get_next()[0]
            if count > 0:
                print(f"  {edge}: {count:,}")
    except:
        pass

db.close()
```

