# Usage Examples: Impact Analysis & Visualization

Quick reference guide for using the impact analysis and visualization modules.

## Quick Start

```python
from src.code_explorer.graph import DependencyGraph
from src.code_explorer.impact import ImpactAnalyzer
from src.code_explorer.visualizer import MermaidVisualizer
from pathlib import Path

# 1. Create and populate graph
graph = DependencyGraph()

# Add functions
graph.add_function("main", "app.py", start_line=10, end_line=20)
graph.add_function("process", "app.py", start_line=22, end_line=35)

# Add call relationships
graph.add_call("app.py", "main", "app.py", "process", call_line=15)

# 2. Analyze impact
analyzer = ImpactAnalyzer(graph)
results = analyzer.analyze_function_impact(
    file="app.py",
    function="process",
    direction="upstream"  # Find who calls this
)

# 3. Visualize
visualizer = MermaidVisualizer(graph)
diagram = visualizer.generate_function_graph(
    focus_function="process",
    file="app.py"
)
visualizer.save_to_file(diagram, Path("output.md"))
```

## Impact Analysis Examples

### Example 1: Find Who Calls a Function (Upstream)

**Use case:** "If I change this function's signature, what will break?"

```python
analyzer = ImpactAnalyzer(graph)

# Find all functions that call 'authenticate_user'
upstream = analyzer.analyze_function_impact(
    file="auth.py",
    function="authenticate_user",
    direction="upstream",
    max_depth=5
)

# Display results
for result in upstream:
    print(f"Caller: {result.function_name} in {result.file_path}")
    print(f"  Line: {result.line_number}, Depth: {result.depth}")
```

**Output:**
```
Caller: login_handler in routes.py
  Line: 42, Depth: 1
Caller: api_authenticate in api.py
  Line: 103, Depth: 1
Caller: handle_request in server.py
  Line: 78, Depth: 2
```

### Example 2: Find What a Function Calls (Downstream)

**Use case:** "What functions does this depend on? What might break this?"

```python
# Find all functions called by 'process_payment'
downstream = analyzer.analyze_function_impact(
    file="payments.py",
    function="process_payment",
    direction="downstream",
    max_depth=3
)

# Display as Rich table
from rich.console import Console
console = Console()
table = analyzer.format_as_table(downstream)
console.print(table)
```

### Example 3: Full Impact (Both Directions)

**Use case:** "What's the complete picture of dependencies for this function?"

```python
# Get both upstream and downstream
full_impact = analyzer.analyze_function_impact(
    file="core.py",
    function="save_data",
    direction="both",
    max_depth=2
)

# Separate by type
callers = [r for r in full_impact if r.impact_type == "caller"]
callees = [r for r in full_impact if r.impact_type == "callee"]

print(f"Functions that call save_data: {len(callers)}")
print(f"Functions that save_data calls: {len(callees)}")
```

### Example 4: Variable Impact Analysis

**Use case:** "Where is this variable used?"

```python
# Find all uses of a variable
usages = analyzer.analyze_variable_impact(
    file="config.py",
    var_name="DATABASE_URL",
    definition_line=10
)

print(f"Variable used in {len(usages)} location(s):")
for file, function, line in usages:
    print(f"  {function}() at {file}:{line}")
```

## Visualization Examples

### Example 1: Function-Focused Diagram

**Use case:** "Show me a visual of what this function depends on"

```python
visualizer = MermaidVisualizer(graph)

# Create diagram centered on one function
diagram = visualizer.generate_function_graph(
    focus_function="handle_request",
    file="server.py",
    max_depth=2,           # Show 2 levels up and down
    highlight_impact=True  # Color-code nodes
)

# Save to markdown file
visualizer.save_to_file(diagram, Path("diagrams/handle_request.md"))

# Or print directly
print(diagram)
```

**Result:** Mermaid diagram with:
- Yellow highlight on focus function
- Red for functions that call it (upstream)
- Blue for functions it calls (downstream)

### Example 2: Module Overview Diagram

**Use case:** "Show me all functions in this file and how they connect"

```python
# Generate module-level view
module_diagram = visualizer.generate_module_graph(
    file="utils.py",
    include_imports=True  # Show external calls too
)

visualizer.save_to_file(module_diagram, Path("diagrams/utils_module.md"))
```

**Result:** Shows all functions in `utils.py` with:
- Square boxes for internal functions
- Round boxes for external functions
- All call relationships

### Example 3: Internal-Only Module Diagram

**Use case:** "Show only internal function calls within this module"

```python
# Show only internal calls
internal_diagram = visualizer.generate_module_graph(
    file="models.py",
    include_imports=False  # Hide external calls
)

visualizer.save_to_file(internal_diagram, Path("diagrams/models_internal.md"))
```

## Advanced Usage

### Limiting Search Depth

Control how far to traverse the dependency graph:

```python
# Only direct callers (1 hop)
direct_callers = analyzer.analyze_function_impact(
    file="app.py",
    function="main",
    direction="upstream",
    max_depth=1
)

# Deep search (5 hops)
deep_impact = analyzer.analyze_function_impact(
    file="app.py",
    function="main",
    direction="both",
    max_depth=5
)
```

**Trade-off:** Higher depth = more complete picture but slower queries

### Filtering Results

```python
results = analyzer.analyze_function_impact(
    file="app.py",
    function="process",
    direction="upstream"
)

# Filter by file
local_callers = [r for r in results if r.file_path == "app.py"]

# Filter by depth
immediate_callers = [r for r in results if r.depth == 1]

# Sort by file then function
results.sort(key=lambda r: (r.file_path, r.function_name))
```

### Programmatic Diagram Generation

```python
# Generate multiple diagrams
functions_to_analyze = ["process", "validate", "save"]

for func in functions_to_analyze:
    diagram = visualizer.generate_function_graph(
        focus_function=func,
        file="app.py",
        max_depth=2
    )

    output_path = Path(f"diagrams/{func}_dependencies.md")
    visualizer.save_to_file(diagram, output_path)
    print(f"Generated {output_path}")
```

## Integration with Rich Console

### Pretty Print Results

```python
from rich.console import Console
from rich.table import Table

console = Console()

# Use built-in table formatter
results = analyzer.analyze_function_impact(...)
table = analyzer.format_as_table(results)
console.print(table)

# Or create custom table
custom_table = Table(title="Custom Impact Analysis")
custom_table.add_column("Function", style="cyan")
custom_table.add_column("Location", style="green")

for result in results:
    custom_table.add_row(
        result.function_name,
        f"{result.file_path}:{result.line_number}"
    )

console.print(custom_table)
```

### Progress Indicators

```python
from rich.progress import track

# Analyze multiple functions with progress bar
functions = ["func1", "func2", "func3", "func4"]

for func in track(functions, description="Analyzing..."):
    results = analyzer.analyze_function_impact(
        file="app.py",
        function=func,
        direction="both"
    )
    # Process results...
```

## Common Patterns

### Pattern 1: Pre-Change Impact Assessment

Before modifying a function, check what depends on it:

```python
def assess_change_impact(file: str, function: str):
    """Assess impact before changing a function."""
    analyzer = ImpactAnalyzer(graph)

    upstream = analyzer.analyze_function_impact(
        file=file, function=function, direction="upstream"
    )

    print(f"⚠️  Changing {function} will affect {len(upstream)} caller(s):")
    for result in upstream:
        print(f"  • {result.file_path}:{result.function_name} (line {result.line_number})")

    return len(upstream) > 0

# Usage
has_impact = assess_change_impact("auth.py", "login")
if has_impact:
    print("Warning: This change has wide impact!")
```

### Pattern 2: Dependency Audit

Find functions with too many dependencies:

```python
def find_highly_coupled_functions(threshold: int = 5):
    """Find functions with many dependencies."""
    all_functions = graph.get_all_functions_in_file("app.py")

    highly_coupled = []
    for func in all_functions:
        downstream = analyzer.analyze_function_impact(
            file=func.file,
            function=func.name,
            direction="downstream",
            max_depth=1
        )

        if len(downstream) > threshold:
            highly_coupled.append((func.name, len(downstream)))

    return sorted(highly_coupled, key=lambda x: x[1], reverse=True)

# Usage
coupled = find_highly_coupled_functions(threshold=5)
print("Functions with >5 dependencies:")
for name, count in coupled:
    print(f"  {name}: {count} dependencies")
```

### Pattern 3: Generate Documentation

Create documentation with diagrams:

```python
def generate_function_docs(file: str, function: str, output_dir: Path):
    """Generate documentation with impact analysis and diagram."""

    # Analyze impact
    impact = analyzer.analyze_function_impact(
        file=file, function=function, direction="both", max_depth=2
    )

    # Generate diagram
    diagram = visualizer.generate_function_graph(
        focus_function=function, file=file, max_depth=2
    )

    # Write documentation
    doc_path = output_dir / f"{function}.md"
    with open(doc_path, "w") as f:
        f.write(f"# Function: {function}\n\n")
        f.write(f"**File:** `{file}`\n\n")
        f.write(f"## Impact Analysis\n\n")

        callers = [r for r in impact if r.impact_type == "caller"]
        callees = [r for r in impact if r.impact_type == "callee"]

        f.write(f"- **Called by:** {len(callers)} function(s)\n")
        f.write(f"- **Calls:** {len(callees)} function(s)\n\n")

        f.write("## Dependency Diagram\n\n")
        f.write(f"```mermaid\n{diagram}\n```\n")

    print(f"Generated documentation: {doc_path}")

# Usage
generate_function_docs("app.py", "main", Path("docs/functions"))
```

## Troubleshooting

### No Results Found

```python
results = analyzer.analyze_function_impact(...)

if not results:
    # Check if function exists
    func = graph.get_function("app.py", "process")
    if func is None:
        print("Function not found in graph")
    else:
        print("Function exists but has no dependencies in this direction")
```

### Empty Diagrams

```python
diagram = visualizer.generate_module_graph("app.py")

if "No functions found" in diagram:
    # Check if file has functions
    functions = graph.get_all_functions_in_file("app.py")
    print(f"Found {len(functions)} functions in file")
```

## Viewing Generated Diagrams

Generated `.md` files can be viewed in:

1. **GitHub/GitLab:** Automatically renders Mermaid diagrams
2. **VS Code:** Install "Markdown Preview Mermaid Support" extension
3. **Online:** Paste code at https://mermaid.live
4. **CLI:** Use `mdcat` or `glow` for terminal rendering

```bash
# View in terminal with glow
glow output.md

# View in browser
open https://mermaid.live
# Then paste the mermaid code
```

## Performance Tips

1. **Limit depth for large graphs:**
   ```python
   # Fast: max_depth=2
   # Slow: max_depth=10
   ```

2. **Cache results for repeated queries:**
   ```python
   from functools import lru_cache

   @lru_cache(maxsize=100)
   def get_impact_cached(file: str, func: str):
       return analyzer.analyze_function_impact(file, func)
   ```

3. **Use direction wisely:**
   ```python
   # Faster: Single direction
   upstream_only = analyzer.analyze_function_impact(direction="upstream")

   # Slower: Both directions
   both = analyzer.analyze_function_impact(direction="both")
   ```

## Next Steps

- See `test_impact_visualizer.py` for complete working examples
- See `demo_real_code.py` for real-world usage
- See `IMPLEMENTATION_SUMMARY.md` for technical details
