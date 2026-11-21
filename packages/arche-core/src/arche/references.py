# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""References: the lists a mention is linked to, and the version a receipt names.

A *reference* is anything that can answer "which of your records might be
this?" -- a file you downloaded, a register, a hosted service -- and say
exactly which data it searched. :func:`link` asks a reference for candidates,
lets :func:`arche.resolve.reconcile` decide, and pins the reference's release
into every decision id, so a receipt names the data it was matched against and
a replay against a newer release is visibly a different decision.

Any object with these members is a reference (structural typing)::

    class Reference(Protocol):
        name: str
        def candidates(self, record, *, limit=20) -> list[dict]: ...
        def pins(self) -> dict: ...            # must include "release"

:class:`FileReference` is the one arche ships: records in memory or a CSV,
JSON-lines, JSON or Parquet file, indexed for candidate retrieval on the
laptop. A hosted reference (Renyi's place search, for one) implements the same
three members in its own package; arche never depends on it.

**What leaves the machine.** :func:`link` sends a reference a *projection* of
each mention -- by default only ``name``, ``admin_path``, ``lat``, ``lon`` and
``country`` -- never the document or any other field. Mask the document first
(:func:`arche.deidentify`), extract the mentions, then link: a hosted
reference then sees facility or company names, not the text around them.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

#: The mention fields :func:`link` sends to a reference unless told otherwise.
DEFAULT_QUERY_FIELDS = ("name", "admin_path", "lat", "lon", "country")


@runtime_checkable
class Reference(Protocol):
    """A list mentions are linked to. See the module docstring."""

    name: str

    def candidates(self, record: Mapping[str, Any], *, limit: int = 20) -> list[dict[str, Any]]:
        """Records that might be ``record``: each a dict with ``id`` and ``name``."""
        ...

    def pins(self) -> dict[str, Any]:
        """JSON-safe description of the data searched; must include ``release``."""
        ...


# ── FileReference ────────────────────────────────────────────────────────────


def _distinctive(name: Any, extra_stop: Iterable[str] = (), domain: str | None = None
                 ) -> set[str]:
    """Name tokens that can identify: not a type word ("primary health centre"),
    not a place's own unit name, at least three characters."""
    import re

    from arche.resolve._matcher import _normalise_text, load_type_vocab

    text = _normalise_text(str(name or ""))
    words = set()
    if domain:
        for synonym in load_type_vocab(domain):
            words.update(synonym.split())
    stop = words | {w.lower() for w in extra_stop}
    return {t for t in re.split(r"[^a-z0-9]+", text) if len(t) >= 3 and t not in stop}


def _metres(a: Mapping[str, Any], b: Mapping[str, Any]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (float(a["lat"]), float(a["lon"]),
                                            float(b["lat"]), float(b["lon"])))
    h = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return 2 * 6_371_000 * math.asin(math.sqrt(h))


def _has_point(r: Mapping[str, Any]) -> bool:
    try:
        return r.get("lat") is not None and r.get("lon") is not None \
            and not math.isnan(float(r["lat"])) and not math.isnan(float(r["lon"]))
    except (TypeError, ValueError):
        return False


class FileReference:
    """Records you hold, indexed for linking. Nothing is sent anywhere.

    Candidates for a mention share at least one distinctive name token with it
    and, when both sides say where they are:

    * within ``radius_m`` when the mention has coordinates;
    * otherwise in the same admin unit at ``block_on`` (state and LGA by
      default) when the mention states those levels.

    Ranked by shared tokens, then distance; at most ``limit``.

    ``release`` names the data; by default it is the content digest of the
    records, so two different files can never pin the same release.
    """

    def __init__(self, records: Iterable[Mapping[str, Any]], *, name: str,
                 release: str | None = None, licence: str | None = None,
                 id_field: str = "id", block_on: Sequence[str] = ("admin1", "admin2"),
                 radius_m: float = 3000.0, domain: str | None = "health_facility") -> None:
        self.name = name
        self._licence = licence
        self._block_on = tuple(block_on)
        self._radius_m = float(radius_m)
        self._domain = domain
        self._records: list[dict[str, Any]] = []
        for raw in records:
            row = dict(raw)
            if id_field != "id":
                row["id"] = row.get(id_field)
            if row.get("id") in (None, ""):
                raise ValueError(f"{name}: every reference record needs an id ({id_field!r})")
            row["id"] = str(row["id"])
            self._records.append(row)
        if release is None:
            from arche.ids import canonical_json

            body = canonical_json(sorted(self._records, key=lambda r: r["id"]))
            release = "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()
        self._release = release
        self._index: dict[str, list[int]] = {}
        for i, r in enumerate(self._records):
            for token in self._tokens(r):
                self._index.setdefault(token, []).append(i)

    @classmethod
    def from_file(cls, path: str | Path, *, name: str | None = None, **kwargs: Any
                  ) -> FileReference:
        """A CSV, JSON-lines, JSON (a list) or Parquet file; ``release`` defaults
        to the file's own digest."""
        path = Path(path)
        raw = path.read_bytes()
        kwargs.setdefault("release", "sha256:" + hashlib.sha256(raw).hexdigest())
        suffix = path.suffix.lower()
        if suffix == ".csv":
            import csv
            import io

            rows: list[dict[str, Any]] = list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))
        elif suffix in (".jsonl", ".ndjson"):
            rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
        elif suffix == ".json":
            rows = json.loads(raw.decode("utf-8"))
        elif suffix == ".parquet":
            import duckdb

            con = duckdb.connect()
            cur = con.execute("SELECT * FROM read_parquet(?)", [str(path)])
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
        else:
            raise ValueError(f"unsupported reference file type: {path.suffix}")
        return cls(rows, name=name or path.stem, **kwargs)

    def __len__(self) -> int:
        return len(self._records)

    def _tokens(self, r: Mapping[str, Any]) -> set[str]:
        # The names of the units a record is blocked within (state, LGA) say
        # where it is, not which it is: "Dala PHC" in Dala LGA. Finer units are
        # kept -- a ward is often what a facility is named after (Zango ward,
        # Zango 1 Health Post).
        ap = r.get("admin_path") if isinstance(r.get("admin_path"), Mapping) else {}
        own = [ap[level] for level in self._block_on if ap.get(level)]
        local = set().union(*(_distinctive(v) for v in own)) if own else set()
        return _distinctive(r.get("name"), domain=self._domain) - local

    def candidates(self, record: Mapping[str, Any], *, limit: int = 20) -> list[dict[str, Any]]:
        mine = self._tokens(record)
        shared: dict[int, int] = {}
        for token in mine:
            for i in self._index.get(token, ()):
                shared[i] = shared.get(i, 0) + 1
        out: list[tuple[int, float, dict[str, Any]]] = []
        ap = record.get("admin_path") if isinstance(record.get("admin_path"), Mapping) else {}
        block = tuple(ap.get(level) for level in self._block_on)
        for i, n in shared.items():
            r = self._records[i]
            if _has_point(record) and _has_point(r):
                d = _metres(record, r)
                if d > self._radius_m:
                    continue
            elif ap and None not in block:
                theirs = r.get("admin_path") if isinstance(r.get("admin_path"), Mapping) else {}
                if tuple(theirs.get(level) for level in self._block_on) != block:
                    continue
                d = math.inf
            else:
                d = math.inf
            out.append((n, d, r))
        out.sort(key=lambda t: (-t[0], t[1], t[2]["id"]))
        return [dict(r) for _, _, r in out[:limit]]

    def pins(self) -> dict[str, Any]:
        pins: dict[str, Any] = {"reference": self.name, "release": self._release,
                                "records": len(self._records)}
        if self._licence:
            pins["licence"] = self._licence
        return pins


# ── link ─────────────────────────────────────────────────────────────────────


def link(mentions: Sequence[Mapping[str, Any]], reference: Reference, *,
         entity: str = "place", id_field: str = "id", limit: int = 20,
         query_fields: Sequence[str] = DEFAULT_QUERY_FIELDS,
         **reconcile_kwargs: Any) -> dict[str, Any]:
    """Link each mention to ``reference``: candidates from the reference, the
    decision from :func:`arche.resolve.reconcile`, the release in every receipt.

    Returns reconcile's result plus ``reference_records`` (the candidates that
    were scored, deduplicated -- what a ledger's ``record_batch`` needs as its
    right-hand list) and ``reference`` (the reference's pins).

    ``query_fields`` is everything a reference ever sees of a mention. A
    reference that does not name its ``release`` is refused, because a receipt
    that cannot say what it was matched against cannot be checked later.
    Pass ``unique_match=True`` when mentions have no coordinates.
    """
    from arche.resolve import reconcile

    by_id: dict[str, dict[str, Any]] = {}
    pairs: list[dict[str, Any]] = []
    for position, mention in enumerate(mentions):
        a_id = mention.get(id_field, position)
        query = {k: mention[k] for k in query_fields if mention.get(k) is not None}
        for cand in reference.candidates(query, limit=limit):
            b_id = str(cand["id"])
            by_id.setdefault(b_id, dict(cand))
            pairs.append({"a_id": a_id, "b_id": b_id, "route": str(reference.name)})
    # Read after the queries: a hosted reference learns its release from its
    # answers (and must refuse, itself, to mix two releases in one run).
    pins = dict(reference.pins())
    if not pins.get("release"):
        raise ValueError(f"reference {getattr(reference, 'name', reference)!r} does not "
                         "name its release; a receipt could not say what it matched")
    right = list(by_id.values())
    result = reconcile(list(mentions), right, entity=entity, id_field=id_field,
                       candidate_pairs=pairs,
                       candidate_pins={"reference": pins, "query_fields": list(query_fields),
                                       "limit": limit},
                       **reconcile_kwargs)
    result["reference_records"] = right
    result["reference"] = pins
    return result


__all__ = ["DEFAULT_QUERY_FIELDS", "FileReference", "Reference", "link"]
