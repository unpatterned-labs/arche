# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Resolve layer - link mentions across documents to canonical entities.

Ships a fuzzy/Fellegi-Sunter probabilistic record
linkage implementation in ``arche.resolve.classical`` suitable for
in-memory operation up to ~100K records. African-context comparator
functions handle Yoruba/Hausa/Swahili name variants, patronymics, and
transliteration differences.

Public API::

    from arche.resolve import resolve_entities, resolve_identity_records
    from arche.resolve import ResolvedEntity

For production-scale entity resolution (millions of records), install
``arche-core[resolve]`` which pulls Splink + DuckDB. With the extra
installed, ``resolve_entities(..., use_splink=True)`` auto-engages a
Splink-backed Fellegi-Sunter pipeline at sizes >=10 entities and falls
back to the fuzzy implementation on import error.

A first-class ``SplinkResolver`` user class (CSV-in / cluster-out)
arrives in v0.3 alongside the ``arche-core[graph]`` Kuzu backend and the
``StorageBackend`` Protocol. See ``docs-site/docs/rfcs/0001-v0.3-storage.md``.

----

v0.3 note: the v0.1 callable-module shim (``arche.resolve(text)``) is
removed. Use ``arche.Pipeline(...).process(text)`` for the composition
pattern, or ``resolve.pairwise`` / ``resolve.crosswalk`` from this facade.
"""

from __future__ import annotations

import warnings as _warnings

from arche.resolve._tokenfreq import TokenFrequencyTable  # noqa: E402,F401
from arche.resolve.artists import artist_aliases  # noqa: E402,F401

# Re-export the v0.2 classical resolver surface so existing
# ``from arche.resolve import X`` calls keep working.
# Private symbols used internally by pipeline.py and other modules.
from arche.resolve.classical import (  # noqa: E402,F401  # noqa: E402,F401
    ResolvedEntity,
    _build_resolved,
    _single_entity_to_resolved,
    resolve_entities,
    resolve_identity_records,
)

# Place/entity crosswalk engine (list-to-list reconciliation) and the
# term-frequency table its ``tftoken`` comparator + reranker consume.
from arche.resolve.reconcile import reconcile  # noqa: E402,F401

# ---------------------------------------------------------------------------
#
# Two entry points by USE-SHAPE, sharing primitives but deliberately distinct
# combination laws:
#   pairwise(a, b)            -> "are these two the same?" (Fellegi-Sunter +
#                                gate, signable CoReferenceDecision)
#   crosswalk(list_a, list_b) -> "link two lists at scale" (weighted-mean +
#                                gate + blocking, id-only candidates)
# The scores are NOT comparable across the two (different math, on purpose).
# `coref_*` and `reconcile` remain importable, but the facade is the documented
# surface. (`compare_lists` on main: wrapper-or-deprecate at merge)
# ---------------------------------------------------------------------------

# Canned comparator specs per entity type — the "entity pack" axis. A pack is
# CONFIG over the same engine, never a fork. Records use these field names;
# bring your own comparators= for a different schema.
ENTITY_PACKS: dict[str, list[dict]] = {
    "person": [
        {"field": "name", "kind": "name", "weight": 2.0},
        {"field": "name", "kind": "tftoken", "weight": 2.0},
        # Date of birth. Weighted like a name rather than like `national_id`,
        # because a birthday is strongly identifying without being unique: in
        # any large population thousands share one.
        #
        # Measured on the Parrish linkage set (294 true pairs, 8 true
        # non-matches), against the same pack unable to see the date:
        #
        #     no date comparator       219 true, 14 false   precision 0.9399
        #     weight 2.0               265 true,  1 false   precision 0.9962
        #     weight 2.0 + refutation  259 true,  0 false   precision 1.0000
        #
        # All 14 of those false merges were two different children sharing a
        # name. Weight 3.0 scored higher again (274 true, recall 0.9320) and
        # was not taken: it is one synthetic benchmark, and tuning a shipped
        # default until it peaks there is how a number stops surviving contact
        # with real data.
        #
        # `refutes_below` is deliberately NOT declared here, though a date is
        # exactly the asymmetric signal it was built for. `test_discriminator_
        # veto.py` guards established packs against gaining refutation as a
        # side effect of some other change, and this is some other change. It
        # also measured slightly worse on the only set we have. Callers who
        # want it pass `comparators=` with `"refutes_below": 0.5`, which is
        # what `examples/notebooks/15_parrish_record_linkage.ipynb` does.
        {"field": "birth_date", "kind": "date", "weight": 2.0},
        {"field": "national_id", "kind": "id", "weight": 3.0},
        {"field": "phone", "kind": "phone", "weight": 1.5},
        {"field": "email", "kind": "email", "weight": 1.5},
        {"field": "address", "kind": "address", "weight": 1.0},
    ],
    # Places are calibrated as places, not people: `placename` never consults
    # the person equivalence lexicon (Fatima Hospital vs Fatouma Hospital are
    # plausibly two facilities named after two different people); `type` scores
    # the facility tier separately 
    "place": [
        {"field": "name", "kind": "placename", "weight": 2.0},
        {"field": "name", "kind": "tftoken", "weight": 2.0},
        {"field": "name", "kind": "type", "domain": "health_facility", "weight": 0.0},
        # `veto_km` is a hard constraint, not a weight. As a scored signal geo
        # was outvoted 4:1 by name+tftoken, so two facilities sharing a common
        # Hausa name merged 143 km apart with geo scoring 0.000.
        #
        # Benchmarked on GRID3 x OpenStreetMap (Kano, 685 x 1,723), scored
        # against LGA agreement — a label both sources carry independently:
        #
        #     no veto   497 same-LGA / 137 diff-LGA   78.4%   72 matches >10km
        #     50 km     497          / 113            81.5%   48
        #     25 km     497          /  80            86.1%   15
        #     10 km     495          /  67            88.1%    0
        #
        # These are the SHIPPED configuration (orthography off). An earlier
        # version of this comment carried the +hausa numbers (494/492), which
        # describe a configuration the pack does not ship.
        #
        # Re-measured when the pack moved from a table self-calibrated over the
        # two lists to the shipped `place` frequency table. The sweep's shape is
        # unchanged and 10 km is still the pick; the counts rose because the
        # population table changes which tokens are rare, and rare tokens are a
        # blocking key — so more true pairs reach the comparators at all.
        #
        # 10 km is the pick. Against 25 km it gives up 2 same-LGA matches to
        # remove 13 cross-LGA ones, and leaves nothing matched beyond 10 km.
        # The asymmetry is what justifies the tighter threshold: a veto demotes
        # to `review`, never `no_match`, so being too strict costs a human
        # glance while being too loose costs a clinic its allocation.
        #
        # Records with no coordinates are never vetoed — absent evidence
        # refutes nothing.
        {"kind": "geo", "lat": "lat", "lon": "lon", "weight": 1.0,
         "decay_km": 3.0, "veto_km": 10.0},
        {"kind": "containment", "field": "admin_path", "weight": 1.0},
        {"field": "address", "kind": "address", "weight": 1.0},
    ],
    # Artists: MBID/ISNI are the registry identifiers (a national-ID analogue);
    # alias-expand the catalog with resolve.artist_aliases() for recall.
    "artist": [
        {"field": "name", "kind": "name", "weight": 2.0},
        {"field": "name", "kind": "tftoken", "weight": 2.0},
        {"field": "mbid", "kind": "id", "weight": 3.0},
        {"field": "isni", "kind": "id", "weight": 2.0},
    ],
    # Products, electronics only and marked EXPERIMENTAL. There is no generic
    # `product` pack and shipping one would be an overclaim: what counts as a
    # code and which specifications carry identity are properties of a product
    # *category*. Levi's `501` is a model that a length threshold rejects,
    # `32x32` is not a model but looks like one, and reading `600mg` as a drug's
    # model code would be dangerous. Food, books and apparel register their own
    # rules via `resolve._productcode.register_category`; the machinery is
    # shared, the rules are not.
    #
    # Identity contract: a **purchasable variant (SKU)**. A 16GB player and a
    # 32GB player are different products however alike their titles, which is
    # why `spec` refutes rather than merely scoring.
    "product_electronics": [
        # A shared *rare* code is the identity signal. Weighted highest because
        # rarity-conditioned precision on Abt-Buy is 0.9973 with the rarity
        # filter (754 pairs) against 0.8865 without it (881).
        # Ordered so the evidence keys read plainly. The first comparator on a
        # field claims the bare field name, so `name` must be the name
        # comparator; otherwise a reviewer sees `name: 1.0` and has no way to
        # know it meant "these share a rare product code".
        {"field": "name", "kind": "name", "weight": 1.5},
        {"field": "name", "kind": "code", "weight": 3.0, "category": "electronics"},
        {"field": "name", "kind": "tftoken", "weight": 1.5},
        # Identity-bearing specifications under the SKU contract. Scored low and
        # refuting: on Abt-Buy 47 of 47 true pairs carrying a comparable unit
        # agree on every one, so the refutation is close to free there — though
        # 47 of 1,097 is a thin evidence base and the changelog says so.
        {"field": "name", "kind": "spec", "weight": 0.5,
         "category": "electronics", "refutes_below": 0.5},
    ],
    # Organisations: companies, cooperatives, unions, institutional bodies.
    # EXPERIMENTAL. Measured on ER_Magellan Fodors-Zagats (946 labelled pairs,
    # 110 positives) against criteria declared before the run:
    #
    #                        P       R      F1    false merges
    #     organisation    0.9626  0.9364  0.9493        4
    #     person          0.9863  0.6545  0.7869        1
    #     token-sort      0.8333  0.9545  0.8898       21
    #
    # The token-sort row is the meaningful comparison: +0.0595 F1 while cutting
    # false merges from 21 to 4. Beating the `person` pack only shows this pack
    # is genuinely calibrated rather than renamed.
    #
    # What that number is NOT: the set is small, near-saturated (published
    # learned baselines report ~100 F1) and is Anglophone restaurant listings.
    # It says nothing about African organisation names. The set that would
    # settle that is OpenSanctions Pairs (755,540 analyst-labelled pairs, 31
    # countries, cross-script), which is CC-BY-NC and needs a purchased licence
    # for commercial use. Reproduce with
    # `datasets/organisations_dataops/bench_organisation.py`.
    #
    # Ships with a population frequency table built from GLEIF (CC0) — see
    # datasets/organisations_dataops/SOURCES.md. It knows that `Limited`,
    # `Holdings` and `Central` are ordinary corporate tokens, which is what
    # stops a shared generic name clearing the distinctive gate. It knows
    # nothing about West African cooperative naming — LEI lists 51 entities
    # for the world's largest cocoa producer — so it must never be cited as
    # evidence for a claim about African organisation names.
    "organisation": [
        # `placename`, not `name`: organisation names must never consult the
        # person equivalence lexicon. Fatima≡Fatouma is a fact about people,
        # not about two businesses named after two different people — and
        # merging two companies is a commercial and legal error, not a
        # near-miss. Same reasoning as `place`, and it binds harder here.
        {"field": "name", "kind": "placename", "weight": 2.0,
         "strip_type": "organization"},
        {"field": "name", "kind": "tftoken", "weight": 2.0,
         "strip_type": "organization"},
        # Legal form and aggregation-node vocabulary — `Ltd`, `SARL`,
        # `Cooperative Society`, `Farmers Union`, `Washing Station`, `Factory`,
        # `Estate`. Ships at weight 0.0 like `place`'s type comparator:
        # visible in the evidence, deliberately uncalibrated until measured on
        # labelled pairs. Its real work is upstream — the vocabulary strips the
        # shared form so `tftoken` compares "Kuapa Kokoo" rather than letting
        # "Cooperative Union Ltd" carry the score.
        {"field": "name", "kind": "type", "domain": "organization", "weight": 0.0},
        # A company registration number is the national-ID analogue and the
        # only exact identity signal most supplier files carry.
        {"field": "registration_id", "kind": "id", "weight": 3.0},
        # The site/operator discriminator — the largest false-merge risk in
        # supply-chain data, and the one nothing else can catch. `Nyeri Hill
        # Factory` (site) and `Nyeri Hill Tea Factory Co Ltd` (its operator)
        # share a name AND a coordinate, so name, tftoken and geo all point the
        # wrong way at once, and stripping the type token leaves them MORE
        # alike. Only a declared class refutes it.
        #
        # weight 0.0 + refutes_below 1.0 is a pure discriminator: disagreement
        # demotes to `review`, agreement adds nothing. `category` is not a
        # distinctive kind, so two records both being SITE can never clear the
        # gate on that alone. A missing class refutes nothing, exactly as
        # absent coordinates cannot fire `veto_km` — so the comparator costs
        # callers who do not carry the field precisely nothing.
        {"field": "entity_class", "kind": "category", "weight": 0.0,
         "refutes_below": 1.0},
        {"field": "address", "kind": "address", "weight": 1.0},
        # Geo is weak evidence for a party and carries NO veto, unlike `place`.
        # A registered office and an operational site are legitimately far
        # apart, so distance cannot refute a company; and a site sits on top of
        # its operator, so proximity cannot confirm one either. It informs a
        # reviewer and barely scores.
        {"kind": "geo", "lat": "lat", "lon": "lon", "weight": 0.5,
         "decay_km": 5.0},
    ],
}

# American spelling accepted for the same pack — `organization` is the more
# common form globally and in the type vocabulary's own domain key, while this
# codebase writes `organisation` in prose. Guessing wrong should not be an
# error a caller has to debug; both names are the same list object.
ENTITY_PACKS["organization"] = ENTITY_PACKS["organisation"]

# Packs whose tftoken comparator defaults to a SHIPPED population table rather
# than self-calibration (small artist catalogs mislead a self-calibrated table
# — the toy-corpus trap the place tutorials document).
# Packs whose population is NOT the two lists being linked. Self-calibrating
# over a small pair of lists cannot know that `hospital` is common and
# `Gyaranya` is rare — that is a fact about the population, not about the
# lists. Before the place table shipped, `place` fell through to the person
# table, where facility words are unseen and therefore read as *rare*: two
# "General Hospital" records 4.4 km apart cleared the distinctiveness gate
# with the same evidence as two sharing a genuinely distinctive name.
_PACK_TF_DOMAIN: dict[str, str] = {
    "artist": "artist", "place": "place",
    # Both spellings, because both are keys of ENTITY_PACKS. Without a
    # shipped table the pack self-calibrated over the two lists being
    # linked, which is not a population: fourteen records cannot know
    # that "Central" is ordinary, so `Central Cooperative Society` in
    # two districts merged on a shared generic token.
    "organisation": "organisation", "organization": "organisation",
}



def _provided_tf_pin(tf: TokenFrequencyTable) -> str:
    """Name a caller-supplied token-frequency table, not merely its existence.

    This used to pin the string ``"provided"``. A token-frequency table decides
    which tokens are rare, and rarity is both a comparator input and a blocking
    key, so two different tables reach different verdicts on the same pair. The
    rest of this file already states that rule and follows it for shipped
    tables, which pin as ``shipped:place@sha256:...``. A caller's own table got
    the one word, so two runs that could not agree pinned identically, and
    `decision_id` claimed a reproducibility it did not have.

    Falls back to the bare word only when the table cannot be serialised. That
    is a weaker claim and it reads as one: no digest means the table was not
    identified, rather than quietly implying it was.
    """
    version = getattr(tf, "version", None)
    if version:
        return f"provided@{version}"
    digest = _tf_digest(tf)
    return f"provided@sha256:{digest}" if digest else "provided"


def _tf_digest(tf: TokenFrequencyTable) -> str | None:
    """sha256 over the table's canonical form, or ``None`` if it will not serialise.

    The table, not the corpus it came from. The table IS the scoring input, it
    is an aggregate rather than a copy of the records, and hashing it keeps the
    pin the same size whether it was built from ten names or ten million.
    """
    try:
        from arche.ids import content_hash
        return content_hash(tf.to_dict(), prefix="tf").split(":")[-1]
    except (AttributeError, TypeError, ValueError):
        return None


def pairwise(a, b, *, entity: str = "person", **kwargs):
    """Decide whether two records/documents/results refer to the same entity.

    Dispatches on input shape:

    * two Pipeline ``Result``s -> ``coref_from_pipeline`` (the compliance-aware
      path: statute citations travel; drop-actioned values are restricted);
    * two canonical ``Reference``s -> ``coref_references`` (the deterministic,
      reproducible core);
    * two strings -> ``coref_documents`` (extract-then-resolve).

    Returns a signable ``CoReferenceDecision``. Currently ``entity="person"``
    only — pairwise place/product decisions are roadmap.
    """
    if entity != "person":
        raise NotImplementedError(
            f"pairwise entity={entity!r} is not available yet; person only. "
            "Use crosswalk(...) for place lists."
        )
    from arche.resolve.coreference import (
        coref_documents,
        coref_from_pipeline,
        coref_references,
    )

    if hasattr(a, "detections") and hasattr(b, "detections"):
        return coref_from_pipeline(a, b, **kwargs)
    if hasattr(a, "attributes") and hasattr(b, "attributes"):
        return coref_references(a, b, **kwargs)
    if isinstance(a, str) and isinstance(b, str):
        return coref_documents(a, b, **kwargs)
    raise TypeError(
        f"pairwise expects two Results, two References, or two strings; "
        f"got {type(a).__name__} and {type(b).__name__}"
    )


def crosswalk(list_a, list_b, *, entity: str | None = None,
              comparators: list[dict] | None = None, tf=None, decl=None,
              **kwargs):
    """Link/dedupe two record lists at scale (blocking + gate + evidence).

    Pass ``entity=`` to use a canned comparator pack (:data:`ENTITY_PACKS`),
    or bring explicit ``comparators=`` for your own schema. When the pack uses
    a ``tftoken`` comparator and no ``tf`` is given: packs with a shipped
    population table (``artist``) load it; other packs self-calibrate a table
    over both lists' text. Pass ``tf="default"`` (person table) or a domain
    name (``tf="artist"``) to choose explicitly. Delegates to
    :func:`~arche.resolve.reconcile.reconcile`.

    Every returned edge carries a ``decision_id`` hashed over the evidence and
    the run's ``pins`` (which include the declaration pin when ``decl=`` is
    used, and the tf table's provenance); sign edges with
    :func:`arche.resolve.reconcile.sign_edges`.
    """
    extra_pins = dict(kwargs.pop("extra_pins", None) or {})
    tf_provenance: str | None = None
    if isinstance(tf, str):
        tf_provenance = f"shipped:{'person' if tf == 'default' else tf}"
    elif tf is not None:
        tf_provenance = _provided_tf_pin(tf)
    if decl is not None:
        # A declaration IS a user-defined entity pack: generated comparators,
        # its own id_field and tf defaults. Explicit args still win.
        if entity is not None:
            raise ValueError("pass either decl= or entity=, not both")
        if comparators is None:
            comparators = decl.comparators()
        kwargs.setdefault("id_field", decl.id_field)
        extra_pins.setdefault("declaration", decl.pin())
        if tf is None and decl.tf is not None:
            tf = decl.tf
            tf_provenance = f"shipped:{'person' if tf == 'default' else tf}" \
                if isinstance(tf, str) else "provided"
    if comparators is None:
        if entity is None:
            raise ValueError(
                f"pass entity= (one of {sorted(ENTITY_PACKS)}), decl=, or "
                "explicit comparators="
            )
        try:
            comparators = ENTITY_PACKS[entity]
        except KeyError:
            raise ValueError(
                f"unknown entity pack {entity!r}; available: {sorted(ENTITY_PACKS)}"
            ) from None
    if tf is None and any(c.get("kind") == "tftoken" for c in comparators):
        domain = _PACK_TF_DOMAIN.get(entity or "")
        if domain is not None:
            # This pack's population is not the lists being linked (a small
            # artist catalog miscalibrates itself) — use the shipped table,
            # falling back loudly if the data asset is absent.
            try:
                tf = TokenFrequencyTable.default(domain=domain)
                # Name the exact table, not just the domain. A rebuild changes
                # which tokens are rare, and rare tokens are both a comparator
                # input and a BLOCKING key — so a new table proposes a
                # different candidate set and can change a decision. That has
                # to be visible in the pin.
                tf_provenance = f"shipped:{domain}"
                if getattr(tf, "version", None):
                    tf_provenance += f"@{tf.version}"
                # The phrase table is a second scoring input and changes
                # decisions, so it is named in the pin too. A decision has to
                # say which data produced it, not merely which domain.
                phrases = getattr(tf, "phrases", None)
                if phrases is not None and getattr(phrases, "version", None):
                    tf_provenance += f"+phrases@{phrases.version}"
            except FileNotFoundError as exc:
                _warnings.warn(
                    f"shipped {domain!r} frequency table unavailable ({exc}); "
                    "self-calibrating over the two lists instead",
                    RuntimeWarning,
                    stacklevel=2,
                )
        if tf is None:
            # Self-calibrate distinctiveness over the lists being linked — the
            # designed reconcile path for a corpus-specific vocabulary.
            fields = {c["field"] for c in comparators if c.get("kind") == "tftoken"}
            texts = [str(r.get(f, "")) for r in [*list_a, *list_b] for f in fields]
            tf = TokenFrequencyTable.from_corpus(t for t in texts if t)
            # Name the table this run built, not merely the fact that it built
            # one. A self-calibrated table is computed FROM THE TWO LISTS, so
            # the same pair scored in two different batches gets two different
            # rarities and can get two different decisions. Measured on one
            # pair: `Ngozi Adeyemi` against `Ngozi Adeyemi Bello` scores 0.7135
            # and matches among twelve unrelated names, and 0.6608 and goes to
            # review among twelve other Adeyemis.
            #
            # Pinning the bare string `self-calibrated` said a table existed
            # and not which one, so both of those runs pinned identically while
            # disagreeing about the answer. That is the same fault the shipped
            # tables avoid by naming a digest, and it made `decision_id` claim
            # a reproducibility it did not have.
            #
            # With the digest the batch dependence is still real. It is now
            # VISIBLE: two decisions carrying different tf digests were scored
            # against different vocabularies and were never expected to agree.
            digest = _tf_digest(tf)
            tf_provenance = (f"self-calibrated@sha256:{digest}" if digest
                             else "self-calibrated")
    if tf_provenance is not None:
        extra_pins.setdefault("tf", tf_provenance)
    return reconcile(list_a, list_b, comparators, tf=tf,
                     extra_pins=extra_pins or None, **kwargs)

# The v0.1 callable-module shim (``arche.resolve(text)`` forwarding to the
# pipeline with a DeprecationWarning) was removed in v0.3.0a1 as promised.
# ``arche.resolve`` is now purely the facade package: ``resolve.pairwise``,
# ``resolve.crosswalk``. The v0.1 function lives on as
# ``arche.workflow.pipeline.resolve`` for the Pipeline internals.