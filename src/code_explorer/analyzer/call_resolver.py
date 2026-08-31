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
        """Resolve calls and return the legacy list-of-dicts representation."""
        return self.resolve_all_calls_frame().to_dicts()

    def resolve_all_calls_frame(self) -> pl.DataFrame:
        """Resolve all function calls using Polars joins.

        This method efficiently matches function calls to their definitions by:
        1. Extracting all calls as a DataFrame
        2. Extracting all functions as a DataFrame
        3. Joining caller functions to get caller_start_line
        4. Joining callee functions to find matches
        5. Selecting and formatting the result columns

        Returns:
            A Polars DataFrame with:
            - caller_file: str - File containing the calling function
            - caller_function: str - Name of the calling function
            - caller_start_line: int - Start line of the calling function
            - callee_file: str - File containing the called function
            - callee_function: str - Name of the called function
            - callee_start_line: int - Start line of the called function
            - call_line: int - Line number where the call occurs

            Same-file definitions are preferred. Cross-file calls are only
            resolved for globally unique names; ambiguous names are left
            unresolved rather than expanded into false many-to-many edges.
        """
        if not self.results:
            return pl.DataFrame()

        # Step 1: Extract all calls as DataFrame
        call_data = []
        for result in self.results:
            for call in result.function_calls:
                call_data.append(
                    {
                        "caller_file": result.file_path,
                        "caller_func": call.caller_function,
                        "called_name": call.called_name,
                        "call_line": call.call_line,
                    }
                )

        if not call_data:
            return pl.DataFrame()

        df_calls = pl.DataFrame(call_data).with_row_index("_call_id")
        del call_data

        # Step 2: Extract all functions as DataFrame
        func_data = []
        for result in self.results:
            for func in result.functions:
                func_data.append(
                    {
                        "file": result.file_path,
                        "name": func.name,
                        "start_line": func.start_line,
                    }
                )

        if not func_data:
            return pl.DataFrame()

        df_funcs = pl.DataFrame(func_data)
        del func_data

        # Step 3: Join caller functions to get caller_start_line
        df_with_caller = df_calls.join(
            df_funcs,
            left_on=["caller_file", "caller_func"],
            right_on=["file", "name"],
            how="inner",
        ).rename({"start_line": "caller_start_line"})

        # Step 4a: Prefer definitions in the caller's own file. This keeps
        # common names from becoming a repository-wide many-to-many join.
        df_local = df_with_caller.join(
            df_funcs,
            left_on=["caller_file", "called_name"],
            right_on=["file", "name"],
            how="inner",
        ).with_columns(
            pl.col("caller_file").alias("callee_file"),
            pl.col("called_name").alias("callee_function"),
            pl.col("start_line").alias("callee_start_line"),
        )

        # Step 4b: Resolve cross-file calls only when exactly one definition
        # with that name exists in the repository. Ambiguous calls are safer
        # left unresolved than expanded into thousands of false CALLS edges.
        unique_names = (
            df_funcs.group_by("name")
            .agg(pl.len().alias("definition_count"))
            .filter(pl.col("definition_count") == 1)
            .select("name")
        )
        unique_funcs = df_funcs.join(unique_names, on="name", how="inner")
        calls_without_local_match = df_with_caller.join(
            df_local.select("_call_id").unique(), on="_call_id", how="anti"
        )
        df_global = calls_without_local_match.join(
            unique_funcs,
            left_on="called_name",
            right_on="name",
            how="inner",
        ).rename(
            {
                "file": "callee_file",
                "called_name": "callee_function",
                "start_line": "callee_start_line",
            }
        )

        resolved_columns = [
            "caller_file",
            pl.col("caller_func").alias("caller_function"),
            "caller_start_line",
            "callee_file",
            "callee_function",
            "callee_start_line",
            "call_line",
        ]

        # Step 5: Select and rename columns
        result_df = pl.concat(
            [df_local.select(resolved_columns), df_global.select(resolved_columns)]
        )

        return result_df
