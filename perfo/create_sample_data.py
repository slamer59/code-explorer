#!/usr/bin/env python3
"""
Create sample Parquet files for testing the bulk loader.

This script creates minimal sample data to verify the test_load.py script works correctly.
For real performance testing, use actual graph exports.
"""

from pathlib import Path
import pandas as pd
from datetime import datetime

OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def create_sample_nodes():
    """Create sample node Parquet files."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Sample files
    # KuzuDB TIMESTAMP expects datetime64[ns] in Parquet
    from pandas import Timestamp
    timestamp = Timestamp.now()
    files_df = pd.DataFrame({
        'path': ['/project/main.py', '/project/utils.py', '/project/models.py'],
        'language': ['python', 'python', 'python'],
        'last_modified': pd.to_datetime([timestamp, timestamp, timestamp]),
        'content_hash': ['hash1', 'hash2', 'hash3']
    })
    files_df.to_parquet(OUTPUT_DIR / 'files.parquet', index=False)

    # Sample functions
    functions_df = pd.DataFrame({
        'id': ['func1', 'func2', 'func3', 'func4'],
        'name': ['main', 'process_data', 'validate', 'save_result'],
        'file': ['/project/main.py', '/project/utils.py', '/project/utils.py', '/project/utils.py'],
        'start_line': [1, 10, 30, 50],
        'end_line': [8, 25, 45, 65],
        'is_public': [True, True, False, True],
        'source_code': ['def main():\n    pass'] * 4
    })
    functions_df.to_parquet(OUTPUT_DIR / 'functions.parquet', index=False)

    # Sample classes
    classes_df = pd.DataFrame({
        'id': ['class1', 'class2'],
        'name': ['DataModel', 'Validator'],
        'file': ['/project/models.py', '/project/utils.py'],
        'start_line': [1, 70],
        'end_line': [50, 100],
        'bases': ['BaseModel', 'object'],
        'is_public': [True, True],
        'source_code': ['class DataModel:\n    pass'] * 2
    })
    classes_df.to_parquet(OUTPUT_DIR / 'classes.parquet', index=False)

    # Sample variables
    variables_df = pd.DataFrame({
        'id': ['var1', 'var2', 'var3'],
        'name': ['config', 'logger', 'VERSION'],
        'file': ['/project/main.py', '/project/utils.py', '/project/__init__.py'],
        'definition_line': [5, 3, 1],
        'scope': ['module', 'module', 'module']
    })
    variables_df.to_parquet(OUTPUT_DIR / 'variables.parquet', index=False)

    # Sample imports
    imports_df = pd.DataFrame({
        'id': ['import1', 'import2', 'import3'],
        'imported_name': ['os', 'pathlib.Path', 'utils'],
        'import_type': ['module', 'member', 'module'],
        'alias': [None, 'Path', None],
        'line_number': [1, 2, 10],
        'is_relative': [False, False, True],
        'file': ['/project/main.py', '/project/main.py', '/project/models.py']
    })
    imports_df.to_parquet(OUTPUT_DIR / 'imports.parquet', index=False)

    # Sample decorators
    decorators_df = pd.DataFrame({
        'id': ['dec1', 'dec2'],
        'name': ['property', 'staticmethod'],
        'file': ['/project/models.py', '/project/utils.py'],
        'line_number': [10, 75],
        'arguments': ['', '']
    })
    decorators_df.to_parquet(OUTPUT_DIR / 'decorators.parquet', index=False)

    # Sample attributes
    attributes_df = pd.DataFrame({
        'id': ['attr1', 'attr2', 'attr3'],
        'name': ['name', 'value', 'status'],
        'class_name': ['DataModel', 'DataModel', 'Validator'],
        'file': ['/project/models.py', '/project/models.py', '/project/utils.py'],
        'definition_line': [5, 10, 72],
        'type_hint': ['str', 'int', 'bool'],
        'is_class_attribute': [False, False, False]
    })
    attributes_df.to_parquet(OUTPUT_DIR / 'attributes.parquet', index=False)

    # Sample exceptions
    exceptions_df = pd.DataFrame({
        'id': ['exc1', 'exc2'],
        'name': ['ValueError', 'ValidationError'],
        'file': ['/project/utils.py', '/project/utils.py'],
        'line_number': [35, 40]
    })
    exceptions_df.to_parquet(OUTPUT_DIR / 'exceptions.parquet', index=False)

    # Sample modules
    modules_df = pd.DataFrame({
        'id': ['mod1', 'mod2', 'mod3'],
        'name': ['project', 'project.utils', 'project.models'],
        'path': ['/project', '/project/utils.py', '/project/models.py'],
        'is_package': [True, False, False],
        'docstring': ['Main project package', 'Utility functions', 'Data models']
    })
    modules_df.to_parquet(OUTPUT_DIR / 'modules.parquet', index=False)

    print(f"✓ Created sample node files in {OUTPUT_DIR}/")


def create_sample_edges():
    """Create sample edge Parquet files."""
    # Sample CALLS edges
    calls_df = pd.DataFrame({
        'src': ['func1', 'func1', 'func2'],
        'dst': ['func2', 'func3', 'func4'],
        'call_line': [5, 6, 20]
    })
    calls_df.to_parquet(OUTPUT_DIR / 'calls.parquet', index=False)

    # Sample REFERENCES edges
    references_df = pd.DataFrame({
        'src': ['func1', 'func2'],
        'dst': ['var1', 'var2'],
        'line_number': [3, 15],
        'context': ['use', 'define']
    })
    references_df.to_parquet(OUTPUT_DIR / 'references.parquet', index=False)

    # Sample CONTAINS_FUNCTION edges
    contains_function_df = pd.DataFrame({
        'src': ['/project/main.py', '/project/utils.py', '/project/utils.py', '/project/utils.py'],
        'dst': ['func1', 'func2', 'func3', 'func4']
    })
    contains_function_df.to_parquet(OUTPUT_DIR / 'contains_function.parquet', index=False)

    # Sample CONTAINS_CLASS edges
    contains_class_df = pd.DataFrame({
        'src': ['/project/models.py', '/project/utils.py'],
        'dst': ['class1', 'class2']
    })
    contains_class_df.to_parquet(OUTPUT_DIR / 'contains_class.parquet', index=False)

    # Sample CONTAINS_VARIABLE edges
    contains_variable_df = pd.DataFrame({
        'src': ['/project/main.py', '/project/utils.py'],
        'dst': ['var1', 'var2']
    })
    contains_variable_df.to_parquet(OUTPUT_DIR / 'contains_variable.parquet', index=False)

    # Sample IMPORTS edges (file to file)
    imports_file_df = pd.DataFrame({
        'src': ['/project/main.py', '/project/models.py'],
        'dst': ['/project/utils.py', '/project/utils.py'],
        'line_number': [10, 5],
        'is_direct': [True, True]
    })
    imports_file_df.to_parquet(OUTPUT_DIR / 'imports_file.parquet', index=False)

    # Sample HAS_IMPORT edges
    has_import_df = pd.DataFrame({
        'src': ['/project/main.py', '/project/main.py', '/project/models.py'],
        'dst': ['import1', 'import2', 'import3']
    })
    has_import_df.to_parquet(OUTPUT_DIR / 'has_import.parquet', index=False)

    # Sample MODULE_OF edges
    module_of_df = pd.DataFrame({
        'src': ['/project/utils.py', '/project/models.py'],
        'dst': ['mod2', 'mod3']
    })
    module_of_df.to_parquet(OUTPUT_DIR / 'module_of.parquet', index=False)

    # Sample METHOD_OF edges
    method_of_df = pd.DataFrame({
        'src': ['func3'],
        'dst': ['class2']
    })
    method_of_df.to_parquet(OUTPUT_DIR / 'method_of.parquet', index=False)

    # Sample DECORATED_BY edges
    decorated_by_df = pd.DataFrame({
        'src': ['func3'],
        'dst': ['dec1'],
        'position': [0]
    })
    decorated_by_df.to_parquet(OUTPUT_DIR / 'decorated_by.parquet', index=False)

    # Sample ACCESSES edges
    accesses_df = pd.DataFrame({
        'src': ['func2', 'func4'],
        'dst': ['attr1', 'attr2'],
        'line_number': [15, 55],
        'access_type': ['read', 'write']
    })
    accesses_df.to_parquet(OUTPUT_DIR / 'accesses.parquet', index=False)

    # Sample HANDLES_EXCEPTION edges
    handles_exception_df = pd.DataFrame({
        'src': ['func2', 'func3'],
        'dst': ['exc1', 'exc2'],
        'line_number': [20, 38],
        'context': ['raises', 'catches']
    })
    handles_exception_df.to_parquet(OUTPUT_DIR / 'handles_exception.parquet', index=False)

    # Sample INHERITS edges
    inherits_df = pd.DataFrame({
        'src': [],
        'dst': []
    })
    inherits_df.to_parquet(OUTPUT_DIR / 'inherits.parquet', index=False)

    # Sample DEPENDS_ON edges
    depends_on_df = pd.DataFrame({
        'src': [],
        'dst': [],
        'dependency_type': [],
        'line_number': []
    })
    depends_on_df.to_parquet(OUTPUT_DIR / 'depends_on.parquet', index=False)

    # Sample HAS_ATTRIBUTE edges
    has_attribute_df = pd.DataFrame({
        'src': ['class1', 'class1', 'class2'],
        'dst': ['attr1', 'attr2', 'attr3']
    })
    has_attribute_df.to_parquet(OUTPUT_DIR / 'has_attribute.parquet', index=False)

    # Sample IMPORTS_FROM edges
    imports_from_df = pd.DataFrame({
        'src': ['import3'],
        'dst': ['func2']
    })
    imports_from_df.to_parquet(OUTPUT_DIR / 'imports_from.parquet', index=False)

    # Sample CONTAINS_MODULE edges
    contains_module_df = pd.DataFrame({
        'src': ['mod1', 'mod1'],
        'dst': ['mod2', 'mod3']
    })
    contains_module_df.to_parquet(OUTPUT_DIR / 'contains_module.parquet', index=False)

    print(f"✓ Created sample edge files in {OUTPUT_DIR}/")


def main():
    """Create all sample data files."""
    print("Creating sample Parquet files for testing...")
    print(f"Output directory: {OUTPUT_DIR}")
    print()

    create_sample_nodes()
    create_sample_edges()

    print()
    print("✓ Sample data creation complete!")
    print()
    print("You can now run: python perfo/test_load.py")


if __name__ == "__main__":
    main()
