"""Extracts a def/class body's docstring (first line) from tree-sitter.

Runs during the same tree-sitter walk functions.py/classes.py already do at
extraction (indexing) time -- reuses the body node already in hand rather
than re-parsing anything, so this adds no second parse pass. See
docs/explanation/source-of-truth-and-search-representations.md for why this
matters (search_text is derived at indexing time, not later at ingest).

Mirrors the module-docstring pattern already used in
base_analyzer.py._extract_module_info: a docstring is the first statement in
a body, if it's an `expression_statement` whose expression is a bare
`string` literal.
"""

from typing import Any, Optional


def extract_docstring(body_node: Any) -> Optional[str]:
    """Return a function/class body's docstring's first line, or None."""
    if body_node is None or not hasattr(body_node, "children") or not body_node.children:
        return None

    first_stmt = body_node.children[0]
    if not hasattr(first_stmt, "type") or first_stmt.type != "expression_statement":
        return None

    expr = (
        first_stmt.child_by_field_name("expression")
        if hasattr(first_stmt, "child_by_field_name")
        else None
    )
    if expr is None and hasattr(first_stmt, "children") and first_stmt.children:
        expr = first_stmt.children[0]
    if expr is None or not hasattr(expr, "type") or expr.type != "string":
        return None

    try:
        text = expr.text.decode("utf-8") if isinstance(expr.text, bytes) else expr.text
    except Exception:
        return None

    docstring = text.strip("\"'")
    if not docstring:
        return None
    first_line = docstring.strip().splitlines()[0].strip()
    return first_line or None
