#!/usr/bin/env python
# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""Where the studio keeps what a reviewer decided.

    data/review_packs/_studio.sqlite3

Why this exists
---------------
Adjudications used to live in memory until someone pressed Save, at which point
the whole pack was rewritten as a CSV. That has three problems and the third is
the serious one:

1. A browser refresh lost the work.
2. Marking one row rewrote every row.
3. **There was no history.** The CSV held the *current* outcome and nothing
   about how it got there. If a reviewer changed their mind, the earlier call
   vanished, and a reviewer changing their mind is exactly the event an audit
   would want to see.

So marks are append-only here. Nothing is ever updated in place and nothing is
deleted. The current outcome is the newest row for a decision id, which means
the history is free and the audit question is answerable.

Why SQLite
----------
It is in the standard library, so the tool keeps its "no dependencies" claim.
It handles concurrent readers, survives a crash mid-write, and a single file is
something a person can copy, inspect with any tool, or delete. For the volume a
human reviewer generates it will never be the bottleneck.

The *packs* are a different question. They are analytical reads over columns and
will reach millions of rows, which is a DuckDB shape rather than a SQLite one.
This module deliberately covers only the studio's own state.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS mark (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    pack         TEXT NOT NULL,
    pack_digest  TEXT NOT NULL,
    decision_id  TEXT NOT NULL,
    outcome      TEXT NOT NULL,
    reason       TEXT NOT NULL DEFAULT '',
    reviewer     TEXT NOT NULL,
    marked_at    TEXT NOT NULL
);
-- Reading a pack means "newest mark per decision id", so index that path.
CREATE INDEX IF NOT EXISTS mark_pack_decision ON mark (pack, decision_id, id DESC);
CREATE INDEX IF NOT EXISTS mark_reviewer ON mark (reviewer, marked_at);
"""

OUTCOMES = ("same_entity", "different", "unresolved")


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class Store:
    """Append-only adjudication state. One file, no schema migrations yet."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        # A reviewer's laptop can lose power. WAL survives that better, and
        # costs nothing at this volume.
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        return c

    # ── writes ───────────────────────────────────────────────────────────
    def mark(self, *, pack: str, pack_digest: str, decision_id: str,
             outcome: str, reviewer: str, reason: str = "") -> dict:
        """Record one adjudication. Never overwrites an earlier one."""
        if outcome not in OUTCOMES:
            raise ValueError(f"outcome must be one of {OUTCOMES}")
        reviewer = (reviewer or "").strip()
        if not reviewer:
            raise ValueError("a reviewer name is required; an unattributed "
                             "adjudication cannot be audited")
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO mark (pack, pack_digest, decision_id, outcome,"
                " reason, reviewer, marked_at) VALUES (?,?,?,?,?,?,?)",
                (pack, pack_digest, decision_id, outcome,
                 (reason or "").strip(), reviewer, _now()))
            return {"id": cur.lastrowid, "marked_at": _now()}

    # ── reads ────────────────────────────────────────────────────────────
    def current(self, pack: str) -> dict[str, dict[str, Any]]:
        """The standing outcome per decision id: the newest mark for each."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT m.* FROM mark m JOIN (SELECT decision_id, MAX(id) AS id"
                "  FROM mark WHERE pack = ? GROUP BY decision_id) t"
                " ON m.id = t.id", (pack,)).fetchall()
        return {r["decision_id"]: dict(r) for r in rows}

    def history(self, pack: str, decision_id: str) -> list[dict]:
        """Every call ever made on one pair, oldest first."""
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM mark WHERE pack = ? AND decision_id = ?"
                " ORDER BY id", (pack, decision_id))]

    def summary(self, pack: str) -> dict:
        """Counts a reviewer wants in the toolbar, plus the changed-mind count."""
        cur = self.current(pack)
        by_outcome: dict[str, int] = {}
        for r in cur.values():
            by_outcome[r["outcome"]] = by_outcome.get(r["outcome"], 0) + 1
        with self._conn() as c:
            total = c.execute("SELECT COUNT(*) FROM mark WHERE pack = ?",
                              (pack,)).fetchone()[0]
            reviewers = [r[0] for r in c.execute(
                "SELECT DISTINCT reviewer FROM mark WHERE pack = ? ORDER BY 1",
                (pack,))]
            # A pack whose digest moved between marks was edited underneath the
            # reviewer. Worth surfacing rather than discovering later.
            digests = [r[0] for r in c.execute(
                "SELECT DISTINCT pack_digest FROM mark WHERE pack = ?", (pack,))]
        return {"marked": len(cur), "by_outcome": by_outcome,
                "revisions": total - len(cur), "reviewers": reviewers,
                "digests_seen": digests}
