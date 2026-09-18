# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Shipped Splink recipes: a configuration per entity, written by hand, held in CI.

    from arche.resolve import reconcile
    from arche.resolve.recipes import PERSON

    result = reconcile(a, b, backend="splink", splink_settings=PERSON)

Why recipes and not derivation
------------------------------
``splink_settings="derive"`` infers a Splink configuration from an arche
comparator pack. It was measured on three datasets and was wrong in a
different way on each (no date format, uncosted blocking keys, coerced
coordinates), and structurally a derived configuration can order pairs but
cannot calibrate them -- see :mod:`arche.resolve._splink_backend`. A recipe
is the other answer: one hand-written ``SettingsCreator`` and training plan
per entity, carrying the **column schema it expects**, benchmarked on a
labelled set, and gated so it cannot drift under its own name.

A recipe says what it needs. ``PERSON`` reads ``given_name`` and ``surname``
as two columns, not one ``name`` blob, because Splink learns separate m and u
for each and that is where its Febrl advantage comes from; it reads
``date_of_birth`` as ``%Y%m%d`` because a date comparison without a format
trains nothing. Records that do not carry these columns should not be handed
to this recipe; ``columns`` is the contract and :func:`Recipe.check` says so
before Splink sees a frame.

A recipe withholds. Q1 on Abt-Buy measured the difference between giving
Splink every column and giving it only the ones the pack declares
identity-bearing as F1 0.537 against 0.785: descriptive similarity taught EM
to stop caring about the identifier. Which fields the estimator may learn from
is the recipe's decision, and it is the more important half of it.

The threshold is part of the recipe. A Splink probability has no portable
scale, so each recipe ships the operating point it was benchmarked at and the
benchmark that set it.

What is here today
------------------
``PERSON`` -- Febrl 4 without the identifier, Splink's own published recipe
with the u-sampling seeded. Precision 1.0000, recall 0.9530 at p >= 0.99,
gated in ``data/scripts/benchmark_gate.py`` beside the engine's own numbers.
More follow one at a time, each with its benchmark: organisation on the
supplier world, place on the England schools link, product on Abt-Buy.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Recipe:
    """One hand-written Splink configuration, with everything a run needs."""

    name: str
    entity: str
    #: The columns the settings read. A record without them is refused.
    columns: tuple[str, ...]
    #: Builds the ``SettingsCreator``. Imports splink lazily so the base
    #: wheel never pulls it.
    settings: Callable[[], Any]
    #: Trains a built ``Linker``. ``seed`` makes the u-sampling reproducible.
    train: Callable[[Any, int], None]
    #: The operating point the recipe was benchmarked at, and its review band.
    threshold: float
    review_margin: float
    #: Where the numbers come from, so a reader can re-run them.
    benchmark: str
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def digest(self) -> str:
        """A content id for the pins: the recipe's declaration, not its code.

        Two runs under one digest read the same columns at the same threshold
        with the same declared shape. A change to the settings function is a
        change to ``name`` or ``notes`` by convention, and the benchmark gate
        is what catches the one that is not.
        """
        payload = {"name": self.name, "entity": self.entity, "columns": self.columns,
                   "threshold": self.threshold, "review_margin": self.review_margin,
                   "benchmark": self.benchmark}
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return "sha256:" + hashlib.sha256(raw).hexdigest()[:16]

    def check(self, records: Sequence[dict], *, side: str = "records") -> None:
        """Refuse records that do not carry the recipe's columns.

        Every column must be present on at least one record; a column absent
        from all of them would make Splink compare NULL against NULL and call
        that agreement, which is the failure a declared schema exists to stop.
        """
        if not records:
            return
        seen = set()
        for r in records:
            seen.update(k for k, v in r.items() if v not in (None, ""))
        missing = [c for c in self.columns if c not in seen]
        if missing:
            raise ValueError(
                f"recipe {self.name!r} reads {list(self.columns)}; {side} carry no "
                f"{missing}. The recipe's schema is its contract -- rename your "
                f"columns to match, or write your own SettingsCreator."
            )


# --------------------------------------------------------------- person ------

PERSON_COLUMNS = ("given_name", "surname", "date_of_birth", "street_number",
                  "address_1", "postcode", "state")


def _person_settings():
    import splink.comparison_library as cl
    from splink import SettingsCreator, block_on

    return SettingsCreator(
        link_type="link_only",
        comparisons=[
            cl.NameComparison("given_name").configure(term_frequency_adjustments=True),
            cl.NameComparison("surname").configure(term_frequency_adjustments=True),
            cl.DateOfBirthComparison("date_of_birth", input_is_string=True,
                                     datetime_format="%Y%m%d"),
            cl.ExactMatch("street_number").configure(term_frequency_adjustments=True),
            cl.DamerauLevenshteinAtThresholds("postcode", [1, 2]).configure(
                term_frequency_adjustments=True),
        ],
        blocking_rules_to_generate_predictions=[
            block_on("given_name", "surname"),
            "l.given_name = r.surname and l.surname = r.given_name",
            block_on("date_of_birth"),
            block_on("state", "address_1"),
            block_on("street_number", "address_1"),
            block_on("postcode"),
        ],
        retain_intermediate_calculation_columns=False,
    )


def _person_train(linker, seed: int) -> None:
    from splink import block_on

    linker.training.estimate_probability_two_random_records_match(
        [block_on("given_name", "surname", "date_of_birth")], recall=0.8)
    # Seeded: the unseeded version of this line measured 0.9528, 0.9534 and
    # 0.9536 recall on different days, and a gate cannot hold a number that
    # moves on its own.
    linker.training.estimate_u_using_random_sampling(max_pairs=2e6, seed=seed)
    for rule in (block_on("date_of_birth"), block_on("postcode")):
        linker.training.estimate_parameters_using_expectation_maximisation(rule)


PERSON = Recipe(
    name="person/febrl-v1",
    entity="person",
    columns=PERSON_COLUMNS,
    settings=_person_settings,
    train=_person_train,
    threshold=0.99,
    review_margin=0.79,
    benchmark="datasets/names_dataops/bench_splink_febrl.py (no soc_sec_id)",
    notes=(
        "Splink's own published Febrl 4 configuration, identifier withheld.",
        "given_name and surname are separate columns on purpose; one `name` "
        "blob loses the per-field m and u that carry this recipe's recall.",
        "date_of_birth is %Y%m%d; without the format the date trains nothing.",
    ),
)

RECIPES: dict[str, Recipe] = {PERSON.name: PERSON, "person": PERSON}

__all__ = ["PERSON", "PERSON_COLUMNS", "RECIPES", "Recipe"]
