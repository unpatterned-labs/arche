# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Storage interfaces and local reference implementations for Arche."""

from __future__ import annotations

from .base import ArcheStore
from .duckdb import DuckDBStore

__all__ = ["ArcheStore", "DuckDBStore"]
