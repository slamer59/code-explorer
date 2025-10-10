# Implementation Tasks

## 1. Git Blame Infrastructure
- [ ] 1.1 Add GitPython to pyproject.toml
- [ ] 1.2 Create git_blame.py with Git repository detection
- [ ] 1.3 Implement blame extraction for specific file and line range
- [ ] 1.4 Add caching to avoid redundant git blame calls
- [ ] 1.5 Handle repositories without Git (graceful degradation)

## 2. Database Schema Updates
- [ ] 2.1 Add author field to Function node (STRING)
- [ ] 2.2 Add last_modified_by field to Function node (STRING, may differ from author)
- [ ] 2.3 Add last_commit_hash field to Function node (STRING)
- [ ] 2.4 Add last_commit_date field to Function node (TIMESTAMP)
- [ ] 2.5 Create migration for existing databases (add fields, default to NULL)

## 3. Analyzer Integration
- [ ] 3.1 Modify analyzer.py to call git_blame during analysis
- [ ] 3.2 Extract blame for each function's line range
- [ ] 3.3 Determine primary author (most lines in function)
- [ ] 3.4 Handle functions with multiple authors
- [ ] 3.5 Add --skip-git flag to disable blame collection

## 4. Graph Storage
- [ ] 4.1 Update add_function() to accept author parameters
- [ ] 4.2 Store Git blame data in Function nodes
- [ ] 4.3 Create index on author field for fast queries
- [ ] 4.4 Handle NULL values for non-Git repositories

## 5. CLI Commands
- [ ] 5.1 Add `owners` command to list code ownership
- [ ] 5.2 Implement `code-explorer owners --author alice@example.com`
- [ ] 5.3 Add `code-explorer impact --owner alice` to filter impact by owner
- [ ] 5.4 Display author in `code-explorer stats` output
- [ ] 5.5 Add `--group-by-owner` flag to stats command

## 6. Ownership Queries
- [ ] 6.1 Implement query: functions owned by specific author
- [ ] 6.2 Implement query: authors who touched specific file
- [ ] 6.3 Implement query: ownership distribution per module
- [ ] 6.4 Add team-based queries (group emails by domain)

## 7. Display Enhancements
- [ ] 7.1 Show author in impact analysis output
- [ ] 7.2 Show author in visualizations (node labels or tooltip)
- [ ] 7.3 Color-code nodes by author in Mermaid diagrams
- [ ] 7.4 Add author column to search results

## 8. Performance Optimization
- [ ] 8.1 Parallelize git blame across files
- [ ] 8.2 Cache blame results during single analysis run
- [ ] 8.3 Skip blame for unchanged files (use existing cached data)
- [ ] 8.4 Add progress indicator for blame collection

## 9. Testing
- [ ] 9.1 Test Git blame extraction with various repo types
- [ ] 9.2 Test behavior in non-Git directories
- [ ] 9.3 Test multi-author functions
- [ ] 9.4 Test ownership queries with various filters
- [ ] 9.5 Test performance with large repositories (1000+ files)

## 10. Documentation
- [ ] 10.1 Add owners command to CLI reference
- [ ] 10.2 Add how-to: "Find Code Owners"
- [ ] 10.3 Document Git requirements and --skip-git flag
- [ ] 10.4 Add examples of ownership-based impact analysis
- [ ] 10.5 Document privacy considerations (author emails)
