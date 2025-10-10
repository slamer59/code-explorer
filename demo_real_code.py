#!/usr/bin/env python3
"""
Demo script showing impact analysis on real code.

This demonstrates analyzing the actual export_dependencies_json.py file
to show how the impact analyzer would work in practice.
"""

from pathlib import Path

from src.code_explorer.graph import DependencyGraph
from src.code_explorer.impact import ImpactAnalyzer
from src.code_explorer.visualizer import MermaidVisualizer


def create_export_dependencies_graph() -> DependencyGraph:
    """Create graph based on export_dependencies_json.py structure."""
    graph = DependencyGraph()

    # Add functions from export_dependencies_json.py
    graph.add_function("extract_imports", "export_dependencies_json.py", 15, 58)
    graph.add_function("build_python_dependency_graph", "export_dependencies_json.py", 61, 160)
    graph.add_function("main", "export_dependencies_json.py", 163, 213)

    # Add function calls
    # main() calls build_python_dependency_graph()
    graph.add_call(
        "export_dependencies_json.py", "main",
        "export_dependencies_json.py", "build_python_dependency_graph",
        193
    )

    # build_python_dependency_graph() calls extract_imports()
    graph.add_call(
        "export_dependencies_json.py", "build_python_dependency_graph",
        "export_dependencies_json.py", "extract_imports",
        120
    )

    return graph


def main():
    """Run demo on real code."""
    print("\n" + "=" * 70)
    print("Demo: Analyzing Real Code (export_dependencies_json.py)")
    print("=" * 70)

    graph = create_export_dependencies_graph()
    analyzer = ImpactAnalyzer(graph)
    visualizer = MermaidVisualizer(graph)

    # Analyze impact of changing extract_imports()
    print("\nScenario: What if we change extract_imports() signature?")
    print("-" * 70)
    print("Question: Who will break if we change extract_imports()?")

    impact = analyzer.analyze_function_impact(
        file="export_dependencies_json.py",
        function="extract_imports",
        direction="upstream",
        max_depth=3
    )

    print(f"\nFound {len(impact)} functions that call extract_imports():\n")
    for result in impact:
        print(f"  → {result.function_name} at line {result.line_number} (depth: {result.depth})")

    # Generate visualization
    print("\nGenerating visualization...")
    mermaid = visualizer.generate_function_graph(
        focus_function="extract_imports",
        file="export_dependencies_json.py",
        max_depth=2,
        highlight_impact=True
    )

    output_path = Path("/tmp/demo-export-dependencies.md")
    visualizer.save_to_file(mermaid, output_path)
    print(f"✅ Saved diagram to {output_path}")

    print("\nDiagram preview:")
    print("-" * 70)
    print(mermaid)

    # Show full module graph
    print("\n\nGenerating full module dependency graph...")
    print("-" * 70)
    module_graph = visualizer.generate_module_graph(
        file="export_dependencies_json.py",
        include_imports=False
    )

    output_path = Path("/tmp/demo-full-module.md")
    visualizer.save_to_file(module_graph, output_path)
    print(f"✅ Saved full module graph to {output_path}")

    print("\n" + "=" * 70)
    print("Demo Complete!")
    print("=" * 70)
    print("\nKey Insights:")
    print("  • extract_imports() is called by build_python_dependency_graph()")
    print("  • If we change extract_imports(), we must check build_python_dependency_graph()")
    print("  • The visualizations show the call hierarchy clearly")
    print("\nNext steps:")
    print("  • View diagrams at https://mermaid.live")
    print("  • Integrate with real AST analysis for production use")


if __name__ == "__main__":
    main()
