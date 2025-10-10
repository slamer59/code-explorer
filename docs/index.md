# Code Explorer Documentation

Welcome to Code Explorer, a Python dependency analyzer with persistent graph storage.

This documentation follows the [Diátaxis framework](https://diataxis.fr/), organizing content by user needs:

## 📚 [Tutorials](tutorials/getting-started.md)
**Learning-oriented**: Step-by-step lessons to get you started.
- [Getting Started](tutorials/getting-started.md) - Your first dependency analysis
- [Understanding Impact Analysis](tutorials/impact-analysis.md) - Track how changes propagate

## 🎯 [How-To Guides](how-to/index.md)
**Problem-oriented**: Practical guides for specific tasks.
- [Analyze a codebase](how-to/analyze-codebase.md)
- [Find function dependencies](how-to/find-dependencies.md)
- [Visualize dependency graphs](how-to/visualize-graphs.md)
- [Use Kuzu Explorer](how-to/use-kuzu-explorer.md)
- [Optimize performance](how-to/optimize-performance.md)

## 📖 [Reference](reference/index.md)
**Information-oriented**: Technical descriptions of the system.
- [CLI Commands](reference/cli-commands.md)
- [Graph Schema](reference/graph-schema.md)
- [Python API](reference/python-api.md)
- [Configuration](reference/configuration.md)

## 💡 [Explanation](explanation/index.md)
**Understanding-oriented**: Clarification and discussion of key topics.
- [Architecture](explanation/architecture.md) - How Code Explorer works
- [Design Decisions](explanation/design-decisions.md) - Why we chose AST + Astroid + KuzuDB
- [Incremental Updates](explanation/incremental-updates.md) - Content hash-based change detection
- [Graph Algorithms](explanation/graph-algorithms.md) - Dependency traversal strategies

## Quick Links

- **Installation**: `pip install -e .`
- **Quick Start**: `code-explorer analyze ./src`
- **GitHub**: [Repository](https://github.com/your-org/code-explorer)
- **Issues**: [Bug Reports & Feature Requests](https://github.com/your-org/code-explorer/issues)
