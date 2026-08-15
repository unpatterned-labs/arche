# Organisation frequency table — sources, licence, and what it cannot tell you

Built by `build_organisation_frequencies.py` into
`packages/arche-core/src/arche/resolve/_data/organisation_frequencies.json.gz`.

## Why the table exists

`ENTITY_PACKS["organisation"]` shipped without one. The distinctive-signal cap
that prevents an identical-but-*generic* name clearing the match gate is
conditioned on `tf.population_scale`, and a table self-calibrated over the two
lists being linked is correctly not one — fourteen records cannot know that
`Central` is common. Without this asset, two records both named
`Central Cooperative Society` merge on a shared generic token. That is the
`Central Dispensary` over-merge the `place` pack fixed by shipping a table, and
this is the same fix for organisations.

## Source

- **Source:** GLEIF (Global Legal Entity Identifier Foundation), Level 1
  legal-entity reference data.
- **URL:** <https://api.gleif.org> · <https://www.gleif.org/en/about/open-data>
- **Licence:** **CC0 1.0 Universal** — a public domain dedication.
- **Retrieved:** 2026-08-15.

## Why CC0 decided this, over two better-fitting datasets

The licence was the gate, not the domain fit, and two datasets that fit the
problem *better* were rejected on it. Recording the reasoning so it is not
re-litigated from scratch:

| Candidate | Licence | Verdict |
|---|---|---|
| **GLEIF LEI** | CC0 1.0 | **Used.** No attribution condition, no share-alike, no commercial restriction, so a derived table ships inside an Apache-2.0 wheel without encumbering it. |
| **Open Food Facts** | ODbL | **Rejected for vendoring.** Share-alike reaches *derived databases*, and a frequency table built from its names is one: shipping it would put an ODbL-encumbered component inside an Apache-2.0 wheel and oblige us to license the result under ODbL. Fine to analyse with. Not fine to ship from. |
| **Trase** (Ghana / Côte d'Ivoire cocoa) | CC BY 4.0 on charts; **per dataset** otherwise | **Usable — sequenced after GLEIF, not blocked by licence.** This is the *right* population: real Ghanaian and Ivorian cocoa exporters, the entities the pack exists for. |

### Correction — CC BY is not a blocker, and an earlier draft of this file implied it was

The first version of this document treated Trase's licence as an obstacle
comparable to Open Food Facts'. That was wrong, and the distinction matters
enough to write down rather than quietly edit:

* **ODbL propagates.** Its share-alike condition reaches *derived databases*, so
  a frequency table built from Open Food Facts must itself be offered under
  ODbL. Shipping it inside an Apache-2.0 wheel would encumber the wheel. That is
  a genuine blocker.
* **CC BY does not propagate.** It asks for attribution and nothing else. It
  places no condition on the licence of the work it travels in.

**This repository already ships CC BY 4.0 data inside the Apache-2.0 wheel and
says so** — see `data/er_bench/SOURCES.md` on the Leipzig benchmark sets:
*"Creative Commons Attribution 4.0 (CC BY 4.0). Redistribution is permitted with
attribution, which is what this file provides."* Trase under CC BY would be that
same, already-established pattern, and arche's own datasets are published on
comparable terms.

Two things from the original flag do survive, and both are small:

1. Trase sets licensing **per dataset**, so read the specific supply-chain
   dataset's own terms rather than inferring from the site-wide statement.
2. Trase asks commercial users to make contact. That is a request, not a
   prohibition, and it is not engaged at all by an open case study or a
   published benchmark. Worth an email anyway before anything commercial builds
   on it — it costs one message and it is how you would want to be treated.

The rule this actually encodes is narrower than the one first written here:
**share-alike on a derived database is a blocker for a vendored artifact;
attribution is not.** GLEIF was still the right *first* build, because CC0
removes even the attribution bookkeeping and its global corporate coverage is
what closes the generic-token gap. Trase is the right *second* one, because it
covers the population GLEIF demonstrably cannot — 51 registered entities for the
world's largest cocoa producer — and the two tables answer different questions.

## Use and intent — and what this section deliberately is not

This work is done for **research and open knowledge**: an open entity-resolution
engine, published methods, and benchmarks reported whichever way they fall. The
tables here exist so that a health ministry, a journalist, a cooperative or a
researcher can reconcile records without buying a licence to do it. Attribution
to every upstream source is given above and kept current.

**That is a statement of intent, not a licence condition, and the difference
matters enough to be explicit.**

- GLEIF is **CC0** — a public domain dedication that imposes *no* conditions.
  There is nothing here to restrict, and writing a restriction into this file
  would not create one.
- `arche-core` is **Apache-2.0**. Anyone who installs the wheel needs to know
  the data inside it is unencumbered. A "non-commercial" notice sitting in an
  Apache-2.0 package would make a downstream user reasonably wonder whether
  part of the wheel is off-limits to them, which would chill exactly the reuse
  this project exists to enable.
- arche is developed alongside a commercial hosted product. A file declaring
  the data non-commercial would be inconsistent with that on its face, and an
  inconsistency in a licence note is worse than no note.

So: intent stated, provenance attributed, **rights not narrowed**. If you build
something commercial on this, the licences above already permit it and nothing
in this file takes that away.

Two commitments that *are* binding on us, because they are ours to make:

1. Every source is named, with its licence, before it is used — the licence
   check is a build gate, not an afterthought.
2. Where a source asks for contact before commercial use (Trase does), we make
   that contact before anything commercial builds on it. It is a courtesy the
   licence does not require and we would want extended to us.

## Known bias — read before quoting anything built on this

LEI registration follows participation in financial markets, so coverage is
extremely uneven, and it is thinnest exactly where arche claims strength:

| | | | |
|---|---|---|---|
| Côte d'Ivoire | **51** | Netherlands | 194,784 |
| Ghana | **138** | Germany | 254,088 |
| Nigeria | 978 | Belgium | 67,476 |
| Kenya | 306 | Switzerland | 27,993 |
| Ethiopia | **16** | | |
| **10 W/E African countries combined** | **1,743** | **Global index** | 3,403,130 |

Fifty-one registered entities for the world's largest cocoa producer.

**So this table knows corporate naming — that `Limited`, `Holdings`, `Group`,
`International` and `Central` are ordinary — and it does not know West African
cooperative naming.** It is the right instrument for stopping a generic token
clearing the gate. It is the wrong instrument for any claim about African
organisation names, and it must never be cited as evidence for one. Those claims
still require adjudicated African data, which does not exist in this repo.

The `place` table has the opposite shape — built from Nigerian facilities, it
knows African facility vocabulary and nothing about European corporate forms.
Neither is a general-purpose organisation population, and saying so is cheaper
than having a reader assume otherwise.

## Sampling

Two strata, deliberately unequal:

1. **Census** of every LEI record in 20 African jurisdictions. Taken whole
   because they are small — a proportional random draw would have returned
   almost nothing, and near-nothing of the population we most care about.
2. **Spread sample** of 150 pages of the global index at evenly spaced offsets.
   Spaced rather than the first 150 pages because the index is LEI-ordered, so
   the top of it is not a random draw.

Both legal names and transliterated/other name forms are counted: a token that
is common only in transliteration is still common, and a matcher will meet both.

## Rebuilding

```sh
python datasets/organisations_dataops/build_organisation_frequencies.py
```

The raw corpus is cached beside the builder as `gleif_names.json.gz`, so the
table can be rebuilt and audited without re-fetching. The builder refuses to
write a table from fewer than 5,000 distinct name forms, because below that it
is not a population claim and the `population_scale` flag would be a lie.

## The two halves, and which one you should edit

The artefact has a measured half and a curated half, and almost every
correction belongs in the second:

| | File | What it is |
|---|---|---|
| Measured | `gleif_names.json.gz` (cached corpus) | 52,875 name forms pulled from GLEIF. Regenerate with `--refetch`. |
| **Curated** | **`packages/arche-core/src/arche/resolve/_data/organisation_tokens.yaml`** | **Hand-editable. Where domain knowledge goes.** |
| Built | `_data/organisation_frequencies.json.gz` | Measured counts with the curated layer applied last. |

The curated layer is not a convenience. It is where arche's African-context
calibration for organisations actually lives, because GLEIF *structurally
cannot* supply it:

```
                measured (GLEIF)    curated
  farmers                      1        223
  cooperative                 10        223
  society                     19        223
  central                     40        223
```

One occurrence of `farmers` in 52,875 organisation names. Measured alone, the
table concludes `farmers` is a rare, identifying token — so two unrelated
`X Farmers Cooperative Society` records would clear the distinctiveness gate on
that word. No larger GLEIF pull fixes it, because LEI lists financial-market
participants and cooperatives do not register LEIs. Someone who has read a cocoa
or coffee supplier list has to assert it.

This is the same mechanism, for the same reason, as `place_tokens.yaml`, which
met the identical failure with `PHC` at 4 occurrences in 51,022 Nigerian
facility names.

**The one rule that keeps the file from doing harm:** never add a distinctive
proper name. `kuapa`, `sefwi`, `gicherori`, `kericho` are precisely the tokens
that must stay rare — they are what tells one cooperative from another, and
marking them generic would stop the pack matching the records it exists for. A
commodity word (`cocoa`) is generic; a place word (`sefwi`) is not. Two tests
enforce both directions.

Editing is a data change, not a code change:

```sh
# edit organisation_tokens.yaml, then — seconds, no network
python datasets/organisations_dataops/build_organisation_frequencies.py
```
