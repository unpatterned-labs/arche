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
Three recipes, each with the benchmark that set its numbers and a flag that
says whether ``backend="auto"`` may choose it:

``PERSON`` -- Febrl 4 without the identifier, Splink's own published recipe
with the u-sampling seeded. 4,761 true / 0 false at p >= 0.99. ``auto=True``:
Splink won every person benchmark.

``PLACE`` -- name and coordinates, the configuration that won the England
schools link (278 true / 0 false at p >= 0.9 against the engine's 278 / 32)
and the Nigerian register (190 / 0 against 146 / 2). ``auto=True``. The
threshold is 0.9 and not 0.5 because at 0.5 on a 1,200-record batch the same
model merges 368 of 400 known-different schools; at 0.9 it merges 2.

``PRODUCT`` -- Abt-Buy, the *identity* recipe: the extracted model code and
the brand, and **nothing else** -- the title is withheld from the estimator.
Given the title too, precision collapses from 0.94 to 0.41. 732 true / 49
false at p >= 0.5. ``auto=False``: the engine wins this benchmark (741 / 22),
so auto keeps the engine for products and the recipe is there to be asked for.
It is the clearest example of what a recipe is *for*: it needs a ``prepare``
step (arche's representation, run before Splink sees a frame) and it is the
withholding that makes it work.
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
    #: Builds the ``SettingsCreator`` for a link type. Imports splink lazily
    #: so the base wheel never pulls it. ``reconcile(records, records)`` is
    #: a dedupe and ``reconcile(a, b)`` a link; the same comparisons serve
    #: both, but Splink must be told which, so the recipe takes it.
    settings: Callable[[str], Any]
    #: Trains a built ``Linker``. ``seed`` makes the u-sampling reproducible.
    train: Callable[[Any, int], None]
    #: The operating point the recipe was benchmarked at, and its review band.
    threshold: float
    review_margin: float
    #: Where the numbers come from, so a reader can re-run them.
    benchmark: str
    notes: tuple[str, ...] = field(default_factory=tuple)
    #: Turns the caller's records into the columns the recipe reads, when
    #: those are derived rather than given -- a product title becomes a code
    #: and a brand. ``None`` means the records already carry the columns.
    #: Runs before :meth:`check`, so the contract is on what comes out.
    prepare: Callable[[Sequence[dict]], list[dict]] | None = None
    #: The columns a caller must supply *before* ``prepare``. Defaults to
    #: ``columns`` when there is no prepare step.
    input_columns: tuple[str, ...] | None = None
    #: Whether ``backend="auto"`` may choose this recipe. True only where
    #: Splink beat the engine on the recipe's own benchmark; a recipe that
    #: lost stays available by name and is never picked silently.
    auto: bool = True

    @property
    def requires(self) -> tuple[str, ...]:
        """What a caller's records must carry."""
        return self.input_columns if self.input_columns is not None else self.columns

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
        """Refuse records that do not carry what the recipe requires.

        Every required column must be present on at least one record; a
        column absent from all of them would make Splink compare NULL against
        NULL and call that agreement, which is the failure a declared schema
        exists to stop.
        """
        if not records:
            return
        seen = set()
        for r in records:
            seen.update(k for k, v in r.items() if v not in (None, ""))
        missing = [c for c in self.requires if c not in seen]
        if missing:
            raise ValueError(
                f"recipe {self.name!r} reads {list(self.requires)}; {side} carry no "
                f"{missing}. The recipe's schema is its contract -- rename your "
                f"columns to match, or write your own SettingsCreator."
            )


# --------------------------------------------------------------- person ------

PERSON_COLUMNS = ("given_name", "surname", "date_of_birth", "street_number",
                  "address_1", "postcode", "state")


def _person_settings(link_type: str = "link_only"):
    import splink.comparison_library as cl
    from splink import SettingsCreator, block_on

    return SettingsCreator(
        link_type=link_type,
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

# --------------------------------------------------------------- place --------

PLACE_COLUMNS = ("name", "lat", "lon")


def _place_settings(link_type: str = "link_only"):
    import splink.comparison_library as cl
    from splink import SettingsCreator, block_on

    return SettingsCreator(
        link_type=link_type,
        comparisons=[
            cl.NameComparison("name").configure(term_frequency_adjustments=True),
            cl.DistanceInKMAtThresholds("lat", "lon", [0.1, 0.5, 2, 10]),
        ],
        blocking_rules_to_generate_predictions=[
            block_on("name"),
            block_on("substr(name,1,8)"),
            block_on("round(lat,2)", "round(lon,2)"),
            block_on("round(lat,1)", "round(lon,1)"),
        ],
        retain_intermediate_calculation_columns=False,
    )


def _place_train(linker, seed: int) -> None:
    from splink import block_on

    linker.training.estimate_probability_two_random_records_match(
        [block_on("name")], recall=0.5)
    linker.training.estimate_u_using_random_sampling(max_pairs=2e6, seed=seed)
    # The coordinate rule trains the name; the name rule trains the distance.
    # Never the other way round: a comparison whose column is in the blocking
    # rule is untrainable in that session, and the first England run scored
    # a model whose name levels were still at their defaults.
    for rule in (block_on("round(lat,2)", "round(lon,2)"), block_on("name")):
        linker.training.estimate_parameters_using_expectation_maximisation(rule)


def _place_prepare(records: Sequence[dict]) -> list[dict]:
    """Coordinates as numbers. arche's own place records carry them as strings."""
    out = []
    for r in records:
        row = dict(r)
        for key in ("lat", "lon"):
            try:
                row[key] = float(r[key]) if r.get(key) not in (None, "") else None
            except (TypeError, ValueError):
                row[key] = None
        out.append(row)
    return out


PLACE = Recipe(
    name="place/name-coords-v1",
    entity="place",
    columns=PLACE_COLUMNS,
    prepare=_place_prepare,
    settings=_place_settings,
    train=_place_train,
    threshold=0.9,
    review_margin=0.4,
    benchmark="datasets/names_dataops/bench_splink_england_schools.py; "
              "bench_splink_nigeria.py",
    notes=(
        "Name with term frequency, distance at 100 m / 500 m / 2 km / 10 km.",
        "0.9, not 0.5: on a 1,200-record batch with nothing to learn from, the "
        "same model at 0.5 merges 368 of 400 known-different schools; at 0.9, 2.",
        "lat and lon must be numeric; a string coordinate makes DuckDB refuse "
        "radians(VARCHAR), which is how the first derived run died.",
    ),
)


# --------------------------------------------------------------- product ------

PRODUCT_INPUT = ("name",)
PRODUCT_COLUMNS = ("code1", "codes", "brand", "specs")


def _product_prepare(records: Sequence[dict]) -> list[dict]:
    """arche's representation, as the columns Splink is allowed to see.

    The title itself is NOT among them. Given it, EM learns that similar
    titles are evidence of identity, which for products they are not, and
    prices "no shared code" at -0.09 bits instead of -4.13 (Q1, plan §7f).
    """
    import re

    from arche.resolve._productcode import extract_product_code_candidates, extract_specs

    word = re.compile(r"[a-z0-9]+")
    out = []
    for r in records:
        title = str(r.get("name") or "")
        tokens = word.findall(title.casefold())
        codes = sorted(extract_product_code_candidates(title, category="electronics"))
        specs = sorted(f"{u}:{v:g}" for u, vals in
                       extract_specs(title, "electronics").items() for v in vals)
        row = {k: v for k, v in r.items() if k != "name"}
        row.update({"code1": codes[0] if codes else None, "codes": codes,
                    "brand": tokens[0] if tokens else None, "specs": specs})
        out.append(row)
    return out


def _product_settings(link_type: str = "link_only"):
    import splink.comparison_level_library as cll
    import splink.comparison_library as cl
    from splink import SettingsCreator, block_on

    code = cl.CustomComparison(output_column_name="code", comparison_levels=[
        cll.NullLevel("code1"),
        cll.ExactMatchLevel("code1").configure(tf_adjustment_column="code1"),
        cll.ArrayIntersectLevel("codes", min_intersection=1),
        cll.ElseLevel(),
    ])
    spec = cl.CustomComparison(output_column_name="spec", comparison_levels=[
        cll.CustomLevel("len(specs_l) = 0 OR len(specs_r) = 0",
                        label_for_charts="a spec missing on one side"
                        ).configure(is_null_level=True),
        cll.ArrayIntersectLevel("specs", min_intersection=1),
        cll.ElseLevel(),
    ])
    return SettingsCreator(
        link_type=link_type,
        comparisons=[code,
                     cl.ExactMatch("brand").configure(term_frequency_adjustments=True),
                     spec],
        blocking_rules_to_generate_predictions=[block_on("code1"), block_on("brand")],
        retain_intermediate_calculation_columns=False,
    )


def _product_train(linker, seed: int) -> None:
    from splink import block_on

    linker.training.estimate_probability_two_random_records_match(
        [block_on("code1")], recall=0.7)
    linker.training.estimate_u_using_random_sampling(max_pairs=2e6, seed=seed)
    for rule in (block_on("brand"), block_on("code1")):
        linker.training.estimate_parameters_using_expectation_maximisation(rule)


PRODUCT = Recipe(
    name="product/identity-v1",
    entity="product_electronics",
    columns=PRODUCT_COLUMNS,
    input_columns=PRODUCT_INPUT,
    prepare=_product_prepare,
    settings=_product_settings,
    train=_product_train,
    threshold=0.5,
    review_margin=0.3,
    benchmark="datasets/products_dataops/bench_splink_abt_buy.py (identity recipe)",
    auto=False,
    notes=(
        "Code and brand only. The title is withheld on purpose; with it, "
        "precision falls from 0.94 to 0.41 on Abt-Buy.",
        "auto=False: the engine's product pack wins Abt-Buy (741 / 22 against "
        "this recipe's 732 / 49), so auto keeps the engine. Ask for the recipe.",
        "The pack's guarantees (different code => different, the stop list) "
        "stay outside the model; a learned refutation moved by 3 bits between "
        "two configurations and is not a guarantee.",
    ),
)

RECIPES: dict[str, Recipe] = {
    PERSON.name: PERSON, "person": PERSON,
    PLACE.name: PLACE, "place": PLACE,
    PRODUCT.name: PRODUCT, "product_electronics": PRODUCT,
}

__all__ = ["PERSON", "PERSON_COLUMNS", "PLACE", "PLACE_COLUMNS", "PRODUCT",
           "PRODUCT_COLUMNS", "PRODUCT_INPUT", "RECIPES", "Recipe"]
