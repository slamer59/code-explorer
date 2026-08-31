"""End-to-end coverage for the bounded search rebuild path."""

from click.testing import CliRunner

from code_explorer.cli import cli


def test_search_reindex_accepts_worker_cap_and_builds_index(temp_dir):
    (temp_dir / "opportunity.py").write_text(
        "def update_opportunity_model():\n"
        "    pass\n"
        "def caller():\n"
        "    update_opportunity_model()\n"
    )

    result = CliRunner().invoke(
        cli,
        [
            "search",
            "update opportunity",
            str(temp_dir),
            "--reindex",
            "--workers",
            "1",
            "--no-context",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Resolved 1 calls" in result.output
    assert "update_opportunity_model" in result.output
