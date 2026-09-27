# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""One way to open a world and look at it.

    from arche_synthetic import load

    w = load("data/synthetic/worlds/ng_supplier_v0")
    w.describe()                      # what this is, in one block
    w.observations                    # what a matcher is given
    w.differences                     # why two records disagree, labelled
    w.frame("differences")            # the same, as a DataFrame

Three world families ship here and they answer different questions, so they
have different files: the supplier and artist worlds carry observations and
truth, the place worlds carry a master sheet and delivery requests. Before
this module each had its own loader and asking the wrong one for the wrong
world produced ``FileNotFoundError: places_v0/observations.parquet``, which
tells a reader nothing about what they should have called instead.

:func:`load` reads ``manifest.yaml`` and hands back a :class:`World` whose
``kind`` says which family it is and whose tables are whatever that family
has. It is a *reading* API. :class:`~arche_synthetic.evaluate.Benchmark` and
:class:`~arche_synthetic.places.PlaceBenchmark` are the *scoring* APIs and are
unchanged; they are what the benchmark arms use, and `World.benchmark()` hands
you the right one.

Why a separate module rather than a method on ``Benchmark``: scoring needs the
truth collapsed into pair sets, which is exactly the transformation that makes
the labelled rows unreadable. ``Benchmark`` folds all 32,596 rows of
``differences`` into two dicts of pairs and drops ``attribute``, ``entity_id``
and ``event_id``, so the one column this project exists for could not be seen
through the public API at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Which tables each family carries, and which of them a matcher may see.
#: The second element is the file a matcher is given; everything else is truth.
_FAMILIES: dict[str, tuple[tuple[str, ...], str]] = {
    "records": (("observations", "truth", "differences", "events", "collisions"),
                "observations"),
    "places": (("sheet", "requests", "truth"), "requests"),
}


@dataclass
class World:
    """A generated world, opened for reading.

    ``kind`` is ``"records"`` (a supplier or artist world) or ``"places"``.
    Every table is a ``list[dict]``; ``frame()`` gives the same rows as a
    pandas DataFrame when pandas is installed.
    """

    path: Path
    kind: str
    manifest: dict[str, Any]
    tables: dict[str, list[dict[str, Any]]] = field(repr=False, default_factory=dict)

    # -- the tables, by the name the family uses --------------------------

    def __getattr__(self, name: str) -> list[dict[str, Any]]:
        # `tables` is set in __init__, so a miss here means an unknown name.
        tables = self.__dict__.get("tables", {})
        if name in tables:
            return tables[name]
        known = ", ".join(sorted(tables)) or "none"
        raise AttributeError(
            f"{self.pack!r} has no table {name!r}; it has: {known}"
            if "manifest" in self.__dict__ else f"no table {name!r}")

    @property
    def pack(self) -> str:
        return self.manifest.get("world_pack") or self.manifest.get("world_id", "?")

    @property
    def seed(self) -> int | None:
        return self.manifest.get("seed")

    @property
    def given_to_a_matcher(self) -> str:
        """The one table a matcher is allowed to read. Everything else is truth."""
        return _FAMILIES[self.kind][1]

    @property
    def truth(self) -> dict[str, str]:
        """``record_id`` to the entity it really refers to.

        Only on a ``records`` world. A place world's truth is one row per
        (request, role) and is in ``w.tables["truth"]``.
        """
        if self.kind != "places":
            return {r["record_id"]: r["truth_entity_id"] for r in self.tables["truth"]}
        # TypeError, not AttributeError: a property that raises AttributeError
        # is swallowed by `__getattr__` below, which would then find the raw
        # `truth` table and hand it back as though nothing had gone wrong.
        raise TypeError(
            "a places world's truth is one row per (request_id, role), not per "
            'record; use w.tables["truth"]')

    # -- reading ------------------------------------------------------------

    def frame(self, table: str):
        """One table as a pandas DataFrame.

        pandas is not a dependency of the generator, deliberately: writing a
        world needs pyarrow and nothing else. It is what a person reads with,
        so this is the one place that asks for it, and says so plainly when it
        is missing rather than raising ``ModuleNotFoundError`` from a stack
        frame the caller did not write.
        """
        if table not in self.tables:
            known = ", ".join(sorted(self.tables))
            raise KeyError(f"{self.pack!r} has no table {table!r}; it has: {known}")
        try:
            import pandas as pd
        except ImportError:  # pragma: no cover - exercised without pandas
            raise ImportError(
                "frame() needs pandas: pip install pandas. The tables are "
                f"plain dicts without it: w.{table}[0].keys()") from None
        return pd.DataFrame(self.tables[table])

    def counts(self) -> dict[str, int]:
        return {name: len(rows) for name, rows in sorted(self.tables.items())}

    def describe(self) -> str:
        """What this world is, printed. Also returned, for a notebook cell."""
        lines = [
            f"{self.pack}  seed {self.seed}  ({self.kind} world)",
            f"  path        {self.path}",
            "  tables      " + ", ".join(f"{n} {c:,}" for n, c in self.counts().items()),
            f"  matcher sees  {self.given_to_a_matcher}.parquet; everything else is truth",
        ]
        if self.kind == "places":
            renderings = (self.manifest.get("counts") or {}).get("renderings")
            if renderings:
                lines.append("  renderings  " + ", ".join(
                    f"{k} {v}" for k, v in sorted(renderings.items())))
        else:
            by_kind = self.difference_counts()
            if by_kind:
                lines.append("  disagreements by kind  " + ", ".join(
                    f"{k} {v:,}" for k, v in sorted(by_kind.items())))
        for entry in self.manifest.get("provenance", [])[:1]:
            lines.append(f"  provenance  {entry.get('asset')}: {entry.get('class')}")
        print("\n".join(lines))

    def difference_counts(self, by: str = "difference_kind") -> dict[str, int]:
        """How many labelled disagreements of each kind, or each cause.

        ``by="cause"`` is the column no other entity-resolution benchmark has:
        not *that* two records disagree but *why*, so a matcher can be scored
        on the ones where both records are true.
        """
        counts: dict[str, int] = {}
        for row in self.tables.get("differences", []):
            key = row.get(by)
            if key is not None:
                counts[key] = counts.get(key, 0) + 1
        return counts

    def records_of(self, entity_id: str) -> list[dict[str, Any]]:
        """Every observation of one entity, oldest first.

        The way to see a relocation or a rename: the same entity, observed by
        four source systems at different times, disagreeing for reasons the
        ``differences`` table names.
        """
        if self.kind == "places":
            raise AttributeError("a places world has requests, not entity observations")
        wanted = {r["record_id"] for r in self.tables["truth"]
                  if r["truth_entity_id"] == entity_id}
        return sorted((o for o in self.tables["observations"] if o["record_id"] in wanted),
                      key=lambda o: (o.get("observed_at") or "", o["record_id"]))

    def why(self, record_a: str, record_b: str) -> list[dict[str, Any]]:
        """Every labelled reason these two records disagree."""
        return [r for r in self.tables.get("differences", [])
                if {r["observation_a"], r["observation_b"]} == {record_a, record_b}]

    # -- scoring, when you want it -------------------------------------------

    def benchmark(self):
        """The scoring API for this family: ``Benchmark`` or ``PlaceBenchmark``."""
        if self.kind == "places":
            from .places import PlaceBenchmark

            return PlaceBenchmark.load(self.path)
        from .evaluate import Benchmark

        return Benchmark.load(self.path)


def worlds_dir() -> Path:
    """Where the shipped worlds are, derived from the installed package.

    Lets a caller name a world without knowing where the repository root is,
    and lets an example run from any working directory.
    """
    return Path(__file__).resolve().parent.parent / "worlds"


def available() -> list[str]:
    """The shipped worlds, by name. Empty if the package is installed alone."""
    directory = worlds_dir()
    if not directory.is_dir():
        return []
    return sorted(p.name for p in directory.iterdir()
                  if (p / "manifest.yaml").is_file())


def load(world: str | Path) -> World:
    """Open a generated world for reading, whichever family it is.

    ``world`` is a path, or the bare name of a shipped world: ``load("artists_v0")``
    finds it beside the package, so a caller does not need to know where the
    repository root is and an example runs from any directory. A path is tried
    first, so a local world of the same name always wins.
    """
    import yaml

    path = Path(world)
    if not (path / "manifest.yaml").is_file():
        packaged = worlds_dir() / str(world)
        if (packaged / "manifest.yaml").is_file():
            path = packaged
    manifest_path = path / "manifest.yaml"
    if not manifest_path.is_file():
        known = available()
        raise FileNotFoundError(
            f"{path} is not a generated world: no manifest.yaml. "
            + (f"Shipped worlds: {', '.join(known)}. " if known else "")
            + f"Generate one with `python -m arche_synthetic --world-pack "
            f"ng_supplier_v0 --out {path}` (run it from data/synthetic).")
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))

    kind = "places" if (path / "sheet.parquet").is_file() else "records"
    import pyarrow.parquet as pq

    tables: dict[str, list[dict[str, Any]]] = {}
    for name in _FAMILIES[kind][0]:
        file = path / f"{name}.parquet"
        if file.is_file():                      # `events` and `collisions` are optional
            tables[name] = pq.read_table(file).to_pylist()
    return World(path=path, kind=kind, manifest=manifest, tables=tables)


__all__ = ["World", "available", "load", "worlds_dir"]
