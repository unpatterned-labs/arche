# The five ER activities — where arche stands

Entity resolution has a textbook decomposition ([Talburt](https://doi.org/10.1016/C2009-0-63396-1), *Entity Resolution and Information Quality*), and it begins with a discipline this whole project is built on — Talburt's opening move, paraphrased:

> **Entities do not exist in the information system — they exist in the real world.** Information systems store and manipulate *references* to entities, never the entities themselves.

arche takes that literally. There is deliberately no `Entity` object in the codebase: [`Reference`](../how-to/declare-your-schema.md) is the working object, and `entity_id` is a keyed *pseudonymous claim about* a real-world entity — evidence that references co-refer — never the entity itself. (One naming inconsistency is on record and stays: `ResolvedEntity` in the classical resolver is really a resolved *reference cluster*. Renaming it would break importers for a cosmetic gain, so the name stands and the discrepancy is documented here instead.)

Talburt names five ER activities. Here is arche against each, honestly:

| # | Activity | What it means | arche today |
|---|---|---|---|
| 1 | **Entity reference extraction** | Getting references out of documents and systems | Shipped: the detect layer, `Reference.from_detections` / `from_record`, and declaration-driven LLM extraction (`extract_declared`) |
| 2 | **Entity reference preparation** | Standardization, enhancement — what references look like when compared | Shipped, as the [representation thesis](representation-engine.md): normalizers, equivalence packs, frequency tables, declared roles. This is where most of arche's work sits |
| 3 | **Entity reference resolution** | Deciding co-reference | Shipped pairwise (gated, veto'd, [signable](attest.md)) and at scale (`crosswalk`); transitive clustering is gated post-beta work |
| 4 | **Entity identity management** | Persistent identity over time: a living knowledge base, corrections, splits and merges | **Out of scope for arche-core, deliberately.** `entity_id` is a *stateless*, recomputable claim: arche decides co-reference and hands you the evidence, and never keeps a registry of who is who between calls. Anything that remembers identity across runs — a store, its corrections, its split/merge history — is a stateful system with its own governance obligations, and it is not this library |
| 5 | **Entity relationship analysis** | Analyzing relationships *between resolved entities*: households, networks, hierarchies, bridges | **Not yet** — one demonstrated taste (the [artist collaboration graph](../tutorials/artist_resolution.md)); the plan below |

## The plan for entity relationship analysis (gated, in order)

**Why not now:** relationships connect *entities*, and before clustering ships arche only holds *references*. Relationship analysis over unresolved references puts the same person in a network three times — it conflates exactly the two things the discipline above separates. So ERA opens **after** transitive clustering (which opens after the benchmark), and the sequence is structural, not preferential.

**Phase 0 — already in hand.** Relationship *evidence* is just another data hook: the artist tutorial's collaboration edges (recording credits) and the place pack's containment hierarchy are relationship data flowing through the engine today.

**Phase 1 — relationships enter the declaration.** A `relationships:` block in the [declaration format](../how-to/declare-your-schema.md): edge types with endpoint roles, evidence fields, and a license class — so relationship data obeys the same meta-schema, the same provenance firewall, and the same pin as everything else. Representation-as-data, extended to edges.

**Phase 2 — analysis primitives, consume-don't-build.** Components (shared with clustering), community detection, centrality and **bridge detection** — the graph reading of the existing review doctrine: a single weak edge joining two large communities is precisely what routes to a human. NetworkX in-memory first; the out-of-core DataFusion path (billion-edge components in ~10 GB) is the tracked backend for national scale.

**Phase 3 — governed relationships (the arche twist).** A relationship claim is itself personal data: *who lives with whom, who transacts with whom* is often more sensitive than either party's name. So edges get what attributes already have — statute classes, masked-by-default rendering, restricted semantics, and signable relationship claims. The graph algorithms are commodity; governing the edges as personal data is the part arche would be adding.

**One rule carries over from the pairwise engine:** relationship-derived evidence never auto-merges identities. Edges are evidence, never decisions — and nothing on this list is claimed as a capability before the phase that backs it ships.

## The bookshelf

Talburt is the vocabulary, but he is one of three references arche is deliberately built against (the formulas from these books, as arche actually runs them, are taught in [From place to entity](from-place-to-entity.md)):

- **Talburt**, [*Entity Resolution and Information Quality*](https://doi.org/10.1016/C2009-0-63396-1) (2011) — the five activities above, and the entities-vs-references discipline.
- **Christen**, [*Data Matching*](https://doi.org/10.1007/978-3-642-31164-2) (2012) — the engineering practice: the pre-processing → indexing/blocking → comparison → classification pipeline that `crosswalk` instantiates (evaluation, the fifth stage, lives in the benchmark), and the evaluation discipline (measure on labelled pairs, report both error directions) behind arche's name-frequency evaluation — publishing that evaluation as a runnable benchmark is [in-flight roadmap work](roadmap.md#in-flight).
- **Christen, Ranbaduge & Schnell**, [*Linking Sensitive Data*](https://doi.org/10.1007/978-3-030-59706-1) (2020) — the privacy discipline: linked records are more identifying than any of their parts, and the re-identification literature puts location near the top (Golle & Partridge 2009; de Montjoye et al. 2013). arche's masked-by-default rendering and restricted-field semantics are that discipline enforced at the boundary; the book's privacy-preserving linkage techniques (comparing encoded records, e.g. Bloom filters, so no party ever reveals cleartext) are tracked as consume-don't-build capability for when two parties need to link without exchanging raw records.

One domain note that spans all three: for *place* references, coordinates alone cannot decide identity — the industrial evidence is the [Foursquare location-matching competition](https://www.kaggle.com/competitions/foursquare-location-matching), where winning solutions used proximity to propose candidates and decided with learned classifiers in which name and category features carry much of the weight. The full argument is in [A place is not a point](a-place-is-not-a-point.md).

---

*Related: [the representation engine](representation-engine.md) · [the data packs](https://github.com/unpatterned-labs/arche/tree/main/datasets) · [A place is not a point](a-place-is-not-a-point.md).*
