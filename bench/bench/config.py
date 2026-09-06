"""Corpora and tool registry, read from TOML so adding either is not a code change."""

from __future__ import annotations

import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
RUNS = RESULTS / "runs"
REPORTS = RESULTS / "reports"
HISTORY = RESULTS / "history.jsonl"
QUERYSETS = ROOT / "querysets"


def _load(name: str) -> dict:
    path = ROOT / name
    if not path.exists():
        return {}
    return tomllib.loads(path.read_text())


def corpora() -> dict[str, dict]:
    return _load("corpora.toml").get("corpus", {})


def tools() -> dict[str, dict]:
    return _load("adapters.toml").get("tool", {})


#: Substituted into any path or command string in the TOML files, so the
#: registries stay portable and nothing depends on the caller's cwd.
PLACEHOLDERS = {"root": str(ROOT), "repo": str(ROOT.parent)}


def expand(value: str) -> str:
    return value.format(**PLACEHOLDERS)


def resolve(value: str) -> Path:
    """Absolute path from a TOML value; relative values are relative to bench/."""
    path = Path(expand(value)).expanduser()
    return path if path.is_absolute() else (ROOT / path).resolve()


def corpus_path(name: str) -> Path:
    entry = corpora().get(name)
    if entry is None:
        raise SystemExit(f"unknown corpus {name!r}; known: {', '.join(corpora())}")
    return resolve(entry["path"])


def tool_options(name: str) -> dict:
    """Adapter options for a tool, with placeholders expanded in `command`."""
    entry = dict(tools().get(name) or {})
    command = entry.get("command")
    if command:
        entry["command"] = [expand(part) for part in command]
    return entry


def queryset_path(name: str) -> Path:
    entry = corpora().get(name, {})
    return QUERYSETS / entry.get("queryset", f"{name}.json")
