# A representation engine, not an inference engine

arche is a **representation engine**: it ships the data that decides what two records look like when compared — equivalence packs, frequency tables, ID grammars, statute packs — and delegates probabilistic scoring to commodity inference engines like [Splink](https://moj-analytical-services.github.io/splink/). This page states that claim in full, with the annotated bibliography for both halves at the end.

### Terminology

This page uses [Talburt's](https://doi.org/10.1016/C2009-0-63396-1) vocabulary, which arche's canonical layer implements directly:

| Term | Meaning |
|---|---|
| **entity** | the real-world thing (a person, a clinic, an artist) |
| **entity reference** | a record that mentions an entity |
| **identity attributes** | the fields of a reference that can distinguish one entity from another (name, national ID, registry identifier) |
| **co-refer** | two references point at the same entity; resolution decides this |

### The two halves

**Inference** computes *how likely is it that two references co-refer, given some evidence of agreement?* Pairwise scoring under the standard model (Fellegi–Sunter, 1969; the formula arche's pairwise path implements, worked in bits, is on [the science page](from-place-to-entity.md#the-probability-heritage-fellegisunter)) is a solved commodity — Splink runs it over a million records on a laptop — and arche deliberately [does not compete with it](../tutorials/arche_vs_alternatives.md). The open remainder of inference is real: collective and graph-based resolution, clustering under transitive closure. That is exactly the post-beta work arche keeps gated.

**Representation** decides *what the references look like when compared*: what counts as agreement, what agreement is worth, and what may be compared at all.

The line between the halves isn't clean — Splink accepts custom comparison levels and external term-frequency tables; dedupe learns comparators from your labels; and neural matchers ([Ditto](https://arxiv.org/abs/2004.00584)-class encoders, [embedding-based blocking](https://arxiv.org/abs/2005.14471)) genuinely ship representation **as weights**. arche's claim is precise: representation shipped **as data** — inspectable, versioned, citable, correctable by the person who knows the fact. The case for that delivery form (deterministic replay, PII that can't reach a model, facts that outlive checkpoints) is made below.

## Representation failures: what inference can't see

Take the pair that anchors everything arche does: *Diallo* (Francophone spelling) and *Jallow* (Anglophone spelling) — one Fula surname split by a colonial border. Hand these to any inference engine and it computes, correctly, that the strings show only partial, coincidental similarity, below any match threshold. The probability math is flawless. The answer is wrong — because the evidence the inference needed, *these two tokens co-refer*, **never existed in the records**. Someone has to put it there.

| The failure | What inference sees | The missing representation |
|---|---|---|
| Diallo ↔ Jallow | partial string similarity, coincidental not evidential | an [equivalence group](https://github.com/unpatterned-labs/arche/tree/main/datasets): one surname, two orthographies |
| Damini Ogulu ↔ Burna Boy | zero token overlap | an alias pack: legal name ↔ stage name |
| "agreement on *Ibrahim*" | a token match — unweighted unless someone supplies a table | a [frequency table](https://github.com/unpatterned-labs/arche/tree/main/datasets): *Ibrahim* is common, weak evidence; *Gyaranya* is rare, strong |
| "Karfi Health Post" ↔ "Karfi PHC" | partial overlap on one rare token | a type-token vocabulary that isolates the facility-type words and a corpus that knows what *Karfi* is worth — and because the two types disagree, the pair correctly **stays in review**. Representation also decides when *not* to merge |
| "behind the Total filling station, Madina junction" | an unparseable string | landmark-grammar address representation |
| NIN vs phone number | two 11-digit strings | an identifier grammar (format, issuer, checksum where a public spec exists) — plus, separately, the statute pack that governs the field's handling |

Representation decides **what counts as agreement, what agreement is worth, and what may be compared at all**. Inference does the arithmetic afterwards — supplied with evidence that only representation can create.

## What a representation engine ships

Seen through this lens, almost everything in arche is representation, shipped in two forms: **data packs** (inspectable files you can diff and correct) and **canonical forms defined in code** (executable contracts). Both are reviewable; only the first is a dataset.

- **[`Reference`](../tutorials/entity_resolution.md) and identity attributes** *(canonical form)* — the shape of "a record that refers to an entity": which fields identify, which merely describe, and which are *restricted* — usable as match evidence but never disclosable. What a record *is*, before any comparison.
- **Equivalence packs** *(data)* — [name equivalences](https://github.com/unpatterned-labs/arche/tree/main/datasets) across 20+ ethnic and linguistic traditions, artist alias groups by genre. External knowledge that makes variants count as agreement. Recall lives here.
- **Frequency tables** *(data)* — measured token distinctiveness over real populations, loaded via `TokenFrequencyTable.default()` (persons) and `TokenFrequencyTable.default(domain="artist")` (a 500k-artist MusicBrainz sample). What agreement is *worth* — the tables feed the classical value-specific frequency adjustment (Winkler, 1989). 40% → 0% false-match rate on arche's name-frequency evaluation set (publishing it as a reproducible benchmark is [in-flight](roadmap.md#in-flight), not shipped); a self-calibrated table on a small corpus [measurably fails](../tutorials/artist_resolution.md#3-why-the-shipped-table-matters-the-toy-corpus-trap) where the population table doesn't.
- **Normalizers and candidate keys** *(data + canonical form)* — casefolding, diacritic folding, the type-token vocabulary ("PHC" ↔ "Primary Health Centre"), E.164 phone normalization: the canonical text under every comparator. Blocking is representation too — which attributes may propose a candidate pair at all (H3 cells for places, multi-pass keys for persons).
- **Statute packs** *(data)* — what a field *is, legally*: the NDPA/POPIA/GDPR/HIPAA YAML that decides sensitivity, lawful action, and the citation every detection carries.
- **Masked-by-default rendering** *(canonical form)* — what a record looks like *when shown*: PII masked unless explicitly revealed, restricted values never.
- **Canonical signing form** *(canonical form)* — what a decision looks like *when proven*: deterministic canonical JSON, pinned comparators, keyed identifiers — the same evidence always produces the same signable decision, verified via [`attest`](../tutorials/sign_share_extract.md).

The one piece of inference opinion arche does hold is small and deliberate: the **distinctive-evidence gate** — no merge without at least one piece of distinctive agreement, which is how the Febrl4 person benchmark (synthetic, evaluated at the pairwise level where arche's shipped surface lives) holds [zero false merges at 0.877 auto-match recall](../tutorials/person_resolution_at_scale.md). Everything else defers: the Fellegi–Sunter core is intentionally thin, and arche does not claim to improve the maths — [Splink runs the same model better](../tutorials/arche_vs_alternatives.md), with proper EM-estimated parameters. What arche adds is the representation those parameters are estimated *over*. At scale the shipped path is arche's own `crosswalk` with union blocking; Splink is reachable only through the deprecated v0.1 `resolve_entities()`, and no part of `pairwise`, `crosswalk` or the frequency tables imports it.

In code, the surface is two calls:

```python
from arche import resolve
from arche.attest import attest

out = resolve.crosswalk(statement, catalog, entity="artist")  # or "person", "place"

decision = resolve.pairwise(record_a, record_b, issuer_key=key_bytes)
decision.identity      # "same_entity" | "review" | "different"
decision.factors       # per-field evidence
decision.decision_id   # reproducible content address

signed = attest(decision, issuer_keypair, mode="jws")
```

`crosswalk` links lists at scale (blocking + gate + evidence; see [reading its output](../how-to/read-crosswalk-output.md)); `pairwise` returns a signable co-reference decision and is person-shaped today — the two share primitives and the gate but are deliberately distinct scoring paths.

## Can an LLM be the representation?

The evidence that language models *help* with matching is real: pre-trained transformers beat classical matchers on standard benchmarks ([Ditto](https://arxiv.org/abs/2004.00584), 2020), foundation models do credible zero-shot entity matching ([Narayan et al.](https://arxiv.org/abs/2205.09911), 2022), LLMs need far less task-specific training data ([Peeters & Bizer](https://arxiv.org/abs/2310.11244), 2023), and the line of work since has only strengthened, with fine-tuned open-weights judges closing on frontier accuracy. They are also genuinely good at representation *authoring*: parsing landmark addresses into components, proposing candidate equivalences, transliterating across scripts.

Three properties still disqualify a model from *being* the representation:

1. **Its decisions are not replayable.** Sampling can be tamed — temperature 0, constrained output schemas — but a hosted model's decision cannot be re-verified once that model version retires, and a signature you cannot re-verify is not a signature. The prompt- and model-sensitivity the matching literature documents is the same defect observed from outside. The knowledge itself is real where it's needed least: models know *Damini Ogulu ↔ Burna Boy* (a memorized fact about a famous person); on the tail where identity actually lives — *Gyaranya*, a rural facility, a low-resource orthography — the equivalence knowledge is a plausible guess, and plausible-but-wrong is the most expensive failure mode in identity.
2. **The reference often may not reach the model.** Entity references are PII: under NDPA/GDPR, sending them to a third-party API can itself be the violation, and in civil-registry and health deployments data-sovereignty and procurement rules close the door regardless of contract. The objection is to egress, not to models — so when a model touches this data it runs where the data lives (GLiNER-class extractors on CPU as an opt-in extra, behind the egress guard). Open weights carry a second, quieter property: only a model pinnable by hash can live inside a signed decision. **You cannot attest what you cannot pin.**
3. **The representation must outlive any model.** A fact like *Diallo ↔ Jallow* deserves to be written down once, reviewed, versioned, cited, and executed deterministically at dictionary-lookup cost. Weights make facts unreviewable and rentable. There is also arithmetic: a million-record deduplication is ~10⁷ candidate pairs after blocking; per-pair model calls cost real money and hours of latency on every run, for facts a pack answers in microseconds, forever.

Every serious mitigation — retrieval over a curated corpus, constrained schemas, a fine-tuned judge graded against labeled truth — smuggles the pack back in; grounding the model concedes that the ground, not the model, is the product. The division of labour that follows: **models propose, curators accept, the engine executes.** The [evaluation harness](../how-to/bring-your-own-llm.md) closes the loop in the other direction: bring your own LLM for extraction and matching, and arche grades it against the deterministic engine and records an honest account of how the answer was reached.

## Grounding, operationally

The [symbol grounding problem](https://doi.org/10.1016/0167-2789(90)90087-6) (Harnad, 1990) says a system that only manipulates symbols never touches what the symbols are about. A bare model asked about a name computes over text about the string, not the person — and resolution alone doesn't close the gap either: co-reference links references to *each other*, not to the entity; anchoring still needs trusted identifiers and registries. But when an AI system *acts* in the real world, grounding becomes concrete and entity-shaped — which actual person is this claim about, and may this data move? — and a reference resolved through curated representation, anchored to identifiers, with evidence, a citation, and a signature is the operational piece of the answer. Not all of grounding; a load-bearing part. Read at the representation level, that is what the agent-facing surface is for: agents don't need arche to think, they need it to stand on.

## Design consequences

**A new entity type is a representation, not a program.** Persons, places, and artists run on the same crosswalk engine and comparator kit — a new type is configuration plus data: an identity-attribute mapping, equivalence data, frequency calibration. The [artist pack](../tutorials/artist_resolution.md) added no new comparator code at all. (Signable `pairwise` decisions are person-shaped today; extending them is roadmap, not implied.)

**Engines are swappable below; callers are agnostic above.** Because the representation layer is the contract, the inference backend can be arche's in-memory core today and Splink tomorrow — and the caller can be a script, a pipeline, or an AI agent (through whatever tool layer you wire it into — an MCP server is on the roadmap, not in this release).

**Representation quality is measurable.** Inference benchmarks measure classifiers. arche's benchmarks measure *representations*: false-match rates when the frequency table is population-scale vs toy, missed-match rates when equivalence packs are present vs absent — with embedding matchers as baselines and losses published alongside wins. That is the shape of the planned African-name benchmark: sharply named representation failures (transliteration, patronymics, compound names, cross-script variants), runnable against any engine.

**Low-standardization data is the proving ground.** arche's packs and benchmarks are calibrated on identity data with no canonical spellings, landmark addresses, and fragmented ID systems — the regimes where representation failures dominate and where a matcher that only ships inference is silently wrong.

## Further reading — both halves

*The inference half:* Fellegi & Sunter (1969), ["A Theory for Record Linkage"](https://doi.org/10.1080/01621459.1969.10501049) (*JASA* 64), building on Newcombe et al. (1959) in [*Science*](https://doi.org/10.1126/science.130.3381.954), is the model under Splink and arche's pairwise core; Winkler (1989, "Frequency-Based Matching in the Fellegi–Sunter Model of Record Linkage," ASA Survey Research Methods) formalized the value-specific frequency adjustment arche's tables feed. [Linacre et al. (2022)](https://doi.org/10.23889/ijpds.v7i3.1794) describes Splink itself, and Robin Linacre's [interactive Fellegi–Sunter introduction](https://www.robinlinacre.com/probabilistic_linkage/) is the best on-ramp. [Papadakis et al. (2020)](https://doi.org/10.1145/3377455) surveys blocking, and [Bhattacharya & Getoor (2007)](https://doi.org/10.1145/1217299.1217304) is the collective-resolution remainder pairwise scoring doesn't cover.

*The representation half:* Christen's [*Data Matching*](https://doi.org/10.1007/978-3-642-31164-2) (Springer, 2012) is the standard textbook — its pre-processing and comparison chapters are this page's argument in academic form. Talburt's [*Entity Resolution and Information Quality*](https://doi.org/10.1016/C2009-0-63396-1) (2011) supplies the vocabulary arche implements (entities, references, identity attributes, co-reference). [ParaNames](https://arxiv.org/abs/2202.14035) (Sälevä & Lignos, 2022) is multilingual name representation at Wikidata scale; [uk_address_matcher](https://github.com/RobinL/uk_address_matcher) is the direct inspiration for arche's `tftoken` comparator; and Kanerva's [hyperdimensional computing](https://doi.org/10.1007/s12559-009-9009-8) (2009) is our research horizon — hypervector binding offers compositional, similarity-preserving encodings of attribute–value structure, a possible middle path between brittle symbols and opaque embeddings — held to a hard gate: it stays research until it beats the shipped matcher on the public benchmark, and only qualifies if it can stay inspectable.

*Models, weights, and grounding:* [Ditto](https://arxiv.org/abs/2004.00584) (Li et al., 2020), [DeepBlocker](https://arxiv.org/abs/2005.14471) (Thirumuruganathan et al., 2021), [Narayan et al.](https://arxiv.org/abs/2205.09911) (2022), and [Peeters & Bizer](https://arxiv.org/abs/2310.11244) (2023) measure what models can and can't do in matching; [Harnad (1990)](https://doi.org/10.1016/0167-2789(90)90087-6) frames the grounding problem; [Hogan et al. (2021)](https://arxiv.org/abs/2003.02320) survey the entity-centric (knowledge-graph) answer to it.

---

*Related: [the data packs](https://github.com/unpatterned-labs/arche/tree/main/datasets) (the representations themselves) · [why arche, and when to use it](../tutorials/arche_vs_alternatives.md) (the inference landscape) · [from place to entity](from-place-to-entity.md) (the math, worked by hand) · [how arche works](how-it-works.md).*
