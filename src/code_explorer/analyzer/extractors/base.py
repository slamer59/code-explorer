"""
Base extractor interface.

All extractors inherit from BaseExtractor and implement the extract method.
"""

import ast
from abc import ABC, abstractmethod

from code_explorer.analyzer.models import FileAnalysis


class BaseExtractor(ABC):
    """Base class for all extractors.

    Extractors analyze AST trees and populate FileAnalysis results.
    Each extractor is responsible for one aspect of code analysis.
    """

    @abstractmethod
    def extract(self, tree: ast.AST, result: FileAnalysis) -> None:
        """Extract information from AST tree and populate result.

        Args:
            tree: AST tree to analyze
            result: FileAnalysis object to populate with extracted information
        """
        pass
