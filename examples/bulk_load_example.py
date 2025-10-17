#!/usr/bin/env python3
"""
Example: Bulk loading graph data from Parquet files.

This example demonstrates how to use the production-ready bulk loader
to load code-explorer graph data from Parquet files into KuzuDB.

Prerequisites:
- Parquet files must exist in the specified directory
- Run the export script first to generate Parquet files

Usage:
    python examples/bulk_load_example.py [parquet_dir] [db_path]

Example:
    python examples/bulk_load_example.py perfo/data/output .code-explorer/graph.db
"""

import sys
from pathlib import Path

from code_explorer.graph.bulk_loader import load_from_parquet_sync


def main():
    """Main entry point for bulk load example."""
    # Parse command line arguments
    if len(sys.argv) > 1:
        parquet_dir = Path(sys.argv[1])
    else:
        parquet_dir = Path("perfo/data/output")

    if len(sys.argv) > 2:
        db_path = Path(sys.argv[2])
    else:
        db_path = Path(".code-explorer/graph.db")

    print(f"Bulk Loading Example")
    print(f"===================")
    print(f"Parquet directory: {parquet_dir}")
    print(f"Database path: {db_path}")
    print()

    # Verify parquet directory exists
    if not parquet_dir.exists():
        print(f"ERROR: Parquet directory not found: {parquet_dir}")
        print()
        print("Please run the export script first to generate Parquet files.")
        print("Example:")
        print("  python perfo/export_graph.py")
        return 1

    nodes_dir = parquet_dir / "nodes"
    edges_dir = parquet_dir / "edges"

    if not nodes_dir.exists() or not edges_dir.exists():
        print(f"ERROR: Expected nodes/ and edges/ subdirectories in {parquet_dir}")
        return 1

    print(f"Loading data from Parquet files...")
    print()

    # Load data
    stats = load_from_parquet_sync(
        db_path=db_path,
        parquet_dir=parquet_dir,
        create_new=True,  # Remove existing database
    )

    # Display results
    print()
    print("=" * 70)
    print("BULK LOAD COMPLETE")
    print("=" * 70)
    print()

    print(f"Total Nodes:  {stats['total_nodes']:>8,}")
    print(f"Total Edges:  {stats['total_edges']:>8,}")
    print(f"Total Time:   {stats['total_time']:>8.2f}s")
    print()

    total_items = stats['total_nodes'] + stats['total_edges']
    throughput = total_items / stats['total_time'] if stats['total_time'] > 0 else 0
    print(f"Throughput:   {throughput:>8,.0f} items/sec")
    print()

    # Node loading details
    if stats['node_times']:
        print("Node Loading Details:")
        print("-" * 70)
        print(f"{'Table':<15} {'Rows':>10}  {'Time':>8}  {'Rate':>15}")
        print("-" * 70)

        for table_name, (elapsed, count) in stats['node_times'].items():
            rate = count / elapsed if elapsed > 0 else 0
            print(f"{table_name:<15} {count:>10,}  {elapsed:>7.3f}s  {rate:>14,.0f} rows/sec")

        print()

    # Edge loading details
    if stats['edge_times']:
        print("Edge Loading Details:")
        print("-" * 70)
        print(f"{'Relationship':<25} {'Edges':>10}  {'Time':>8}  {'Rate':>15}")
        print("-" * 70)

        for table_name, (elapsed, count) in stats['edge_times'].items():
            rate = count / elapsed if elapsed > 0 else 0
            print(f"{table_name:<25} {count:>10,}  {elapsed:>7.3f}s  {rate:>14,.0f} edges/sec")

        print()

    # Report errors if any
    if stats['errors']:
        print("ERRORS:")
        print("-" * 70)
        for error in stats['errors']:
            print(f"  - {error}")
        print()

    print(f"Database saved to: {db_path}")
    print()

    # Success/failure
    if stats['errors']:
        print("⚠ Completed with errors")
        return 1
    else:
        print("✓ Completed successfully")
        return 0


if __name__ == "__main__":
    sys.exit(main())
