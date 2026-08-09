# Licensing

Three licences, split by asset:

| Layer | Licence | Commercial use |
|---|---|---|
| **Code** — everything in `packages/arche-core/src/` | Apache-2.0 | Yes |
| **Most data** — statute packs, taxonomy, entity packs, vocabularies, benchmarks | CC-BY-4.0 | Yes, with attribution |
| **The African name-equivalence lexicon** — `datasets/name_equivalences/` | CC-BY-NC-SA-4.0 | Needs a separate grant |

The lexicon is held back deliberately and is **under review**; the rest is as
open as we can make it. Reasoning for each split is below, because a licence
without a reason is just an obstacle.

## Code — Apache License 2.0

All source code in `packages/arche-core/` is licensed under the
**Apache License 2.0**. Use it, modify it, distribute it, and build commercial
products on it, with no restrictions beyond the standard Apache-2.0 terms.

This covers the resolution engine (`detect`, `resolve`, `protect`, `attest`,
`addr`, `graph`, `workflow`), the policy and statute-loading layer, the
signing and credential layer, the provider adapters, the CLI, and all test
code.

See [LICENSE](LICENSE) for the full text.

## The name-equivalence lexicon — CC-BY-NC-SA-4.0

`datasets/name_equivalences/` — 114 equivalence groups across African naming
traditions — is licensed under
[**CC-BY-NC-SA-4.0**](https://creativecommons.org/licenses/by-nc-sa/4.0/):
attribution, non-commercial, share-alike.

It is the one asset held back, for one reason: it is the only dataset here that
is **entirely our own curation** rather than a reading of public law or a
derivative of public-domain sources. Commercial use needs a separate grant —
open an issue.

> **This split is under review.** A previous version of this repository licensed
> the lexicon three different ways in three different files. It is now stated
> once, here. If the position changes it will change in this file first, and the
> reasoning will change with it.

### An honest limitation on that restriction

**The same 114 groups are also compiled into `arche/detect/_names/lexicon.py`,
which ships in the Apache-2.0 wheel.** Anyone who installs `arche-core` has the
data under Apache-2.0 terms, and we are not going to pretend otherwise.

So the NC-SA licence on `datasets/name_equivalences/` currently governs the
YAML source of truth and the contribution flow, not the compiled copy. Closing
that gap means either extracting the groups into a separately-licensed data
file, or shipping only the 20-group starter set in the wheel. Both are real
changes with real trade-offs, and neither has been made yet.

## Everything else — CC-BY-4.0

The rest of `datasets/`, and the data packs shipped inside the wheel, are
licensed under
[**Creative Commons Attribution 4.0 International**](https://creativecommons.org/licenses/by/4.0/):

- **The Pan-African PII Taxonomy** — a classification standard, and a standard
  nobody may use commercially does not become a standard
- **Statute packs** — NDPA-2023, POPIA, Kenya DPA, Ghana DPA, GDPR,
  HIPAA Safe Harbor, and the EU AI Act overlay. These are *our reading of
  public law*. The text of a statute is not ours to restrict, and a compliance
  artifact a fintech cannot use in production is one nobody ever checks.
- **Artist equivalences** — built on MusicBrainz, which is **CC0**. We are not
  going to assert a restriction over public-domain material we merely curated.
- **Frequency tables** — built from **US Census 2010** (public domain) and
  **Wikidata / ParaNames** (CC-BY-4.0). Same reasoning.
- **Place type-token vocabularies, address tokens, and the Hausa orthography
  pack** — small linguistic rule sets whose whole value is that they spread.
- **The spatial-role gold set** — a benchmark. A yardstick the people being
  measured may not legally run is not a yardstick.

**You may** use, share, and adapt all of it, for any purpose including
commercial, provided you give attribution and indicate whether you made
changes. No non-commercial clause, no share-alike, nothing to buy.

Note what this list is: everything here is either a reading of public law, or
derived from public-domain and CC-BY sources. Restricting any of it would mean
claiming rights we do not hold. That is the actual reason these are open — not
generosity, and not a growth tactic.

A previous version of this document described the statute packs as
**proprietary** with only a "starter subset" open, and simultaneously described
the naming dataset as Apache-2.0 in one file and CC-BY-NC-SA-4.0 in another.
All three statements are superseded by this file.

See [datasets/DATASET_LICENSE.md](datasets/DATASET_LICENSE.md) for the full
terms.

## Attribution

For the data, CC-BY-4.0 attribution is satisfied by crediting Unpatterned Labs
and linking to the repository. In academic work:

```
arche: an open engine for messy, multilingual, real-world data.
Unpatterned Labs, 2026. https://github.com/unpatterned-labs/arche
```

Where a dataset carries its own citation block, prefer that — see
[datasets/DATACARD.md](datasets/DATACARD.md).

## A note on what the data is not

The statute packs are **our reading of the sections they cite**, and every
pack declares this in a `review_status` field. All six currently ship as
`self-reviewed`; none claims `regulator-reviewed`, and the loader rejects any
pack that claims it without naming a reviewer.

CC-BY-4.0 means you may use them commercially. It does not mean they are legal
advice, and it does not transfer the obligation to do your own review. See
[SECURITY.md](SECURITY.md) and the alpha warning in the README.

## Third-party data

Provider responses fetched through `arche.adapters` — geocoders, registries —
carry **their own licence, not ours**, and every `ProviderEvidence` object
records which. OpenStreetMap and Nominatim data is ODbL and requires
attribution and share-alike on derived databases.

Such responses are evidence for a single decision. They are never ingested
into arche's own packs, which is enforced in code: `may_enter_packs` is False
for any licence class outside the open set. That firewall is what keeps the
packs above unencumbered and genuinely CC-BY-4.0.

## Contact

- Repository: <https://github.com/unpatterned-labs/arche>
- Security: see [SECURITY.md](SECURITY.md)
- Lab: <https://unpatterned.org>
