# Change Proposal: add-git-blame-integration

## Why

When analyzing dependencies, developers need to know WHO owns the code to contact for questions, reviews, or bug reports. Git blame data provides ownership context that's currently missing from dependency analysis.

## What Changes

- Extract Git blame information (author, last_modified, commit) for each function
- Store ownership data in graph database alongside functions
- Add ownership queries: "who owns this function?", "what does Alice own?"
- Display author info in CLI output and visualizations
- Enable filtering by author or team
- **BREAKING**: None - additive feature with optional Git integration

## Impact

- **Affected specs**: New capability `git-integration`
- **Affected code**:
  - New file: `src/code_explorer/git_blame.py` (Git blame extraction)
  - Modified: `src/code_explorer/analyzer.py` (collect blame during analysis)
  - Modified: `src/code_explorer/graph.py` (add author, last_commit fields)
  - Modified: `src/code_explorer/cli.py` (add `owners` command)
  - Modified: `pyproject.toml` (add dependency: GitPython)
- **Database changes**: Add fields to Function node (author, last_modified_by, last_commit_hash, last_commit_date)
- **Performance**: Git blame adds ~1-2 seconds per 100 functions (runs in parallel)
- **Requirements**: Git repository (gracefully degrades if not in Git repo)
