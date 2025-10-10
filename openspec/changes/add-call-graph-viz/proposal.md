# Change Proposal: add-call-graph-viz

## Why

Static Mermaid diagrams are limited for exploring large dependency graphs. Developers need an interactive web UI to pan, zoom, expand/collapse nodes, and dynamically explore call relationships without regenerating diagrams.

## What Changes

- Add lightweight web server serving interactive call graph visualization
- Use D3.js or Cytoscape.js for interactive graph rendering
- Support expand-on-click to load function dependencies dynamically
- Provide filtering by file, depth, and function visibility
- Add search/highlight functionality in visualization
- **BREAKING**: None - additive feature alongside existing `visualize` command

## Impact

- **Affected specs**: New capability `visualization` (extends existing graph visualization)
- **Affected code**:
  - New file: `src/code_explorer/web_server.py` (FastAPI/Flask server)
  - New directory: `src/code_explorer/static/` (HTML/CSS/JS assets)
  - New file: `src/code_explorer/api.py` (REST API for graph queries)
  - Modified: `src/code_explorer/cli.py` (add `serve` command)
  - Modified: `pyproject.toml` (add dependencies: fastapi, uvicorn)
- **Performance**: Web server runs on-demand, no impact when not used
- **Port**: Default localhost:8080 (configurable via --port)
