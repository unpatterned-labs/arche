# arche datasets — Licence

Copyright 2026 Unpatterned Labs

Two licences here, split by asset. The **code** in this repository is
Apache-2.0, which is a third licence for a separate thing — see
[LICENSING.md](../LICENSING.md).

## Name equivalences — CC-BY-NC-SA-4.0

`name_equivalences/` is licensed under
[Creative Commons Attribution-NonCommercial-ShareAlike 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/).

Full text: <https://creativecommons.org/licenses/by-nc-sa/4.0/legalcode>

Non-commercial use, with attribution, and derivatives under the same terms.
Commercial use needs a separate grant — open an issue.

This is the one asset held back, because it is the only dataset here that is
entirely our own curation rather than a reading of public law or a derivative
of public-domain sources. **The position is under review.**

Be aware of a limitation we are not going to hide: the same 114 groups are also
compiled into `arche/detect/_names/lexicon.py` and ship in the Apache-2.0
wheel. This licence governs the YAML source of truth and the contribution flow;
it does not retroactively restrict the copy already distributed in the package.

## Everything else — CC-BY-4.0

The rest of this directory, and the data packs shipped inside the `arche-core`
wheel, are licensed under
[Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/).

Full text: <https://creativecommons.org/licenses/by/4.0/legalcode>

- **Pan-African PII Taxonomy** — `pan-african-pii-taxonomy/`
- **Artist equivalences** — `artist_equivalences/`
- **Statute packs** shipped in the wheel — NDPA-2023, POPIA, Kenya DPA,
  Ghana DPA, GDPR, HIPAA Safe Harbor, and the EU AI Act overlay
- **Place vocabularies** — type tokens, the Hausa orthography pack
- **Frequency tables** and the spatial-role gold set

These are open for a specific reason, not out of generosity: every one of them
is either a reading of public law, or derived from public-domain and CC-BY
sources — US Census 2010, Wikidata / ParaNames, MusicBrainz (CC0). Restricting
them would mean claiming rights we do not hold.

## What you may do (CC-BY-4.0 assets)

- **Use** them, for any purpose, **including commercially**
- **Share** them — copy and redistribute in any medium or format
- **Adapt** them — remix, transform, and build upon them

## The one condition

**Attribution.** Give appropriate credit, link to the licence, and indicate if
you made changes. Crediting *Unpatterned Labs* with a link to
<https://github.com/unpatterned-labs/arche> satisfies this.

You may do so in any reasonable manner, but not in any way that suggests we
endorse you or your use.

Earlier versions of this file and of `LICENSING.md` disagreed with each other —
one said Apache-2.0, another said CC-BY-NC-SA-4.0, and a third described the
statute packs as proprietary. All of that is superseded by the split at the top
of this file.

## Contributing

By submitting a pull request you agree to license your contribution under the
licence of the asset you are contributing to: **CC-BY-NC-SA-4.0** for
`name_equivalences/`, **CC-BY-4.0** for everything else.

Contributions that add or correct naming conventions for underrepresented
languages and ethnic groups are the most valuable thing anyone can send us. If
you know a convention first-hand, that knowledge is the qualification that
matters — see the "Data correction or addition" issue template.

## What this data is not

The statute packs are **our reading of the sections they cite**. Every pack
carries a `review_status` field; all six currently ship as `self-reviewed`, and
none claims `regulator-reviewed`. CC-BY-4.0 lets you use them commercially. It
does not make them legal advice, and it does not do your compliance review for
you.

The naming conventions encoded here originate from living cultural and
linguistic traditions practised by hundreds of millions of people. Treat
corrections from native speakers as authoritative over anything we inferred.

## Third-party data

Data fetched at runtime through `arche.adapters` carries its own licence, not
this one. OpenStreetMap and Nominatim responses are ODbL. Such responses are
evidence for a single decision and are never ingested into these datasets —
enforced in code, so that everything above stays genuinely CC-BY-4.0.

## Citation

```bibtex
@misc{arche_datasets_2026,
  title  = {arche datasets: name equivalences, statute packs, and entity packs},
  author = {Unpatterned Labs},
  year   = {2026},
  url    = {https://github.com/unpatterned-labs/arche},
  note   = {CC-BY-4.0}
}
```
