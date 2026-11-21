# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Documents to a review queue: the parties they name, paired up for a person.

:func:`review_parties` parses each document, reads its parties
(:func:`arche.doc.parties`), keeps the ones in one role and of one kind (the
person each invoice is *for*, by default), compares every pair with
:func:`arche.resolve.reconcile`, and writes a review pack that
``arche studio`` opens. With ``ledger=`` it also records the decisions, so the
studio's Explain pane can show why each pair came out as it did.

The pack is **masked by default**, like every pack. A masked pack cannot be
judged: nobody can say whether two people are one when both names are hidden.
``reveal=True`` writes a working copy for a reviewer on this machine. Keep it
local and out of ``data/review_packs/``, which ``arche studio`` shows by
default: in this repository revealed packs go in ``data/private_packs/``
(git-ignored) and are opened with ``arche studio --packs data/private_packs``.
"""

from __future__ import annotations

import glob
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

#: entity pack -> the party kind it compares.
_KIND = {"person": "person", "organisation": "organisation", "organization": "organisation"}


def _sources(source: str | Path | Iterable[str | Path]) -> list[Path]:
    if isinstance(source, (str, Path)):
        text = str(source)
        if any(ch in text for ch in "*?["):
            paths = [Path(p) for p in sorted(glob.glob(text))]
        elif Path(text).is_dir():
            paths = sorted(p for p in Path(text).iterdir() if p.is_file())
        else:
            paths = [Path(text)]
    else:
        paths = [Path(p) for p in source]
    if not paths:
        raise ValueError(f"no documents found at {source!s}")
    return paths


def review_parties(
    source: str | Path | Iterable[str | Path],
    out_dir: str | Path,
    *,
    role: str = "customer",
    entity: str = "person",
    reveal: bool = False,
    ledger: Any = None,
    backend: str = "auto",
    quiet: bool = True,
) -> dict[str, Any]:
    """Pair up the ``role`` parties of the documents at ``source`` for review.

    ``source`` is a glob, a directory, one file, or a list of files. Each
    party record carries the document's file name as its id and as
    ``document``. Every pair the engine scores ``match`` or ``review`` becomes
    a pack row; pairs it rejects are not a queue and are left out.

    ``ledger`` is a :class:`arche.ledger.Ledger` or a path to a DuckDB file
    (created if absent); the decisions are recorded in it and matches linked.

    Returns the pack manifest plus ``records`` (one per document kept),
    ``skipped`` (documents with no ``role`` party of that kind, and why) and
    ``ledger`` (its path, when one was given). ``quiet`` silences the
    parsing libraries' logs, as :func:`arche.doc.resolve_documents` does.
    """
    from contextlib import nullcontext

    from arche.doc import parse
    from arche.doc._documents import _quiet
    from arche.doc._parties import parties
    from arche.report import review_pack
    from arche.resolve import reconcile

    if entity not in _KIND:
        raise ValueError(f"entity must be one of {sorted(_KIND)}, got {entity!r}")
    kind = _KIND[entity]
    records: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    seen: dict[str, int] = {}
    for path in _sources(source):
        with (_quiet() if quiet else nullcontext()):
            found = [p for p in parties(parse(str(path)), backend=backend) if p.role == role]
        party = next((p for p in found if p.kind == kind), None)
        if party is None:
            why = (f"no {role} found" if not found
                   else f"the {role} is {'an ' if found[0].kind == 'organisation' else 'a '}"
                        f"{found[0].kind or 'party of unknown kind'}, not a {kind}")
            skipped.append({"document": path.name, "reason": why})
            continue
        doc_id = path.stem if path.stem not in seen else f"{path.stem}~{seen[path.stem] + 1}"
        seen[path.stem] = seen.get(path.stem, 0) + 1
        records.append(party.as_record(id=doc_id, document=path.name))
    if len(records) < 2:
        raise ValueError(f"{len(records)} document(s) name a {kind} as {role}; a review "
                         "queue needs two. Skipped: "
                         + "; ".join(f"{s['document']} ({s['reason']})" for s in skipped))

    # Every pair once: a self-join, keeping a < b in document order.
    result = reconcile(records, records, entity=entity, block=None)
    order = {r["id"]: i for i, r in enumerate(records)}
    result["matches"] = [m for m in result["matches"] if order[m["a_id"]] < order[m["b_id"]]]
    result["count"] = len(result["matches"])

    manifest = review_pack(result, records, records, out_dir=out_dir, entity=entity,
                           reveal=reveal, meta={"source": "arche.doc.parties", "role": role})
    ledger_path = None
    if ledger is not None:
        from arche.ledger import Ledger

        book = Ledger(str(ledger)) if isinstance(ledger, (str, Path)) else ledger
        try:
            book.record_batch(result, records, records,
                              call={"entity": entity, "id_field": "id", "block": None})
        finally:
            if book is not ledger:
                book.close()
        ledger_path = str(ledger) if isinstance(ledger, (str, Path)) else None
    return {**manifest, "records": [_shown(r, reveal) for r in records],
            "skipped": skipped, "ledger": ledger_path}


def _shown(record: Mapping[str, Any], reveal: bool) -> dict[str, Any]:
    """Which fields a document contributed; the values only when revealed."""
    if reveal:
        return dict(record)
    return {"id": record["id"], "document": record["document"],
            "fields": sorted(k for k in record if k not in ("id", "document"))}


__all__ = ["review_parties"]
