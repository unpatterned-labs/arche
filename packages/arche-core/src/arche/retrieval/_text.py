# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The text a record is retrieved by."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

#: Fields, in order, joined into a record's retrieval text when present.
#: Context travels with the name ("Zango Health Post | Dala | Kano"), because a
#: name alone retrieves every namesake in the country.
DEFAULT_FIELDS = ("name", "type", "admin_path.admin2", "admin_path.admin1")


def _get(record: Mapping[str, Any], dotted: str) -> Any:
    value: Any = record
    for part in dotted.split("."):
        if not isinstance(value, Mapping):
            return None
        value = value.get(part)
    return value


def record_text(record: Mapping[str, Any], fields: Sequence[str] = DEFAULT_FIELDS,
                *, sep: str = " | ") -> str:
    """``fields`` that the record has, as one string. A dotted field reads into
    a mapping (``admin_path.admin2``)."""
    parts = []
    for name in fields:
        value = _get(record, name)
        if value is None:
            continue
        text = " ".join(str(value).split())
        if text:
            parts.append(text)
    return sep.join(parts)
