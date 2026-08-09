# Why arche, and when to use it

*Presidio labels spans. GLiNER extracts them. Splink and Senzing link records. Every one of them has to be told what counts as agreement in the data in front of it, and none of them ships that knowledge. arche is building the layer that does — **entity representation**: a shared, inspectable, correctable account of what the world's entities are called and which is which. This page states that claim, corrects one we got wrong, and is honest about where the alternatives are the better pick.*

!!! warning "Status: pre-beta (v0.3.0a1) — not for production use yet"

    Suitable today for research, prototyping, evaluation, benchmarking, and contributing.

---

## What arche is for

Record linkage has a settled mathematical core. Fellegi and Sunter wrote it down in 1969: for each field, weigh the probability that two records agree given they refer to the same entity against the probability they agree by chance, add the log-odds, compare against two thresholds. Splink runs that over a million records on a laptop. Senzing sells entity resolution as a product. arche implements the model too. Nobody is competing on the arithmetic.

What is not settled, and what nothing ships, is the input the arithmetic needs. Before you can weigh agreement you have to decide **what agreement is**. Is `Diallo` agreement with `Jallow`? Is `Karfi PHC` agreement with `Karfi Health Post`? Is agreeing on `Ibrahim` worth the same as agreeing on `Gyaranya`? Is `12345678901` a national identity number, a bank verification number, or a phone number with the leading zero eaten by a spreadsheet?

Those are not questions about probability. They are questions about the world, and every one of them has an answer that somebody knows and that no model can reliably guess. Generic engines make you supply those answers yourself, per project, in code that never leaves your repository. Nobody else gets the correction. Nobody can check it. When you leave, it goes.

**arche's contribution is that layer, shipped as data.** Equivalence packs, frequency tables, identifier grammars, type-token vocabularies, orthography rules, statute mappings — inspectable files you can diff, cite, version and correct, rather than weights you can only retrain or heuristics you can only reimplement. [A representation engine, not an inference engine](../concepts/representation-engine.md) makes the full argument, including why a language model can author a representation but cannot be one.

That is the forward-looking version of "why arche". The feature comparison below is real and it is worth reading, but it is a snapshot of a landscape, not the reason the project exists.

## The Splink question, answered plainly

An earlier version of this page — and, at the time of writing, the package description on PyPI — said arche "composes with Splink" and delegates probabilistic scoring to it. That is true of exactly one legacy function and false of everything else, and stating it plainly matters more than the tidiness of the story.

You can check it yourself in about fifteen lines. Watch `sys.modules` while calling each entry point, with splink installed.

```python
import sys

import splink
print("splink installed:", splink.__version__)
for name in [m for m in sys.modules if m.split(".")[0] == "splink"]:
    del sys.modules[name]


def loaded():
    return len([m for m in sys.modules if m.split(".")[0] == "splink"])


from arche.canonical import Reference
from arche.extract import Entity
from arche.resolve import (
    TokenFrequencyTable, crosswalk, pairwise, resolve_entities,
)
print(f"{'import arche.resolve':44} splink modules loaded: {loaded()}")

a = Reference.from_record({"id": "A", "full_name": "Ngozi Adeyemi",
                           "national_id": "12345678901"})
b = Reference.from_record({"id": "B", "full_name": "N. Adeyemi",
                           "national_id": "12345678901"})
pairwise(a, b, issuer_key=b"k" * 32)
print(f"{'pairwise()':44} splink modules loaded: {loaded()}")

crosswalk([{"id": "A", "name": "Karfi PHC"}],
          [{"id": "B", "name": "Karfi Health Post"}], entity="person")
print(f"{'crosswalk()':44} splink modules loaded: {loaded()}")

TokenFrequencyTable.default()
print(f"{'TokenFrequencyTable.default()':44} splink modules loaded: {loaded()}")

# The v0.2 classical resolver, ten entities or more, with the extra installed.
resolve_entities([Entity(text=f"Adesola Okonkwo {i // 3}", entity_type="PERSON",
                         confidence=0.9, start=0, end=10) for i in range(12)],
                 use_splink=True)
print(f"{'resolve_entities(..., use_splink=True)':44} splink modules loaded: {loaded()}")
```

```text
splink installed: 4.0.16
import arche.resolve                         splink modules loaded: 0
pairwise()                                   splink modules loaded: 0
crosswalk()                                  splink modules loaded: 0
TokenFrequencyTable.default()                splink modules loaded: 0
resolve_entities(..., use_splink=True)       splink modules loaded: 84
```

*(Splink prints its own EM-training chatter during the last call; it is elided above.)*

One import site exists in the whole package, inside `_resolve_splink` in `resolve/classical.py`, on the v0.2 `resolve_entities()` path. `_matcher.py`'s own docstring says it "replaces Splink as the primary matching engine". `_tokenfreq.py` names Splink once, in a comment describing "the term-frequency adjustment a Splink user gets from their own data" — an analogy for what the shipped table does, not a dependency on it.

**The honest relationship is this: arche and Splink implement the same statistical framework.** Both are Fellegi-Sunter. Splink is the better implementation of the framework — distributed backends, EM parameter estimation, a million records on a laptop, an ecosystem. arche's contribution is not a better scorer. It is **the representation the scorer runs on**: the comparators, vocabularies and frequency tables that make Fellegi-Sunter work on names and places that generic comparison levels get wrong. Those are portable. A Splink user can build a custom comparison level around arche's name lexicon or feed arche's frequency table as a term-frequency adjustment, and get the benefit without importing arche's matcher at all. That is a better description of composition than a dependency edge, and it is the one that survives contact with the code.

## Two kinds of failure

### The one you can see in thirty seconds

Detection first, because it is the failure that is immediately visible. Install Microsoft Presidio, feed it identifiers from the four launch jurisdictions, and take its highest-confidence answer.

```python
from presidio_analyzer import AnalyzerEngine

from arche import Pipeline

CASES = [
    ("NG", "Customer Fatima Abdullahi, NIN 12345678901."),
    ("NG", "BVN 22156789012 on file."),
    ("ZA", "ID number 8001015009087 on the application."),
    ("GH", "Ghana Card GHA-123456789-0 presented."),
    ("KE", "KRA PIN A012345678Z registered."),
]

engine = AnalyzerEngine()

for jurisdiction, text in CASES:
    guesses = sorted(engine.analyze(text=text, language="en"),
                     key=lambda r: -r.score)
    top = (f"{guesses[0].entity_type} ({guesses[0].score})" if guesses
           else "(nothing detected)")
    ours = [(d.category, d.text)
            for d in Pipeline(jurisdiction=jurisdiction).process(text).detections
            if d.category.startswith("PII-2")]
    print(text)
    print(f"    presidio : {top}")
    print(f"    arche    : {ours}")
```

```text
Customer Fatima Abdullahi, NIN 12345678901.
    presidio : PHONE_NUMBER (0.4)
    arche    : [('PII-2-NIN', '12345678901')]
BVN 22156789012 on file.
    presidio : DATE_TIME (0.85)
    arche    : [('PII-2-BVN', '22156789012')]
ID number 8001015009087 on the application.
    presidio : US_BANK_NUMBER (0.05)
    arche    : [('PII-2-NATIONAL_ID', '8001015009087')]
Ghana Card GHA-123456789-0 presented.
    presidio : PHONE_NUMBER (0.4)
    arche    : [('PII-2-GHANA_CARD', 'GHA-123456789-0')]
KRA PIN A012345678Z registered.
    presidio : (nothing detected)
    arche    : [('PII-2-KRA_PIN', 'A012345678Z')]
```

A Nigerian bank verification number read as a date at 0.85 confidence. A South African ID — thirteen digits with an embedded date of birth, gender, citizenship flag and a Luhn check digit — read as a US bank account. A Kenyan tax PIN not seen at all.

The Presidio team did nothing wrong. They shipped recognisers for the data their users had, and their extension API is exactly how you are meant to add your own. The point is what "add your own" costs: an identifier grammar per scheme, a check-digit validator where a public spec exists, a sensitivity classification, and the statute section that justifies it — multiplied by every jurisdiction you operate in, maintained against amendments, forever. That work is representation. It is the same work whichever engine you plug it into, and it is worth doing once in public.

arche ships **26 identifier patterns** in `detect._africa.ids.ID_PATTERNS`, covering the four launch jurisdictions plus eleven further African countries, with structural and check-digit validation wherever the underlying scheme publishes one. Phone normalisation runs through `phonenumbers` for E.164. Neural NER is the opt-in `arche-core[detect]` extra and is never on the critical path — the base wheel is rule-based and CPU-only by design.

### The one you cannot see

The second failure is quieter and more expensive, because the arithmetic is flawless and the answer is still wrong.

Hand `Mamadou Diallo` and `Mohamed Jallow` to any string comparator and it computes, correctly, that the strings barely overlap. `Diallo` and `Jallow` are one Fula surname split by a colonial border — Francophone and Anglophone transcriptions of the same name. No amount of probability recovers that, because the evidence the probability needed never existed in the records. Somebody has to put it there.

```python
from jellyfish import jaro_winkler_similarity

from arche.resolve._matcher import compare_names

PAIRS = [
    ("Mamadou Diallo", "Mohamed Jallow"),         # one Fula surname, two orthographies
    ("Chukwuemeka Okafor", "Emeka Okafor"),       # Igbo prefix-elision
    ("Fatima Abdullahi", "Fatoumata Abdoulaye"),  # Hausa / Wolof cognates
    ("Adeyẹmí Okonkwo", "Adeyemi Okonkwo"),       # Yoruba tone marks
    ("Ngozi Adeyemi", "Chinwe Balogun"),          # a negative that must not move
]

print(f"{'jaro-winkler':>13} {'arche':>7}  pair")
for a, b in PAIRS:
    similarity, _u = compare_names(a, b)
    print(f"{jaro_winkler_similarity(a, b):>13.3f} {similarity:>7.3f}"
          f"  {a!r} <> {b!r}")
```

```text
 jaro-winkler   arche  pair
        0.769   0.911  'Mamadou Diallo' <> 'Mohamed Jallow'
        0.752   1.000  'Chukwuemeka Okafor' <> 'Emeka Okafor'
        0.683   0.943  'Fatima Abdullahi' <> 'Fatoumata Abdoulaye'
        0.947   1.000  'Adeyẹmí Okonkwo' <> 'Adeyemi Okonkwo'
        0.371   0.447  'Ngozi Adeyemi' <> 'Chinwe Balogun'
```

Jaro-Winkler is not a strawman here: `JaroWinklerAtThresholds` is a standard Splink comparison level and is what arche's own classical path configures when it hands work to Splink. The lexicon moves the true pairs and leaves the negative where it was. It is deliberately conservative — arche does not claim `Mamadou` and `Mary` are the same name, only equivalences documented by people who speak the languages. **114 equivalence groups, 454 name forms, across 20-plus ethnic and linguistic traditions**, published CC-BY-4.0 in [`datasets/name_equivalences`](https://github.com/unpatterned-labs/arche/tree/main/datasets/name_equivalences) with a per-file breakdown in `datasets/STATISTICS.md`.

The other half of the same problem is what agreement is *worth*. Two records agreeing on `Ibrahim` is weak evidence in northern Nigeria and strong evidence in Reykjavik, and no comparator can know that without a population.

```python
from arche.resolve import TokenFrequencyTable

tf = TokenFrequencyTable.default()
print(f"shipped person table: {tf.vocabulary_size:,} tokens "
      f"over {tf.total_count:,.0f} counts")
print(f"{'token':12} {'rel. freq':>10} {'distinctiveness':>16}")
for token in ("ibrahim", "mohammed", "gyaranya", "okonkwo"):
    print(f"{token:12} {tf.rel_freq(token):>10.6f} "
          f"{tf.distinctiveness(token):>16.4f}")
```

```text
shipped person table: 50,591 tokens over 1,903,937 counts
token         rel. freq  distinctiveness
ibrahim        0.001399           0.5709
mohammed       0.000384           0.6832
gyaranya       0.000050           0.8602
okonkwo        0.000018           0.9479
```

This is Winkler's 1989 value-specific frequency adjustment — a piece of the classical model that has been in the literature for thirty-five years, that every serious engine supports, and that most deployments never switch on because it needs a table nobody publishes for their population. Splink accepts external term-frequency tables. So does arche. The table is the contribution, not the mechanism.

The consequence at decision time is that `Ibrahim Musa` matched against `Ibrahim Musa` **does not clear arche's pairwise gate**, because neither shared token is rare enough to distinguish two people. It goes to a human instead. [Entity resolution](entity_resolution.md#the-same-pair-two-engines-two-answers) shows that abstention, and the pair of engines that disagree about it, in full.

## Where it is calibrated, and why that is Africa

Almost every worked example on this site is Nigerian, Kenyan, South African or Ghanaian. That is a statement about calibration, not about scope.

Representation failures dominate wherever identity data has no canonical spellings, addresses are landmarks rather than grids, identifier schemes are young and fragmented, and the same person appears under a legal name, a praise name, a transliteration and an initial. A matcher that only ships inference is not slightly worse there — it is confidently wrong, and it cannot tell you so. Calibrating against that regime is what forces the packs to be real: a comparator tuned on clean Western names would never have needed the Hausa boundary-collapsing rules, and a frequency table calibrated on a different population prices its tokens for that population and not for yours.

The regime is not confined to Africa. It is South and Southeast Asia, Latin America, migrant registries, historical archives, and any dataset that crossed a script boundary or a colonial border. The engine is entity-generic already — [persons](person_resolution_at_scale.md), [places](place_resolution_at_scale.md) and [recording artists](artist_resolution.md) run on the same crosswalk engine and the same comparator kit, and adding the artist pack required no new comparator code at all. The statute layer ships GDPR and HIPAA Safe Harbor alongside the four African packs. What arrives next is more representation, contributed by the people who hold the facts, not more engine.

## What arche ships as data

| Pack | What it decides | Where it lives |
|---|---|---|
| Name equivalences | Whether two spellings are the same name | [`datasets/name_equivalences`](https://github.com/unpatterned-labs/arche/tree/main/datasets/name_equivalences) (CC-BY-4.0) |
| Frequency tables | What agreement on a token is worth | `TokenFrequencyTable.default()`, and `default(domain="artist")` |
| Identifier grammars | What a string of digits actually is | `detect._africa.ids.ID_PATTERNS` — 26 patterns, validated |
| Type-token vocabulary | That `PHC` and `Primary Health Centre` are the same tier | `resolve/type_tokens.yaml` |
| Orthography rules | That `Mai Tsidau` and `Maitsidau` share a token | `resolve/_data/orthography.yaml` — opt-in, with its gaps written down |
| Statute packs | What a field is, legally, and what may be done to it | `arche/policy/statutes/*.yaml` |
| PII taxonomy | The category vocabulary all of the above agree on | [`datasets/pan-african-pii-taxonomy`](https://github.com/unpatterned-labs/arche/tree/main/datasets/pan-african-pii-taxonomy) — 54 categories, CC-BY-4.0 |

Every one of those is a file. You can read it, diff it, fork it, cite it in a paper, and send a pull request correcting it when it is wrong about your language. That is the property weights do not have.

## The statute layer, which the open-source alternatives do not have

Detection is one floor. Every `Detection` arche emits already carries the statute section that classifies it and the sensitivity tier that follows, populated from the statute YAML before the policy engine runs.

```python
from arche import Pipeline

TEXT = ("Customer Fatima Abdullahi, NIN 12345678901, BVN 22156789012, "
        "phone 0803 555 7890, RC 245678.")

result = Pipeline(jurisdiction="NG").process(TEXT)
for d in result.detections:
    print(f"{d.category:14} {d.text!r:18} tier={d.sensitivity_tier:8} "
          f"{d.regulatory_citation}")
print()
print(result.redacted_text)
```

```text
PII-2-RC       'RC 245678'        tier=low      NDPA-2023 s.31 (legitimate interests)
PII-2-BVN      '22156789012'      tier=high     NDPA-2023 s.30, CBN BVN policy 2014
PII-2-NIN      '12345678901'      tier=high     NDPA-2023 s.30, NIMC Act s.27
PII-1-NAME     'Fatima'           tier=moderate NDPA-2023 s.30
PII-1-NAME     'Abdullahi'        tier=moderate NDPA-2023 s.30
PII-3-PHONE    '0803 555 7890'    tier=moderate NDPA-2023 s.30

Customer NAME_099000a2 NAME_e38a0fcd, NIN [NIN], BVN [BVN], phone PHONE_d3100c11, RC 245678.
```

Change `jurisdiction="NG"` to `"ZA"` for POPIA, `"KE"` for the Kenya DPA, `"GH"` for the Ghana DPA, or any EU-27 or EEA country code — `"DE"`, `"FR"`, `"IE"` — for the GDPR. Sectoral regimes take the explicit escape hatch, `Pipeline(jurisdiction="US", statute="HIPAA-SAFE-HARBOR")`. Six packs ship; three of them still carry a `v0.1-scaffold` version label that understates how complete they are, and correcting those labels is [outstanding](../concepts/roadmap.md). The company registration number is `retain` rather than masked, because the NDPA treats it under legitimate interests and the pack says so out loud.

Watch the failure mode at the edge of that map, because it is silent: `"EU"` is not a jurisdiction code. `Pipeline(jurisdiction="EU")` constructs happily, resolves no statute, and returns text unchanged. That is exactly the case `EgressGuard` exists to catch — no statute means no policy means no permission to emit.

The two labels on every pack are independent by design: `version` is a claim about our work, `review_status` is a claim about the world. **No pack claims `regulator-reviewed`**, and the loader fails closed on one that does so without naming a reviewer. Statute amendments are YAML changes, not code changes.

## When to use each tool

**Use Microsoft Presidio when** your data is English-language US or EU PII, you are already in the Microsoft ecosystem, or you are prepared to write and maintain per-country recognisers yourself. Its extension model is good and its Western coverage is better than arche's.

**Use GLiNER when** you need multilingual soft-PII — free-form names, occupations, organisations — from a single model, your categories overlap what it ships, and you can absorb the install footprint. It ships no African government identifiers. arche composes with it through `arche-core[detect]`, deterministic validators disposing of what the model proposes.

**Use Splink when** you have a large volume of structured records to link and your comparison logic is either standard or something you are happy to author. It is the better inference engine and this page is not arguing otherwise. Bring arche's frequency table and name comparators to it if your names need them.

**Use Senzing or another commercial ER product when** you want an operational system rather than a library: identity resolution as a running service, with a support contract, an operator console and an entity store. arche is a library that returns decisions; it has no server, no console and no storage backend.

**Use an LLM when** you need representation *authored* — parsing landmark addresses, proposing candidate equivalences, transliterating across scripts. Models are genuinely good at that. Do not let one *be* the representation: its decisions cannot be replayed once a version retires, the records often may not legally reach it, and the facts deserve to outlive any checkpoint. [`arche.llm`](../how-to/bring-your-own-llm.md) exists to grade a model against the deterministic engine, not to defer to it.

**Use arche when** any of these is true. Your identifiers are not covered by the Western defaults and you would otherwise be writing grammars and validators yourself. Your names need equivalence knowledge and frequency calibration a generic comparator cannot supply. You need every detection to cite the statute section that classifies it, because someone will eventually ask which rule fired. You need a decision you can sign, hand to a third party, and have them verify offline. Or you need the answer "a human must look at this" to be a first-class output rather than a threshold you tuned.

**Do not use arche when** your data is clean Western PII with no African or low-standardisation footprint and Presidio's defaults already work; when you want a hosted, supported identity-resolution platform rather than a library; or when you just want to scrub PII out of one document, where a regular expression is more direct and more honest.

## What arche does not do today

Stated so adopters can hold us to scope. Each of these is verifiable against the source tree.

| Gap | Today |
|---|---|
| **MCP server** | Does not exist. There is no MCP module in the wheel or the source tree; the only mentions are docstrings describing a future surface. Any description of arche MCP tools is describing something unbuilt. |
| **Clustering / transitive closure** | `crosswalk` returns pairwise edges. Collective resolution is the open remainder and is post-beta. |
| **Signable place decisions** | `pairwise(entity="place")` raises `NotImplementedError`. `crosswalk` is the place path. |
| **Email detection by default** | `Pipeline` does not detect email addresses unless you ask. The detector exists and is deliberately off, because adding it would change every existing caller's detections and redacted text; opt in with `detectors=[..., "emails"]`. The resolution path includes it already. |
| **`Pipeline(address_parsing=True)`** | Accepted and ignored — output is byte-identical with and without it. Documented known issue. |
| **Unknown jurisdiction codes** | Accepted silently. A code with no statute mapping yields no policy and unchanged text rather than an error. |
| **Detectors outside Africa** | The GDPR and HIPAA statute packs load for any EU/EEA code and for `statute="HIPAA-SAFE-HARBOR"`, but only the cross-cutting detectors run there. `Pipeline(jurisdiction="US", statute="HIPAA-SAFE-HARBOR")` finds no US identifiers, because there are none to find — running African ID regexes on German or American text would produce confident mislabels, so it deliberately does not. Compose Presidio for that coverage. |
| **Hash-chained audit log** | The `prev_hash` and `signature` columns exist; nothing populates them. Append-only by convention, not tamper-evident. |
| **Persistent storage** | SQLite for the audit log only. `StorageBackend` is named in an RFC and does not exist as a protocol. |
| **FHIR, OpenCRVS, MOSIP, DHIS2, OpenG2P adapters** | Not in scope. Early stubs were deleted because they were empty modules pretending to be features. |
| **Post-quantum signatures** | Ed25519 only. There is no `arche-core[pqc]` extra. |
| **W3C VC 1.1 JSON-LD** | SD-JWT-VC only. |
| **Organisation-side DSAR** | Citizen-side drafting only, and draft-only at that. |
| **Statute packs at v1.0** | NDPA-2023, GDPR and HIPAA Safe Harbor are labelled `v1.0`; POPIA, Kenya DPA and Ghana DPA still carry `v0.1-scaffold`. No pack is regulator-reviewed. |

Two measurement caveats belong here rather than in a footnote. The place pack's headline **88.2% is a consistency figure, not accuracy** — OpenStreetMap's Kano health facilities share lineage with GRID3, and [the place benchmark](../concepts/place-benchmark.md) shows that from the data. And the Febrl4 person figures (precision 1.0, zero false merges, 0.877 auto-match recall) are measured on a **synthetic** corpus at the pairwise level; [person resolution at scale](person_resolution_at_scale.md) has the run.

## Install

```bash
pip install arche-core                     # base — rule-based, CPU-only, no ML
pip install arche-core[detect]             # + GLiNER for multilingual soft-PII
pip install arche-core[presidio]           # + Presidio for Western PII overlap
pip install arche-core[doc]                # + docling for PDF / DOCX / PPTX / XLSX
pip install arche-core[geo]                # + shapely and duckdb for polygon work
pip install arche-core[resolve]            # + splink and duckdb (see the note below)
pip install arche-core[all]                # pdf, docx, detect, presidio, resolve, llm
```

`[resolve]` is the one extra whose name over-promises. Installing it changes the behaviour of exactly one function — `resolve_entities(..., use_splink=True)`, the v0.2 classical path — and has no effect on `pairwise`, `crosswalk` or `reconcile`.

```python
from arche import Pipeline

result = Pipeline(jurisdiction="NG").process("your text here")
```

## See also

- [A representation engine, not an inference engine](../concepts/representation-engine.md) — the full argument, with the bibliography for both halves
- [Entity resolution](entity_resolution.md) — the shipped resolution surface, end to end
- [The place benchmark](../concepts/place-benchmark.md) — what a benchmark number can and cannot tell you, and a ten-line test for dataset independence
- [Architecture](../concepts/architecture.md) — which component is permitted to conclude anything
- [Match African names](../how-to/match-african-names.md) — the name packs in practice
- [Bring your own LLM](../how-to/bring-your-own-llm.md) — models propose, curators accept, the engine executes
