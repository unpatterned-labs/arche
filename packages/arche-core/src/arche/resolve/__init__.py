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
pattern, or ``resolve.compare`` / ``resolve.reconcile`` from this facade.
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

# The engine, imported privately. The public `reconcile` below IS this
# function plus entity-pack lookup: handed the same comparators the two
# produce byte-identical output, `decision_id` included, which is why they
# are merged into one verb rather than kept as two names for one question.
from arche.resolve.reconcile import reconcile as _reconcile_engine  # noqa: E402,F401

# What would settle a pair the engine declined to settle. Imported here rather
# than left private because the caller who needs it most is an agent, and an
# agent reaches for the documented surface. It reads `ENTITY_PACKS` from this
# module, so it imports that lazily inside the call to keep the cycle broken.
from arche.resolve._unresolved import would_resolve  # noqa: E402,F401

# The keys that make a lookup a lookup. Public because a master list is
# asked about many times and its keys do not change between questions;
# computing them once is what lets `find` scale past a scan.
from arche.resolve._fingerprint import (  # noqa: E402,F401
    FingerprintIndex,
    fingerprint,
)

# ---------------------------------------------------------------------------
#
# Two verbs, by the QUESTION being asked:
#   compare(a, b)               -> "are these two the same?"
#   reconcile(list_a, list_b)   -> "which of these are the same?"
#
# Both are named for the question, never for the algorithm that answers it or
# for one of the answers it can give. That rule is why `pairwise` (the shape of
# the algorithm) and `crosswalk` (the artifact handed back) are now the older
# spellings rather than the primary ones, and why `match` is not a verb here at
# all: a verb that promises its own happy path cannot also return `no_match`.
#
# The two scores are NOT comparable. `compare` on a person sums log-odds;
# `reconcile` takes a weighted mean over a comparator pack. 0.8 from one does
# not mean what 0.8 from the other means, which is why every receipt pins the
# engine that issued it. Read the verdict; read the score only against other
# scores from the same engine.
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
    # Home goods: furniture, bedding, rugs, window treatments, decor.
    # EXPERIMENTAL. Exists because `product_electronics` pointed at this
    # catalogue silently loses both of its safety mechanisms -- `code` finds no
    # model numbers in a home-goods title and `spec` is looking for GB and GHz.
    # What is left is title similarity with a rarity gate, which merges variants
    # of one family.
    #
    # `code` keeps its weight because a rug still carries `AT312A` when the
    # retailer publishes it. The difference is `spec`, which reads the
    # `home_goods` category: lengths in feet and inches, plus the categorical
    # attributes that actually distinguish a purchasable item here -- size,
    # colour, material and shape -- and the variant-versus-family asymmetry.
    # Groceries: supermarket listings, own-label and branded.
    # EXPERIMENTAL. The `food` category has shipped since 0.5 with extraction
    # tests and no pack, because its docstring says plainly that its matching
    # accuracy is unmeasured -- "no open grocery corpus with complete ground
    # truth is available to this project". This pack exists because one became
    # available: five UK supermarkets with a barcode on every row, so a shared
    # GTIN is truth assigned by nobody with an interest in the answer.
    #
    # The corpus is client data and is not in this repository. Run
    # `datasets/bench_product_matching.py <dir> --suite grocery` against it.
    #
    # `quantities_are_specs` is the difference that matters. Under the
    # electronics rules `415g` is a code candidate; here net contents ARE the
    # identity of a SKU, so `Tesco Almonds 200G` and `Tesco Almonds 500G` are
    # two products and the weight refutes rather than identifies.
    "product_grocery": [
        {"field": "name", "kind": "name", "weight": 1.5},
        {"field": "name", "kind": "code", "weight": 3.0, "category": "food"},
        {"field": "name", "kind": "tftoken", "weight": 1.5},
        # Weight 0.0, unlike the other product packs, and the difference is not
        # cosmetic. At weight 0.5 a refuting 0.0 drags the score down as well as
        # refuting, and on `Tesco Almonds 200G` against `Tesco Almonds 500G`
        # that put the pair at 0.505 -- under the return floor, so the edge was
        # DROPPED rather than demoted and the reviewer never saw the size
        # conflict at all. `test_raising_the_weight_overcorrects_and_loses_the_
        # pair` names that outcome as strictly worse than `review`.
        #
        # A pure discriminator refutes and never confirms, which is what a pack
        # size is: two different sizes prove two products, two identical sizes
        # prove nothing.
        {"field": "name", "kind": "spec", "weight": 0.0,
         "category": "food", "refutes_below": 0.5},
        # Own-label is the false merge this lane has to survive. `Tesco Chopped
        # Tomatoes 400g` and `Sainsbury's Chopped Tomatoes 400g` are different
        # products with the same net contents, the same category words and a
        # name similarity of 0.85 -- and they matched. The retailer name is the
        # only thing separating them, and it is a distinctive token each side
        # carries and the other lacks, which is exactly what `rival` reads.
        {"field": "name", "kind": "rival", "weight": 0.0, "refutes_below": 0.5},
    ],
    "product_home_goods": [
        {"field": "name", "kind": "name", "weight": 1.5},
        {"field": "name", "kind": "code", "weight": 3.0, "category": "home_goods"},
        {"field": "name", "kind": "tftoken", "weight": 1.5},
        {"field": "name", "kind": "spec", "weight": 0.5,
         "category": "home_goods", "refutes_below": 0.5},
        # Each side carries a distinctive token the other lacks. Weight 0.0 and
        # refuting: it contributes nothing to the score and can only hold a pair
        # back, because "these are not the same" is the only thing it knows.
        #
        # The residual failure the vocabulary could not reach. One retailer
        # lists a rug by product code (`AT21E`), another by design name
        # (`Bethanie`), and everything else agrees. Measured on 600
        # cross-retailer pairs, that shape was 41 of 43 false merges.
        {"field": "name", "kind": "rival", "weight": 0.0, "refutes_below": 0.5},
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
        # The door, refuting and weightless.
        #
        # Two suppliers of one name at different addresses merged before this
        # existed. `address` carries weight 1.0 against name's 4.0 and cannot
        # outvote it, and raising the weight is the wrong instrument: a matching
        # street number is weak evidence (every street has a number 12) while a
        # differing one is strong evidence against, and a weight is symmetric.
        #
        # A `refutes_below` on the address SIMILARITY was tried first and cannot
        # work. Measured, same-premises pairs score 0.867 to 1.000 and
        # different-premises pairs reach 0.992 — `Unit 4, Trafford Park` against
        # `Unit 9, Trafford Park` scores HIGHER than one address written two
        # ways. The distributions overlap, so no threshold divides them and the
        # number has to be compared on its own.
        #
        # **This does sit in tension with the geo comment below**, which says
        # distance cannot refute a company because a registered office and an
        # operational site are legitimately far apart. The same objection
        # applies here and the answer is what the refutation actually does: it
        # demotes to `review`, never to `no_match`. Two records giving one
        # company's office and its site are exactly what a reviewer should see
        # rather than have merged silently, and `entity_class` above is the
        # comparator that settles which is which.
        {"field": "address", "kind": "premises", "weight": 0.0,
         "refutes_below": 0.5},
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


def _compare_via_pack(a: dict, b: dict, entity: str, **kwargs):
    """One pair, decided by the pack engine, returned as a decision.

    Two records and an entity pack is the same question `crosswalk` answers for
    two lists, so this asks it that way rather than growing a second scorer.
    `_score_pair` is right there and calling it directly would be shorter, but
    it would mean re-deriving the pack, the frequency table, the code tables and
    the pins around it — a second path that drifts from the first the day either
    changes. Wrap, do not fork.

    Two deliberate choices, because both are visible in the result:

    **Blocking is off.** `block=None`. Blocking exists to avoid comparing every
    pair in two lists; a caller naming one pair has already done that job. Left
    on, `crosswalk` answers "no shared rare token" — which surfaces as *no
    result* and reads exactly like "not the same". Measured on
    `Karfi Agro Cooperative Ltd` against `Zenith Bank Plc`: `block="union"`
    yields `candidate_pairs=0` (never compared), `block=None` yields
    `candidate_pairs=1` (compared, scored below the floor). Only the second is
    an answer to the question that was asked.

    **A pair below the surfacing floor is `different`, and says so honestly.**
    `crosswalk` emits edges only at or above `threshold - review_margin`; below
    that it emits nothing, which for two lists means "not worth a reviewer's
    time" and for one named pair means "different". The thresholds are NOT bent
    to force an edge out: doing so would make the edge's own `decision` field
    say `review` while the receipt built from it said `different`, and that
    edge's `decision_id` is a hash over the field that disagrees. A receipt
    whose id addresses a different claim than the receipt makes is worse than
    no receipt.
    """
    from arche import ids as _ids
    from arche.canonical import Reference as _Reference
    from arche.resolve.coreference import Receipt

    threshold = kwargs.pop("threshold", 0.7)
    review_margin = kwargs.pop("review_margin", 0.15)
    # Same contract as the person path: a supplied issuer key makes the
    # reference ids (and so the decision address) per-issuer rather than a
    # keyless hash a third party could brute-force back to the source records.
    issuer_key = kwargs.pop("issuer_key", None)
    run = reconcile(
        [dict(a, **{"__arche_side": "a"})], [dict(b, **{"__arche_side": "b"})],
        entity=entity, id_field="__arche_side",
        block=None, threshold=threshold, review_margin=review_margin, **kwargs,
    )
    edge = run["matches"][0] if run["matches"] else None
    ref_a = _Reference.from_record(a)
    ref_b = _Reference.from_record(b)
    ref_id_a = _ids.reference_id(ref_a, key=issuer_key)
    ref_id_b = _ids.reference_id(ref_b, key=issuer_key)
    pins = dict(run["pins"])
    pins["entity_pack"] = entity

    if edge is not None:
        identity, action = (
            ("same_entity", "merge") if edge["decision"] == "match"
            else ("review", "hold")
        )
        factors = {k: v for k, v in edge["evidence"].items()
                   if isinstance(v, (int, float))}
        gate = {"distinctive_max": edge["distinctive_max"],
                "distinctive_floor": pins.get("distinctive_floor")}
        score = edge["score"]
        # The engine's own id, not a recomputed one. It addresses the edge that
        # was actually issued, under the `arche.crosswalk_edge.v1` format, and
        # re-deriving it here under a different shape would quietly mint a
        # second address for one decision.
        the_id = edge["decision_id"]
        basis = f"pack:{entity}"
    else:
        identity, action = "different", "no_op"
        factors, gate, score = {}, {
            "surfacing_floor": round(threshold - review_margin, 4),
            "surfaced": False,
        }, 0.0
        # No edge means the engine issued no receipt, so there is no engine id
        # to quote. This address is computed the way the person path computes
        # its own — over the two reference ids and the pins — so the answer is
        # still citable and still reproducible, and its `dec:` prefix says
        # plainly that it came from here rather than from an emitted edge.
        the_id = _ids.decision_id(
            reference_id_a=ref_id_a, reference_id_b=ref_id_b,
            decision="different", factors={}, gate=gate, vetoes={},
            jurisdiction="default", pins=pins, key=issuer_key,
        )
        basis = f"pack:{entity} (below surfacing floor)"

    return Receipt(
        identity=identity, action=action, basis=basis, score=score,
        factors=factors, field_weights={}, gate=gate, vetoes={},
        explanation=_explain_pack(entity, identity, factors, gate),
        reference_id_a=ref_id_a, reference_id_b=ref_id_b,
        decision_id=the_id, entity_id=None,
        reference_a=ref_a, reference_b=ref_b,
        jurisdiction="default", pins=pins,
    )


def _explain_pack(entity, identity, factors, gate) -> str:
    """One sentence a reviewer can read without knowing the pack."""
    if identity == "different":
        return (f"no {entity} evidence reached the surfacing floor of "
                f"{gate.get('surfacing_floor')}")
    agreeing = sorted((k for k, v in factors.items() if v >= 0.8))
    refuting = sorted((k for k, v in factors.items() if v <= 0.01))
    parts = []
    if agreeing:
        parts.append("agrees on " + ", ".join(agreeing))
    if refuting:
        parts.append("disagrees on " + ", ".join(refuting))
    return "; ".join(parts) if parts else "no strong signals either way"


def compare(a, b, *, entity: str = "person", store=None, **kwargs):
    """Are these two the same thing?

    The pairwise question, for any entity arche has a pack for. Returns a
    signable ``Receipt`` carrying the two-axis outcome
    (``identity`` / ``action``), the evidence that produced it, and a
    ``decision_id`` that re-derives from the same inputs.

    Accepts, on both sides and in any combination the pair agrees on:

    * two plain ``dict`` records -> the structured path;
    * two Pipeline ``Result``s -> the compliance-aware path (statute citations
      travel; drop-actioned values stay restricted);
    * two canonical ``Reference``s -> the deterministic core;
    * two strings -> extract, then decide.

    ``entity`` selects the vocabulary. ``"person"`` runs the Fellegi-Sunter
    engine in :mod:`arche.resolve.coreference`, which carries a fixed person
    schema (name / phone / national_id / email / address / dob / geo) and the
    jurisdiction priors that go with it. Every other entity runs the pack
    engine — the same one :func:`crosswalk` uses — on a single pair.

    **The two engines do not share a score.** One is a log-odds sum, the other
    a weighted mean over a comparator pack, and a 0.8 from each does not mean
    the same thing. That is why ``pins`` records which engine decided: read the
    verdict, and read `score` only against other scores from the same engine.

    ``store=`` takes a :class:`arche.ledger.Ledger` (from :func:`arche.attach`).
    The receipt is then also recorded, together with the two inputs it was made
    from, so it can be found by ``decision_id`` and made again later. The
    receipt itself is identical with or without a store.
    """
    receipt = _compare(a, b, entity=entity, **kwargs)
    if store is not None:
        store.record_compare(receipt, a, b, call={"entity": entity, **kwargs})
    return receipt


def _compare(a, b, *, entity: str = "person", **kwargs):
    """The dispatch behind :func:`compare`; see there."""
    if entity != "person":
        if entity not in ENTITY_PACKS:
            raise ValueError(
                f"no entity pack named {entity!r}; have "
                f"{', '.join(sorted(ENTITY_PACKS))}. Pass comparators= to "
                "reconcile(...) for a schema arche does not ship."
            )
        if not (isinstance(a, dict) and isinstance(b, dict)):
            raise TypeError(
                f"compare(entity={entity!r}) expects two dict records; got "
                f"{type(a).__name__} and {type(b).__name__}. The pack engine "
                "scores declared fields, so it needs the fields."
            )
        return _compare_via_pack(a, b, entity, **kwargs)

    from arche.resolve.coreference import (
        coref_documents,
        coref_from_pipeline,
        coref_references,
    )

    if hasattr(a, "detections") and hasattr(b, "detections"):
        return coref_from_pipeline(a, b, **kwargs)
    # Plain records reach the deterministic core the same way a structured
    # source does anywhere else in arche — through `Reference.from_record`,
    # which is already declaration-aware. Rejecting dicts here while
    # `crosswalk` required them was the seam that made one question look like
    # two different libraries.
    if isinstance(a, dict) and isinstance(b, dict):
        from arche.canonical import Reference as _Reference

        decl = kwargs.get("decl")
        return coref_references(
            _Reference.from_record(a, decl=decl),
            _Reference.from_record(b, decl=decl),
            **kwargs,
        )
    if hasattr(a, "attributes") and hasattr(b, "attributes"):
        return coref_references(a, b, **kwargs)
    if isinstance(a, str) and isinstance(b, str):
        return coref_documents(a, b, **kwargs)
    # Names the shapes, not the function: `pairwise` forwards here, and an
    # error naming a function the caller did not call is a small cruelty.
    raise TypeError(
        f"expects two dicts, two Results, two References, or two strings; "
        f"got {type(a).__name__} and {type(b).__name__}"
    )


# What each comparator kind is actually doing, in the one sentence somebody
# looking at a field list needs. Not documentation of the algorithm — a reason
# the field is in the pack at all.
COMPARATOR_NOTES = {
    "name": "personal-name similarity, tolerant of spelling and of a dropped "
            "middle name",
    "placename": "place-name similarity, after the type word is set aside so "
                 "`General Hospital` and `General Clinic` are not near-matches "
                 "for sharing `General`",
    # Deliberately does NOT say "in these two lists". It said that, and it was
    # true only for a pack without a shipped table. For `place`, `organisation`
    # and `artist` the population is a shipped corpus, and the difference is the
    # whole reason the same pair can be `match` under one pack and `review`
    # under another. A caller told rarity came from their own two lists has no
    # way to predict that, and no reason to look for `frequency_table` below.
    "tftoken": "how rare the shared words are in this pack's reference "
               "population (see `frequency_table`). Agreeing on an ordinary "
               "word is not evidence; agreeing on a rare one is",
    "type": "the facility or organisation type, compared as a category rather "
            "than as text",
    "date": "a date, at whatever precision each side states. A year against a "
            "full date agrees on the year and claims nothing more",
    "id": "an exact identifier. Strong when it agrees",
    "code": "a product or model code",
    "spec": "a specification drawn out of the name, such as a capacity or size",
    "premises": "whether two addresses name the same door — the unit, plot or street number, compared on its own. Two different units on one estate share nearly all their address text, so this is the only part that separates them",
    "tokenset": "how much of the shorter text is also in the longer one, as a bag of words. Order- and length-tolerant, for long titles and descriptions",
    "rival": "whether each side names something distinctive the other does "
             "not. Two listings that each carry their own rare identifier "
             "are identifying different things. It can only hold a pair "
             "back, never push one up",
    "phone": "a phone number, normalised before comparison",
    "email": "an email address",
    "address": "a postal address, compared by its parts",
    "category": "a declared class, compared exactly",
    "geo": "distance between two coordinates",
    "containment": "whether one administrative path contains the other",
}


def compare_names(name_a, name_b, priors=None):
    """Compare two names: returns ``(similarity, u_probability)``.

    Re-exported from :mod:`arche.resolve._matcher`, which is private. The
    function itself was always public-shaped — no leading underscore, a stable
    signature, a documented return — but reaching it meant importing through a
    private module, and anything that did so froze that module's name.

    `arche-mcp` did exactly that. Publishing it would have meant arche-core
    could no longer rename its own private module without breaking a released
    artifact, and a pin does not protect against that because a patch release
    could do it.
    """
    from arche.resolve._matcher import compare_names as _compare_names

    return _compare_names(name_a, name_b, priors)


# What each pack is FOR, in the one line somebody choosing between them needs.
#
# Added after watching a model answer "are General Hospital and General Hospital
# the same place?" by reaching for the `organisation` pack. It got `match` at
# distinctive_max 0.862. The `place` pack gives `review` at 0.564, because its
# frequency table knows `general` and `hospital` are ordinary facility words and
# the person and organisation tables do not.
#
# The engine refused correctly. The caller never reached the engine that would
# refuse. A pack list with no statement of purpose lets a chooser pick the pack
# whose vocabulary happens to flatter the answer, which is the failure this
# project exists to prevent, arriving one level above where it was defended.
ENTITY_PACK_PURPOSE: dict[str, str] = {
    "person": "people — names, dates of birth, national IDs, phone, email, address",
    "place": "physical locations — facilities, buildings, sites, addresses and "
             "coordinates. Use this for anything you would visit or deliver to, "
             "including hospitals, schools and clinics",
    "organisation": "legal and institutional bodies — companies, agencies, "
                    "registered entities, by name and registration id",
    "organization": "alias of `organisation`",
    "artist": "performing artists and recording names, including aliases and "
              "stage names",
    "product_electronics": "electronic products, by model code and specification",
    "product_home_goods": "furniture, bedding, rugs and decor, by variant attributes — size, colour, material, shape and length. Use this rather than `product_electronics` for anything without a model code",
    "product_grocery": "supermarket groceries, by brand and net contents — a 200g pack and a 500g pack of one item are two products",
}


def describe_pack(entity: str) -> dict:
    """What an entity pack reads, and what it does with each field.

    Written for somebody about to hand records to `crosswalk` and wondering
    which columns will be used. The answer is derivable from the pack itself, so
    it is derived rather than maintained as prose that goes stale the first time
    a comparator is added — the `person` pack gained a date comparator in
    0.5.0a1 and any hand-written list would already have been wrong.

    The important thing it says is what happens to everything else. A field the
    pack does not name is **ignored, not rejected**: no error, no warning, no
    effect on the score. That is the right behaviour — records arrive with
    columns that are nobody's business here — but it is silent, and silent is
    how somebody spends an afternoon wondering why `occupation` changed nothing.
    """
    packs = ENTITY_PACKS
    if entity not in packs:
        raise ValueError(
            f"unknown entity pack {entity!r}; available: "
            f"{', '.join(sorted(packs))}")

    by_field: dict[str, dict] = {}
    for comparator in packs[entity]:
        kind = comparator.get("kind", "")
        if kind == "geo":
            # Geo names its columns differently: two of them, and not under
            # `field`. Presented as the pair it is.
            field = f"{comparator.get('lat', 'lat')} + {comparator.get('lon', 'lon')}"
        else:
            field = comparator.get("field", "")
        if not field:
            continue
        entry = by_field.setdefault(field, {
            "field": field, "kinds": [], "weight": 0.0,
            "notes": [], "refutes": False})
        entry["kinds"].append(kind)
        entry["weight"] += float(comparator.get("weight", 0.0) or 0.0)
        note = COMPARATOR_NOTES.get(kind)
        if note and note not in entry["notes"]:
            entry["notes"].append(note)
        if comparator.get("refutes_below") is not None:
            # Asymmetric: disagreement here can pull a pair down into review.
            # It never pushes one up, and it never reaches `no_match`.
            entry["refutes"] = True
        if kind == "geo":
            for key in ("decay_km", "veto_km"):
                if comparator.get(key) is not None:
                    entry.setdefault("geo", {})[key] = comparator[key]

    fields = sorted(by_field.values(), key=lambda f: (-f["weight"], f["field"]))
    return {
        "entity": entity,
        # What it is for, so a caller choosing between packs has something to
        # choose on. The field list says what it reads, never what it is about.
        "purpose": ENTITY_PACK_PURPOSE.get(entity, ""),
        # Which population rarity is measured against, which is the thing most
        # likely to surprise a caller comparing packs. Two records reading
        # `General Hospital` are `review` under `place` (a facility gazetteer
        # knows `hospital` is 1-in-57) and `match` under `organisation` (a
        # legal-entity registry has seen it eleven times). Same strings, same
        # score, different population -- and nothing else in this dict says so.
        #
        # `None` is not "no rarity check". It means the table is built from the
        # two lists handed to `crosswalk`, so a small pair cannot know that any
        # of its own tokens are ordinary and everything reads as rare.
        "frequency_table": _PACK_TF_DOMAIN.get(entity),
        "fields": fields,
        # The names a caller can put on a record and have read. Flattened for
        # the common case of "is this column used?".
        "field_names": sorted(
            name
            for entry in fields
            for name in (entry["field"].split(" + ") if " + " in entry["field"]
                         else [entry["field"]])),
        "ignores_everything_else": True,
    }


def describe_packs() -> dict[str, dict]:
    """Every pack, described. For a picker that has to explain its options."""
    return {name: describe_pack(name) for name in sorted(ENTITY_PACKS)}


def reconcile(list_a, list_b, comparators: list[dict] | None = None, *,
              entity: str | None = None, tf=None, decl=None, store=None, **kwargs):
    """Link two lists of records: which of these are the same thing?

    The batch question, the counterpart to :func:`compare`. Returns the
    edges, the blocking diagnostics and the run pins.

    ``comparators`` is positional so that callers of the lower-level engine
    -- which this function used to sit above under a second name -- keep
    working unchanged. Handed the same comparators, the two produce
    byte-identical output including ``decision_id``; the only thing this
    adds is ``entity=`` pack lookup and declaration handling.

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

    ``backend="splink"`` swaps the scorer for Splink and keeps everything
    around it. It additionally requires ``splink_settings=``, a Splink
    ``SettingsCreator`` you wrote (or the string ``"derive"``, which infers one
    from the pack, warns, and is best-effort). See
    :mod:`arche.resolve._splink_backend` for why arche does not pick one for
    you.

    ``candidate_pairs=`` and ``candidate_pins=`` accept externally retrieved
    candidates on the default arche backend. Each candidate names ``a_id`` and
    ``b_id`` and may include a route and retrieval score; the pins describe the
    retrieval system and are included in each decision. Splink candidate
    generation remains configured through its ``SettingsCreator``.

    ``store=`` records every edge, and both lists, in a
    :class:`arche.ledger.Ledger`, so an edge can be looked up by its
    ``decision_id`` and replayed against the exact batch it was scored in.
    """
    result = _reconcile(list_a, list_b, comparators, entity=entity, tf=tf,
                        decl=decl, **kwargs)
    if store is not None:
        store.record_batch(result, list_a, list_b, call=_batch_call(
            comparators, entity=entity, tf=tf, decl=decl, **kwargs))
    return result


def _batch_call(comparators, **kwargs) -> dict:
    """The arguments a batch verb was called with, as the ledger stores them."""
    call = {"comparators": comparators, **kwargs}
    return {k: v for k, v in call.items() if v is not None}


def _reconcile(list_a, list_b, comparators: list[dict] | None = None, *,
               entity: str | None = None, tf=None, decl=None, **kwargs):
    """The engine dispatch behind :func:`reconcile`; see there."""
    extra_pins = dict(kwargs.pop("extra_pins", None) or {})
    # Read early: the token-frequency work below is arche's own scoring input,
    # and a backend that does not consume it must not pin one. Splink applies
    # term frequency inside its own name comparisons, so building a table here
    # and naming it in the pin would claim an input the decision never saw.
    backend = kwargs.pop("backend", None)
    if backend == "splink" and (
        "candidate_pairs" in kwargs or "candidate_pins" in kwargs
    ):
        raise ValueError(
            "candidate_pairs is currently supported by the default arche "
            "backend only; use backend='arche' or configure candidate "
            "generation in your Splink SettingsCreator"
        )
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
            # One exception: `backend="splink"` with the caller's own
            # `SettingsCreator` needs no pack at all. The settings already say
            # what to compare and how, and demanding a comparator pack besides
            # would be asking for a second description of the same thing.
            # `splink_settings="derive"` does need one and says so itself.
            if backend == "splink" and kwargs.get("splink_settings") is not None:
                return _splink(list_a, list_b, None, extra_pins, kwargs)
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
    if (backend in (None, "arche")
            and tf is None
            and any(c.get("kind") == "tftoken" for c in comparators)):
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

    # Backend dispatch. The default is arche's own engine and stays that way;
    # `backend="splink"` swaps the SCORER and keeps everything arche puts around
    # it (evidence, refusal, pins, decision ids), returning the same result
    # shape so `review_pack`, `crosswalk_report` and the studio are unaffected.
    #
    # It is opt-in because it is a different scoring model with different
    # provenance: it trains on the corpus, so its pins name a model and a
    # corpus rather than a comparator set alone. Selecting it is a decision, not
    # a default somebody inherits.
    #
    # It also requires `splink_settings=`. arche will not infer a Splink
    # configuration from a comparator pack behind the caller's back: a pack
    # says "compare this as a name" and says nothing about column dtype, date
    # format or field cardinality, and inferring them measured worse than
    # arche's own engine. `splink_settings="derive"` opts into the inference
    # and warns.
    if backend in (None, "arche"):
        return _reconcile_engine(list_a, list_b, comparators, tf=tf,
                                 extra_pins=extra_pins or None, **kwargs)
    if backend == "splink":
        return _splink(list_a, list_b, comparators, extra_pins, kwargs)
    raise ValueError(
        f"unknown backend {backend!r}; available: 'arche' (default), 'splink'"
    )


def dedupe(records, comparators: list[dict] | None = None, *,
           entity: str | None = None, tf=None, decl=None, store=None, **kwargs):
    """Collapse one list: which of these records are the same thing?

    The third question, after :func:`compare` ("are these two the same?") and
    :func:`reconcile` ("which of these are the same as those?"). Returns the
    surviving edges, the clusters they imply, and the run pins.

    Not the same as ``reconcile(records, records)``, which answers a question
    nobody asked: joined to itself a list yields ``n`` self-pairs -- every
    record matching itself at 1.000 -- plus two mirrored edges for every real
    pair. Both are dropped here, so an edge is always a claim about two
    *different* records, made once.

    ``clusters`` are the transitive closure over ``match`` edges only.
    ``review`` never merges: an abstention that quietly collapsed two records
    would make the third outcome decorative.

    Every cluster declares how it is held together:

    ``"direct"``
        every pair of members was compared and matched. The cluster is a
        clique; nothing in it is taken on trust.
    ``"transitive"``
        at least one member pair was never directly judged the same. A matched
        B and B matched C, so all three are grouped -- but A and C may never
        have been compared, and if they were, they may not have matched. That
        is the classic way a dedupe run swallows two genuinely different
        records, so it is reported rather than hidden.

    Ids must be unique. Two records sharing one is not a duplicate to be
    found; it is a list that cannot say which record an edge refers to.
    """
    id_field = kwargs.get("id_field", "id")
    # Positions, resolved exactly the way the engine resolves them, so the
    # ordering below refers to the same identities the edges carry.
    identities = [r.get(id_field, i) for i, r in enumerate(records)]
    order: dict = {}
    for position, identity in enumerate(identities):
        try:
            seen = identity in order
        except TypeError:  # an unhashable id: a dict or list in the id column
            raise ValueError(
                f"record {position} has an unhashable {id_field}={identity!r}; "
                "dedupe needs an id it can compare"
            ) from None
        if seen:
            raise ValueError(
                f"duplicate {id_field}={identity!r} at positions "
                f"{order[identity]} and {position}. Deduplication reports which "
                "records are the same thing, so it has to be able to tell them "
                "apart first -- two records sharing an id make every edge "
                "between them ambiguous. Give each row a distinct id, or drop "
                f"{id_field}= and let position identify them."
            )
        order[identity] = position

    run = _reconcile(records, records, comparators, entity=entity, tf=tf,
                     decl=decl, **kwargs)

    # One edge per unordered pair, and none from a record to itself. `order` is
    # consulted rather than comparing ids directly because ids need not be
    # orderable; positions always are.
    edges = [m for m in run["matches"] if order[m["a_id"]] < order[m["b_id"]]]

    matched = [(m["a_id"], m["b_id"]) for m in edges if m["decision"] == "match"]
    clusters = _clusters(identities, matched)
    if store is not None:
        store.record_batch(
            {"matches": edges, "pins": run["pins"], "blocking": run["blocking"]},
            records, records, verb="dedupe",
            call=_batch_call(comparators, entity=entity, tf=tf, decl=decl, **kwargs),
        )
    return {
        "matches": edges,
        "count": len(edges),
        "clusters": clusters,
        "cluster_count": len(clusters),
        "review": [m for m in edges if m["decision"] == "review"],
        "pins": run["pins"],
        "blocking": run["blocking"],
    }


def _clusters(identities: list, matched: list[tuple]) -> list[dict]:
    """Transitive closure over matched pairs, with how each group is held.

    Singletons are included. A record that matched nothing is a finding --
    it is the answer "this one is unique" -- and dropping it would leave the
    output impossible to line up against the input.
    """
    parent = {identity: identity for identity in identities}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in matched:
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            parent[root_b] = root_a

    groups: dict = {}
    for identity in identities:
        groups.setdefault(find(identity), []).append(identity)

    direct = {frozenset(pair) for pair in matched}
    out = []
    for members in groups.values():
        size = len(members)
        # A clique means every member pair was compared and matched. Anything
        # less and some pair is grouped on a chain rather than on evidence.
        pairs_needed = size * (size - 1) // 2
        pairs_present = sum(
            1
            for i, a in enumerate(members)
            for b in members[i + 1:]
            if frozenset((a, b)) in direct
        )
        out.append({
            "members": members,
            "size": size,
            "held_together_by": (
                "direct" if pairs_present == pairs_needed else "transitive"
            ),
        })
    out.sort(key=lambda c: (-c["size"], str(c["members"][0])))
    return out


#: One line per verb: the question it answers, and what it hands back.
#:
#: Written out rather than derived from docstrings because this is the text an
#: agent chooses on, and a docstring's first line is written for a human who
#: has already decided to read it. These are written for a reader deciding
#: which of four to call.
_VERBS: dict[str, dict[str, str]] = {
    "compare": {
        "question": "Are these two the same thing?",
        "takes": "two records (or two documents, or two references)",
        "returns": "a Receipt: identity, action, the evidence, and a "
                   "reproducible decision_id",
    },
    "reconcile": {
        "question": "Which of these are the same as those?",
        "takes": "two lists of records",
        "returns": "edges, blocking diagnostics and run pins",
    },
    "dedupe": {
        "question": "Which of these are the same thing?",
        "takes": "one list of records",
        "returns": "edges plus clusters, each saying whether it is held "
                   "together directly or transitively",
    },
    "find": {
        "question": "Which of these is this one?",
        "takes": "one record, and a list to look in",
        "returns": "a verdict of found / ambiguous / not_found, and when "
                   "ambiguous, the fields that would break the tie",
    },
}


def describe(entity: str | None = None) -> dict:
    """What arche can be asked, and about what.

    Built for a caller deciding what to do next -- typically an agent, which is
    why it is a data structure rather than prose. Names the four verbs, the
    entity packs, and for each pack the fields it reads and what each
    comparator is actually doing.

    Pass ``entity`` for one pack instead of all of them.

    The verb list is the point. Before this surface was tightened there were
    eight overlapping ways to ask three questions -- ``pairwise``, ``match``,
    ``crosswalk``, ``link``, ``resolve_entities``, ``resolve_places``,
    ``resolve_identity_records``, ``group_by_identity`` -- and no way to tell
    from their names which one to reach for. Four named questions can be chosen
    between; eight overlapping ones cannot.
    """
    packs = ({entity: describe_pack(entity)} if entity is not None
             else describe_packs())
    return {
        "verbs": _VERBS,
        "entities": sorted(packs),
        "packs": packs,
        "comparators": dict(COMPARATOR_NOTES),
        "outcomes": {
            "match": "the evidence supports one entity",
            "review": "a human should look; NOT a weak match, and never "
                      "merged automatically",
            "different": "the evidence does not support one entity",
        },
        "note": (
            "Scores are not comparable across verbs: `compare` on a person "
            "sums log-odds, the pack engine takes a weighted mean. Every "
            "receipt pins the engine that issued it -- read the verdict, and "
            "read the score only against others from the same engine."
        ),
    }


#: How close the runner-up may be before a top hit stops being an answer.
#:
#: Not a tuned constant -- a statement about what a score means. `reconcile`
#: scores a pair on its own, so two candidates at 0.85 and 0.84 are two records
#: the evidence cannot separate, not a winner and a loser. Returning the top one
#: would be arche inventing a distinction its own comparators did not find.
#:
#: 0.05 is deliberately generous. Being told "these two, and here is what would
#: tell them apart" costs a glance; picking wrong writes a false identity into a
#: master list, and that is the failure this library exists to avoid.
AMBIGUITY_MARGIN = 0.05


def find(query: dict, within: list[dict], comparators: list[dict] | None = None, *,
         entity: str | None = None, tf=None, decl=None,
         ambiguity_margin: float = AMBIGUITY_MARGIN, store=None, **kwargs):
    """Which of these is this one?

    The lookup question: you hold one record -- a supplier read off an invoice,
    a facility from a survey -- and you want the entry it refers to in a list
    you already have. :func:`compare` answers it for a named pair,
    :func:`reconcile` for two lists, :func:`dedupe` for one; none of them
    answers it for one record against many.

    Returns a verdict, not a ranking:

    ``"found"``
        one candidate matched, and nothing else came close.
    ``"ambiguous"``
        two or more candidates are within ``ambiguity_margin`` of each other.
        ``would_resolve`` says what evidence would separate them. **This is not
        a match.** Taking the top row here is how a wrong supplier gets written
        into a master list, and it is indistinguishable from a correct answer
        afterwards.
    ``"not_found"``
        nothing matched. Reported separately from ``"ambiguous"`` because they
        call for opposite actions: create a new entity, versus go and look.

    ``candidates`` always carries what was actually compared, best first, so a
    caller who disagrees with the verdict can see the same evidence it saw.
    """
    id_field = kwargs.get("id_field", "id")
    run = _reconcile([query], within, comparators, entity=entity, tf=tf,
                     decl=decl, **kwargs)
    if store is not None:
        store.record_batch(run, [query], within, verb="find", call=_batch_call(
            comparators, entity=entity, tf=tf, decl=decl, **kwargs))
    edges = sorted(run["matches"], key=lambda m: m["score"], reverse=True)
    by_id = {r.get(id_field, i): r for i, r in enumerate(within)}

    matches = [e for e in edges if e["decision"] == "match"]
    result = {
        "query": query,
        "candidates": edges,
        "pins": run["pins"],
        "blocking": run["blocking"],
    }

    if not matches:
        # Nothing cleared the bar. Anything that was surfaced is a near miss
        # worth showing -- it is the difference between "no such supplier" and
        # "one that nearly fits, go and look".
        result["verdict"] = "not_found"
        result["match"] = None
        result["reason"] = (
            f"no candidate reached `match`; {len(edges)} were compared and "
            "scored below it" if edges else
            "no candidate was comparable to the query"
        )
        return result

    best = matches[0]
    rivals = [e for e in matches[1:]
              if best["score"] - e["score"] <= ambiguity_margin]
    if rivals:
        result["verdict"] = "ambiguous"
        result["match"] = None
        result["rivals"] = [best, *rivals]
        result["reason"] = (
            f"{len(rivals) + 1} candidates within {ambiguity_margin} of each "
            f"other (top score {best['score']}); the evidence does not "
            "separate them"
        )
        # And what would. Named fields the caller can go and fetch, not a
        # list of everything absent.
        result["would_resolve"] = _what_separates(
            result["rivals"], query, by_id, id_field)
        return result

    result["verdict"] = "found"
    result["match"] = best
    result["reason"] = f"one candidate matched at {best['score']}"
    return result


def _what_separates(rivals, query, by_id, id_field):
    """Fields that would break the tie, most discriminating first.

    Deliberately NOT :func:`would_resolve`. That answers "what would settle
    this pair", and in an ambiguous lookup every tied pair has already settled
    -- asked here it replies "already resolved", which is true and useless. The
    question an ambiguous lookup actually poses is different: not *is this a
    match* but *which of these matches is it*, and that is answered by the
    fields on which the tied candidates disagree.

    A field qualifies when the candidates give different values for it and the
    query gives none. Both halves matter. A field the candidates share cannot
    separate them however well populated it is, and a field the query already
    states has had its chance and did not.
    """
    records = [by_id.get(edge["b_id"], {}) for edge in rivals]
    fields: set = set()
    for record in records:
        fields |= set(record)
    fields.discard(id_field)

    scored = []
    for field in sorted(fields):
        if str(query.get(field, "") or "").strip():
            continue  # the query states it; it did not separate them
        values = {
            str(record.get(field, "") or "").strip().lower()
            for record in records
        }
        values.discard("")
        if len(values) > 1:
            # More distinct values means a cleaner split between the rivals.
            scored.append((len(values), field))
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return [field for _, field in scored]


#: Old spellings, each mapped to the verb that replaced it.
#:
#: Both were named for the wrong thing. `pairwise` names the SHAPE of the
#: algorithm; `crosswalk` names the ARTIFACT handed back. The rule this surface
#: follows is that a verb is named for the question being asked, so they became
#: `compare` and `reconcile`. These remain as working aliases that say so.
#:
#: The word `crosswalk` survives where it was always right: the wire format is
#: still ``arche.crosswalk_edge.v1`` and stays that way, because those strings
#: are hashed into every edge ever signed. A crosswalk is the artifact;
#: reconcile is the question.
_DEPRECATED: dict[str, str] = {
    "crosswalk": "reconcile",
    "pairwise": "compare",
}


def _renamed(old: str, new: str, target):
    """Wrap ``target`` so calling it by its old name says so.

    A wrapper rather than a bare alias, because a bare alias cannot warn --
    which is what these were until every call site in this repo had been
    migrated. Warning before that migration would have fired hundreds of times
    in our own passing test run, and a DeprecationWarning people learn to
    filter is how the next real deprecation gets missed.
    """
    import functools

    @functools.wraps(target)
    def wrapper(*args, **kwargs):
        _warnings.warn(
            f"arche.resolve.{old} is now {new}; the old name still works and "
            "will be removed in a future release",
            DeprecationWarning,
            stacklevel=2,
        )
        return target(*args, **kwargs)

    wrapper.__name__ = old
    wrapper.__qualname__ = old
    wrapper.__doc__ = (
        f"Deprecated spelling of :func:`{new}`. Forwards unchanged, and warns."
    )
    return wrapper


crosswalk = _renamed("crosswalk", "reconcile", reconcile)
pairwise = _renamed("pairwise", "compare", compare)


def _splink(list_a, list_b, comparators, extra_pins: dict, kwargs: dict):
    """Hand off to the Splink backend. One call site, reached from two places."""
    from arche.resolve._splink_backend import splink_crosswalk
    return splink_crosswalk(list_a, list_b, comparators,
                            extra_pins=extra_pins or None, **kwargs)

# The v0.1 callable-module shim (``arche.resolve(text)`` forwarding to the
# pipeline with a DeprecationWarning) was removed in v0.3.0a1 as promised.
# ``arche.resolve`` is now purely the facade package: ``resolve.compare``,
# ``resolve.reconcile``. The v0.1 function lives on as
# ``arche.workflow.pipeline.resolve`` for the Pipeline internals.
