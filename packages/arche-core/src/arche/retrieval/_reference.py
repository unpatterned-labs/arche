# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""A retriever over a record list, as a reference :func:`arche.references.link`
can link mentions to."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

from arche.retrieval._text import DEFAULT_FIELDS, record_text


class IndexedReference:
    """Records you hold, searched by a retriever instead of shared tokens.

    ``retriever`` is a factory: given the gallery texts, it returns an index
    with ``search(text, k)`` and ``pins()`` (:class:`CharNgramIndex`, or
    ``lambda texts: EncoderIndex(texts, encoder)``). Candidates are the top
    ``limit`` rows for the mention's text, best first.

    ``pins()`` names the data (``release``, the content digest by default) and
    the retriever (its own pins, which carry an encoder's weights digest), so
    :func:`link` writes both into every decision id.
    """

    def __init__(self, records: Iterable[Mapping[str, Any]], *, name: str,
                 retriever: Callable[[list[str]], Any], fields: Sequence[str] = DEFAULT_FIELDS,
                 release: str | None = None, licence: str | None = None,
                 id_field: str = "id") -> None:
        from arche.references import records_release

        self.name = name
        self._fields = tuple(fields)
        self._licence = licence
        self._records: list[dict[str, Any]] = []
        for raw in records:
            row = dict(raw)
            if id_field != "id":
                row["id"] = row.get(id_field)
            if row.get("id") in (None, ""):
                raise ValueError(f"{name}: every reference record needs an id ({id_field!r})")
            row["id"] = str(row["id"])
            self._records.append(row)
        self._release = release or records_release(self._records)
        self._index = retriever([record_text(r, self._fields) for r in self._records])

    def __len__(self) -> int:
        return len(self._records)

    def candidates(self, record: Mapping[str, Any], *, limit: int = 20) -> list[dict[str, Any]]:
        text = record_text(record, self._fields)
        if not text:
            return []
        return [dict(self._records[row]) for row, _ in self._index.search(text, limit)]

    def pins(self) -> dict[str, Any]:
        pins: dict[str, Any] = {"reference": self.name, "release": self._release,
                                "records": len(self._records), "fields": list(self._fields),
                                "retriever": self._index.pins()}
        if self._licence:
            pins["licence"] = self._licence
        return pins
