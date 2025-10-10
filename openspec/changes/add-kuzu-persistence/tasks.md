# Implementation Tasks

## 1. KuzuDB Schema Implementation
- [x] 1.1 Create KuzuDB database connection with proper path handling
- [x] 1.2 Define File node table schema
- [x] 1.3 Define Function node table schema
- [x] 1.4 Define Variable node table schema
- [x] 1.5 Define CONTAINS edge table
- [x] 1.6 Define CALLS edge table
- [x] 1.7 Define DEFINES edge table
- [x] 1.8 Define USES edge table
- [x] 1.9 Define IMPORTS edge table

## 2. Update DependencyGraph Class
- [x] 2.1 Add KuzuDB connection initialization
- [x] 2.2 Implement add_file() with KuzuDB insert
- [x] 2.3 Implement add_function() with KuzuDB insert
- [x] 2.4 Implement add_variable() with KuzuDB insert
- [x] 2.5 Implement add_call() with KuzuDB edge insert
- [x] 2.6 Implement add_variable_usage() with KuzuDB edge insert
- [x] 2.7 Update get_callers() to query KuzuDB
- [x] 2.8 Update get_callees() to query KuzuDB
- [x] 2.9 Update get_variable_usage() to query KuzuDB
- [x] 2.10 Implement file_exists() with content hash check

## 3. Incremental Update Logic
- [x] 3.1 Check file content hash before analysis
- [x] 3.2 Delete old nodes/edges for changed files
- [x] 3.3 Re-analyze only changed files
- [x] 3.4 Update file metadata (last_modified, content_hash)

## 4. CLI Updates
- [x] 4.1 Add --db-path option to specify database location
- [x] 4.2 Add --refresh flag to force full re-analysis
- [x] 4.3 Update analyze command to use persistent graph
- [x] 4.4 Show statistics about cached vs new files

## 5. Testing
- [x] 5.1 Test database creation and schema
- [x] 5.2 Test insert operations
- [x] 5.3 Test query operations
- [x] 5.4 Test incremental updates
- [x] 5.5 Test with multiple runs (persistence)
- [x] 5.6 Test with large codebase (performance)

## 6. Documentation
- [ ] 6.1 Document database location and structure
- [ ] 6.2 Add usage examples for incremental updates
- [ ] 6.3 Document how to reset/clear database
