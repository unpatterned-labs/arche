# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Fingerprints: the keys that make a lookup a lookup instead of a scan.

A fingerprint is a cheap, precomputed key with one property: two records that
could be the same thing share at least one. Nothing more is claimed. Sharing a
fingerprint is not evidence of anything -- it is an invitation to compare, and
the comparison is where the evidence comes from.

Why this exists as its own surface rather than staying inside blocking: a
master list is asked about many times, and its keys do not change between
questions. Computing them once and keeping them turns ``find`` from a pass over
every record into a dictionary lookup. On 641,762 supplier records that is the
difference between 2 x 10^11 candidate pairs and a few dozen.

The honest limit, stated because it caps everything downstream: **a pair whose
records share no fingerprint is never compared, and therefore never found.**
Recall is bounded by the keys, not by the comparators. ``index.stats()``
reports the distribution so that bound is visible rather than assumed -- a key
held by 10,052 records is not narrowing anything, and one held by one record
cannot match anybody.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable
from typing import Any

from arche.resolve._block import _norm_tokens

__all__ = ["FingerprintIndex", "fingerprint"]

#: Values that look like data and are not. A key built from one of these is a
#: key shared by everything that also has nothing, which is the opposite of
#: narrowing. Measured on a real supplier file: `test` alone was carried by 303
#: records across 57 countries.
_NULLISH = frozenset({
    "", "-", "--", "n/a", "na", "none", "null", "nil", "unknown", "unspecified",
    "test", "testing", "tbd", "xxx", "xxxx", "dummy", "sample", "example",
})


def _clean(value: Any) -> str:
    """Casefolded, diacritics-folded, whitespace-collapsed text."""
    if value is None:
        return ""
    folded = unicodedata.normalize("NFKD", str(value).strip().lower())
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return " ".join(folded.split())


def _exact_keys(record: dict, fields: Iterable[str]) -> set[str]:
    """One key per stated identifier. Near-deterministic, so kept whole."""
    keys = set()
    for field in fields:
        value = _clean(record.get(field))
        if value and value not in _NULLISH:
            keys.add(f"{field}={value}")
    return keys


def fingerprint(
    record: dict,
    *,
    text_fields: Iterable[str] = ("name",),
    id_fields: Iterable[str] = (),
    max_tokens: int = 12,
) -> list[str]:
    """The keys under which a record can be found.

    Two kinds, and the difference matters when reading a result:

    ``field=value``
        an identifier stated whole -- an email, a website, a registration
        number. Sharing one is nearly always the same thing.
    ``t:token``
        one word from a text field. Sharing one means *worth comparing*, and
        nothing else. Two tour operators both called "City Tours" share
        ``t:city`` and ``t:tours`` and are usually different businesses.

    Placeholder values (``test``, ``n/a``, ``unknown``) are dropped. They are
    not identifiers, and a key everyone shares narrows nothing.

    ``max_tokens`` bounds the work a single pathological record can cause: a
    name field holding a paragraph would otherwise contribute a key per word.
    """
    keys = _exact_keys(record, id_fields)
    tokens: set[str] = set()
    for field in text_fields:
        value = record.get(field)
        if value not in (None, ""):
            tokens |= _norm_tokens(value)
    tokens = {t for t in tokens if t not in _NULLISH and len(t) > 1}
    for token in sorted(tokens)[:max_tokens]:
        keys.add(f"t:{token}")
    return sorted(keys)


class FingerprintIndex:
    """A list you can ask about repeatedly without rereading it.

    Built once over a master list; every later lookup is a dictionary hit on
    the query's own keys. The index holds row positions, never record content,
    so it carries no personal data and can be kept or logged where the records
    themselves could not be.
    """

    def __init__(
        self,
        records: list[dict],
        *,
        text_fields: Iterable[str] = ("name",),
        id_fields: Iterable[str] = (),
        max_block: int = 1000,
    ) -> None:
        self.text_fields = tuple(text_fields)
        self.id_fields = tuple(id_fields)
        self.max_block = max_block
        self.size = len(records)
        self._keys: dict[str, list[int]] = {}
        for position, record in enumerate(records):
            for key in fingerprint(record, text_fields=self.text_fields,
                                   id_fields=self.id_fields):
                self._keys.setdefault(key, []).append(position)

        # Keys held by more than `max_block` records are dropped as blocking
        # keys. This is a cost bound, not a claim about rarity: a key naming a
        # tenth of the file proposes millions of comparisons and rules almost
        # nothing out. `dropped_keys` records them because the drop costs
        # recall, and a recall cost you cannot see is one you will not believe
        # later.
        self.dropped_keys = {
            key: len(rows) for key, rows in self._keys.items()
            if len(rows) > max_block
        }
        for key in self.dropped_keys:
            del self._keys[key]

    def candidates(self, record: dict) -> list[int]:
        """Row positions worth comparing against ``record``."""
        found: set[int] = set()
        for key in fingerprint(record, text_fields=self.text_fields,
                               id_fields=self.id_fields):
            found.update(self._keys.get(key, ()))
        return sorted(found)

    def stats(self) -> dict[str, Any]:
        """What the index can and cannot reach.

        Reported rather than assumed, because every number downstream is capped
        by it: a record reachable under no key is a record no lookup will ever
        return, however good the comparators are.
        """
        sizes = sorted((len(rows) for rows in self._keys.values()), reverse=True)
        reachable = {position for rows in self._keys.values() for position in rows}
        return {
            "records": self.size,
            "keys": len(self._keys),
            "reachable_records": len(reachable),
            "unreachable_records": self.size - len(reachable),
            "largest_block": sizes[0] if sizes else 0,
            "median_block": sizes[len(sizes) // 2] if sizes else 0,
            "dropped_keys": len(self.dropped_keys),
            "dropped_key_rows": sum(self.dropped_keys.values()),
        }
