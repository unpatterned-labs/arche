# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Score a crosswalk with Splink instead of arche's own comparators.

What this is
------------
An adapter, not a translator. The caller brings a Splink configuration; arche
brings everything it puts around a score: per-comparison evidence, refusal, the
distinctive-signal gate, pins that name the trained model and the corpus,
per-edge decision ids, and the review path. The result is the shape
``reconcile`` returns, so ``review_pack``, ``crosswalk_report``, arche studio
and decision-id recomputation keep working unchanged.

    from splink import SettingsCreator, block_on
    import splink.comparison_library as cl

    crosswalk(a, b, id_field="id", backend="splink", threshold=0.99,
              splink_settings=SettingsCreator(
                  link_type="link_only",
                  comparisons=[cl.NameComparison("name"), ...],
                  blocking_rules_to_generate_predictions=[block_on("name")]))

The adapter costs nothing. Handed the same ``SettingsCreator`` and training
recipe the hand-written benchmarks in ``datasets/names_dataops/`` use, it
reproduces their numbers: Febrl 4 without ``soc_sec_id`` recall 0.9530 at
precision 1.0000 against 0.9528 to 0.9534 for the recipe run directly, and 190
of 200 constructed positives with 0 of 400 observed negatives on the Nigerian
school register, which is what that recipe scores too.

Why the caller brings the settings
----------------------------------
This module used to derive a Splink configuration from an arche comparator
pack. It was measured on three datasets and was wrong in a different way on
each one, and each fault was invisible until the next dataset ran:

* Febrl 4: the date comparison was built without ``datetime_format``, could not
  parse ``19151111``, trained nothing, and the strongest signal in the file
  contributed zero.
* ``historical_50k``: blocking keys went in uncosted. ``occupation`` alone is
  639M pairs in one block; the process was killed by the operating system three
  times with no traceback.
* Nigerian schools: coordinates were coerced to strings, DuckDB refused
  ``radians(VARCHAR)``, and once that was fixed the geo comparison still
  trained no m values, because every EM rule keyed on a coordinate column.

The reason is structural rather than a run of bad luck. A pack says "compare
this field as a name". Splink needs the strptime format, the column dtype, the
field cardinality, which columns a blocking key can afford to use, and which
rules to run EM on so that each comparison still varies inside at least one of
them. None of that is in the pack, and some of it is not in the records either:
arche's ``person`` pack compares one ``name`` blob where Splink's own Febrl
recipe compares ``given_name`` and ``surname`` as separate columns and learns
separate m and u for each. That is a schema the caller never supplied, and no
amount of enriching the pack conjures it back.

Two further faults turned up while fixing those three, and they are the reason
derivation is opt-in rather than merely careful. Both were found the same way,
by running the next dataset:

* Choosing the deterministic rule that seeds
  ``probability_two_random_records_match`` by taking the most selective
  blocking rule left the Nigerian positives at 0.8936, just under the 0.9 the
  hand recipe clears, with the ordering identical either way. Seeding it from
  exact agreement on every compared field instead took Nigeria to 190 of 200
  at 0 false, and in the same change took Febrl 4 at p >= 0.99 DOWN from 0.7026
  to 0.5448. The ranking barely moved; the scale did.
* That is the general shape of it. A derived configuration can order pairs
  well and cannot calibrate them, because the calibration is a prior about how
  many true matches the corpus holds and nothing in a record list says.

So derivation is available and is not the default. ``splink_settings="derive"``
opts in, warns, and is documented as best-effort. Read it at a threshold you
swept on your own labels, never at a borrowed one. Measured numbers are in
``datasets/names_dataops/bench_backend_compare.py``; at p >= 0.5 on Febrl 4 it
reaches recall 0.8952 at precision 1.0000, above arche's own engine, and at
p >= 0.99 it reaches 0.5448, well below it. Same run, same edges, same order.

Batch dependence, stated plainly
--------------------------------
Splink trains on the corpus being linked, so the same pair scored in a different
batch can get a different answer. That is not new here: arche's own ``tf``
self-calibrates over the two lists whenever no shipped table exists. What
matters is that the pin says so. A decision from this backend pins the trained
model and the corpus, so two decisions with different pins were scored against
different models and were never expected to agree.

The gate is OFF by default here, on purpose
-------------------------------------------
arche's distinctive-signal gate consumes per-comparator evidence and refuses
when nothing distinctive agreed. Splink emits one probability. Recomputing
arche's own name evidence purely to overrule a model that already priced name
evidence is two correlated rules, and it can be worse than either alone. On the
Nigerian set the gate costs 44 true merges to prevent 2, and queues 393 of 400
pairs. ``gate=True`` is available; turning it on is a decision someone makes
with a measurement in hand.
"""

from __future__ import annotations

import json
import warnings
from collections import Counter
from collections.abc import Callable, Sequence
from typing import Any

# A Splink match probability is a posterior, not a weighted mean of bounded
# similarities. Its scale moves with `probability_two_random_records_match`,
# the prior for how many true matches the corpus holds, so the same number
# means different things on different data. There is therefore no default
# threshold here and `threshold=` is required; see `_NO_THRESHOLD`.
# 0.99 is Splink's own published Febrl cut, kept as a named starting point.
SPLINK_THRESHOLD = 0.99
SPLINK_REVIEW_MARGIN = 0.09          # review down to threshold - 0.09
SPLINK_SEED = 20260816
SPLINK_PAIR_CAP = 1_000_000

_NO_SETTINGS = """\
backend="splink" needs a Splink configuration; arche will not invent one.

  splink_settings=SettingsCreator(...)
      The supported path. You own the comparisons and the blocking rules,
      because you are the one who knows the column dtypes, the date format
      and the field cardinalities. arche owns the evidence, the pins, the
      gate, the decision ids and the review pack.

  splink_settings="derive"
      Best-effort derivation from the arche comparator pack. Opt in with a
      measurement in hand: on Febrl 4 it has measured BELOW arche's own
      engine. See datasets/names_dataops/bench_backend_compare.py.
"""

_NO_THRESHOLD = """\
backend="splink" needs threshold=; there is no portable default.

A Splink match probability is a posterior, and its scale moves with
`probability_two_random_records_match` - the prior for how many true matches
the corpus holds at all. Measured on the two benchmark sets in
datasets/names_dataops/, at p >= 0.99:

  Febrl 4          a hand-written configuration merges 4,765 true pairs
  Nigerian schools the SAME hand-written recipe merges nothing at all,
                   and its own benchmark reports at p >= 0.9

One number cannot serve both. Sweep the threshold on labelled data and pass
what you find. `SPLINK_THRESHOLD` (0.99) is Splink's own published Febrl cut if
you want a starting point.
"""


class SplinkBackendError(RuntimeError):
    """The Splink backend could not produce a result.

    Raised rather than falling back. `classical.py` used to catch bare
    ``Exception`` and return fuzzy output in the same shape, so a caller could
    not tell which algorithm had answered. For a library whose claim is
    auditable decisions that is the worst available behaviour.
    """


def _require_splink() -> tuple[Any, Any]:
    try:
        import duckdb
        import splink
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise SplinkBackendError(
            "the splink backend needs splink and duckdb: "
            "pip install arche-core[resolve]"
        ) from exc
    return splink, duckdb


def _digest(payload: Any) -> str:
    """A full sha256 over canonical JSON, via arche's own hasher.

    Same function the rest of the pins use, so a reader comparing a Splink pin
    against a comparator pin is comparing like with like.
    """
    from arche.ids import content_hash
    return content_hash(payload, prefix="x").split(":")[-1]


def _corpus_digest(list_a: list[dict], list_b: list[dict],
                   columns: Sequence[str]) -> str:
    """Identify the corpus the model was trained on.

    The columns that were compared, in record order, from both sides. A model
    is a function of the data it saw, so a decision that depends on the model
    depends on this.
    """
    return _digest([[{c: str(r.get(c, "")) for c in columns} for r in side]
                    for side in (list_a, list_b)])


# --------------------------------------------------------------- the frame --

def _column_types(list_a: list[dict], list_b: list[dict],
                  columns: Sequence[str]) -> dict[str, str]:
    """Classify each column as ``number`` or ``text`` from the caller's types.

    Read the types the caller already gave us rather than letting pandas infer
    them, because both directions of inference have already broken a run:

    * a sparse text column with mostly empty cells infers as ``float64`` and
      DuckDB then refuses the string function the comparison wants;
    * lat/lon coerced to text breaks ``DistanceInKMAtThresholds`` inside DuckDB
      with ``radians(VARCHAR)``, which is how the ``place`` pack failed the
      first time this ran against it.

    The rule is deterministic and needs no heuristic: a column is numeric only
    if every non-empty value in it is already a Python ``int`` or ``float``.
    One string anywhere in the column makes the whole column text. A postcode
    supplied as ``"01234"`` therefore stays text and keeps its leading zero.
    """
    types: dict[str, str] = {}
    for col in columns:
        numeric, seen = True, False
        for side in (list_a, list_b):
            for record in side:
                value = record.get(col)
                if value is None or value == "":
                    continue
                seen = True
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    numeric = False
                    break
            if not numeric:
                break
        types[col] = "number" if (seen and numeric) else "text"
    return types


def _frame(records: list[dict], columns: Sequence[str], types: dict[str, str],
           id_field: str) -> Any:
    """One Splink input table, with the dtypes ``_column_types`` decided."""
    import pandas as pd

    def cell(value: Any, col: str) -> Any:
        if value is None or value == "":
            return None
        if types[col] == "number":
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
        return str(value)

    frame = pd.DataFrame([
        {"unique_id": str(r.get(id_field, i)),
         **{c: cell(r.get(c), c) for c in columns}}
        for i, r in enumerate(records)
    ], columns=["unique_id", *columns])
    text_cols = [c for c in columns if types[c] == "text"]
    return frame.astype({c: "object" for c in text_cols})


# ------------------------------------------------------------ blocking cost --

def _worst_block(list_a: list[dict], list_b: list[dict],
                 key: Callable[[dict], tuple | None]) -> int:
    """Pairs the commonest value of ``key`` would put in one block.

    This is the same cost bound ``arche.resolve._block`` applies to rare-token
    keys. Bounding only single-field rules is not enough and was measured the
    hard way: on ``historical_50k`` ``occupation`` alone is 639M pairs and gets
    skipped, but ``birth_place`` AND ``occupation`` together were still large
    enough to have the run killed by the operating system, twice, with no
    traceback to show for it. So every candidate key is costed, conjunctions
    and SQL expressions included, and nothing goes in unbounded.
    """
    count_a = Counter(k for k in map(key, list_a) if k is not None)
    if not count_a:
        return 0
    count_b = Counter(k for k in map(key, list_b) if k is not None)
    if not count_b:
        return 0
    return max((n * count_b.get(v, 0) for v, n in count_a.items()), default=0)


def _exact_key(*fields: str) -> Callable[[dict], tuple | None]:
    def key(record: dict) -> tuple | None:
        out = []
        for f in fields:
            value = record.get(f)
            if value is None or value == "":
                return None
            out.append(str(value))
        return tuple(out)
    return key


def _prefix_key(field: str, n: int) -> Callable[[dict], tuple | None]:
    def key(record: dict) -> tuple | None:
        value = str(record.get(field) or "")[:n]
        return (value,) if value else None
    return key


def _token_key(field: str, index: int) -> Callable[[dict], tuple | None]:
    def key(record: dict) -> tuple | None:
        parts = [p for p in str(record.get(field) or "").split(" ") if p]
        if not parts:
            return None
        return (parts[0] if index == 1 else parts[-1],)
    return key


def _total_pairs(list_a: list[dict], list_b: list[dict],
                 key: Callable[[dict], tuple | None]) -> int:
    """Pairs the key generates in total, across every value."""
    count_a = Counter(k for k in map(key, list_a) if k is not None)
    if not count_a:
        return 0
    count_b = Counter(k for k in map(key, list_b) if k is not None)
    return sum(n * count_b.get(v, 0) for v, n in count_a.items())


def _rounded_geo_key(lat: str, lon: str, places: int
                     ) -> Callable[[dict], tuple | None]:
    def key(record: dict) -> tuple | None:
        try:
            return (round(float(record[lat]), places),
                    round(float(record[lon]), places))
        except (KeyError, TypeError, ValueError):
            return None
    return key


# ----------------------------------------------------------- the derivation --

def _date_format(values: Sequence[str]) -> str:
    """Guess the strptime format Splink needs for a date column.

    Splink parses dates with ONE declared format and arche's own comparator
    accepts several, so this bridges them. Getting it wrong is not a small
    error: with an unparseable format the comparison trains no parameters and
    contributes nothing, which cost the derived path 40 points of recall on
    Febrl 4 before it was caught (0.5140 against 0.9210 for a hand-written
    configuration on the same fields).
    """
    import re
    for value in values:
        text = str(value).strip()
        if re.fullmatch(r"\d{8}", text):
            return "%Y%m%d"
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return "%Y-%m-%d"
        if re.fullmatch(r"\d{2}/\d{2}/\d{4}", text):
            return "%d/%m/%Y"
    return "%Y-%m-%d"


def _comparison_for(spec: dict, cl: Any, samples: Sequence[str]) -> Any | None:
    kind, field = spec.get("kind"), spec.get("field")
    if kind in ("name", "placename") and field:
        return cl.NameComparison(field).configure(term_frequency_adjustments=True)
    if kind == "date" and field:
        return cl.DateOfBirthComparison(
            field, input_is_string=True,
            datetime_format=spec.get("datetime_format") or _date_format(samples))
    if kind == "id" and field:
        return cl.DamerauLevenshteinAtThresholds(field, [1, 2])
    if kind in ("email", "phone", "category", "postcode") and field:
        return cl.ExactMatch(field).configure(term_frequency_adjustments=True)
    # `type` and `tftoken` are deliberately unmapped. Both read the NAME column
    # and mean something other than the raw string: `type` is a vocabulary
    # lookup for the facility tier, `tftoken` is term-frequency weighting that
    # the Splink name comparison already applies. Mapping either onto
    # ExactMatch(field) would add a second comparison over the same column and
    # price the same evidence twice.
    if kind == "address" and field:
        return cl.LevenshteinAtThresholds(field, [2, 4])
    if kind == "geo":
        return cl.DistanceInKMAtThresholds(
            spec.get("lat", "lat"), spec.get("lon", "lon"), [0.5, 2, 10, 50])
    return None


def _present(spec: dict, list_a: list[dict], list_b: list[dict]) -> bool:
    """Drop comparators no record on either side can answer.

    arche's own ``_field_sim`` returns None for a field absent on one side, so
    the comparator abstains rather than scoring a disagreement; the same rule
    applies here.
    """
    names = ([spec.get("lat", "lat"), spec.get("lon", "lon")]
             if spec.get("kind") == "geo" else [spec.get("field")])
    return all(
        any(r.get(n) not in (None, "") for r in (*list_a, *list_b))
        for n in names if n
    )


def _derive(list_a: list[dict], list_b: list[dict], comparators: list[dict],
            cl: Any, block_on: Any, pair_cap: int) -> dict[str, Any]:
    """Best-effort Splink configuration from an arche comparator pack.

    Returns the comparisons, the blocking rules, the EM training rules and the
    columns the frame needs. Everything it decides is costed or measured; where
    it cannot know something it refuses rather than guessing, which is why the
    two failure modes here are exceptions and not silently poor recall.
    """
    comparisons, used = [], []
    for spec in comparators:
        if not _present(spec, list_a, list_b):
            continue
        field = spec.get("field")
        samples = [str(r[field]) for r in (*list_a, *list_b)
                   if field and r.get(field) not in (None, "")][:50]
        made = _comparison_for(spec, cl, samples)
        if made is not None:
            comparisons.append(made)
            used.append(spec)
    if not comparisons:
        raise SplinkBackendError(
            f"no comparator in the pack maps onto a Splink comparison "
            f"(kinds seen: {sorted({str(c.get('kind')) for c in comparators})}). "
            "Pass comparators= with a supported kind, or use the default backend."
        )
    if len(comparisons) == 1:
        raise SplinkBackendError(
            "cannot derive a Splink configuration from one mappable comparison. "
            "Every candidate key would be built from the same field, so Splink "
            "cannot estimate that comparison's m probabilities. Pass a "
            "SettingsCreator and splink_train= with independent evidence "
            "columns, or use the default arche backend."
        )

    geo_pairs = [(s.get("lat", "lat"), s.get("lon", "lon")) for s in used
                 if s.get("kind") == "geo"]
    geo_cols = {c for pair in geo_pairs for c in pair}
    scalar = sorted({s["field"] for s in used if s.get("field")})
    text_fields = sorted({s["field"] for s in used
                          if s.get("kind") in ("name", "placename")
                          and s.get("field")})
    columns = sorted(set(scalar) | geo_cols)

    # Candidate blocking keys, each costed before it is allowed in. Coordinates
    # are never an exact key: two surveys of one school agree to about a
    # hundred metres and never to the float, so `block_on("lat")` generates
    # candidates for nothing but coincidences. Rounded coordinates are the key
    # that actually reaches them, and are what a practitioner writes by hand.
    candidates: list[tuple[int, str, Any]] = []

    def offer(label: str, rule: Any, key: Callable) -> None:
        cost = _worst_block(list_a, list_b, key)
        if 0 < cost <= pair_cap:
            candidates.append((cost, label, rule))

    for f in scalar:
        offer(f, block_on(f), _exact_key(f))
    for i, f in enumerate(scalar):
        for g in scalar[i + 1:]:
            offer(f"{f}+{g}", block_on(f, g), _exact_key(f, g))
    for f in text_fields:
        # A name blob is the arche schema's compromise: Splink's own Febrl
        # recipe blocks on given_name and surname separately and this pack has
        # one `name` column. Blocking on the first and last token recovers part
        # of that, and the prefix rule survives a typo an exact rule misses.
        offer(f"{f}[:4]", block_on(f"substr({f}, 1, 4)"), _prefix_key(f, 4))
        offer(f"{f}.first", block_on(f"split_part({f}, ' ', 1)"),
              _token_key(f, 1))
        offer(f"{f}.last", block_on(f"split_part({f}, ' ', -1)"),
              _token_key(f, -1))
    for lat, lon in geo_pairs:
        for places in (2, 1):
            offer(f"geo/{places}",
                  block_on(f"round({lat}, {places})", f"round({lon}, {places})"),
                  _rounded_geo_key(lat, lon, places))

    candidates.sort(key=lambda c: (c[0], c[1]))
    kept = candidates[:12]
    if not kept:
        raise SplinkBackendError(
            f"no blocking key stays under pair_cap={pair_cap:,}: every "
            f"candidate over {columns} has a value common enough to blow up "
            "the candidate set. Pass splink_settings= with blocking rules you "
            "have costed yourself, or raise pair_cap if you know the cost is "
            "affordable."
        )

    # EM has to be blocked on something the target comparison still VARIES
    # within. Blocking on `birth_date` leaves every birth date in the block
    # identical, so that comparison learns nothing and predict() falls back to
    # defaults for it. The fix is not a cleverer single rule, it is a SET: one
    # rule keyed on each comparison's own columns, so every comparison varies
    # freely inside at least one of the others. Trained on `place` with two
    # coordinate-keyed rules, `lat_lon` reported "no m values are trained" and
    # the run merged 0 of 400 constructed positives.
    by_label = {label: (cost, rule) for cost, label, rule in kept}
    em: list[tuple[int, Any]] = []
    covered: set[str] = set()
    for spec in used:
        if spec.get("kind") == "geo":
            family, labels = "geo", ["geo/2", "geo/1"]
        else:
            field = spec.get("field")
            if not field:
                continue
            family = field
            labels = [field, f"{field}.first", f"{field}[:4]"]
        if family in covered:
            continue
        for label in labels:
            if label in by_label:
                em.append(by_label[label])
                covered.add(family)
                break
    em.sort(key=lambda r: r[0])

    # The deterministic rule feeds `probability_two_random_records_match`, the
    # prior for how many true matches the corpus holds at all. It has to be a
    # rule whose hits are near-certainly matches, which is NOT the same thing
    # as the most selective blocking rule: picking the cheapest one put the
    # Nigerian positives at 0.8936 where the same records under a hand-written
    # deterministic rule cleared 0.99, with the ordering identical either way.
    # Exact agreement on every scalar field compared is the closest thing to
    # "certainly the same record" that a pack can express, so that is the rule,
    # narrowing to single fields only if the conjunction matches nothing.
    deterministic, det_label = None, None
    for fields in (tuple(scalar), *((f,) for f in sorted(
            scalar, key=lambda f: _total_pairs(list_a, list_b, _exact_key(f))))):
        if fields and _total_pairs(list_a, list_b, _exact_key(*fields)) > 0:
            deterministic, det_label = block_on(*fields), "+".join(fields)
            break

    return {
        "comparisons": comparisons,
        "blocking_rules": [rule for _, _, rule in kept],
        "blocking_labels": [label for _, label, _ in kept],
        "em_rules": [rule for _, rule in em[:3]],
        "deterministic_rules": [deterministic] if deterministic else [],
        "deterministic_label": det_label,
        "columns": columns,
        "text_fields": text_fields,
    }


# ------------------------------------------------------------------- pieces --

def _record_columns(list_a: list[dict], list_b: list[dict],
                    id_field: str) -> list[str]:
    """Columns to put in the frame when the caller owns the settings.

    Every record key except the id, which is what a Splink user expects: they
    wrote the settings against their own records, so the columns they named are
    in there. Guessing a subset would mean parsing arbitrary SQL out of the
    blocking rules, and getting it wrong drops a column the model was told to
    compare.
    """
    seen: list[str] = []
    for side in (list_a, list_b):
        for record in side:
            for key in record:
                if key != id_field and key not in seen:
                    seen.append(key)
    if not seen:
        raise SplinkBackendError(
            "records carry no columns besides the id field; nothing to compare."
        )
    return sorted(seen)


def _link_type(settings: Any) -> str | None:
    """What the caller's settings say they are doing."""
    if isinstance(settings, dict):
        return settings.get("link_type")
    return getattr(settings, "link_type", None)


def _settings_blocking_rules(settings: Any) -> list[Any]:
    """The prediction blocking rules out of whatever settings object we got."""
    if isinstance(settings, dict):
        return list(settings.get("blocking_rules_to_generate_predictions") or [])
    return list(
        getattr(settings, "blocking_rules_to_generate_predictions", None) or [])


def _default_train(linker: Any, deterministic: Sequence[Any],
                   em_rules: Sequence[Any], seed: int) -> None:
    """Splink's documented training recipe over rules already chosen.

    Kept small on purpose. A caller with an opinion passes ``splink_train=``
    and this is not used at all.

    ``recall=0.6`` is an assumption, not a measurement: it says the
    deterministic rule is expected to catch 60% of the true matches. Nothing in
    a record list can tell you that number, which is one of the reasons a
    derived configuration's probabilities are not comparable with a
    hand-written one's.
    """
    if deterministic:
        linker.training.estimate_probability_two_random_records_match(
            list(deterministic), recall=0.6)
    linker.training.estimate_u_using_random_sampling(max_pairs=2e6, seed=seed)
    for rule in em_rules:
        try:
            linker.training.estimate_parameters_using_expectation_maximisation(
                rule)
        except Exception:  # noqa: BLE001 - EM on one rule may not converge
            continue


def _as_model_dict(model: Any) -> dict:
    if isinstance(model, str):
        try:
            model = json.loads(model)
        except ValueError:
            return {}
    return model if isinstance(model, dict) else {}


def _model_lambda(model: Any) -> float | None:
    """``probability_two_random_records_match`` out of the saved model."""
    value = _as_model_dict(model).get("probability_two_random_records_match")
    return round(float(value), 12) if isinstance(value, (int, float)) else None


def _model_blocking_sql(model: Any) -> list[str]:
    """The blocking SQL Splink actually used, out of the saved model.

    ``str()`` on a Splink rule object yields ``<... object at 0x7f...>``, so a
    pin built from it changed on every run and identified nothing. The saved
    model carries the SQL, which is stable across runs.
    """
    out = []
    for rule in (_as_model_dict(model)
                 .get("blocking_rules_to_generate_predictions") or []):
        out.append(str(rule.get("blocking_rule") or rule)
                   if isinstance(rule, dict) else str(rule))
    return out


# -------------------------------------------------------------------- entry --

def splink_crosswalk(
    list_a: list[dict],
    list_b: list[dict],
    comparators: list[dict] | None = None,
    *,
    splink_settings: Any = None,
    splink_train: Callable[[Any], None] | None = None,
    columns: Sequence[str] | None = None,
    id_field: str = "id",
    threshold: float | None = None,
    review_margin: float | None = None,
    gate: bool = False,
    distinctive_floor: float | None = None,
    pair_cap: int = SPLINK_PAIR_CAP,
    seed: int = SPLINK_SEED,
    extra_pins: dict | None = None,
    **_ignored: Any,
) -> dict:
    """Link two lists with Splink, returning arche's crosswalk result shape.

    ``splink_settings`` is required and takes a ``SettingsCreator``, a settings
    dict, or the string ``"derive"``. See the module docstring for why arche
    does not pick one for you.

    ``splink_train`` takes a callable that receives the built ``Linker`` and
    trains it however you like. Without one, Splink's documented recipe runs
    over the blocking rules already in the settings.

    ``threshold`` is required. A Splink probability has no portable scale, and
    the shipped 0.99 that used to stand here auto-merged nothing at all on one
    of the two benchmark sets.
    """
    splink, duckdb = _require_splink()
    import splink.comparison_library as cl
    from splink import DuckDBAPI, Linker, SettingsCreator, block_on

    from arche.ids import content_hash

    if splink_settings is None:
        raise SplinkBackendError(_NO_SETTINGS)
    if threshold is None:
        raise SplinkBackendError(_NO_THRESHOLD)

    threshold = float(threshold)
    review_margin = (SPLINK_REVIEW_MARGIN if review_margin is None
                     else float(review_margin))

    derived = isinstance(splink_settings, str)
    if derived and splink_settings != "derive":
        raise SplinkBackendError(
            f"splink_settings={splink_settings!r} is not understood; pass a "
            'SettingsCreator, a settings dict, or the string "derive".'
        )

    text_fields: list[str] = sorted({
        c["field"] for c in (comparators or [])
        if c.get("kind") in ("name", "placename") and c.get("field")})

    if derived:
        if not comparators:
            raise SplinkBackendError(
                'splink_settings="derive" needs comparators= or entity=; '
                "there is nothing to derive a configuration from."
            )
        warnings.warn(
            'splink_settings="derive" is best-effort and is not the supported '
            "path. A configuration inferred from a comparator pack orders "
            "pairs reasonably and cannot calibrate them: on Febrl 4 the same "
            "derived run measures recall 0.8952 at p >= 0.5 and 0.5448 at "
            "p >= 0.99, either side of arche's own engine at 0.8382. Sweep the "
            "threshold on labelled data before trusting a number, or pass a "
            "SettingsCreator you wrote yourself.",
            UserWarning, stacklevel=2,
        )
        plan = _derive(list_a, list_b, comparators, cl, block_on, pair_cap)
        settings = SettingsCreator(
            # `crosswalk(records, records)` is arche's dedupe idiom. Handing
            # Splink two copies of one table gives every record a perfect twin
            # in the other table, and those n free matches go straight into
            # `estimate_probability_two_random_records_match` and the u
            # sampling. The adapter honours whatever link type the caller
            # declared; the derivation has to decide, and one list twice means
            # dedupe.
            link_type="dedupe_only" if list_a is list_b else "link_only",
            comparisons=plan["comparisons"],
            blocking_rules_to_generate_predictions=plan["blocking_rules"],
            retain_intermediate_calculation_columns=False,
        )
        blocking_rules = plan["blocking_rules"]
        em_rules = plan["em_rules"]
        deterministic = plan["deterministic_rules"]
        derived_labels = {"blocking": plan["blocking_labels"],
                          "deterministic": plan["deterministic_label"]}
        text_fields = plan["text_fields"]
        frame_columns = list(columns) if columns else plan["columns"]
    else:
        settings = splink_settings
        blocking_rules = _settings_blocking_rules(settings)
        # Two rules keyed on different columns, so most comparisons vary inside
        # at least one of them. A caller who cares passes `splink_train=`.
        em_rules = blocking_rules[:2]
        deterministic = blocking_rules[:1]
        derived_labels = None
        frame_columns = (list(columns) if columns
                         else _record_columns(list_a, list_b, id_field))

    if gate and not text_fields:
        raise SplinkBackendError(
            "gate=True needs to know which column holds a name: it recomputes "
            "arche's own distinctiveness over it. Pass comparators= (or "
            "entity=) declaring a field of kind 'name' or 'placename', or "
            "leave the gate off."
        )

    # `crosswalk(records, records)` is arche's dedupe idiom, and a caller whose
    # settings say `link_type="dedupe_only"` means it. Handing Splink two copies
    # of one table instead would double the corpus, which changes the u
    # estimates and the term-frequency weights, so the declared link type has to
    # be honoured rather than worked around.
    dedupe = _link_type(settings) == "dedupe_only"
    if dedupe and list_a is not list_b:
        ids_a = [str(r.get(id_field, i)) for i, r in enumerate(list_a)]
        ids_b = [str(r.get(id_field, i)) for i, r in enumerate(list_b)]
        if ids_a != ids_b:
            raise SplinkBackendError(
                'link_type="dedupe_only" needs one list; pass the same records '
                "as both arguments (arche's dedupe idiom), or set "
                'link_type="link_only" in your settings.'
            )

    types = _column_types(list_a, list_b, frame_columns)
    try:
        df_a = _frame(list_a, frame_columns, types, id_field)
        if dedupe:
            linker = Linker(df_a, settings, db_api=DuckDBAPI())
        else:
            df_b = _frame(list_b, frame_columns, types, id_field)
            linker = Linker([df_a, df_b], settings, db_api=DuckDBAPI(),
                            input_table_aliases=["a", "b"])
        if splink_train is not None:
            splink_train(linker)
        else:
            _default_train(linker, deterministic, em_rules, seed)
        floor = max(0.0, threshold - review_margin)
        predicted = linker.inference.predict(
            threshold_match_probability=floor).as_pandas_dataframe()
        model = linker.misc.save_model_to_json()
    except SplinkBackendError:
        raise
    except Exception as exc:  # noqa: BLE001 - surfaced, never swallowed
        raise SplinkBackendError(f"splink backend failed: {exc}") from exc

    pins: dict[str, Any] = {
        "engine": "crosswalk.splink.v1",
        "backend": "splink",
        # Who configured the scorer. A derived run and a hand-written run are
        # not the same decision, and the pin says which one happened.
        "settings": "derived" if derived else "caller",
        "training": "caller" if splink_train is not None else "default",
        "link_type": "dedupe_only" if dedupe else "link_only",
        "splink_version": splink.__version__,
        "duckdb_version": duckdb.__version__,
        # The trained model IS the scoring function. Two runs with different
        # models are not comparable, so the model is named, not merely implied.
        "model_sha256": _digest(model),
        "corpus_sha256": _corpus_digest(list_a, list_b, frame_columns),
        "blocking_sha256": _digest(_model_blocking_sql(model)),
        # The prior for how many true matches the corpus holds. It moves the
        # whole probability scale, so two runs with different values of it are
        # not on the same scale and their thresholds do not mean the same
        # thing. Naming it is the only way a reader can tell.
        "lambda": _model_lambda(model),
        "threshold": threshold,
        "review_margin": review_margin,
        "seed": seed,
        "gate": bool(gate),
    }
    if comparators is not None:
        pins["comparators_sha256"] = content_hash(
            comparators, prefix="cmp").split(":")[-1]
    if gate:
        from arche.resolve._gate import DISTINCTIVE_FLOOR
        pins["distinctive_floor"] = (DISTINCTIVE_FLOOR if distinctive_floor is None
                                     else float(distinctive_floor))
    pins.update(extra_pins or {})

    by_a = {str(r.get(id_field, i)): r for i, r in enumerate(list_a)}
    by_b = {str(r.get(id_field, i)): r for i, r in enumerate(list_b)}
    gamma_cols = [c for c in predicted.columns if c.startswith("gamma_")]

    matches: list[dict] = []
    for row in predicted.to_dict("records"):
        prob = float(row["match_probability"])
        decision = "match" if prob >= threshold else "review"
        # Splink's comparison LEVEL, normalised for display. It is not a
        # similarity and is not arche's comparator output; the key is suffixed
        # so nobody reads it as one.
        evidence: dict[str, Any] = {}
        for col in gamma_cols:
            level = row.get(col)
            if level is None or int(level) < 0:
                continue
            evidence[f"{col[len('gamma_'):]}_level"] = int(level)
        evidence["match_probability"] = round(prob, 4)

        distinctive_max = 0.0
        if gate:
            distinctive_max = _distinctive_max(
                by_a.get(str(row["unique_id_l"])), by_b.get(str(row["unique_id_r"])),
                text_fields)
            if decision == "match" and distinctive_max < pins["distinctive_floor"]:
                decision = "review"

        edge = {
            "a_id": row["unique_id_l"],
            "b_id": row["unique_id_r"],
            "score": round(prob, 4),
            "decision": decision,
            "evidence": evidence,
            "distinctive_max": round(distinctive_max, 3),
        }
        edge["decision_id"] = content_hash(
            {"schema": "arche.crosswalk_edge.v1", **edge, "pins": pins},
            prefix="xwd",
        )
        matches.append(edge)

    matches.sort(key=lambda m: m["score"], reverse=True)
    return {
        "matches": matches,
        "count": len(matches),
        "pins": pins,
        "blocking": {"candidate_pairs": None, "reduction_ratio": None,
                     "strategies": {"splink_rules": len(blocking_rules),
                                    **({"derived": derived_labels}
                                       if derived_labels else {})}},
    }


def _distinctive_max(rec_a: dict | None, rec_b: dict | None,
                     text_fields: Sequence[str]) -> float:
    """arche's own distinctiveness over the name fields, for the optional gate.

    Deliberately a separate computation from Splink's score. That is exactly why
    it is off by default: two rules over the same evidence can disagree, and the
    combined error profile has not been measured.
    """
    if not rec_a or not rec_b or not text_fields:
        return 0.0
    from arche.resolve._gate import shared_name_distinctiveness
    from arche.resolve._tokenfreq import TokenFrequencyTable
    texts = [str(r.get(f, "")) for r in (rec_a, rec_b) for f in text_fields]
    tf = TokenFrequencyTable.from_corpus([t for t in texts if t])
    return max((shared_name_distinctiveness(str(rec_a.get(f, "")),
                                            str(rec_b.get(f, "")), tf)
                for f in text_fields), default=0.0)
