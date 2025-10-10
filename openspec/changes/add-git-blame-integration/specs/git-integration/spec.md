# Git Integration Specification

## ADDED Requirements

### Requirement: Git Blame Collection
The system SHALL extract Git blame information during code analysis.

#### Scenario: Analyze with Git blame
- **WHEN** user runs `code-explorer analyze ./src` in Git repository
- **THEN** system collects Git blame for each function
- **AND** stores author, last commit date, and commit hash
- **AND** shows progress indicator for blame collection

#### Scenario: Non-Git repository
- **WHEN** user runs analysis in non-Git directory
- **THEN** system skips Git blame collection
- **AND** continues with regular analysis
- **AND** shows warning: "Not a Git repository, skipping ownership data"

#### Scenario: Skip Git blame
- **WHEN** user runs `code-explorer analyze ./src --skip-git`
- **THEN** system skips blame collection even in Git repo
- **AND** analysis completes faster

### Requirement: Author Determination
The system SHALL determine function ownership based on Git blame.

#### Scenario: Single author function
- **WHEN** all lines in function were written by same author
- **THEN** that author is marked as owner
- **AND** stored in Function node

#### Scenario: Multi-author function
- **WHEN** function has contributions from multiple authors
- **THEN** author with most lines is marked as primary owner
- **AND** last modifier is also tracked separately
- **AND** both are stored in database

#### Scenario: Recently modified function
- **WHEN** function was edited by different author than original
- **THEN** original author stored in `author` field
- **AND** recent modifier stored in `last_modified_by` field
- **AND** commit date and hash stored

### Requirement: Ownership Queries
The system SHALL provide queries to find code ownership.

#### Scenario: Find functions by owner
- **WHEN** user runs `code-explorer owners --author alice@example.com`
- **THEN** system lists all functions authored by Alice
- **AND** shows file path, function name, line count, last modified date
- **AND** groups by file for readability

#### Scenario: Find owners of file
- **WHEN** user runs `code-explorer owners --file src/module.py`
- **THEN** system lists all authors who contributed to file
- **AND** shows number of functions per author
- **AND** includes last modification date

#### Scenario: Ownership distribution
- **WHEN** user runs `code-explorer owners --stats`
- **THEN** system shows:
  - Total authors count
  - Functions per author (top 20)
  - Most active committers
  - Ownership concentration metrics

### Requirement: Team-Based Queries
The system SHALL support team-level ownership queries.

#### Scenario: Filter by email domain
- **WHEN** user runs `code-explorer owners --team example.com`
- **THEN** system shows all functions owned by authors with @example.com
- **AND** aggregates by individual authors within team

#### Scenario: Multiple teams
- **WHEN** user runs `code-explorer owners --team acme.com --team partner.org`
- **THEN** system shows functions from both teams
- **AND** indicates which team owns each function

### Requirement: Impact Analysis with Ownership
The system SHALL integrate ownership into impact analysis.

#### Scenario: Impact filtered by owner
- **WHEN** user runs `code-explorer impact src/api.py:endpoint --owner alice`
- **THEN** system shows only impacted functions owned by Alice
- **AND** helps identify if Alice's other code is affected

#### Scenario: Cross-team impact
- **WHEN** user runs `code-explorer impact src/core.py:critical_func --group-by-owner`
- **THEN** system groups impact by author
- **AND** shows which team members need to be notified
- **AND** includes contact emails

### Requirement: Visualization with Ownership
The system SHALL display ownership in visualizations.

#### Scenario: Color-coded ownership
- **WHEN** user generates Mermaid diagram
- **THEN** nodes are color-coded by author
- **AND** legend shows author-to-color mapping

#### Scenario: Owner tooltips
- **WHEN** user views node in visualization
- **THEN** tooltip shows owner name and email
- **AND** includes last modification date

### Requirement: Statistics with Ownership
The system SHALL include ownership in statistics.

#### Scenario: Ownership in stats
- **WHEN** user runs `code-explorer stats`
- **THEN** output includes ownership section:
  - Total unique authors
  - Functions per author (top 10)
  - Most modified functions (by author churn)
- **AND** identifies potential ownership gaps (no clear owner)

#### Scenario: Stale code detection
- **WHEN** user runs `code-explorer owners --stale 365`
- **THEN** system finds functions not modified in 365 days
- **AND** shows original author and last commit date
- **AND** helps identify orphaned code

### Requirement: Author Privacy
The system SHALL handle author information responsibly.

#### Scenario: Anonymize emails
- **WHEN** user runs `code-explorer analyze --anonymize-authors`
- **THEN** system hashes email addresses before storage
- **AND** uses hashed IDs for queries
- **AND** still allows ownership tracking without exposing emails

#### Scenario: No author storage
- **WHEN** user runs `code-explorer analyze --skip-git`
- **THEN** no author information is collected or stored
- **AND** ownership queries return empty results

### Requirement: Performance
The system SHALL collect Git blame efficiently.

#### Scenario: Parallel blame collection
- **WHEN** analyzing 100 files with Git blame
- **THEN** blame runs in parallel across files
- **AND** completes in < 10 seconds
- **AND** shows progress indicator

#### Scenario: Cached blame
- **WHEN** re-analyzing unchanged files
- **THEN** system reuses existing blame data
- **AND** skips git blame execution
- **AND** analysis remains fast

### Requirement: Error Handling
The system SHALL handle Git errors gracefully.

#### Scenario: Corrupted Git repository
- **WHEN** Git commands fail
- **THEN** system logs warning
- **AND** continues without blame data
- **AND** analysis completes successfully

#### Scenario: Large repository
- **WHEN** Git blame takes > 30 seconds
- **THEN** system shows progress indicator
- **AND** allows user to cancel with Ctrl+C
- **AND** continues analysis without blame if cancelled
