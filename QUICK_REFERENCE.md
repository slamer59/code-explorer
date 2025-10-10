# Quick Reference: Impact Analysis & Visualization

## Import Statements

```python
from src.code_explorer.graph import DependencyGraph
from src.code_explorer.impact import ImpactAnalyzer, ImpactResult
from src.code_explorer.visualizer import MermaidVisualizer
from pathlib import Path
```

## Graph Setup

```python
# Create graph
graph = DependencyGraph()

# Add function
graph.add_function(
    name="process_data",
    file="app.py",
    start_line=10,
    end_line=20
)

# Add function call
graph.add_call(
    caller_file="app.py",
    caller_function="main",
    callee_file="app.py",
    callee_function="process_data",
    call_line=15
)

# Add variable
graph.add_variable(
    name="config",
    file="app.py",
    definition_line=5,
    scope="module"
)
```

## Impact Analysis

```python
analyzer = ImpactAnalyzer(graph)

# Find callers (upstream)
upstream = analyzer.analyze_function_impact(
    file="app.py",
    function="process_data",
    direction="upstream",
    max_depth=5
)

# Find callees (downstream)
downstream = analyzer.analyze_function_impact(
    file="app.py",
    function="process_data",
    direction="downstream",
    max_depth=5
)

# Find both
both = analyzer.analyze_function_impact(
    file="app.py",
    function="process_data",
    direction="both",
    max_depth=5
)

# Variable usage
usages = analyzer.analyze_variable_impact(
    file="app.py",
    var_name="config",
    definition_line=5
)
```

## Display Results

```python
# Print simple
for result in upstream:
    print(f"{result.function_name} at {result.file_path}:{result.line_number}")

# Rich table
from rich.console import Console
console = Console()
table = analyzer.format_as_table(upstream)
console.print(table)
```

## Visualization

```python
visualizer = MermaidVisualizer(graph)

# Function-focused diagram
diagram = visualizer.generate_function_graph(
    focus_function="process_data",
    file="app.py",
    max_depth=2,
    highlight_impact=True
)

# Module diagram
module = visualizer.generate_module_graph(
    file="app.py",
    include_imports=True
)

# Save to file
visualizer.save_to_file(diagram, Path("output.md"))

# Or print
print(diagram)
```

## Common Patterns

### Pattern 1: Check Before Changing
```python
def check_impact(file: str, func: str):
    results = analyzer.analyze_function_impact(
        file=file, function=func, direction="upstream"
    )
    if results:
        print(f"⚠️  {len(results)} functions will be affected!")
        return False
    return True
```

### Pattern 2: Find Highly Coupled Functions
```python
def find_coupled(max_deps: int = 5):
    for func in graph.get_all_functions_in_file("app.py"):
        deps = analyzer.analyze_function_impact(
            file=func.file,
            function=func.name,
            direction="downstream",
            max_depth=1
        )
        if len(deps) > max_deps:
            print(f"{func.name}: {len(deps)} dependencies")
```

### Pattern 3: Generate Docs
```python
def gen_docs(file: str, func: str):
    impact = analyzer.analyze_function_impact(file, func, "both")
    diagram = visualizer.generate_function_graph(func, file)

    with open(f"docs/{func}.md", "w") as f:
        f.write(f"# {func}\n\n")
        f.write(f"Dependencies: {len(impact)}\n\n")
        f.write(f"```mermaid\n{diagram}\n```\n")
```

## ImpactResult Fields

```python
result = ImpactResult(
    function_name="process",      # Name of impacted function
    file_path="app.py",           # File where function is defined
    line_number=15,               # Line where call/usage occurs
    impact_type="caller",         # "caller" or "callee"
    depth=1                       # Hops from origin (1=direct)
)
```

## Graph Query Methods

```python
# Get function
func = graph.get_function("app.py", "process_data")

# Get all functions in file
funcs = graph.get_all_functions_in_file("app.py")

# Get who calls this function
callers = graph.get_callers("app.py", "process_data")
# Returns: [(file, function, line), ...]

# Get what this function calls
callees = graph.get_callees("app.py", "process_data")
# Returns: [(file, function, line), ...]

# Get variable usage
usages = graph.get_variable_usage("app.py", "config", 5)
# Returns: [(file, function, line), ...]
```

## Direction Options

```python
direction="upstream"    # Who calls this? (callers)
direction="downstream"  # What does this call? (callees)
direction="both"        # Both upstream and downstream
```

## Mermaid Colors

- **Focus function:** Yellow (`#ff9`)
- **Callers (upstream):** Red (`#f96`)
- **Callees (downstream):** Blue (`#9cf`)
- **Internal functions:** Blue (`#9cf`)
- **External functions:** Gray (`#ccc`)

## View Diagrams

```bash
# GitHub/GitLab - automatic rendering
git add diagram.md && git commit && git push

# VS Code - install extension
code --install-extension bierner.markdown-mermaid

# Online viewer
open https://mermaid.live

# Terminal (with glow)
glow diagram.md
```

## Testing

```bash
# Run tests
python test_impact_visualizer.py

# Run demo
python demo_real_code.py

# Check outputs
ls -lh /tmp/test-*.md
```

## Performance Tips

1. **Limit depth:** `max_depth=2` is faster than `max_depth=10`
2. **Single direction:** `upstream` is faster than `both`
3. **Cache results:** Use `@lru_cache` for repeated queries
4. **Filter after:** Query broadly, filter in Python if needed

## Error Handling

```python
# Check if function exists
func = graph.get_function("app.py", "missing")
if func is None:
    print("Function not found")

# Validate direction
try:
    results = analyzer.analyze_function_impact(
        file="app.py",
        function="process",
        direction="invalid"  # Will raise ValueError
    )
except ValueError as e:
    print(f"Error: {e}")

# Handle empty results
results = analyzer.analyze_function_impact(...)
if not results:
    print("No dependencies found")
```

## File Locations

- **Impact module:** `/home/thomas/Developpments/playground/code-explorer/src/code_explorer/impact.py`
- **Visualizer:** `/home/thomas/Developpments/playground/code-explorer/src/code_explorer/visualizer.py`
- **Graph:** `/home/thomas/Developpments/playground/code-explorer/src/code_explorer/graph.py`
- **Tests:** `/home/thomas/Developpments/playground/code-explorer/test_impact_visualizer.py`
- **Demo:** `/home/thomas/Developpments/playground/code-explorer/demo_real_code.py`

## More Info

- **Full guide:** `USAGE_EXAMPLES.md`
- **Implementation details:** `IMPLEMENTATION_SUMMARY.md`
- **Design doc:** `openspec/changes/add-dependency-analysis/design.md`
