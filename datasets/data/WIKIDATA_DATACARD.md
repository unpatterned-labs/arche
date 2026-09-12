# Wikidata pulls — real names the generator cannot invent

Pulled 2026-09-11 by `datasets/pull_wikidata.py`. Source: **Wikidata, CC0** — no permission needed, which is the whole reason this lane moved while `ai4privacy` (academic-only), i2b2 (DUA) and OpenSanctions (purchase) stayed blocked. Attribution is not required by CC0 and is given anyway.

## `wikidata_name_pairs.jsonl` — 8,156 real given+family pairs

```json
{"country": "NG", "family": "Igwe", "given": "Amaechi"}
```

| country | pairs | | country | pairs |
|---|---:|---|---|---:|
| ZA | 942 | | SN | 827 |
| NG | 931 | | TZ | 846 |
| GH | 925 | | UG | 780 |
| KE | 888 | | ZW | 629 |
| CI | 872 | | ZM | 291 |
| | | | ET | 225 |

**The pair is the point.** A list of given names and a list of family names is what the generator already has — 12,369 of them. What it cannot invent is which ones go *together*, and that is exactly what `P735` (given name) and `P734` (family name) record on one person.

**The signal, measured on the pull itself: 18% of given names appearing five or more times are concentrated in a single country (≥80% of their occurrences).** That is the regional structure the notebook measured at **0.0%** in generated names against **90.4%** in real facility names. It is the input to plan N1.

**What it is not.** Wikidata's coverage is of *notable* people — athletes, politicians, musicians — so this is not a census. Common names will be under-represented relative to a population register and notable-person naming may skew colonial-era or urban. It is enough to condition a generator on and not enough to claim a population distribution. Ethiopia (225) and Zambia (291) are thin; Cameroon failed its query entirely and is absent.

## `wikidata_artist_aliases.jsonl` — 1,468 artists, 2,218 variants

```json
{"canonical": "Tamy Moyo", "country": "Zimbabwe", "entity_id": "Q30093332",
 "variants": ["Thamsanqa 'Tamy' Moyo", "Thamsanqa Moyo"]}
```

Ground truth comes free: the entity is a QID, so every variant of one artist is a known true pair and any two artists are a known true negative. No adjudication, no labelling budget.

Three kinds of variant appear, and they test different things:

- **Stage name against legal name** — `Jua Cali` / `Paul Julius Nunda`, `Jacob Radebe` / `Mpharanyana`. **Zero string overlap.** No edit distance and no frequency table solves these; an equivalence list is the only thing that can.
- **Fuller form** — `Stella Mwangi` / `Stella Nyambura Mwangi`. A middle name appears or does not.
- **Orthographic** — `Achieng Abura` / `Achien'g Abura` / `Achieng' Abura`. Punctuation and tone marking.

This is the variant list for the ablation (plan N4): supply it, withhold it, report **recall and false merges together**.

**What it is not.** 1,468 groups is thinner than the 10,000 hoped for, and the ceiling is real: Wikidata holds only so many African musicians carrying an English `skos:altLabel`. Widening means more countries, more occupations, or MusicBrainz — which has far more artists but needs either its rate-limited API (1 request/second) or a full database dump. **1.5 variants per artist is also thin**; the interesting cases are the artists with four or five.

## Reproducing

```bash
python datasets/pull_wikidata.py names   --out datasets/data/wikidata_name_pairs.jsonl
python datasets/pull_wikidata.py aliases --out datasets/data/wikidata_artist_aliases.jsonl
```

Two things the puller learned the hard way and now encodes. WDQS answers a query it considers too expensive by **closing the connection**, which arrives as `http.client.RemoteDisconnected` — a `ConnectionError`, not a `URLError`, so it escaped the first retry handler and ended the run. And `ORDER BY` over the whole result set is what made the name query too expensive at every page size; querying one country at a time returns 5,000 rows in about three seconds. An unlabelled entity comes back as its bare QID (`Faith Q16870958`), on either half of the name.
