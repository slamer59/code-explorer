#!/usr/bin/env python3
"""
Simple integration test for analyzer + graph.

Tests that the analyzer and graph modules work together.
"""

from pathlib import Path
from src.code_explorer.analyzer import CodeAnalyzer
from src.code_explorer.graph import DependencyGraph


def test_basic_integration():
    """Test basic analysis and graph construction."""
    print("=== Integration Test ===\n")

    # Initialize components
    analyzer = CodeAnalyzer()
    graph = DependencyGraph()

    # Analyze a simple test file
    test_file = Path("src/code_explorer/analyzer.py")
    print(f"1. Analyzing {test_file}...")
    result = analyzer.analyze_file(test_file)

    print(f"   ✓ Found {len(result.functions)} functions")
    print(f"   ✓ Found {len(result.function_calls)} function calls")
    print(f"   ✓ Found {len(result.variables)} variables")
    print(f"   ✓ Content hash: {result.content_hash[:16]}...")

    # Add functions to graph
    print("\n2. Building graph...")
    for func in result.functions:
        graph.add_function(
            name=func.name,
            file=func.file,
            start_line=func.start_line,
            end_line=func.end_line,
            is_public=func.is_public
        )

    # Add variables to graph
    for var in result.variables:
        graph.add_variable(
            name=var.name,
            file=var.file,
            definition_line=var.definition_line,
            scope=var.scope
        )

    # Add function calls
    for call in result.function_calls:
        # Find caller and callee functions
        caller_func = None
        callee_func = None

        for func in result.functions:
            if func.name == call.caller_function:
                caller_func = func
            if func.name == call.called_name:
                callee_func = func

        if caller_func and callee_func:
            graph.add_call(
                caller_file=caller_func.file,
                caller_function=caller_func.name,
                callee_file=callee_func.file,
                callee_function=callee_func.name,
                call_line=call.call_line
            )

    print(f"   ✓ Graph built successfully")

    # Test queries
    print("\n3. Testing graph queries...")

    # Get a sample function
    test_func = result.functions[0]
    print(f"\n   Testing function: {test_func.name}")

    # Get callers
    callers = graph.get_callers(test_func.file, test_func.name)
    print(f"   - Called by {len(callers)} functions")

    # Get callees
    callees = graph.get_callees(test_func.file, test_func.name)
    print(f"   - Calls {len(callees)} functions")
    if callees:
        print(f"     Examples: {[c[1] for c in callees[:3]]}")

    # Get statistics
    print("\n4. Graph statistics:")
    stats = graph.get_statistics()
    for key, value in stats.items():
        if key != 'most_called_functions':
            print(f"   - {key}: {value}")

    if stats['most_called_functions']:
        print(f"\n   Most called functions:")
        for func_info in stats['most_called_functions'][:5]:
            print(f"     - {func_info['name']}: {func_info['call_count']} calls")

    print("\n✓ All tests passed!")
    return True


if __name__ == "__main__":
    try:
        test_basic_integration()
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
