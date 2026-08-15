# Place identity: where arche stands

Places are the entity type where identity is hardest to pin down: the thing itself never appears in any system, its coordinates disagree, its names repeat, and it changes while you watch. This page states arche's position in five claims, each with the research it stands on and the code that implements it. The [essay](../blog/a-place-is-not-a-point.md) tells the story; this page is the reference.

| # | Position | Implemented by |
|---|---|---|
| 1 | A place reference is not the place — systems hold references; the place lives in the world | [no `Place` object](#1-a-place-reference-is-not-the-place); `crosswalk` links references |
| 2 | Space proposes, place decides — coordinates generate candidates; names, types, and containment decide | [union blocking + the place pack](#2-the-signals-and-what-each-encodes) |
| 3 | An address is an identity attribute — invented to identify, not to navigate | [`addr` parsing, landmark anchors, spatial roles](#3-the-unaddressed-majority) |
| 4 | Place identity is temporal — a match decision is true *as of* its evidence | [`decision_id` + `sign_edges` pins](#4-time-drift-and-the-signature) |
| 5 | Location past a certain precision *is* the person | [masked by default, offsets only](#5-the-sensitive-half) |

## 1. A place reference is not the place

Talburt's discipline ([the five ER activities](er-activities.md)) applies with full force: *Karfi Health Post* and *Karfi Primary Health Centre* are two references whose disagreement is history, not noise. The facility was upgraded under both of them. arche therefore has no `Place` object and no place registry (resolver-not-registry): the working objects are records, `PlaceMention`s, and crosswalk *edges* between references, each carrying its evidence. Merging references into a persistent place identity is the clustering/identity-management layer, deliberately gated.

## 2. The signals, and what each encodes

Before the table, the same picture the [product page](product-identity.md) uses, with the roles renamed for places. The middle group is different here: for a product it is *granularity*, for a place it is **geometry**, which proposes candidates and is never allowed to decide one.

<div class="arche-attrmap">
<svg viewBox="0 0 760 372" role="img" aria-label="A facility record with its attributes grouped by whether they carry identity, only propose candidates, or describe without identifying.">
  <rect class="subject" x="300" y="128" width="164" height="112" rx="9"/>
  <text class="subject-label" x="382" y="170" text-anchor="middle">One facility row</text>
  <text class="subject-sub" x="382" y="190" text-anchor="middle">Karfi Primary</text>
  <text class="subject-sub" x="382" y="206" text-anchor="middle">Health Centre, Kano</text>

  <g class="identity">
    <path class="lead" d="M300 148 H210"/>
    <rect class="chip" x="30" y="132" width="180" height="30"/>
    <text class="chip-text" x="44" y="151">Distinctive name token</text>
    <text class="chip-note" x="216" y="146">Karfi, not Health Centre</text>
  </g>
  <g class="identity">
    <path class="lead" d="M300 178 H210"/>
    <rect class="chip" x="30" y="178" width="180" height="30"/>
    <text class="chip-text" x="44" y="197">Official facility code</text>
    <text class="chip-note" x="216" y="192">when a registry assigns one</text>
  </g>
  <g class="identity">
    <path class="lead" d="M300 206 H210"/>
    <rect class="chip" x="30" y="224" width="180" height="30"/>
    <text class="chip-text" x="44" y="243">Containment path</text>
    <text class="chip-note" x="216" y="238">state, LGA, ward, matched top down</text>
  </g>

  <g class="depends">
    <path class="lead" d="M464 150 H556 V60"/>
    <rect class="chip" x="556" y="42" width="176" height="30"/>
    <text class="chip-text" x="570" y="61">Coordinates</text>
  </g>
  <g class="depends">
    <path class="lead" d="M464 172 H548 V106"/>
    <rect class="chip" x="556" y="88" width="176" height="30"/>
    <text class="chip-text" x="570" y="107">Landmark anchor</text>
  </g>
  <g class="depends">
    <path class="lead" d="M464 194 H540 V152"/>
    <rect class="chip" x="556" y="134" width="176" height="30"/>
    <text class="chip-text" x="570" y="153">Facility tier or type</text>
  </g>

  <g class="describes">
    <path class="lead" d="M464 218 H556 V222"/>
    <rect class="chip" x="556" y="208" width="176" height="28"/>
    <text class="chip-text" x="570" y="226">Bed count · staffing</text>
  </g>
  <g class="describes">
    <path class="lead" d="M464 226 H548 V268"/>
    <rect class="chip" x="556" y="252" width="176" height="28"/>
    <text class="chip-text" x="570" y="270">Opening hours</text>
  </g>
  <g class="describes">
    <path class="lead" d="M464 234 H540 V312"/>
    <rect class="chip" x="556" y="296" width="176" height="28"/>
    <text class="chip-text" x="570" y="314">Ownership · phone</text>
  </g>
  <g class="describes">
    <path class="lead" d="M382 240 V342 H420"/>
    <rect class="chip" x="240" y="328" width="180" height="28"/>
    <text class="chip-text" x="254" y="346">Last survey date</text>
  </g>
</svg>
<div class="legend">
  <span><i class="k-identity"></i> carries identity</span>
  <span><i class="k-depends"></i> proposes candidates, never decides</span>
  <span><i class="k-describes"></i> describes only, never identifies</span>
</div>
</div>

Two rows in that middle group deserve their reputation. **Coordinates** for one facility routinely sit kilometres apart between surveys, so distance can generate candidates and must not settle them. And a **landmark anchor**, the "behind the central mosque" half of an unaddressed description, is genuine structure rather than a failed address, but it points at something that can close down while the junction keeps its name.

The place pack is theory written down as comparators. Each signal carries one research finding:

| Signal | Encodes | Research | Source |
|---|---|---|---|
| `geo` (haversine, 3 km decay) | Space is precise and unreliable: field coordinates for one facility routinely sit kilometres apart | Foursquare location-matching lesson: distance can't decide alone | `resolve/_matcher.py` |
| union blocking (H3 ∪ rare-token ∪ shared-id) | Space may *propose* — but a spatial-only proposal step measurably drops far-apart true pairs | ditto; measured recall cliff | `resolve/_block.py` |
| `placename` | Place names are fuzzy but durable — and never routed through the *person* equivalence lexicon (Fatima ≡ Fatouma is a fact about people, not two hospitals named after them) | [representation as data](representation-engine.md) | `resolve/_matcher.py` |
| `name_tftoken` | Agreement is worth what its rarity says (agreeing on "Karfi" ≫ agreeing on "Clinic") | Newcombe 1959 → Winkler's frequency adjustment | self-calibrated per run |
| `containment` | The named admin hierarchy is the *place* half of location — matched top-down so repeated settlement names across LGAs can't fake co-location | Relph: place is named, not measured | `resolve/_matcher.py` |
| `type` | Facility tier is evidence a reviewer reads — shown at weight 0 until calibrated on labelled pairs | Foursquare: category was a top feature — *when learned, not guessed* | `resolve/type_tokens.yaml` |
| `address` | Component-weighted, landmark anchor first; shared city names alone are weak | UK address-matching practice | `addr/parse.py` |

The math under every row of this table, with hand-computable numbers, is [From place to entity](place-identity.md#the-maths-underneath). Decoding the output row-by-row is [read crosswalk output](../how-to/read-crosswalk-output.md); running it at national scale is [the tutorial](../tutorials/place_resolution_at_scale.md). Note the blocking default is `block="union"`. Spatial cells, rare tokens, and shared identifiers OR-ed, so a true match with discordant coordinates (or none at all) still reaches the comparators.

## 3. The unaddressed majority

Billions of people live at places that are named but not addressed, and arche treats those descriptions as structure, not failure. "Behind the central mosque, Ungwan Rimi" parses into a landmark **anchor** (a first-class matching component with its own multilingual relation vocabulary in `address_tokens.yaml`), a containment tail, and, when the sentence says what the place is *for*. A **spatial role**: [`extract_places`](../how-to/extract-places-with-roles.md) labels origin/destination/location/via with the linguistic cue as evidence, abstaining as `unknown` when cues conflict. The address-as-identity-attribute argument, with its history, is in [the essay](../blog/a-place-is-not-a-point.md); the role taxonomy is ISO-Space's MOVELINK (spatial role labeling, SemEval-2012).

## 4. Time, drift, and the signature

States split, tiers upgrade, the landmark closes while the junction keeps its name, and admin boundary layers (GADM, GRID3, Overture) genuinely disagree. So a place decision never claims permanence: every crosswalk edge carries a `decision_id`, a content hash over the whole edge (ids, score, decision, evidence) plus the run's pins. Engine version, thresholds, blocking strategy, frequency-table provenance, your declaration pin, and (via `extra_pins`) the boundary layer's vintage. Signing turns that into a portable claim:

```python
from arche.resolve import crosswalk
from arche.resolve.reconcile import sign_edges
from arche.sign import generate_keypair, verify

result = crosswalk(list_a, list_b, entity="place")
kp = generate_keypair()
signed = sign_edges(result, private_key=kp.private_key, kid=kp.did_key)
verify(signed[0]["jws"], public_key=kp.public_key).valid   # True
```

The signature says *given this evidence and this representation, this was the decision*. The only honest claim about entities that have histories. Why signatures, and when they are worth their cost: [the signature on the decision](attest.md).

## 5. The sensitive half

A clinic is public; a home is not, and the re-identification literature is blunt about which side location falls on: a home/work location pair narrows most people to a handful (Golle & Partridge 2009), and four coarse spatio-temporal points uniquely identify 95% of a 1.5M-person mobility set (de Montjoye et al. 2013). arche's doctrine, enforced rather than advised: reports render [masked by default](../how-to/declare-your-schema.md), restricted fields never reach clear text, and `PlaceMention.to_dict(reveal=False)` returns **offsets only**. Never address text, so raw values stay on the caller's side of the trust boundary. (That masked shape is what an agent-facing surface would emit; no MCP server ships in v0.3.0a1.) Privacy-preserving linkage encodings (Bloom filters et al., Christen/Ranbaduge/Schnell 2020) are tracked as consume-don't-build; the declaration pin already provides the pre-encoding contract two linking parties actually need.

## The maths underneath

*Folded in from a separate page, because the signals table above and the formulas below were describing the same thing twice.*

Two rows, two Nigerian registries: *Karfi Health Post* and *Karfi Primary Health Centre*, coordinates 2.1 km apart, each record carrying its named admin path (Kano State → Kura LGA → Karfi). Feed them to `crosswalk(..., entity="place")` with the small frequency table we build below, and the engine answers: score **0.6942**, decision **review**. This page teaches the math behind that number, from a 1969 statistics paper down to the exponential in the geo comparator, so that by the end you can compute it by hand, and we will, and it will agree with the engine to four decimal places. The [five positions](place-identity.md) say where we stand; this page is why the numbers come out the way they do.

### The probability heritage: Fellegi–Sunter

Ivan Fellegi and Alan Sunter (1969) put record linkage on probability theory: for each field, estimate `m = P(agree | same entity)` and `u = P(agree | different entities)`, sum the log likelihood ratios across fields, and. Their own third verdict, often forgotten. Send the middle band to a human. arche's pairwise path implements this directly:

```
agreement      →  w = log2(m / u)
disagreement   →  w = log2((1 − m) / (1 − u))
partial (similarity s)  →  w = s · log2(m/u) + (1 − s) · log2((1−m)/(1−u))
```

Weights sum across fields, then `P(match) = 2^W / (1 + 2^W)`. One worked number, with the shipped defaults `name_m = 0.92`, `name_u = 0.01`: exact name agreement is worth `log2(0.92/0.01) = 6.52` bits, so a name alone gives `2^6.52 / (1 + 2^6.52) ≈ 0.989`. Disagreement costs `log2(0.08/0.99) = −3.63` bits. The pairwise decision then bands at 0.85 (match) and 0.40 (review). The math is not ours and we do not improve it. [Splink runs the same model](../tutorials/arche_vs_alternatives.md) with proper EM-estimated parameters, and runs it better. arche implements a thin version itself and spends its effort on the representation the model scores over. At scale the shipped path is arche's own `crosswalk`; nothing in `pairwise`, `crosswalk` or the frequency tables imports Splink.

### Rarity is evidence

Howard Newcombe noticed in 1959. A decade before the theory. That agreeing on a rare surname proves more than agreeing on a common one, and William Winkler later formalized it as the value-specific frequency adjustment: don't use one `u` per field, use one per *value*. arche does this twice. In the pairwise path, the Nigeria pack overrides `u` for common names: agreeing on *Mohammed* (`u = 0.08`) is worth `log2(0.92/0.08) = 3.52` bits against 6.52 for a default-rare name. The identical agreement, exactly 3 bits cheaper, because `0.08/0.01 = 2³`. Alone it yields `P ≈ 0.92` instead of 0.989.

In the crosswalk path the same idea generalizes to a table computed over real corpora: `distinctiveness(t) = min(1, −log10(rel_freq(t)) / 5)`, so a token at frequency 10⁻⁴ scores 0.8 and one at 10⁻¹ scores 0.2. The `tftoken` comparator is then a distinctiveness-weighted Jaccard. Take *Karfi Health Post* vs *Karfi Primary Health Centre* with a table where karfi = 10⁻⁴, health = centre = 10⁻¹, post = primary = 10⁻²: shared tokens weigh 0.8 + 0.2 = 1.0, all tokens weigh 2.0, similarity **0.50**, and most of that 0.50 is *Karfi*. Swap Karfi for another common token and the same overlap drops fast. Agreement is worth what its rarity says, and the [shipped population tables](representation-engine.md) are what make the rarity estimate trustworthy when your list is too small to calibrate itself.

### Geometry, honestly

Coordinates get one comparator and it is deliberately humble: `sim = exp(−d / decay_km)` over the haversine distance. The place pack sets `decay_km = 3.0` (the generic default is 1.5) because in field-captured African facility data roughly a quarter of true-match pairs sit more than 2 km apart. Someone measured at the gate, someone at the junction. Numbers you can check on a calculator: 1 km → `exp(−1/3)` = **0.72**, 2 km → **0.51**, 3 km → **0.37**. Never zero, never decisive on its own. The evidence dict also reports `distance_km` raw, because a reviewer reads "2.1 km apart", not "0.497".

The other half of location is the *named* hierarchy, and `compare_containment` is a small decision tree over it: walk state → LGA → settlement, top-down, and stop at the first disagreement. Full agreement to the finest level scores by depth. Settlement **1.0**, LGA **0.6**, state **0.3**, and the top-down stop rule exists because settlement names repeat heavily (Sabon Gari, Tudun Wada): two points in different LGAs whose settlements merely share a name stop at the LGA disagreement and never collect the settlement score. Disagreement at the coarsest level returns 0.0, and downstream any containment conflict demotes a would-be match to review. The map gets a voice, not a gavel.

### The engineering that makes it safe at scale

Scoring every pair in two 100k-record lists is 10¹⁰ comparisons, so every real system *blocks*. Only scores pairs that could plausibly co-refer. The brutal property of blocking is that a dropped true pair is unrecoverable: no downstream math can rescore a pair it never saw, which is why recall is the only metric a blocker is judged on, and why `reconcile` reports `blocking_recall` against labelled truth when you have it. The default is a union of three keys. H3 spatial cells (resolution 7, with a coarser safety ring because 1-ring recall collapses beyond ~2 km of GPS offset), rare shared tokens, and shared identifiers. ORed, so a true match with discordant coordinates, or none at all, still reaches the comparators. Rarity here is enforced as a cost bound, not a guess: a token whose occurrences would contribute more than `pair_cap = 1000` pairs ("clinic") is too common to block on and is skipped.

Each surviving pair gets a weighted mean of its comparator similarities. Comparators with nothing to say return `None` and are dropped from the mean, never scored as disagreement. Then two safety devices apply. The **distinctive-signal gate**: a pair may only be `match` if some *distinctive* comparator (name, placename, id, tftoken) reaches `distinctive_floor = 0.75`; geo, containment, and address amplify but never manufacture a merge, so a shared coordinate with a weak name lands in review, never match. And **banding**: `match` at/above `threshold = 0.7`, `review` within `review_margin = 0.15` below it. Fellegi–Sunter's third verdict, kept as a first-class outcome rather than an embarrassment.

Now the promised hand computation. Place-pack weights: placename 2, tftoken 2, geo 1, containment 1 (the type comparator shows in evidence at weight 0. Health Post vs PHC disagree, a reviewer sees it, the score ignores it until calibrated). Fuzzy placename similarity is the one number you take from the library: `compare_place_names` returns 0.8342. Geo at 2.1 km: `exp(−2.1/3) = 0.4966`. Containment: same settlement, 1.0. Tftoken from the table above: 0.50.

```
(2 × 0.8342 + 2 × 0.5000 + 1 × 0.4966 + 1 × 1.0) / 6 = 0.6942
```

0.6942 sits six thousandths below the 0.7 threshold, inside the review band: **review**, which is the correct answer. This pair is [the upgrade story](../blog/a-place-is-not-a-point.md), and only local knowledge resolves it. To reproduce it exactly, give both records an `admin_path` dict keyed by the containment levels the comparator walks (`admin1`, `admin2`, `settlement`) and pass `tf=TokenFrequencyTable({"karfi": 1e-4, "health": 1e-1, "centre": 1e-1, "post": 1e-2, "primary": 1e-2})`; leave the table out and the engine self-calibrates over your two lists instead, `tftoken` falls from 0.50 to 0.30, and the score lands at 0.6276. Same verdict, different arithmetic, which is itself the lesson about why shipped tables matter: a two-record corpus cannot tell you that *Karfi* is rare and *Health* is not.

The edge then gets a `decision_id`: a content hash over the evidence, the decision, and the run's pins (engine version, comparator-spec hash, thresholds, blocking strategy, frequency-table provenance). No timestamp, no randomness. Anyone holding the same inputs recomputes the same id, which is what makes the edge [citable and signable](place-identity.md).

### Measuring honesty: the referee math

The same discipline runs upstream, where [`extract_places`](../how-to/extract-places-with-roles.md) labels spans with spatial roles. Its confidences are a lookup table over evidence tiers. Cue quality × span quality, from (adjacent cue, parsed address) = 0.95 down to a floor of 0.25. Ordinal labels, not probabilities, and nothing in arche ever multiplies them. An absent or conflicting cue structurally forces `role="unknown"`: abstention is built into the table, not bolted on.

`grade_places` scores any extractor against the gold set with per-role precision, recall, and F1. Plus two numbers standard F1 cannot see, because F1 treats a non-answer and a wrong answer identically. **`over_guess`**: predicting a committed role where gold abstained, counted as a false positive *and* named separately, because it is the failure the feature exists to prevent. **`missed_by_abstention`**: answering `unknown` where gold committed, counted as a false negative but never a false positive. The asymmetry is the argument: an agent that flips origin and destination books the courier backwards; one that abstains asks a question. Those are not the same cost, so they must not be the same number. Empty denominators return `None`, never a fake zero. No grade over zero items.

### What arche adds

The math above is commodity and we say so plainly: the three-verdict model is 1969, rarity-as-evidence is 1959, the string comparators are the 1980s, and Splink executes all of it better at scale than our in-memory core. What we claim is narrower, and it is delivery form, defaults, and discipline:

- **Representation shipped as data, not weights.** The literature gives the model and its parameters; engines let you supply them. We ship the *inputs*. Equivalence packs, frequency tables, type vocabularies, cue packs, gold sets. As inspectable, versioned files with content-hash pins, correctable by the person who knows the fact. The [thesis page](representation-engine.md) makes the full case.
- **The refusal architecture.** Fellegi–Sunter defined the review verdict; we extend abstention structurally through every layer: comparators return `None` rather than fake zeros, roles return `unknown` on conflicting cues, the distinctive gate demotes rather than merges, uncalibrated signals ride at weight 0 in plain sight.
- **Signable decisions with provenance pins.** The literature provides reproducibility norms; we make each decision a content-addressed, Ed25519-signable claim pinned to the exact representation that produced it. *given this evidence and this representation, this was the decision*.
- **Refusal-aware evaluation.** Christen's discipline gives precision/recall on labelled pairs; we add `over_guess` and `missed_by_abstention` as first-class metrics, so an evaluated extractor (including your LLM) is priced on when it should have stayed silent.
- **African calibration as first-class data.** The classical results assume populations someone already tabulated. We ship the tables nobody shipped: measured name frequencies, a 3 km decay calibrated on African facility data, landmark-address grammar, cultural equivalences. Kept *out* of the place lane where they would cause false merges. That last decision is representation too.

None of these is a new theorem. All of them are choices the papers leave open, and they are where the 40% → 0% false-match result on arche's name-frequency evaluation set actually came from.

## What we don't claim

The spatial-role gold set is a 54-sentence probe, not a citable benchmark. The `type` signal is displayed, not yet weighted. Boundary polygons carry a vintage and the layers disagree. Transitive clustering, and with it persistent place identity and relationship analysis, is [gated work](er-activities.md), sequenced behind the benchmark. Where the engine is uncertain, it routes to review; where the docs would be uncertain, they say so.

---

!!! abstract "Four pages about places, and which one you want"

    Places have more written about them than any other entity type here, because
    they were the first lane to be measured. The four pages do different jobs and
    it is worth saying which, because the overlap is real.

    | Page | Job | Read it when |
    |---|---|---|
    | **This page** | the reference | you want the positions and what implements each |
    | [A place is not a point](../blog/a-place-is-not-a-point.md) | the essay | you want the argument and the history, in prose |
    | [From place to entity](place-identity.md#the-maths-underneath) | the maths | you want the formulas with hand-computable numbers |
    | [The place benchmark](place-benchmark.md) | the measurement | you want the numbers and how they were obtained |

    If you only read one, read this page. If you only read one for pleasure, read
    the essay.

*The story: [A place is not a point](../blog/a-place-is-not-a-point.md) · the practice: [place resolution at scale](../tutorials/place_resolution_at_scale.md) · the roles: [extract places](../how-to/extract-places-with-roles.md) · the math: [from place to entity](place-identity.md#the-maths-underneath).*
