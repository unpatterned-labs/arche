# Afrobeats to the world: resolving artists across catalogs

*A royalty statement says "Ayodeji Balogun". A catalog says "Wizkid". A press release says "Starboy". Same person, three systems, and money moves (or doesn't) on whether software can tell.*

This tutorial resolves **Afrobeats, hip-hop, and pop artists** across name forms, links them through their real collaborations, and signs one identity decision, on live [MusicBrainz](https://musicbrainz.org) data (CC0). The equivalence packs are organised by **genre** (`afrobeats.yaml`, `hiphop.yaml`, `pop.yaml`), one engine for everyone's names, wherever they're from.

It's also the proof of arche's central claim, **match, don't guess**, and of the sentence under it: *a new entity type is a data pack, not new code*. That sentence is only true if the data actually ships. For artists it does, as the same two-layer recipe as African person names:

| layer | for people | for artists |
|---|---|---|
| equivalence (recall) | `datasets/name_equivalences/` (Diallo ↔ Jallow ↔ Jalloh) | **`datasets/artist_equivalences/`** (Damini Ogulu ↔ Burna Boy) |
| frequency (precision) | shipped person table (US Census + African lexicon) | **shipped artist table** (500k-artist MusicBrainz sample) |
| identity attributes | NIN, BVN, phone | **MBID, ISNI** |
| relationships | household, admin | **recording credits** (features) |

## 1. The artist pack ships in arche

The curated alias groups and the population-scale frequency table install with `pip install arche-core`, and `ENTITY_PACKS["artist"]` wires both into the engine:

```python
from arche.resolve import ENTITY_PACKS, TokenFrequencyTable, artist_aliases

aliases = artist_aliases()                             # 38 curated groups
tf_pop = TokenFrequencyTable.default(domain="artist")  # 95,306 tokens
```

```text
alias groups shipped: 38   e.g. Burna Boy ↔ ('Damini Ebunoluwa Ogulu', 'Damini Ogulu')
artist frequency table: 95,306 tokens (1,294,701 occurrences, 500k-artist sample)
pack comparators: [('name', 'name'), ('name', 'tftoken'), ('mbid', 'id'), ('isni', 'id')]

token distinctiveness under the shipped table (0 = ubiquitous, 1 = rare):
  dj        0.46 █████████
  band      0.48 ██████████
  black     0.58 ████████████
  boy       0.65 █████████████
  ogulu     0.86 █████████████████
  openiyi   0.86 █████████████████
```

"DJ", "band", "black" are catalog wallpaper, agreement on them is weak evidence. "Ogulu" and "Openiyi" are near-unique, agreement on them is strong. That asymmetry is what the frequency table knows and a toy corpus can't (§3).

## 2. Resolve a messy royalty statement

Alias-expand the catalog (one row per known name-form, each carrying the artist's MBID), then run the artist pack, the shipped frequency table loads automatically:

```python
out = resolve.crosswalk(statement, catalog, entity="artist", block=None)
```

```text
WIZKID               -> Wizkid      [match] 1.0   via 'Wizkid'
Ayodeji Balogun      -> Wizkid      [match] 1.0   via 'Ayodeji Balogun'
Damini Ogulu         -> Burna Boy   [match] 1.0   via 'Damini Ogulu'
Divine Ikubor        -> Rema        [match] 1.0   via 'Divine Ikubor'
Temilade Openiyi     -> Tems        [match] 1.0   via 'Temilade Openiyi'
Aubrey Graham        -> Drake       [match] 1.0   via 'Aubrey Graham'
...
resolved 12/12 lines
```

Four of those lines are **legal names that share no string with the stage name**. The equivalence layer makes variants *count as agreement*; the engine then weighs the evidence, the same recipe as African person names.

## 3. Why the shipped table matters: the toy-corpus trap

Earlier versions of this flow self-calibrated token frequencies over the ~180 names being linked, the trap the place tutorials document at Karfi: in a tiny corpus **every** token looks rare, so "DJ", "Black", "Young" count as strong agreement. Measured directly, on pairs of *different real artists* sharing one common token:

```text
toy tf (self-calibrated on these 10 names):
   DJ Spinall    vs DJ Snake       -> review  0.5738
   Black Sherif  vs Black Coffee   -> review  0.5596
   Young Jonn    vs Young Thug     -> review  0.5588

population tf (shipped 500k-artist table):
   nothing surfaced - every shared-token pair correctly ignored
```

Same engine, same pairs, different frequency data: three different-artist pairs stop wasting a human reviewer's time. Equivalence buys recall; **population-scale frequency buys precision**. That is why the pack ships both.

## 4. An honest failure: the wrong Tyla

Our catalog's "Tyla" came from a name-only MusicBrainz search, and it returned a **UK artist**, not the South African amapiano star. The shipped pack's Tyla group is hand-corrected to the SA artist, so its "Tyla Seethal" variant attached to whatever row the catalog calls "Tyla", and made the wrong match *more* confident (1.0). Equivalence data **amplifies the catalog's identity choice**; it cannot fix it.

That is the whole argument for identity attributes: **names describe; identifiers distinguish.** In music the registry identifiers are MBIDs/ISNIs, and agreement on one is strong evidence in exactly the way a national-ID match is for a person. The signable path uses it:

```python
ra = Reference.from_record({"full_name": "WIZKID", "national_id": wizkid_mbid})
rb = Reference.from_record({"full_name": "Wizkid", "national_id": wizkid_mbid})
decision = resolve.pairwise(ra, rb, issuer_key=KEY)   # same_entity / merge
signed = attest(decision, issuer, mode="jws")          # verified, reproducible, PII-free
```

The MBID plays the registry-identifier role; the decision mints a keyed `entity_id` from it and the attestation is a reproducible, signed claim that two catalog rows are one artist, the artifact a royalty pipeline can carry instead of a fuzzy score in a spreadsheet.

## 5. The bridge: who connects the scenes

From the African artists' actual recording credits, 16 real collaboration edges to the global hip-hop / pop set:

```text
Rema        - Selena Gomez    'Calm Down'
Wizkid      - Beyoncé         'BROWN SKIN GIRL'
Wizkid      - Drake           'Come Closer'
Burna Boy   - Ed Sheeran      'For My Hand'
Tems        - Beyoncé         'MOVE'
Tems        - Future          'Bunce Road Blues'
Ayra Starr  - Coldplay        'GOOD FEELiNGS'
Asake       - Travis Scott    'Active'
...

Biggest bridges: Tems, Wizkid - 4 global collaborators each
```

On a *resolved* catalog these edges are where royalty attribution actually lives: who is owed what flows along exactly these lines, which is why resolution is the substrate and attribution is the application.

## Takeaways

- **A new entity type is a data pack, and the pack actually ships**, `datasets/artist_equivalences/` + the 500k-sample frequency table + `ENTITY_PACKS["artist"]`, zero new engine code.
- **Equivalence buys recall, population frequency buys precision**: the toy-corpus measurement in §3 is the difference, made visible.
- **Names describe; identifiers distinguish**: the wrong-Tyla failure (which the pack honestly *amplifies*) is the cautionary tale; the MBID-anchored signed decision is the remedy.

**Siblings:** [places at scale](place_resolution_at_scale.md) · [persons at scale, scored](person_resolution_at_scale.md) · [read crosswalk output](../how-to/read-crosswalk-output.md)
