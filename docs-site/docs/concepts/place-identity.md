# Place identity: where arche stands

Places are the entity type where identity is hardest to pin down: the thing itself never appears in any system, its coordinates disagree, its names repeat, and it changes while you watch. This page states arche's position in five claims, each with the research it stands on and the code that implements it. The [essay](a-place-is-not-a-point.md) tells the story; this page is the reference.

| # | Position | Implemented by |
|---|---|---|
| 1 | A place reference is not the place — systems hold references; the place lives in the world | [no `Place` object](#1-a-place-reference-is-not-the-place); `crosswalk` links references |
| 2 | Space proposes, place decides — coordinates generate candidates; names, types, and containment decide | [union blocking + the place pack](#2-the-signals-and-what-each-encodes) |
| 3 | An address is an identity attribute — invented to identify, not to navigate | [`addr` parsing, landmark anchors, spatial roles](#3-the-unaddressed-majority) |
| 4 | Place identity is temporal — a match decision is true *as of* its evidence | [`decision_id` + `sign_edges` pins](#4-time-drift-and-the-signature) |
| 5 | Location past a certain precision *is* the person | [masked by default, offsets only](#5-the-sensitive-half) |

## 1. A place reference is not the place

Talburt's discipline ([the five ER activities](er-activities.md)) applies with full force: *Karfi Health Post* and *Karfi Primary Health Centre* are two references whose disagreement is history, not noise — the facility was upgraded under both of them. arche therefore has no `Place` object and no place registry (resolver-not-registry): the working objects are records, `PlaceMention`s, and crosswalk *edges* between references, each carrying its evidence. Merging references into a persistent place identity is the clustering/identity-management layer, deliberately gated.

## 2. The signals, and what each encodes

The place pack is theory written down as comparators — each signal carries one research finding:

| Signal | Encodes | Research | Source |
|---|---|---|---|
| `geo` (haversine, 3 km decay) | Space is precise and unreliable: field coordinates for one facility routinely sit kilometres apart | Foursquare location-matching lesson: distance can't decide alone | `resolve/_matcher.py` |
| union blocking (H3 ∪ rare-token ∪ shared-id) | Space may *propose* — but a spatial-only proposal step measurably drops far-apart true pairs | ditto; measured recall cliff | `resolve/_block.py` |
| `placename` | Place names are fuzzy but durable — and never routed through the *person* equivalence lexicon (Fatima ≡ Fatouma is a fact about people, not two hospitals named after them) | [representation as data](representation-engine.md) | `resolve/_matcher.py` |
| `name_tftoken` | Agreement is worth what its rarity says (agreeing on "Karfi" ≫ agreeing on "Clinic") | Newcombe 1959 → Winkler's frequency adjustment | self-calibrated per run |
| `containment` | The named admin hierarchy is the *place* half of location — matched top-down so repeated settlement names across LGAs can't fake co-location | Relph: place is named, not measured | `resolve/_matcher.py` |
| `type` | Facility tier is evidence a reviewer reads — shown at weight 0 until calibrated on labelled pairs | Foursquare: category was a top feature — *when learned, not guessed* | `resolve/type_tokens.yaml` |
| `address` | Component-weighted, landmark anchor first; shared city names alone are weak | UK address-matching practice | `addr/parse.py` |

The math under every row of this table, with hand-computable numbers, is [From place to entity](from-place-to-entity.md). Decoding the output row-by-row is [read crosswalk output](../how-to/read-crosswalk-output.md); running it at national scale is [the tutorial](../tutorials/place_resolution_at_scale.md). Note the blocking default is `block="union"` — spatial cells, rare tokens, and shared identifiers OR-ed, so a true match with discordant coordinates (or none at all) still reaches the comparators.

## 3. The unaddressed majority

Billions of people live at places that are named but not addressed — and arche treats those descriptions as structure, not failure. "Behind the central mosque, Ungwan Rimi" parses into a landmark **anchor** (a first-class matching component with its own multilingual relation vocabulary in `address_tokens.yaml`), a containment tail, and — when the sentence says what the place is *for* — a **spatial role**: [`extract_places`](../how-to/extract-places-with-roles.md) labels origin/destination/location/via with the linguistic cue as evidence, abstaining as `unknown` when cues conflict. The address-as-identity-attribute argument, with its history, is in [the essay](a-place-is-not-a-point.md); the role taxonomy is ISO-Space's MOVELINK (spatial role labeling, SemEval-2012).

## 4. Time, drift, and the signature

States split, tiers upgrade, the landmark closes while the junction keeps its name — and admin boundary layers (GADM, GRID3, Overture) genuinely disagree. So a place decision never claims permanence: every crosswalk edge carries a `decision_id`, a content hash over the whole edge (ids, score, decision, evidence) plus the run's pins — engine version, thresholds, blocking strategy, frequency-table provenance, your declaration pin, and (via `extra_pins`) the boundary layer's vintage. Signing turns that into a portable claim:

```python
from arche.resolve import crosswalk
from arche.resolve.reconcile import sign_edges
from arche.sign import generate_keypair, verify

result = crosswalk(list_a, list_b, entity="place")
kp = generate_keypair()
signed = sign_edges(result, private_key=kp.private_key, kid=kp.did_key)
verify(signed[0]["jws"], public_key=kp.public_key).valid   # True
```

The signature says *given this evidence and this representation, this was the decision* — the only honest claim about entities that have histories. Why signatures, and when they are worth their cost: [the signature on the decision](attest.md).

## 5. The sensitive half

A clinic is public; a home is not — and the re-identification literature is blunt about which side location falls on: a home/work location pair narrows most people to a handful (Golle & Partridge 2009), and four coarse spatio-temporal points uniquely identify 95% of a 1.5M-person mobility set (de Montjoye et al. 2013). arche's doctrine, enforced rather than advised: reports render [masked by default](../how-to/declare-your-schema.md), restricted fields never reach clear text, and `PlaceMention.to_dict(reveal=False)` returns **offsets only** — never address text — so raw values stay on the caller's side of the trust boundary. (That masked shape is what an agent-facing surface would emit; no MCP server ships in v0.3.0a1.) Privacy-preserving linkage encodings (Bloom filters et al., Christen/Ranbaduge/Schnell 2020) are tracked as consume-don't-build; the declaration pin already provides the pre-encoding contract two linking parties actually need.

## What we don't claim

The spatial-role gold set is a 54-sentence probe, not a citable benchmark. The `type` signal is displayed, not yet weighted. Boundary polygons carry a vintage and the layers disagree. Transitive clustering — and with it persistent place identity and relationship analysis — is [gated work](er-activities.md), sequenced behind the benchmark. Where the engine is uncertain, it routes to review; where the docs would be uncertain, they say so.

---

*The story: [A place is not a point](a-place-is-not-a-point.md) · the practice: [place resolution at scale](../tutorials/place_resolution_at_scale.md) · the roles: [extract places](../how-to/extract-places-with-roles.md) · the math: [from place to entity](from-place-to-entity.md).*
