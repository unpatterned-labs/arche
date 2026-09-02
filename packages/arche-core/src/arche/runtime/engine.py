# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The M0 runtime handle.

Reconciliation intentionally does not live here yet. The runtime first owns
the durable contracts and store boundary that later resolution and agentic
control work will use.
"""

from __future__ import annotations

from dataclasses import dataclass

from arche.store.base import ArcheStore


@dataclass(frozen=True)
class ArcheEngine:
    """A runtime bound to one canonical entity store."""

    store: ArcheStore


def attach(uri: str) -> ArcheEngine:
    """Attach Arche to a local DuckDB entity store.

    Example:
        >>> engine = attach("duckdb:///:memory:")
        >>> engine.store.ensure_schema()

    Parameters:
        uri: A ``duckdb:///`` URI. Use ``duckdb:///:memory:`` for an ephemeral store.

    Returns:
        An engine whose store has an idempotently initialised schema.

    Raises:
        ValueError: If ``uri`` is not a supported DuckDB URI.
        ImportError: If the optional runtime dependency is not installed.
    """
    if not uri.startswith("duckdb:///"):
        raise ValueError(
            f"unsupported Arche store URI {uri!r}; use duckdb:///:memory: or "
            "duckdb:///arche.duckdb"
        )

    database = uri.removeprefix("duckdb:///")
    if not database:
        raise ValueError(
            "DuckDB store URI needs a database path; use duckdb:///:memory: or "
            "duckdb:///arche.duckdb"
        )

    from arche.store.duckdb import DuckDBStore

    store = DuckDBStore(database)
    store.ensure_schema()
    return ArcheEngine(store=store)
