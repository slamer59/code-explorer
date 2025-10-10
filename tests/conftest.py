"""
Pytest configuration and shared fixtures for code-explorer tests.
"""

import tempfile
from pathlib import Path
from typing import Generator

import pytest


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Provide a temporary directory that is cleaned up after test.

    Yields:
        Path to temporary directory
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def temp_db_path(temp_dir: Path) -> Path:
    """Provide a temporary database path for testing.

    Args:
        temp_dir: Temporary directory fixture

    Returns:
        Path to temporary database
    """
    return temp_dir / "test_graph.db"


@pytest.fixture
def sample_python_file(temp_dir: Path) -> Path:
    """Create a simple Python file for testing.

    Args:
        temp_dir: Temporary directory fixture

    Returns:
        Path to created Python file
    """
    file_path = temp_dir / "sample.py"
    content = '''"""Sample module for testing."""

import os
from pathlib import Path


def public_function(x: int, y: int) -> int:
    """Add two numbers."""
    result = x + y
    return result


def _private_function(name: str) -> str:
    """Process a name."""
    processed = name.upper()
    return processed


def caller_function() -> int:
    """Call other functions."""
    value = public_function(5, 10)
    name = _private_function("test")
    return value


class SampleClass:
    """Sample class."""

    def method_one(self) -> None:
        """First method."""
        self.value = 42

    def method_two(self) -> int:
        """Second method."""
        self.method_one()
        return self.value
'''
    file_path.write_text(content, encoding='utf-8')
    return file_path


@pytest.fixture
def complex_python_file(temp_dir: Path) -> Path:
    """Create a more complex Python file with various constructs.

    Args:
        temp_dir: Temporary directory fixture

    Returns:
        Path to created Python file
    """
    file_path = temp_dir / "complex.py"
    content = '''"""Complex module with multiple dependencies."""

import json
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


# Module-level variable
CONFIG = {"debug": True, "timeout": 30}


def load_config(path: str) -> Dict:
    """Load configuration from file."""
    with open(path) as f:
        data = json.load(f)
    return data


def process_data(items: List[str]) -> List[str]:
    """Process list of items."""
    results = []
    for item in items:
        processed = transform_item(item)
        if validate_item(processed):
            results.append(processed)
    return results


def transform_item(item: str) -> str:
    """Transform a single item."""
    return item.strip().lower()


def validate_item(item: str) -> bool:
    """Validate a single item."""
    return len(item) > 0


def main() -> None:
    """Main entry point."""
    config = load_config("config.json")
    items = ["Item1", "Item2", "Item3"]
    results = process_data(items)
    logger.info(f"Processed {len(results)} items")
'''
    file_path.write_text(content, encoding='utf-8')
    return file_path


@pytest.fixture
def malformed_python_file(temp_dir: Path) -> Path:
    """Create a Python file with syntax errors.

    Args:
        temp_dir: Temporary directory fixture

    Returns:
        Path to created Python file
    """
    file_path = temp_dir / "malformed.py"
    content = '''"""This file has syntax errors."""

def broken_function(
    """Missing closing parenthesis."""
    return "broken"

def another_broken():
    if True
        return "missing colon"
'''
    file_path.write_text(content, encoding='utf-8')
    return file_path


@pytest.fixture
def sample_project(temp_dir: Path) -> Path:
    """Create a sample project with multiple files.

    Args:
        temp_dir: Temporary directory fixture

    Returns:
        Path to project root directory
    """
    # Create project structure
    (temp_dir / "src").mkdir()
    (temp_dir / "src" / "myapp").mkdir()
    (temp_dir / "tests").mkdir()

    # Create __init__.py
    (temp_dir / "src" / "myapp" / "__init__.py").write_text(
        '"""My application."""\n\n__version__ = "0.1.0"\n',
        encoding='utf-8'
    )

    # Create utils.py
    utils_content = '''"""Utility functions."""


def helper_function(value: int) -> int:
    """Helper function."""
    return value * 2


def another_helper(text: str) -> str:
    """Another helper."""
    return text.upper()
'''
    (temp_dir / "src" / "myapp" / "utils.py").write_text(
        utils_content,
        encoding='utf-8'
    )

    # Create main.py
    main_content = '''"""Main module."""

from .utils import helper_function, another_helper


def process(value: int) -> int:
    """Process a value."""
    result = helper_function(value)
    return result


def format_output(text: str) -> str:
    """Format output text."""
    formatted = another_helper(text)
    return formatted


def main() -> None:
    """Main entry point."""
    value = process(42)
    output = format_output("hello")
    print(f"Result: {value}, Output: {output}")
'''
    (temp_dir / "src" / "myapp" / "main.py").write_text(
        main_content,
        encoding='utf-8'
    )

    return temp_dir / "src" / "myapp"
