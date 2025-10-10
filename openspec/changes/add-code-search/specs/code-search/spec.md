# Code Search Specification

## ADDED Requirements

### Requirement: Semantic Search
The system SHALL provide semantic code search using natural language queries.

#### Scenario: Find functions by intent
- **WHEN** user runs `code-explorer search "validate user input"`
- **THEN** system returns functions that perform input validation
- **AND** results are ranked by semantic similarity
- **AND** each result shows file path, function name, and relevance score

#### Scenario: Find authentication logic
- **WHEN** user runs `code-explorer search "authentication logic"`
- **THEN** system returns functions related to authentication
- **AND** includes login, token validation, session management functions
- **AND** results include code snippets for context

#### Scenario: Query with filters
- **WHEN** user runs `code-explorer search "parse JSON" --top-k 5`
- **THEN** system returns top 5 most relevant functions
- **AND** results are limited to specified count

### Requirement: Embedding Index Management
The system SHALL maintain a vector embedding index for efficient search.

#### Scenario: Index creation
- **WHEN** user runs first search command
- **THEN** system builds embedding index from all functions
- **AND** stores index at `.code-explorer/search_index.faiss`
- **AND** shows progress during indexing

#### Scenario: Incremental index updates
- **WHEN** user analyzes code and then searches
- **THEN** system detects if index is stale
- **AND** automatically rebuilds index if database has changed
- **AND** notifies user about index refresh

#### Scenario: Manual index rebuild
- **WHEN** user runs `code-explorer search "query" --rebuild-index`
- **THEN** system forces full index rebuild
- **AND** uses updated function data from database

### Requirement: Query Processing
The system SHALL convert natural language queries into vector embeddings for similarity search.

#### Scenario: Query embedding generation
- **WHEN** user provides a search query
- **THEN** system generates query embedding using same model as function embeddings
- **AND** performs cosine similarity search against index
- **AND** returns top-k most similar functions

#### Scenario: Empty or invalid queries
- **WHEN** user provides empty string or very short query
- **THEN** system shows error message
- **AND** suggests minimum query length (3+ words)

### Requirement: Search Results
The system SHALL display search results with context and relevance information.

#### Scenario: Result formatting
- **WHEN** search returns results
- **THEN** each result shows:
  - Function name and file path
  - Line numbers (start-end)
  - Relevance score (0.0-1.0)
  - First 3 lines of function code as snippet
- **AND** results are sorted by relevance score descending

#### Scenario: No results found
- **WHEN** search finds no relevant functions
- **THEN** system displays "No results found" message
- **AND** suggests trying different keywords or rebuilding index

### Requirement: Embedding Model
The system SHALL use lightweight, pre-trained sentence transformer models for embeddings.

#### Scenario: Model initialization
- **WHEN** system first generates embeddings
- **THEN** downloads `all-MiniLM-L6-v2` model (22MB)
- **AND** caches model locally for reuse
- **AND** shows download progress

#### Scenario: Offline usage
- **WHEN** model is already cached
- **THEN** system works without internet connection
- **AND** uses cached model from `~/.cache/huggingface`

### Requirement: Performance
The system SHALL provide fast search results even for large codebases.

#### Scenario: Search performance
- **WHEN** searching index with 10,000 functions
- **THEN** query completes in < 1 second
- **AND** memory usage remains < 500MB

#### Scenario: Index building performance
- **WHEN** building index for 1,000 functions
- **THEN** indexing completes in < 5 seconds
- **AND** shows progress bar during processing
