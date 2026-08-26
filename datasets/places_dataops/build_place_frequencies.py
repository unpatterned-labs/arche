# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Build the population-scale PLACE token-frequency table shipped with arche.

Why this exists
---------------
Until this table shipped, `crosswalk(entity="place")` scored distinctiveness
against the *person* table. The commonest words in any facility register —
``hospital``, ``health``, ``clinic``, ``centre`` — are absent from a person-name
corpus, so they landed on ``_UNKNOWN_FLOOR`` and read as **rare**. Two
facilities called "General Hospital" 4.4 km apart therefore merged with exactly
the same score and evidence as two sharing a genuinely rare name.

The mechanism was never wrong: on person names it correctly routes
``Ibrahim Musa`` to ``review``. The corpus was missing. This script builds it.

What a place table has to contain
---------------------------------
Two vocabularies, and both matter:

* **Generic type words** — ``hospital``, ``phc``, ``dispensary``, ``surgery``,
  ``practice``, ``substation``, ``solar``, ``primary``, ``school``. These must
  come out *common*, because agreement on them is nearly no evidence.
* **Distinctive residuals** — settlement names and personal names embedded in
  facility names (``Karfi`` in "Karfi Health Post"). These must stay *rare*.
  That is why populated places are counted alongside facilities: the
  distinctiveness of ``Karfi`` is a fact about how many places are called Karfi,
  and only a settlement corpus knows it.

Coverage is deliberately cross-country and cross-sector. A table built only on
Nigerian health facilities would leave UK ``surgery``/``practice`` and energy
``substation``/``feeder`` reading as rare, which is the same bug in a new place.

Provenance
----------
Every source here is CC-BY (or CC-BY-IGO) and is recorded in the output's
``provenance`` block with its licence and URL, so the attribution chain is
carried by the artefact rather than by a README nobody reads.

**OpenStreetMap is deliberately excluded.** ODbL's share-alike would propagate
into a derived database, and the pack must stay unencumbered. That is the
provenance firewall doing its job, and it is why this table is built from
registries and GeoNames rather than the easier OSM extract.

Usage
-----
    python datasets/places_dataops/build_place_frequencies.py
    python datasets/places_dataops/build_place_frequencies.py --prune-min 3
    python datasets/places_dataops/build_place_frequencies.py --countries GB,NG
    python datasets/places_dataops/build_place_frequencies.py --offline   # cache only
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
import re
import time
import urllib.parse
import urllib.request
import zipfile
from collections import Counter
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "packages" / "arche-core" / "src"))
from arche.resolve._tokenfreq import (  # noqa: E402
    TokenFrequencyTable,
    _tokens as _raw_tokens,
)

# Bound to the CLI rule in main(); every counting path goes through it so
# the artefact and its stamp cannot disagree.
_TOKEN_RULE = "plain"


def _tokens(text):
    return _raw_tokens(text, _TOKEN_RULE)


def _merge_strata(strata, how: str):
    """Combine per-stratum counts into one table.

    **`equal-mass` was the original and it has a measured defect.** Each stratum
    is scaled to the mean stratum mass and the scaled counts are then SUMMED. A
    token occurring in twelve strata therefore accumulates twelve contributions
    while a token occurring in one accumulates a single one -- so a word that is
    ordinary in exactly one country comes out of the merge diluted by roughly the
    number of countries it is absent from.

    That is not hypothetical. Measured against Nigeria's own 25 commonest place
    words, with Nigeria INSIDE the table::

        15 of 25 scored at or above the distinctive floor of 0.75
        gidan, tungan, garin, mallam -- Hausa for house-of, settlement-of, town-of

    Those are the `Saint` and `Mill` of northern Nigeria, and the table called
    them rare enough to carry a match on their own. Meanwhile `school` and
    `hospital`, which appear across a dozen anglophone strata, came out correctly
    ordinary at 0.31-0.41. **The merge that exists to stop the largest stratum
    setting the vocabulary instead let the most WIDELY SHARED vocabulary set it**,
    which for a table built to serve African registers is the same bug wearing a
    different coat.

    **`peak-rate` was the attempted fix and it is measurably WORSE.** For each
    token it takes the rate within the stratum where the token is most common.
    That was expected to rescue `gidan`; it did not, and the arithmetic says why
    it could not. For a token appearing in exactly one stratum, equal-mass
    computes ``c * (target/mass)`` and peak-rate computes ``rate * target``.
    **They are the same number.** Equal-mass never diluted single-stratum tokens.
    What peak-rate changes is multi-stratum tokens, which it lowers -- pushing
    MORE words above the floor, not fewer::

        commonest 25 words at or above the 0.75 floor
                        equal-mass    peak-rate
            NG               15/25        19/25
            FR               18/25        19/25
            IT               20/25        23/25

    It is kept, not deleted, so nobody spends another afternoon on it.

    **The real cause is the floor, not the merge.** A distinctiveness of 0.75
    corresponds to a rate of 1 in 5,623, which in this 160,373-token table is
    about rank 400. Only the ~400 commonest tokens are therefore treated as
    ordinary, and those ranks are owned by vocabulary shared across many strata
    (`health` 1-in-36, `hospital` 1-in-57). A country contributing one twentieth
    of the table cannot get its own generics into a global top 400, so **the
    merged table is miscalibrated for every country in it, not only for the ones
    it omits.**

    Measured, per-country tables built from the same source::

                        merged      country-only
            NG           15/25            0/25
            FR           18/25            0/25
            IT           20/25            0/25

        gidan   0.678 -> 0.371      tungan  0.782 -> 0.462
        garin   0.774 -> 0.500      mallam  0.820 -> 0.546

    A locale-scoped table is right for all three, including the two the merged
    table has never seen. That is the fix, and it is an architecture change --
    one table per locale, selected by the jurisdiction the pipeline already
    infers -- rather than a different way of averaging. It is not made here
    because it moves every published place number and needs its own measurement.

    Note also what no merge can fix: a token absent from every stratum stays
    unseen and still scores as maximally distinctive. `moulin` and `chiesa` need
    French and Italian strata, not arithmetic.
    """
    masses = [sum(a.counts.values()) for _, a, _ in strata]
    target = sum(masses) / len(masses)
    merged: Counter[str] = Counter()
    descriptors: Counter[str] = Counter()

    if how == "equal-mass":
        for (_, acc, _), mass in zip(strata, masses):
            scale = target / mass if mass else 0.0
            for tok, c in acc.counts.items():
                merged[tok] += c * scale
            # Descriptors scale by the SAME per-stratum factor, so a descriptor
            # count and a token count stay comparable after the merge.
            for canon, c in acc.descriptors.items():
                descriptors[canon] += c * scale
        return merged, descriptors

    peak: dict[str, float] = {}
    peak_desc: dict[str, float] = {}
    for (_, acc, _), mass in zip(strata, masses):
        if not mass:
            continue
        for tok, c in acc.counts.items():
            rate = c / mass
            if rate > peak.get(tok, 0.0):
                peak[tok] = rate
        for canon, c in acc.descriptors.items():
            rate = c / mass
            if rate > peak_desc.get(canon, 0.0):
                peak_desc[canon] = rate
    for tok, rate in peak.items():
        merged[tok] = rate * target
    for canon, rate in peak_desc.items():
        descriptors[canon] = rate * target
    return merged, descriptors


def _normalise_token(raw: str) -> str:
    """One normalised token, or '' — curated keys go through the same
    normaliser as corpus tokens so a YAML edit cannot silently miss."""
    toks = _tokens(str(raw or ""))
    return toks[0] if len(toks) == 1 else ""


_QID_RE = re.compile(r"^Q\d+$")
_UA = "arche-dataops/0.3 (https://unpatterned.org; connect@unpatterned.org)"
_OUT = (
    _REPO / "packages" / "arche-core" / "src" / "arche" / "resolve" / "_data"
    / "place_frequencies.json.gz"
)
_CACHE = _REPO / "datasets" / "data" / "_cache" / "places"

# ── GeoNames ────────────────────────────────────────────────────────────────
# CC-BY-4.0. Per-country dumps, tab-separated, no header. Column order is fixed
# by the published readme.
_GN_BASE = "https://download.geonames.org/export/dump"
_GN_NAME, _GN_ASCII, _GN_ALT = 1, 2, 3
_GN_FCLASS, _GN_FCODE = 6, 7

# Feature codes worth counting, grouped by the sector they teach the table.
# P.* (populated places) is the settlement vocabulary that makes residuals rare.
_GN_HEALTH = {"HSP", "HSPC", "HSPD", "HSPL"}
_GN_ENERGY = {"PS", "PSH", "PSTN"}
_GN_EDU = {"SCH", "SCHA", "SCHC", "SCHL", "SCHM", "SCHN", "SCHT", "UNIV"}
_GN_CIVIC = {"BLDG", "MKT", "MFG", "MFGB", "MFGPH", "AIRP", "RSTN", "BANK",
             "COURT", "GOVL", "HTL", "LIBR", "MUS", "PO", "POL", "PRN", "REST",
             "STDM", "STNB", "TRIG", "WTRW", "CMTY", "CH", "MSQE", "TMPL"}
_GN_FACILITY_CODES = _GN_HEALTH | _GN_ENERGY | _GN_EDU | _GN_CIVIC

# UK and Nigeria first, then breadth. Anglophone-African weighting is
# deliberate — it is the population arche is calibrated for — but Europe, the
# Maghreb, South Asia and Latin America are here so the table is not a
# single-region artefact.
_COUNTRIES = [
    "GB", "IE",                                            # UK + Ireland
    "NG", "GH", "SN", "CI", "CM",                          # West Africa
    "KE", "TZ", "UG", "RW", "ET",                          # East Africa
    "ZA", "ZM", "ZW", "MW",                                # Southern Africa
    "EG", "MA",                                            # North Africa
    "IN", "BR",                                            # other regions
]

# ── Registries and sector lists (all CC-BY / CC-BY-IGO) ─────────────────────
_WRI_POWER = (
    "https://raw.githubusercontent.com/wri/global-power-plant-database/"
    "master/output_database/global_power_plant_database.csv"
)
_HDX = {
    "hdx-nigeria-hfr": (
        "https://data.humdata.org/dataset/nigeria-health-facilities", "cc-by"),
    "hdx-ethiopia": (
        "https://data.humdata.org/dataset/ethiopian-health-facilities", "cc-by"),
    "hdx-guinea": (
        "https://data.humdata.org/dataset/guinea-healthcare-master-data",
        "cc-by-igo"),
}
# Local files already in the repo, with the licence recorded in data/*SOURCES.md.
_LOCAL = [
    ("grid3-nga-health", "data/GRID3_NGA_health_facilities_v2.csv",
     ("facility_name",), "cc-by",
     "https://grid3.org / NHFR — Nigeria health facilities v2"),
    ("hfr-kano", "data/hfr_kano.csv", ("name", "alternate_name"), "cc-by",
     "https://data.humdata.org/dataset/nigeria-health-facilities"),
    ("hfr-edo", "data/hfr_edo.csv", ("name", "alternate_name"), "cc-by",
     "https://data.humdata.org/dataset/nigeria-health-facilities"),
    ("hfr-ondo", "data/hfr_ondo.csv", ("name", "alternate_name"), "cc-by",
     "https://data.humdata.org/dataset/nigeria-health-facilities"),
]


# ── Wikidata (CC0) ──────────────────────────────────────────────────────────
# CC0 is the only licence class the provenance firewall accepts without
# argument, and Wikidata is the one source that can be asked for a *class* of
# place — substations, GP surgeries, wind farms — in any country. GeoNames
# carries settlements but almost no facilities (Nigeria: 22 health, 4 energy),
# so without this the table learns Nigerian health vocabulary and nothing else.
_WD_SPARQL = "https://query.wikidata.org/sparql"
_WD_COUNTRIES = {"GB": "Q145", "NG": "Q1033", "GH": "Q117", "KE": "Q114",
                 "ZA": "Q258", "IN": "Q668"}
# (key, class QID, sector, country code or None for worldwide, limit)
_WD_QUERIES = [
    ("hospital-world",     "Q16917",   "health", None, 25000),
    ("hospital-gb",        "Q16917",   "health", "GB",  8000),
    ("hospital-ng",        "Q16917",   "health", "NG",  4000),
    ("clinic-world",       "Q955824",  "health", None, 12000),
    ("clinic2-world",      "Q1774898", "health", None, 15000),
    ("healthcentre-world", "Q31855",   "health", None, 12000),
    # Q718966 "doctor's office" is the general-medical-practice class, and the
    # only route to UK `surgery`/`practice` vocabulary — NHS ODS and the FHRS
    # API both refuse this network, and OSM is barred by the firewall.
    ("doctorsoffice-world", "Q718966", "health", None, 15000),
    ("doctorsoffice-gb",    "Q718966", "health", "GB",  8000),
    ("substation-world",   "Q174814",  "energy", None, 25000),
    ("powerstation-world", "Q159719",  "energy", None, 25000),
    # Earlier QIDs here were guesses and returned 4 rows. Verified via
    # wbsearchentities: photovoltaic power station / wind farm.
    ("solarfarm-world",    "Q1003207", "energy", None, 15000),
    ("windfarm-world",     "Q194356",  "energy", None, 15000),
    ("school-world",       "Q3914",    "education", None, 25000),
    ("school-gb",          "Q3914",    "education", "GB", 8000),
    ("university-world",   "Q3918",    "education", None, 12000),
]


def _wd_query(qid: str, country: str | None, limit: int) -> str:
    where = [f"?item wdt:P31/wdt:P279* wd:{qid} ."]
    if country:
        where.append(f"?item wdt:P17 wd:{_WD_COUNTRIES[country]} .")
    body = "\n  ".join(where)
    return (
        "SELECT ?itemLabel WHERE {\n  " + body + "\n  "
        'SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }\n'
        "}\nLIMIT " + str(limit)
    )


def wikidata_counts(
    key: str, qid: str, country: str | None, limit: int, *, offline: bool,
    index: dict | None = None,
) -> tuple[_Accumulator, int]:
    """Token counts over the labels of one Wikidata class, cached as JSON."""
    cache = _CACHE / f"wd_{key}.json"
    labels: list[str] | None = None
    if cache.exists() and cache.stat().st_size > 0:
        labels = json.loads(cache.read_text(encoding="utf-8"))
    elif not offline:
        url = (_WD_SPARQL + "?format=json&query="
               + urllib.parse.quote(_wd_query(qid, country, limit)))
        # WDQS returns 502 and truncated bodies under load often enough that a
        # single attempt silently drops whole sectors from the table.
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, headers={
                    "User-Agent": _UA,
                    "Accept": "application/sparql-results+json"})
                with urllib.request.urlopen(req, timeout=300) as resp:  # noqa: S310
                    data = json.loads(resp.read())
                labels = [b["itemLabel"]["value"]
                          for b in data["results"]["bindings"] if "itemLabel" in b]
                # A label that is still a Q-number has no English name; it
                # teaches the table nothing but noise.
                labels = [x for x in labels if not _QID_RE.match(x)]
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps(labels), encoding="utf-8")
                break
            except Exception as exc:  # noqa: BLE001
                if attempt == 2:
                    print(f"    ! wikidata {key}: {type(exc).__name__}: {exc}")
                    return _Accumulator(index or {}), 0
                time.sleep(5 * (attempt + 1))
    acc = _Accumulator(index or {})
    if not labels:
        return acc, 0
    for lab in labels:
        acc.add(lab)
    return acc, len(labels)


def _descriptor_index(tokens_path: Path) -> tuple[dict, dict]:
    """Build the phrase lookup used to count *canonical descriptors*.

    An abbreviation is not a word whose rarity can be inferred from the words it
    stands for. ``PHC`` is a name for a concept, and what a gate needs to know
    is how often that CONCEPT appears in the population — counted over both
    spellings, the abbreviation and the expansion — not how rare the rarest word
    inside the expansion happens to be. An earlier version of this script took
    the minimum over the expansion's token counts, which meant an abbreviation
    for a generic phrase containing one uncommon word (``HEP`` for "hydro
    electric power") inherited that word's rarity and read as distinctive.

    A phrase may credit MORE THAN ONE descriptor: ``ctr`` and ``cntr`` both
    stand for "centre", so an occurrence of "centre" is evidence about both.
    Mapping a phrase to a single canonical let whichever entry was parsed last
    silently take the whole count and left the other reading as rare.

    Returns ``({n: {token_tuple: [canonical, ...]}}, {canonical: expansion})``.
    """
    index: dict[int, dict[tuple, list[str]]] = {}
    labels: dict[str, str] = {}
    if not tokens_path.exists():
        return index, labels
    try:
        import yaml
    except ImportError:
        return index, labels
    pack = yaml.safe_load(tokens_path.read_text(encoding="utf-8")) or {}
    for entry in pack.get("abbreviations") or []:
        tok = _normalise_token(entry.get("token", ""))
        expansion = _tokens(entry.get("expands_to", ""))
        if not tok or not expansion:
            continue
        canon = _normalise_token(entry.get("canonical", "")) or tok
        labels[canon] = entry.get("expands_to", "")
        # Both spellings credit the same descriptor, and a shared expansion
        # credits every descriptor that claims it.
        for form in (tuple(expansion), (tok,)):
            bucket = index.setdefault(len(form), {}).setdefault(form, [])
            if canon not in bucket:
                bucket.append(canon)
    return index, labels


class _Accumulator:
    """Counts tokens and canonical descriptors over one stratum in a single pass."""

    def __init__(self, index: dict) -> None:
        self.counts: Counter[str] = Counter()
        self.descriptors: Counter[str] = Counter()
        self._index = index

    def add(self, text: str) -> bool:
        toks = _tokens(text or "")
        if not toks:
            return False
        self.counts.update(toks)
        for n, table in self._index.items():
            if n > len(toks):
                continue
            for i in range(len(toks) - n + 1):
                for canon in table.get(tuple(toks[i:i + n]), ()):
                    self.descriptors[canon] += 1
        return True


def _fetch(url: str, dest: Path, *, offline: bool) -> Path | None:
    """Download to ``dest`` unless cached. Returns None when unavailable."""
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    if offline:
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=180) as resp:  # noqa: S310
            dest.write_bytes(resp.read())
    except Exception as exc:  # noqa: BLE001 — a missing source must not abort
        print(f"    ! {url.rsplit('/', 1)[-1]}: {type(exc).__name__}: {exc}")
        return None
    return dest


def geonames_counts(
    cc: str, *, offline: bool, include_alt: bool, index: dict | None = None
) -> tuple[_Accumulator, dict[str, int]]:
    """Token counts for one GeoNames country dump, plus a per-sector tally."""
    path = _fetch(f"{_GN_BASE}/{cc}.zip", _CACHE / f"{cc}.zip", offline=offline)
    acc = _Accumulator(index or {})
    tally = {"settlement": 0, "health": 0, "energy": 0, "education": 0, "civic": 0}
    if path is None:
        return acc, tally
    with zipfile.ZipFile(path) as zf:
        with zf.open(f"{cc}.txt") as fh:
            for raw in io.TextIOWrapper(fh, encoding="utf-8", errors="replace"):
                col = raw.rstrip("\n").split("\t")
                if len(col) <= _GN_FCODE:
                    continue
                fclass, fcode = col[_GN_FCLASS], col[_GN_FCODE]
                if fclass == "P":
                    bucket = "settlement"
                elif fclass == "S" and fcode in _GN_FACILITY_CODES:
                    bucket = ("health" if fcode in _GN_HEALTH else
                              "energy" if fcode in _GN_ENERGY else
                              "education" if fcode in _GN_EDU else "civic")
                else:
                    continue
                tally[bucket] += 1
                acc.add(col[_GN_NAME])
                ascii_name = col[_GN_ASCII]
                if ascii_name and ascii_name != col[_GN_NAME]:
                    acc.add(ascii_name)
                if include_alt and len(col) > _GN_ALT and col[_GN_ALT]:
                    # Alternate names carry transliteration and local-language
                    # variants — the cross-script variation the table should see.
                    for alt in col[_GN_ALT].split(",")[:6]:
                        acc.add(alt)
    return acc, tally


def csv_counts(path: Path, fields: tuple[str, ...],
               index: dict | None = None) -> tuple[_Accumulator, int]:
    acc = _Accumulator(index or {})
    rows = 0
    with open(path, encoding="utf-8-sig", errors="replace", newline="") as fh:
        for rec in csv.DictReader(fh):
            got = False
            for f in fields:
                val = (rec.get(f) or "").strip()
                if val and acc.add(val):
                    got = True
            rows += bool(got)
    return acc, rows


def apply_curated_layer(
    counts: Counter[str], tokens_path: Path, *,
    descriptors: Counter[str] | None = None,
    labels: dict[str, str] | None = None,
) -> tuple[Counter[str], dict]:
    """Apply `place_tokens.yaml` over the measured counts.

    A corpus only knows the words that are in it. Nigerian registries spell out
    "Primary Health Care Centre", so `PHC` appears in 4 of 51,022 GRID3 names
    and the measured table calls it *rare* — which would let two unrelated
    "X PHC" records clear the distinctiveness gate on the abbreviation alone.
    No amount of extra corpus fixes that. A person who has read a facility list
    has to say it, and this is where they say it.

    Applied in increasing order of authority: abbreviations, then generic
    tokens, then explicit overrides. Returns the adjusted counts and a report
    of every token this layer touched, which is written into the artefact so
    the curated half is inspectable rather than baked in silently.
    """
    report: dict = {"pack": None, "abbreviations": {}, "generic": {},
                    "overrides": {}, "unresolved": [], "low_evidence": []}
    if not tokens_path.exists():
        print(f"    ! no curated pack at {tokens_path} — measured counts only")
        return counts, report
    try:
        import yaml
    except ImportError:
        print("    ! pyyaml not available — skipping the curated layer")
        return counts, report

    pack = yaml.safe_load(tokens_path.read_text(encoding="utf-8")) or {}
    report["pack"] = {"path": str(tokens_path.relative_to(_REPO)).replace("\\", "/"),
                      "version": pack.get("version"),
                      "sha256": hashlib.sha256(
                          tokens_path.read_bytes()).hexdigest()[:16]}
    settings = pack.get("settings") or {}
    total = sum(counts.values()) or 1.0
    min_evidence = float(settings.get("descriptor_min_evidence", 500.0))

    # 1. An abbreviation names a CONCEPT, and what a gate needs is how common
    #    that concept is — counted over both spellings across the corpus — not
    #    how rare the rarest word inside its expansion happens to be. The
    #    previous rule took the minimum over the expansion's token counts,
    #    which let an abbreviation for a generic phrase containing one uncommon
    #    word inherit that word's rarity and read as distinctive.
    #
    #    `descriptors` holds a real phrase count, gathered in the same pass and
    #    scaled by the same per-stratum factor as the token counts, so the two
    #    are directly comparable. Never lowers an existing count.
    descriptors = descriptors or Counter()
    labels = labels or {}
    for entry in pack.get("abbreviations") or []:
        tok = _normalise_token(entry.get("token", ""))
        expansion = _tokens(entry.get("expands_to", ""))
        if not tok or not expansion:
            continue
        canon = _normalise_token(entry.get("canonical", "")) or tok
        observed = descriptors.get(canon, 0.0)
        # A concept the corpus barely sees cannot be priced from it. Assigning
        # the handful of occurrences we did see would leave the abbreviation
        # reading as *rare*, which is the failure this rule exists to prevent,
        # so report it instead. The fix for a genuinely generic descriptor the
        # corpus does not spell out is `generic_tokens`, which asserts the
        # judgement directly rather than pretending to have measured it.
        if observed < min_evidence:
            report["low_evidence"].append(
                {"token": tok, "descriptor": canon,
                 "observed": round(observed, 2), "floor": min_evidence})
            continue
        if observed > counts.get(tok, 0.0):
            report["abbreviations"][tok] = {
                "from": round(counts.get(tok, 0.0), 2),
                "to": round(observed, 2),
                "descriptor": canon,
                "expands_to": labels.get(canon, entry.get("expands_to")),
            }
            counts[tok] = observed

    # 2. Generic tokens are floored so their distinctiveness cannot reach the
    #    gate. Never lowers an existing count — a word the corpus already knows
    #    is common stays as common as measured.
    floor_rel = float(settings.get("generic_min_rel_freq", 1.0e-3))
    floor_count = floor_rel * total
    for raw in pack.get("generic_tokens") or []:
        tok = _normalise_token(raw)
        if tok and counts.get(tok, 0.0) < floor_count:
            report["generic"][tok] = {"from": round(counts.get(tok, 0.0), 2),
                                      "to": round(floor_count, 2)}
            counts[tok] = floor_count

    # 3. Explicit overrides win over everything, including the corpus.
    for entry in pack.get("frequency_overrides") or []:
        tok = _normalise_token(entry.get("token", ""))
        if not tok or "rel_freq" not in entry:
            continue
        target = float(entry["rel_freq"]) * total
        report["overrides"][tok] = {"from": round(counts.get(tok, 0.0), 2),
                                    "to": round(target, 2),
                                    "reason": entry.get("reason", "").strip()}
        counts[tok] = target

    print(f"  curated pack {report['pack']['version']} "
          f"({report['pack']['sha256']}): "
          f"{len(report['abbreviations'])} abbreviations, "
          f"{len(report['generic'])} generic floors, "
          f"{len(report['overrides'])} overrides"
          + (f", {len(report['unresolved'])} unresolved"
             if report["unresolved"] else ""))
    return counts, report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=_OUT)
    ap.add_argument("--countries", default=",".join(_COUNTRIES))
    ap.add_argument("--tokens", type=Path,
                    default=_REPO / "packages" / "arche-core" / "src" / "arche"
                    / "resolve" / "_data" / "place_tokens.yaml",
                    help="curated abbreviation/generic-token pack")
    ap.add_argument("--token-rule", default="possessive", choices=["plain", "possessive"],
                    help="tokenisation the counts are accumulated under; stamped "
                         "into the artefact so the runtime cannot query it under "
                         "a different rule")
    ap.add_argument("--merge", default="equal-mass",
                    choices=["equal-mass", "peak-rate"],
                    help="how strata are combined; see `_merge_strata`")
    ap.add_argument("--prune-min", type=int, default=2,
                    help="drop tokens seen fewer than N times (wheel size)")
    ap.add_argument("--offline", action="store_true",
                    help="use only what is already cached")
    ap.add_argument("--no-alt-names", action="store_true",
                    help="skip GeoNames alternate names (less transliteration)")
    args = ap.parse_args()

    # The descriptor index has to exist before counting starts: a canonical
    # descriptor's frequency is counted over the corpus in the same pass as the
    # tokens, not reconstructed from token counts afterwards.
    global _TOKEN_RULE
    _TOKEN_RULE = args.token_rule
    print(f"token rule: {_TOKEN_RULE}\n")

    desc_index, desc_labels = _descriptor_index(args.tokens)
    if desc_index:
        forms = sum(len(t) for t in desc_index.values())
        print(f"curated descriptors: {len(desc_labels)} ({forms} surface forms)\n")

    strata: list[tuple[str, _Accumulator, dict]] = []

    print("GeoNames (CC-BY-4.0)")
    for cc in [c.strip().upper() for c in args.countries.split(",") if c.strip()]:
        acc, tally = geonames_counts(
            cc, offline=args.offline, include_alt=not args.no_alt_names,
            index=desc_index,
        )
        if not acc.counts:
            continue
        n = sum(tally.values())
        strata.append((f"geonames-{cc}", acc, {
            "licence": "cc-by", "url": f"{_GN_BASE}/{cc}.zip",
            "records": n, "by_sector": tally,
        }))
        print(f"  {cc}  {n:>7,} records  {len(acc.counts):>7,} distinct tokens  "
              f"(health {tally['health']}, energy {tally['energy']}, "
              f"edu {tally['education']})")

    print("\nWikidata (CC0)")
    for key, qid, sector, cc, limit in _WD_QUERIES:
        acc, n = wikidata_counts(key, qid, cc, limit, offline=args.offline,
                                 index=desc_index)
        if not acc.counts:
            continue
        scope = f", P17 {_WD_COUNTRIES[cc]}" if cc else ""
        strata.append((f"wikidata-{key}", acc, {
            "licence": "cc0",
            "url": f"{_WD_SPARQL} (P31/P279* {qid}{scope})",
            "records": n, "by_sector": {sector: n},
        }))
        print(f"  {key:20} {n:>6,} labels  {len(acc.counts):>6,} distinct tokens")

    print("\nWRI Global Power Plant Database (CC-BY-4.0)")
    wri = _fetch(_WRI_POWER, _CACHE / "global_power_plant_database.csv",
                 offline=args.offline)
    if wri is not None:
        acc, rows = csv_counts(wri, ("name",), desc_index)
        strata.append(("wri-power-plants", acc, {
            "licence": "cc-by", "url": _WRI_POWER, "records": rows,
            "by_sector": {"energy": rows},
        }))
        print(f"  {rows:,} power plants  {len(acc.counts):,} distinct tokens")

    print("\nLocal registries")
    for key, rel, fields, lic, url in _LOCAL:
        p = _REPO / rel
        if not p.exists():
            print(f"  ! missing {rel}")
            continue
        acc, rows = csv_counts(p, fields, desc_index)
        strata.append((key, acc, {
            "licence": lic, "url": url, "records": rows,
            "by_sector": {"health": rows},
        }))
        print(f"  {key:20} {rows:>7,} records  {len(acc.counts):>6,} distinct tokens")

    if not strata:
        print("\nNo sources available — nothing built.", file=sys.stderr)
        return 1

    merged, descriptors = _merge_strata(strata, args.merge)

    before = len(merged)
    if args.prune_min > 1:
        # Prune on *raw* occurrence across strata, not scaled mass, so a rare
        # token from a small stratum is not preferentially dropped.
        raw: Counter[str] = Counter()
        for _, acc, _ in strata:
            raw.update(acc.counts)
        merged = Counter({t: c for t, c in merged.items()
                          if raw[t] >= args.prune_min})

    merged, curated = apply_curated_layer(
        merged, args.tokens, descriptors=descriptors, labels=desc_labels
    )

    table = TokenFrequencyTable(counts=merged, token_rule=args.token_rule)
    payload = table.to_dict()
    payload["curated"] = curated
    # A content version over the counts themselves. Every rebuild that changes
    # a single frequency changes this string, it travels into `pins` on every
    # edge, and therefore into `decision_id`. Without it a table rebuild
    # silently changes which pairs are blocked, scored and merged, while every
    # decision still claims to be reproducible.
    payload["version"] = "sha256:" + hashlib.sha256(
        json.dumps({k: round(v, 4) for k, v in sorted(merged.items())},
                   separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    payload["provenance"] = {
        "built_by": "datasets/places_dataops/build_place_frequencies.py",
        "domain": "place",
        "note": (
            "Equal-mass merge across strata. OpenStreetMap deliberately "
            "excluded: ODbL share-alike would propagate into this derived "
            "database and encumber the pack."
        ),
        "sources": [{"stratum": k, **meta} for k, _, meta in strata],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    import gzip
    with gzip.open(args.out, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh, separators=(",", ":"))

    print(f"\n{len(strata)} strata merged  ->  {before:,} tokens, "
          f"{len(merged):,} after prune-min={args.prune_min}")
    print(f"wrote {args.out}  ({args.out.stat().st_size / 1024:.0f} KB)")

    print("\nSanity — generic type words must be COMMON (low distinctiveness):")
    for t in ("hospital", "health", "clinic", "centre", "center", "primary",
              "general", "surgery", "practice", "medical", "phc", "dispensary",
              "substation", "solar", "power", "station", "school"):
        print(f"  {t:12} rel_freq={table.rel_freq(t):.3e}  "
              f"distinctiveness={table.distinctiveness(t):.4f}")
    print("\nSanity — distinctive residuals must stay RARE (high):")
    for t in ("gyaranya", "karfi", "tsalle", "kainji", "ikeja", "maitsidau"):
        print(f"  {t:12} rel_freq={table.rel_freq(t):.3e}  "
              f"distinctiveness={table.distinctiveness(t):.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
