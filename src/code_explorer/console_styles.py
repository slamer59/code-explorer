"""Console styling utilities for consistent Rich output formatting.

This module provides reusable functions for creating polished console output
inspired by perfo's styling patterns. It includes table builders, status
indicators, and formatting helpers.

Example:
    >>> from code_explorer.console_styles import create_summary_table, format_count
    >>> table = create_summary_table("Analysis Results")
    >>> table.add_row("Files analyzed", format_count(150))
    >>> console.print(table)
"""

from typing import Optional, Tuple
from rich.console import Console
from rich.table import Table
from rich.box import ROUNDED, Box
from rich.panel import Panel


def get_status_icon(success: bool) -> str:
    """Get colored status icon.

    Args:
        success: Whether operation was successful

    Returns:
        str: Colored status icon (✓ or ✗)
    """
    return "[green]✓[/green]" if success else "[red]✗[/red]"


def format_count(count: int) -> str:
    """Format a count with thousands separator.

    Args:
        count: Number to format

    Returns:
        str: Formatted count string
    """
    return f"{count:,}"


def format_time(seconds: float) -> str:
    """Format time duration.

    Args:
        seconds: Duration in seconds

    Returns:
        str: Formatted time string
    """
    return f"{seconds:.3f}s"


def format_rate(count: int, seconds: float, unit: str = "rows/sec") -> str:
    """Format throughput rate.

    Args:
        count: Number of items processed
        seconds: Time taken in seconds
        unit: Unit label for rate (default: "rows/sec")

    Returns:
        str: Formatted rate string
    """
    if seconds <= 0:
        return f"{0:,} {unit}"
    rate = count / seconds
    return f"{rate:,.0f} {unit}"


def create_summary_table(title: str, header_style: str = "bold cyan") -> Table:
    """Create a styled summary table.

    Args:
        title: Table title
        header_style: Rich style for header (default: "bold cyan")

    Returns:
        Table: Configured Rich Table
    """
    table = Table(
        title=title,
        show_header=True,
        header_style=header_style,
        box=ROUNDED,
    )
    table.add_column("Metric", style="cyan")
    table.add_column("Count", justify="right", style="green")
    return table


def create_progress_table(title: str, include_rate: bool = False) -> Table:
    """Create a table for displaying progress/loading information.

    Args:
        title: Table title
        include_rate: Whether to include rate column

    Returns:
        Table: Configured Rich Table for progress display
    """
    table = Table(
        title=title,
        show_header=True,
        header_style="bold cyan",
        box=ROUNDED,
    )
    table.add_column("Item", style="cyan")
    table.add_column("Count", justify="right", style="yellow")
    table.add_column("Time", justify="right", style="blue")

    if include_rate:
        table.add_column("Rate", justify="right", style="magenta")

    return table


def create_data_table(title: str, columns: list[Tuple[str, str, str]]) -> Table:
    """Create a configurable data display table.

    Args:
        title: Table title
        columns: List of (column_name, justify, style) tuples

    Returns:
        Table: Configured Rich Table
    """
    table = Table(
        title=title,
        show_header=True,
        header_style="bold cyan",
        box=ROUNDED,
    )

    for col_name, justify, style in columns:
        table.add_column(col_name, justify=justify, style=style)

    return table


def format_status_line(
    success: bool,
    label: str,
    count: int,
    seconds: float,
    unit: str = "rows"
) -> str:
    """Format a status line like perfo's output.

    Format: ✓ Label: 1,234 items in 0.12s (10,283 items/sec)

    Args:
        success: Whether operation succeeded
        label: Name of operation/item
        count: Number processed
        seconds: Time taken
        unit: Unit name (default: "rows")

    Returns:
        str: Formatted status line
    """
    icon = get_status_icon(success)
    formatted_count = format_count(count)
    formatted_time = format_time(seconds)
    formatted_rate = format_rate(count, seconds, f"{unit}/sec")

    return (
        f"{icon} {label:20} {formatted_count:>10} {unit} in {formatted_time:>8} "
        f"({formatted_rate:>15})"
    )


def create_header_panel(
    title: str,
    subtitle: str = "",
    border_style: str = "cyan"
) -> Panel:
    """Create a styled header panel.

    Args:
        title: Panel title
        subtitle: Optional subtitle
        border_style: Rich style for border

    Returns:
        Panel: Configured Rich Panel
    """
    if subtitle:
        content = f"[bold cyan]{title}[/bold cyan]\n{subtitle}"
    else:
        content = f"[bold cyan]{title}[/bold cyan]"

    return Panel.fit(
        content,
        border_style=border_style,
        padding=(0, 1),
    )


def create_metrics_panel(
    title: str,
    metrics: dict[str, str],
    border_style: str = "green"
) -> Panel:
    """Create a panel displaying metrics.

    Args:
        title: Panel title
        metrics: Dictionary of metric_name -> value
        border_style: Rich style for border

    Returns:
        Panel: Configured Rich Panel with formatted metrics
    """
    lines = [f"[bold white]{title}[/bold white]"]
    lines.append("")

    for key, value in metrics.items():
        lines.append(f"  • {key}: {value}")

    return Panel(
        "\n".join(lines),
        border_style=border_style,
        padding=(1, 2),
        title=f"[bold white]⏱  {title}[/bold white]",
    )


class StyleGuide:
    """Color and styling guide for consistency.

    Attributes:
        header: Style for headers
        success: Style for success messages
        error: Style for error messages
        warning: Style for warnings
        label: Style for labels/headings
        metric: Style for metric values
        dim: Style for less important info
    """

    # Styles
    header = "bold cyan"
    success = "green"
    error = "red"
    warning = "yellow"
    label = "cyan"
    metric = "green"
    dim = "dim"

    # Colors
    header_border = "cyan"
    panel_border = "green"

    # Formatting
    success_icon = "[green]✓[/green]"
    error_icon = "[red]✗[/red]"
    warning_icon = "[yellow]⚠[/yellow]"


def apply_style(text: str, style: str) -> str:
    """Apply a style to text.

    Args:
        text: Text to style
        style: Rich style name

    Returns:
        str: Styled text
    """
    return f"[{style}]{text}[/{style}]"
