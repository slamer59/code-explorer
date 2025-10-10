# Dependency Analysis Specification - Storage Updates

## MODIFIED Requirements

### Requirement: Dependency Graph Storage
The system SHALL store dependency information in a KuzuDB property graph that persists to disk.

#### Scenario: Database initialization
- **WHEN** user runs first analysis command
- **THEN** system creates KuzuDB database at `.code-explorer/graph.db`
- **AND** creates all required node and edge tables
- **AND** database persists between runs

#### Scenario: Persistent storage
- **WHEN** user runs analysis on a codebase
- **THEN** system stores all nodes and edges in KuzuDB
- **AND** data persists to disk automatically
- **AND** subsequent queries read from disk without re-parsing

#### Scenario: Incremental analysis with persistence
- **WHEN** user runs analysis on previously analyzed codebase
- **THEN** system checks content hash for each file in database
- **AND** skips files with unchanged hashes
- **AND** only re-analyzes and updates changed files
- **AND** queries reflect the updated state

#### Scenario: Force refresh
- **WHEN** user runs `code-explorer analyze --refresh`
- **THEN** system clears all cached data
- **AND** performs full re-analysis of all files
- **AND** updates database with fresh data

## ADDED Requirements

### Requirement: Database Management
The system SHALL provide commands to manage the KuzuDB database.

#### Scenario: Specify database location
- **WHEN** user runs `code-explorer analyze --db-path /custom/path`
- **THEN** system uses specified path for database
- **AND** creates database if it doesn't exist
- **AND** defaults to `.code-explorer/graph.db` if not specified

#### Scenario: Check database status
- **WHEN** user runs `code-explorer stats`
- **THEN** system displays database location and size
- **AND** shows number of cached files
- **AND** shows last analysis timestamp

#### Scenario: Clear database
- **WHEN** user runs `code-explorer analyze --refresh`
- **THEN** system deletes all existing nodes and edges
- **AND** performs fresh analysis
- **AND** confirms action with user (unless --yes flag)
