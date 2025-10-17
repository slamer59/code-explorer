"""
Resolves function calls from FileAnalysis results using fast DataFrame joins.

This module provides efficient call resolution using Polars DataFrame operations
instead of nested loops, significantly improving performance for large codebases.
"""

from typing import List, Dict
from pathlib import Path

import polars as pl

from code_explorer.analyzer.models import FileAnalysis


class CallResolver:
    """Resolves function calls from FileAnalysis results using fast DataFrame joins."""

    def __init__(self, results: List[FileAnalysis]):
        """Initialize with FileAnalysis results.

        Args:
            results: List of FileAnalysis objects from analyzer
        """
        self.results = results

    def resolve_all_calls(self) -> List[dict]:
        """Resolve all function calls using Polars joins.

        This method efficiently matches function calls to their definitions by:
        1. Extracting all calls as a DataFrame
        2. Extracting all functions as a DataFrame
        3. Joining caller functions to get caller_start_line
        4. Joining callee functions to find matches
        5. Selecting and formatting the result columns

        Returns:
            List of dicts with:
            - caller_file: str - File containing the calling function
            - caller_function: str - Name of the calling function
            - caller_start_line: int - Start line of the calling function
            - callee_file: str - File containing the called function
            - callee_function: str - Name of the called function
            - callee_start_line: int - Start line of the called function
            - call_line: int - Line number where the call occurs
        """
        if not self.results:
            return []

        # Step 1: Extract all calls as DataFrame
        call_data = []
        for result in self.results:
            for call in result.function_calls:
                call_data.append({
                    'caller_file': result.file_path,
                    'caller_func': call.caller_function,
                    'called_name': call.called_name,
                    'call_line': call.call_line,
                })

        if not call_data:
            return []

        df_calls = pl.DataFrame(call_data)

        # Step 2: Extract all functions as DataFrame
        func_data = []
        for result in self.results:
            for func in result.functions:
                func_data.append({
                    'file': result.file_path,
                    'name': func.name,
                    'start_line': func.start_line,
                })

        if not func_data:
            return []

        df_funcs = pl.DataFrame(func_data)

        # Step 3: Join caller functions to get caller_start_line
        df_with_caller = df_calls.join(
            df_funcs,
            left_on=['caller_file', 'caller_func'],
            right_on=['file', 'name'],
            how='inner'
        ).rename({'start_line': 'caller_start_line'})

        # Step 4: Join callee functions to find matches
        df_resolved = df_with_caller.join(
            df_funcs,
            left_on='called_name',
            right_on='name',
            how='inner'
        ).rename({
            'file': 'callee_file',
            'start_line': 'callee_start_line'
        })

        # Step 5: Select and rename columns
        result_df = df_resolved.select([
            'caller_file',
            pl.col('caller_func').alias('caller_function'),
            'caller_start_line',
            'callee_file',
            pl.col('called_name').alias('callee_function'),
            'callee_start_line',
            'call_line'
        ])

        # Convert to list of dicts
        return result_df.to_dicts()
