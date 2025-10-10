#!/usr/bin/env python3
"""
Test script for impact analysis and visualization modules.

Creates a sample dependency graph and tests the impact analyzer
and Mermaid visualizer.
"""

from pathlib import Path

from src.code_explorer.graph import DependencyGraph
from src.code_explorer.impact import ImpactAnalyzer
from src.code_explorer.visualizer import MermaidVisualizer


def create_sample_graph() -> DependencyGraph:
    """Create a sample dependency graph for testing.

    Graph structure:
        main.py:
            - main() calls process_data() and validate_input()
            - process_data() calls transform() and save_result()
            - validate_input() calls check_type()

        utils.py:
            - transform() calls normalize()
            - save_result() (no calls)
            - normalize() (no calls)

        validators.py:
            - check_type() (no calls)
    """
    graph = DependencyGraph()

    # Add functions
    graph.add_function("main", "main.py", 10, 20)
    graph.add_function("process_data", "main.py", 22, 35)
    graph.add_function("validate_input", "main.py", 37, 42)

    graph.add_function("transform", "utils.py", 5, 15)
    graph.add_function("save_result", "utils.py", 17, 25)
    graph.add_function("normalize", "utils.py", 27, 35)

    graph.add_function("check_type", "validators.py", 8, 20)

    # Add function calls
    # main() calls process_data() and validate_input()
    graph.add_call("main.py", "main", "main.py", "process_data", 15)
    graph.add_call("main.py", "main", "main.py", "validate_input", 17)

    # process_data() calls transform() and save_result()
    graph.add_call("main.py", "process_data", "utils.py", "transform", 28)
    graph.add_call("main.py", "process_data", "utils.py", "save_result", 32)

    # validate_input() calls check_type()
    graph.add_call("main.py", "validate_input", "validators.py", "check_type", 40)

    # transform() calls normalize()
    graph.add_call("utils.py", "transform", "utils.py", "normalize", 12)

    # Add some variables for variable impact testing
    graph.add_variable("user_data", "main.py", 5, "module")
    graph.add_variable("result", "main.py", 30, "function:process_data")

    graph.add_variable_usage(
        "main.py", "process_data", "user_data", "main.py", 5, 25
    )
    graph.add_variable_usage(
        "utils.py", "save_result", "result", "main.py", 30, 20
    )

    return graph


def test_impact_analysis():
    """Test impact analysis functionality."""
    print("=" * 70)
    print("Testing Impact Analysis")
    print("=" * 70)

    graph = create_sample_graph()
    analyzer = ImpactAnalyzer(graph)

    # Test 1: Upstream impact (who calls process_data?)
    print("\nTest 1: Upstream impact of process_data()")
    print("-" * 70)
    upstream = analyzer.analyze_function_impact(
        file="main.py",
        function="process_data",
        direction="upstream",
        max_depth=3
    )
    print(f"Found {len(upstream)} upstream dependencies:")
    for result in upstream:
        print(f"  Depth {result.depth}: {result.file_path}:{result.function_name} "
              f"(line {result.line_number})")

    # Test 2: Downstream impact (what does process_data call?)
    print("\nTest 2: Downstream impact of process_data()")
    print("-" * 70)
    downstream = analyzer.analyze_function_impact(
        file="main.py",
        function="process_data",
        direction="downstream",
        max_depth=3
    )
    print(f"Found {len(downstream)} downstream dependencies:")
    for result in downstream:
        print(f"  Depth {result.depth}: {result.file_path}:{result.function_name} "
              f"(line {result.line_number})")

    # Test 3: Both directions
    print("\nTest 3: Full impact of transform()")
    print("-" * 70)
    full_impact = analyzer.analyze_function_impact(
        file="utils.py",
        function="transform",
        direction="both",
        max_depth=3
    )
    print(f"Found {len(full_impact)} total dependencies:")
    for result in full_impact:
        symbol = "←" if result.impact_type == "caller" else "→"
        print(f"  Depth {result.depth} {symbol}: {result.file_path}:{result.function_name} "
              f"(line {result.line_number})")

    # Test 4: Variable impact
    print("\nTest 4: Variable impact analysis")
    print("-" * 70)
    var_usage = analyzer.analyze_variable_impact(
        file="main.py",
        var_name="user_data",
        definition_line=5
    )
    print(f"Variable 'user_data' is used in {len(var_usage)} location(s):")
    for file, func, line in var_usage:
        print(f"  {file}:{func} (line {line})")

    # Test 5: Format as table (requires rich, so we'll just show we can call it)
    print("\nTest 5: Format results as Rich table")
    print("-" * 70)
    try:
        from rich.console import Console
        console = Console()
        table = analyzer.format_as_table(full_impact)
        console.print(table)
        print("✅ Table formatting works!")
    except ImportError:
        print("⚠️ Rich not installed, skipping table display")

    return graph, analyzer


def test_visualization(graph: DependencyGraph):
    """Test Mermaid visualization functionality."""
    print("\n" + "=" * 70)
    print("Testing Mermaid Visualization")
    print("=" * 70)

    visualizer = MermaidVisualizer(graph)

    # Test 1: Function-focused graph
    print("\nTest 1: Generate function-focused graph for process_data()")
    print("-" * 70)
    function_graph = visualizer.generate_function_graph(
        focus_function="process_data",
        file="main.py",
        max_depth=2,
        highlight_impact=True
    )
    print(function_graph)

    # Save to file
    output_path = Path("/tmp/test-function-graph.md")
    visualizer.save_to_file(function_graph, output_path)
    print(f"\n✅ Saved to {output_path}")

    # Test 2: Module-level graph
    print("\nTest 2: Generate module graph for main.py")
    print("-" * 70)
    module_graph = visualizer.generate_module_graph(
        file="main.py",
        include_imports=True
    )
    print(module_graph)

    # Save to file
    output_path = Path("/tmp/test-module-graph.md")
    visualizer.save_to_file(module_graph, output_path)
    print(f"\n✅ Saved to {output_path}")

    # Test 3: Module graph for utils.py
    print("\nTest 3: Generate module graph for utils.py")
    print("-" * 70)
    utils_graph = visualizer.generate_module_graph(
        file="utils.py",
        include_imports=False  # Only internal calls
    )
    print(utils_graph)

    # Save to file
    output_path = Path("/tmp/test-utils-graph.md")
    visualizer.save_to_file(utils_graph, output_path)
    print(f"\n✅ Saved to {output_path}")


def main():
    """Run all tests."""
    print("\n" + "#" * 70)
    print("# Code Explorer - Impact Analysis & Visualization Test Suite")
    print("#" * 70)

    # Test impact analysis
    graph, analyzer = test_impact_analysis()

    # Test visualization
    test_visualization(graph)

    # Summary
    print("\n" + "=" * 70)
    print("Test Summary")
    print("=" * 70)
    print("✅ Impact analysis module working")
    print("✅ Mermaid visualizer module working")
    print("✅ Sample diagrams saved to /tmp/test-*.md")
    print("\nCheck the files to verify Mermaid syntax is correct!")
    print("\nYou can view them on GitHub, VS Code, or at: https://mermaid.live")


if __name__ == "__main__":
    main()
