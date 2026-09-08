"""Adapter registry. One module per tool under test."""

from __future__ import annotations

from pathlib import Path

from .base import Adapter, Hit, QueryResult
from .code_explorer import CodeExplorerAdapter
from .ripwire import RipwireAdapter
from .zg import ZgAdapter

#: Adapter classes by module name. Registry *keys* in adapters.toml are
#: configuration names and may repeat a module.
ADAPTERS: dict[str, type[Adapter]] = {
    "code_explorer": CodeExplorerAdapter,
    "code-explorer": CodeExplorerAdapter,
    "zg": ZgAdapter,
    "ripwire": RipwireAdapter,
}


def build(name: str, corpus: Path, module: str | None = None, **options: object) -> Adapter:
    """Instantiate the adapter `module` under the configuration name `name`.

    `name` is the registry key and becomes the row label; `module` picks the
    class. They differ whenever one tool is entered under several
    configurations.
    """
    key = module or name
    try:
        cls = ADAPTERS[key]
    except KeyError:
        raise SystemExit(
            f"unknown adapter {key!r}; known: {', '.join(sorted(ADAPTERS))}"
        ) from None
    return cls(corpus, name=name, **options)


__all__ = ["ADAPTERS", "Adapter", "Hit", "QueryResult", "build"]
