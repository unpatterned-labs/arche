# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Writing the benchmark out — and refusing to write a broken one.

**The contract is these files, not a Python class.** A Splink user, a Zingg
user, an R user or somebody with a SQL prompt has to be able to consume this
without installing anything of ours; the moment the truth is only readable
through our own dataclasses, matcher-neutrality is gone and the benchmark is
only useful to us. So: Parquet with documented columns, a JSON Schema beside
each file, and a manifest that says how the data was made.

The two invariants are enforced **here, at write time**, not only in a test:

1. ``observations.parquet`` may not contain a truth column. A benchmark that
   ships the answer inside the question is worse than no benchmark, because it
   scores well and says nothing.
2. no observed value may be an entity id. Belt and braces on the same rule --
   a leak through a *value* would pass a column-name check.

A test can be skipped or deleted. A generator that refuses to write cannot.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

from .ids import content_fingerprint
from .world import World

#: Column names that may never appear in the file a matcher is given.
FORBIDDEN = ("entity_id", "truth_entity_id", "truth", "state_index", "difference_kind",
             "cause", "event_id", "applied")

#: The observation columns, in the order they are written.
OBSERVATION_COLUMNS = ("record_id", "source", "observed_at", "name", "rc_number", "tin",
                       "phone", "email", "address", "city", "bank", "account_number",
                       "director_name", "incorporated_on")


class LeakError(AssertionError):
    """The generator produced a dataset that would give the answer away."""


def _rows_observations(world: World) -> list[dict[str, Any]]:
    rows = []
    for o in world.observations:
        row: dict[str, Any] = {"record_id": o.record_id, "source": o.source,
                               "observed_at": o.observed_at.isoformat()}
        for column in OBSERVATION_COLUMNS[3:]:
            row[column] = o.attributes.get(column)
        rows.append(row)
    return rows


def _rows_truth(world: World) -> list[dict[str, Any]]:
    return [{"record_id": o.record_id, "truth_entity_id": o.entity_id,
             "entity_type": "organisation", "source": o.source,
             "state_index": o.state_index}
            for o in world.observations]


def _rows_differences(world: World) -> list[dict[str, Any]]:
    return [asdict(d) for d in world.differences]


def _rows_events(world: World) -> list[dict[str, Any]]:
    """One row per attribute an event moved: flat, joinable, no nested values."""
    rows = []
    for e in world.events:
        for attribute, (old, new) in sorted(e.changes.items()):
            rows.append({"event_id": e.event_id, "entity_id": e.entity_id,
                         "kind": e.kind, "event_at": e.event_at.isoformat(),
                         "attribute": attribute, "old_value": str(old),
                         "new_value": str(new)})
    return rows


def check_no_leak(observations: list[dict[str, Any]], world: World) -> None:
    """Refuse to publish a dataset that carries its own answer."""
    if not observations:
        raise LeakError("no observations to write")
    columns = set(observations[0])
    bad = columns & set(FORBIDDEN)
    if bad:
        raise LeakError(
            f"observations carry truth column(s) {sorted(bad)}; a matcher given this "
            "file could read the answer instead of deciding it")
    entity_ids = set(world.entities)
    for row in observations:
        for column, value in row.items():
            if isinstance(value, str) and value in entity_ids:
                raise LeakError(
                    f"observation {row['record_id']} leaks entity id {value!r} in "
                    f"column {column!r}")


def _schema(name: str, rows: list[dict[str, Any]], required: list[str]) -> dict[str, Any]:
    """A JSON Schema for one file, so the contract is readable without Python."""
    def kind(value: Any) -> str:
        return {int: "integer", float: "number", bool: "boolean"}.get(type(value), "string")

    properties = {}
    for column in rows[0]:
        sample = next((r[column] for r in rows if r[column] is not None), "")
        properties[column] = {"type": [kind(sample), "null"]
                              if column not in required else kind(sample)}
    return {"$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"https://arche.dev/schemas/synthetic/{name}-v0.json",
            "title": name, "type": "object", "required": required,
            "properties": properties, "additionalProperties": False}


def _write_parquet(path: Path, rows: list[dict[str, Any]]) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    columns = list(rows[0])
    table = pa.table({c: pa.array([r.get(c) for r in rows]) for c in columns})
    pq.write_table(table, path)


def write(world: World, out: Path, *, generator_version: str,
          world_pack: str, notes: dict[str, Any] | None = None) -> dict[str, Any]:
    """Write the whole benchmark and return its manifest."""
    out.mkdir(parents=True, exist_ok=True)
    (out / "schema").mkdir(exist_ok=True)

    tables = {
        "observations": (_rows_observations(world), ["record_id", "source", "observed_at"]),
        "truth": (_rows_truth(world), ["record_id", "truth_entity_id"]),
        "differences": (_rows_differences(world),
                        ["difference_id", "observation_a", "observation_b",
                         "attribute", "difference_kind"]),
        "events": (_rows_events(world), ["event_id", "entity_id", "kind", "event_at"]),
    }
    check_no_leak(tables["observations"][0], world)

    fingerprints = {}
    for name, (rows, required) in tables.items():
        if not rows:
            continue
        _write_parquet(out / f"{name}.parquet", rows)
        (out / "schema" / f"{name}.json").write_text(
            json.dumps(_schema(name, rows, required), indent=2) + "\n",
            encoding="utf-8", newline="\n")
        fingerprints[name] = content_fingerprint(rows)

    kinds: dict[str, int] = {}
    for row in tables["differences"][0]:
        kinds[row["difference_kind"]] = kinds.get(row["difference_kind"], 0) + 1

    manifest = {
        "world_id": world.world_id,
        "world_pack": world_pack,
        "seed": world.seed,
        "generator_version": generator_version,
        "schema_version": 0,
        "counts": {
            "entities": {t: len(world.of_type(t))
                         for t in ("organisation", "person", "place")},
            "observations": len(world.observations),
            "events": len(world.events),
            "differences": len(world.differences),
            "difference_kinds": dict(sorted(kinds.items())),
        },
        "content_fingerprints": fingerprints,
        "provenance": world.provenance,
        "invariants": [
            "observations.parquet carries no truth column (enforced at write time)",
            "no observed value is an entity id (enforced at write time)",
            "record_id is a hash of (world_id, source, sequence) and holds no entity "
            "information",
        ],
        **(notes or {}),
    }
    # newline="\n" is not cosmetic: without it Windows writes CRLF into files
    # the repository pins to LF, so a rebuild of an unchanged world shows as a
    # diff and the "identical world" check has to be read past it.
    (out / "manifest.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True),
        encoding="utf-8", newline="\n")
    return manifest


__all__ = ["FORBIDDEN", "LeakError", "OBSERVATION_COLUMNS", "check_no_leak", "write"]
