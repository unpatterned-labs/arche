# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The Splink arm (B9 S4) — a second, independent engine on the same world.

Splink is the reference probabilistic linker: Fellegi-Sunter with parameters
estimated from the data by expectation-maximisation. It matters here for one
reason above all — **until a second engine that we did not write runs on this
data, the benchmark says how four of our own configurations behave, not how
entity resolution behaves.** That is also the trigger for cutting the separate
repository.

Two things this module is careful about, both learned the hard way.

**Seed the u-estimation.** ``estimate_u_using_random_sampling`` samples, and
unseeded it moves: an earlier arche benchmark quoted a Febrl recall of 0.9210
as a constant and re-running the same recipe twice in one session gave 0.9534
and 0.9528. A stale or unseeded reference makes whatever it is compared with
look better or worse than it is. The seed is fixed and recorded, and
``--splink-repeats`` re-runs with different seeds to report the spread rather
than one flattering decimal.

**Cut on probability, not on a decision.** Splink emits ``match_probability``
and has no third answer. arche emits ``decision in {match, review}`` and its
gate demotes a pair to ``review`` *without lowering the score*, so cutting
arche at a score threshold once reported 398 false merges where the engine's
own decision reported 2. Each engine is scored on the vocabulary it actually
emits; that is why this arm is a separate module rather than a flag.
"""

from __future__ import annotations

import time
from typing import Any

from arche_synthetic.evaluate import Predictions, pair

#: The probability at which a Splink pair is counted as a claim.
#:
#: **0.5, which is the model's own decision boundary** -- above it the model
#: says these two are more likely one thing than two. The first version of this
#: arm used 0.99, imported from the existing Febrl benchmark, and that was the
#: same mistake this module's docstring warns about in the other direction:
#: imposing an arche-flavoured caution on an engine that does not have one.
#: Measured on this world, the difference is not small:
#:
#:     t=0.50   recall 0.731   precision 0.940
#:     t=0.90   recall 0.259   precision 1.000
#:     t=0.99   recall 0.207   precision 1.000
#:
#: The sweep is reported in every run's notes rather than hidden behind one
#: decimal, because a single threshold is a policy choice and the reader's may
#: differ from ours.
DEFAULT_THRESHOLD = 0.5

#: Fixed so the arm is reproducible. See the module docstring.
DEFAULT_SEED = 42


def _frame(observations: list[dict[str, Any]]):
    """Records as Splink should be given them: normalised.

    The first version of this arm handed Splink the raw strings and scored
    **0.000 on relocated suppliers** -- not because Splink cannot link them but
    because `block_on` is case-sensitive and 57% of the representation
    differences in this world are a source that stores its records IN CAPITALS.
    Every block key broke on case alone, blocking recall was 0.404, and the arm
    was measuring my configuration rather than the engine.

    Normalising before loading is what every Splink user does, so it is what a
    fair arm does. A badly configured competitor is worse than no competitor:
    it makes whatever it is compared against look good for a reason that has
    nothing to do with the comparison.
    """
    import pandas as pd

    from arms import normalise

    def lower(value: str | None) -> str | None:
        return value.lower().strip() if value else None

    rows = []
    for o in observations:
        name = normalise(o.get("name")) or None
        rows.append({
            "unique_id": o["record_id"],
            "name": name,
            # A short prefix of the normalised name, so a blocking rule
            # survives a dropped legal suffix and a changed city.
            "name_head": name[:4] if name else None,
            "registration_id": (o.get("rc_number") or "").upper() or None,
            "address": lower(o.get("address")),
            "city": lower(o.get("city")),
            "phone": "".join(c for c in (o.get("phone") or "") if c.isdigit()) or None,
        })
    return pd.DataFrame(rows)


def _settings():
    import splink.comparison_library as cl
    from splink import SettingsCreator, block_on

    return SettingsCreator(
        link_type="dedupe_only",
        comparisons=[
            # Term-frequency adjustment is the whole reason a Fellegi-Sunter
            # linker belongs on this data: the surnames are Zipf-drawn, so
            # agreeing on a common one is weak evidence and agreeing on a rare
            # one is strong. A comparator that cannot express that difference
            # is the gap this world was built to expose.
            cl.NameComparison("name").configure(term_frequency_adjustments=True),
            cl.ExactMatch("registration_id").configure(term_frequency_adjustments=True),
            cl.LevenshteinAtThresholds("address", [2, 5]),
            cl.ExactMatch("city").configure(term_frequency_adjustments=True),
            cl.ExactMatch("phone"),
        ],
        # Deliberately looser than the first attempt. A rule that keys on the
        # city cannot retrieve a supplier that moved, and one that keys on a
        # long name prefix cannot retrieve one that was renamed -- so the set
        # has to include rules that survive each kind of change this world
        # generates, or the arm measures the blocker and reports it as recall.
        blocking_rules_to_generate_predictions=[
            block_on("registration_id"),
            block_on("name_head"),
            block_on("phone"),
            block_on("city", "substr(address, 1, 6)"),
        ],
        retain_intermediate_calculation_columns=False,
    )


def _train(linker, seed: int) -> None:
    from splink import block_on

    linker.training.estimate_probability_two_random_records_match(
        [block_on("registration_id"), block_on("name", "city")], recall=0.8)
    linker.training.estimate_u_using_random_sampling(max_pairs=1e6, seed=seed)
    for rule in (block_on("city"), block_on("name_head")):
        linker.training.estimate_parameters_using_expectation_maximisation(rule)


def splink_arm(observations: list[dict[str, Any]], *,
               threshold: float = DEFAULT_THRESHOLD,
               seed: int = DEFAULT_SEED,
               truth_pairs=None) -> Predictions:
    """One Splink run over the world, cut at ``threshold``."""
    import logging

    from splink import DuckDBAPI, Linker

    logging.getLogger("splink").setLevel(logging.ERROR)

    frame = _frame(observations)
    started = time.perf_counter()
    linker = Linker(frame, _settings(), db_api=DuckDBAPI())
    _train(linker, seed)
    predictions = linker.inference.predict(threshold_match_probability=0.01)
    df = predictions.as_pandas_dataframe()
    seconds = time.perf_counter() - started

    candidates = {pair(a, b) for a, b in
                  zip(df["unique_id_l"], df["unique_id_r"], strict=False)}
    kept = df[df["match_probability"] >= threshold]
    pairs = {pair(a, b) for a, b in
             zip(kept["unique_id_l"], kept["unique_id_r"], strict=False)}
    sweep = {str(t): int((df["match_probability"] >= t).sum())
             for t in (0.5, 0.9, 0.95, 0.99)}
    return Predictions(
        arm="splink", pairs=pairs, candidates=candidates, seconds=seconds,
        notes={"threshold": threshold, "seed": seed,
               "scored_pairs": int(len(df)),
               "claims_at_threshold": sweep,
               "note": ("candidates are the pairs Splink scored above 0.01, so "
                        "blocking recall is a lower bound on what its blocking "
                        "rules retrieved")})


def splink_spread(observations, *, repeats: int = 3, threshold: float = DEFAULT_THRESHOLD,
                  seeds: tuple[int, ...] = (42, 43, 44)) -> list[Predictions]:
    """The same recipe under several seeds.

    ``estimate_u_using_random_sampling`` samples; one decimal from one seed is
    not a measurement. Reporting the spread is the difference between a number
    and a claim.
    """
    return [splink_arm(observations, threshold=threshold, seed=s)
            for s in seeds[:repeats]]


__all__ = ["DEFAULT_SEED", "DEFAULT_THRESHOLD", "splink_arm", "splink_spread"]
