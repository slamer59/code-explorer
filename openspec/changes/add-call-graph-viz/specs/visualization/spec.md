# Interactive Visualization Specification

## ADDED Requirements

### Requirement: Web Server
The system SHALL provide a web server for interactive graph visualization.

#### Scenario: Start server
- **WHEN** user runs `code-explorer serve`
- **THEN** system starts FastAPI server on localhost:8080
- **AND** opens browser to visualization UI automatically
- **AND** displays "Server running at http://localhost:8080" message

#### Scenario: Custom port
- **WHEN** user runs `code-explorer serve --port 3000`
- **THEN** system starts server on port 3000
- **AND** displays correct URL with custom port

#### Scenario: Read-only mode
- **WHEN** user runs `code-explorer serve --read-only`
- **THEN** system opens database in read-only mode
- **AND** allows multiple concurrent viewers safely

### Requirement: Interactive Graph Rendering
The system SHALL display call graphs with interactive pan, zoom, and expand/collapse.

#### Scenario: Initial graph load
- **WHEN** user opens visualization UI
- **THEN** system displays overview of all modules
- **AND** shows node count and edge count statistics
- **AND** provides zoom controls and minimap

#### Scenario: Expand node dependencies
- **WHEN** user double-clicks a function node
- **THEN** system loads and displays its callers and callees
- **AND** animates new nodes appearing
- **AND** maintains focus on clicked node

#### Scenario: Collapse node
- **WHEN** user double-clicks an expanded node
- **THEN** system hides its dependency nodes
- **AND** animates nodes disappearing
- **AND** restores previous view state

#### Scenario: Pan and zoom
- **WHEN** user drags on empty space
- **THEN** graph pans in drag direction
- **WHEN** user scrolls mouse wheel
- **THEN** graph zooms in/out centered on cursor

### Requirement: Node Details
The system SHALL display function details on node interaction.

#### Scenario: View function details
- **WHEN** user clicks a function node
- **THEN** system displays side panel with:
  - Function name and signature
  - File path and line numbers
  - Source code snippet
  - Caller count and callee count
  - Public/private visibility
- **AND** highlights node in graph

#### Scenario: View source code
- **WHEN** user clicks "View Source" in details panel
- **THEN** system displays full function source code
- **AND** provides syntax highlighting
- **AND** shows line numbers

### Requirement: Search and Filter
The system SHALL provide search and filtering for large graphs.

#### Scenario: Search by name
- **WHEN** user types function name in search box
- **THEN** system shows autocomplete suggestions
- **AND** highlights matching nodes in graph
- **WHEN** user selects suggestion
- **THEN** graph centers on selected node

#### Scenario: Filter by file
- **WHEN** user selects files from filter dropdown
- **THEN** system shows only functions from selected files
- **AND** updates edge visibility accordingly

#### Scenario: Filter by visibility
- **WHEN** user toggles "Show private functions" off
- **THEN** system hides functions starting with underscore
- **AND** adjusts layout to fill space

### Requirement: Path Highlighting
The system SHALL highlight dependency paths between functions.

#### Scenario: Show path between nodes
- **WHEN** user Ctrl+clicks two nodes
- **THEN** system highlights shortest path between them
- **AND** dims other nodes and edges
- **AND** displays path length and intermediate functions

#### Scenario: Clear path highlight
- **WHEN** user clicks "Clear" or clicks empty space
- **THEN** system removes path highlighting
- **AND** restores normal node visibility

### Requirement: Layout Algorithms
The system SHALL provide multiple layout options for graph visualization.

#### Scenario: Hierarchical layout
- **WHEN** user selects "Hierarchical" layout
- **THEN** system arranges nodes in tree structure
- **AND** places callers above callees
- **AND** minimizes edge crossings

#### Scenario: Force-directed layout
- **WHEN** user selects "Force-directed" layout
- **THEN** system uses physics simulation for layout
- **AND** keeps connected nodes closer together
- **AND** animates layout convergence

#### Scenario: Circular layout
- **WHEN** user selects "Circular" layout
- **THEN** system arranges nodes in circle
- **AND** groups nodes by module

### Requirement: Export and Sharing
The system SHALL support exporting visualizations.

#### Scenario: Export as image
- **WHEN** user clicks "Export PNG"
- **THEN** system generates high-resolution PNG
- **AND** downloads image with timestamp filename

#### Scenario: Export as SVG
- **WHEN** user clicks "Export SVG"
- **THEN** system generates vector SVG file
- **AND** preserves graph structure and styling

#### Scenario: Share view state
- **WHEN** user clicks "Copy Link"
- **THEN** system generates URL with current view state
- **AND** copies URL to clipboard
- **WHEN** another user opens URL
- **THEN** they see same nodes, layout, and zoom level

### Requirement: Performance
The system SHALL handle large graphs efficiently.

#### Scenario: Large graph rendering
- **WHEN** visualizing graph with 1000+ nodes
- **THEN** UI remains responsive (60 FPS)
- **AND** uses progressive loading for distant nodes

#### Scenario: Fast API responses
- **WHEN** expanding node or searching
- **THEN** API responds in < 200ms
- **AND** UI shows loading indicator for > 100ms requests

### Requirement: Keyboard Shortcuts
The system SHALL provide keyboard shortcuts for common actions.

#### Scenario: Navigation shortcuts
- **WHEN** user presses `F` key
- **THEN** activates search box
- **WHEN** user presses `+` or `-`
- **THEN** zooms in or out
- **WHEN** user presses `R`
- **THEN** resets zoom to fit all nodes
- **WHEN** user presses `Esc`
- **THEN** clears selection and highlights
