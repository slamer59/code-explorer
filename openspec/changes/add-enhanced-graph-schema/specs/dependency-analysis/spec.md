# Dependency Analysis Spec Deltas

## ADDED Requirements

### Requirement: Granular Import Tracking
The system SHALL track individual import statements with full details about what was imported, not just which files import each other.

#### Scenario: Track "from module import function" imports
- **WHEN** analyzing code containing `from utils import calculate, validate`
- **THEN** system creates an Import node for `calculate` with import_type="function"
- **AND** creates an Import node for `validate` with import_type="function"
- **AND** creates HAS_IMPORT edges from File to both Import nodes
- **AND** stores line number where import occurs

#### Scenario: Track "import module as alias" statements
- **WHEN** analyzing code containing `import numpy as np`
- **THEN** system creates Import node with imported_name="numpy" and alias="np"
- **AND** creates HAS_IMPORT edge from File to Import node
- **AND** marks import as non-relative (is_relative=false)

#### Scenario: Track relative imports
- **WHEN** analyzing code containing `from ..utils import helper`
- **THEN** system creates Import node with is_relative=true
- **AND** stores relative import level (2 for `..`)
- **AND** resolves target module based on package structure

#### Scenario: Link imports to source definitions
- **WHEN** Import node references a function defined in the codebase
- **THEN** system creates IMPORTS_FROM edge from Import to source Function node
- **AND** enables querying "what imports this function?"
- **AND** supports impact analysis for function renames

#### Scenario: Query what imports a specific function
- **WHEN** user queries what imports function `calculate` from `utils.py`
- **THEN** system finds all Import nodes with imported_name="calculate"
- **AND** traverses HAS_IMPORT edges to find importing files
- **AND** returns list of (file, line_number, alias) tuples
- **AND** completes query in under 500ms

### Requirement: Decorator Dependency Tracking
The system SHALL track decorators applied to functions and classes, including decorator arguments and resolution to decorator functions.

#### Scenario: Track function decorators
- **WHEN** analyzing function with decorator `@property`
- **THEN** system creates Decorator node with name="property"
- **AND** creates DECORATED_BY edge from Function to Decorator
- **AND** stores line number of decorator application
- **AND** marks decorator as built-in if applicable

#### Scenario: Track decorators with arguments
- **WHEN** analyzing `@lru_cache(maxsize=128)`
- **THEN** system creates Decorator node with name="lru_cache"
- **AND** stores arguments as JSON: `{"maxsize": 128}`
- **AND** creates DECORATED_BY edge from Function to Decorator
- **AND** parses arguments using ast.literal_eval when possible

#### Scenario: Track class decorators
- **WHEN** analyzing class with decorator `@dataclass`
- **THEN** system creates Decorator node with name="dataclass"
- **AND** creates DECORATED_BY edge from Class to Decorator
- **AND** stores decorator arguments if present

#### Scenario: Resolve decorator to function definition
- **WHEN** decorator is a user-defined function in the codebase
- **THEN** system finds the decorator function definition
- **AND** creates DECORATOR_RESOLVES_TO edge from Decorator to Function
- **AND** enables transitive dependency tracking

#### Scenario: Track multiple decorators on same function
- **WHEN** function has multiple decorators `@cached @validate_input`
- **THEN** system creates separate Decorator nodes for each
- **AND** creates DECORATED_BY edges in application order (top to bottom)
- **AND** stores decorator position/order in edge properties

#### Scenario: Query functions using specific decorator
- **WHEN** user queries all functions with `@cached` decorator
- **THEN** system finds Decorator node with name="cached"
- **AND** traverses DECORATED_BY edges in reverse
- **AND** returns list of decorated functions with file and line info

### Requirement: Class Attribute Analysis
The system SHALL track class attributes separately from instance variables, including attribute access and modification patterns.

#### Scenario: Track class-level attributes
- **WHEN** analyzing class with `class MyClass: count = 0`
- **THEN** system creates Attribute node with name="count", is_class_attribute=true
- **AND** creates HAS_ATTRIBUTE edge from Class to Attribute
- **AND** stores definition line number
- **AND** extracts type hint if present

#### Scenario: Track instance attributes from __init__
- **WHEN** analyzing `def __init__(self): self.value = 0`
- **THEN** system creates Attribute node with name="value", is_class_attribute=false
- **AND** creates HAS_ATTRIBUTE edge from Class to Attribute
- **AND** stores definition line within __init__

#### Scenario: Track attribute access patterns
- **WHEN** analyzing function containing `obj.attr`
- **THEN** system creates ACCESSES edge from Function to Attribute
- **AND** stores access line number in edge properties
- **AND** marks access as read operation

#### Scenario: Track attribute modifications
- **WHEN** analyzing function containing `obj.attr = value`
- **THEN** system creates MODIFIES edge from Function to Attribute
- **AND** stores modification line number in edge properties
- **AND** marks modification as write operation

#### Scenario: Distinguish class vs instance attribute access
- **WHEN** analyzing `MyClass.class_var` vs `obj.instance_var`
- **THEN** system correctly identifies class-level access
- **AND** creates appropriate ACCESSES edge with context
- **AND** enables filtering by attribute type

#### Scenario: Query what modifies a class attribute
- **WHEN** user queries what modifies `MyClass.count`
- **THEN** system finds Attribute node for `count`
- **AND** traverses MODIFIES edges to find all modifying functions
- **AND** returns list of (file, function, line) tuples
- **AND** completes query in under 500ms

### Requirement: Exception Flow Analysis
The system SHALL track exception raising and handling to enable exception propagation analysis.

#### Scenario: Track raise statements
- **WHEN** analyzing function containing `raise ValueError("invalid")`
- **THEN** system creates Exception node with name="ValueError"
- **AND** creates RAISES edge from Function to Exception
- **AND** stores line number where exception is raised
- **AND** extracts exception message if literal string

#### Scenario: Track exception handling with try/except
- **WHEN** analyzing `try: ... except ValueError: ...`
- **THEN** system creates Exception node with name="ValueError"
- **AND** creates CATCHES edge from Function to Exception
- **AND** stores line number of except clause
- **AND** marks exception as caught

#### Scenario: Track multiple exception types in except clause
- **WHEN** analyzing `except (ValueError, TypeError):`
- **THEN** system creates Exception nodes for both types
- **AND** creates CATCHES edges from Function to both Exception nodes
- **AND** stores same line number for both edges

#### Scenario: Track bare raise statements
- **WHEN** analyzing `except: raise` (re-raising caught exception)
- **THEN** system marks function as both catching and raising
- **AND** creates both CATCHES and RAISES edges
- **AND** enables propagation analysis

#### Scenario: Query exception propagation chain
- **WHEN** user queries what exceptions function `foo` can raise
- **THEN** system finds all RAISES edges from `foo`
- **AND** recursively finds RAISES from called functions
- **AND** excludes exceptions caught within the call chain
- **AND** returns list of uncaught exception types

#### Scenario: Find all code that needs to handle an exception
- **WHEN** user queries what catches `MyCustomException`
- **THEN** system finds Exception node with name="MyCustomException"
- **AND** traverses CATCHES edges to find handling functions
- **AND** returns list of (file, function, line) tuples

### Requirement: Module and Package Hierarchy
The system SHALL track Python package and module structure to enable module-level dependency analysis.

#### Scenario: Create module node for Python file
- **WHEN** analyzing file `src/utils/helpers.py`
- **THEN** system creates Module node with name="utils.helpers"
- **AND** creates MODULE_OF edge from File to Module
- **AND** marks is_package=false for regular module
- **AND** extracts module docstring if present

#### Scenario: Create module node for package
- **WHEN** analyzing `src/utils/__init__.py`
- **THEN** system creates Module node with name="utils"
- **AND** marks is_package=true
- **AND** creates MODULE_OF edge from File to Module
- **AND** extracts package docstring from __init__.py

#### Scenario: Track module hierarchy
- **WHEN** analyzing package structure `myapp/services/auth/`
- **THEN** system creates Module nodes for "myapp", "myapp.services", "myapp.services.auth"
- **AND** creates CONTAINS_MODULE edges forming hierarchy
- **AND** enables querying parent and child modules

#### Scenario: Resolve relative imports using module hierarchy
- **WHEN** analyzing `from ..utils import foo` in `myapp/services/auth/login.py`
- **THEN** system uses module hierarchy to resolve target module
- **AND** creates IMPORTS_FROM edge to correct module
- **AND** handles multiple levels of relative imports

#### Scenario: Query all files in a module
- **WHEN** user queries files in module "myapp.services"
- **THEN** system finds Module node with name="myapp.services"
- **AND** traverses MODULE_OF edges in reverse
- **AND** recursively includes submodules via CONTAINS_MODULE
- **AND** returns list of all Python files in module tree

#### Scenario: Module-level import analysis
- **WHEN** user queries what modules import "utils.helpers"
- **THEN** system finds Module node for "utils.helpers"
- **AND** finds all Import nodes referencing this module
- **AND** traverses to get importing files and their modules
- **AND** returns module-level import graph
