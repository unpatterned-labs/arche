# Introducing arche v0.2: African PII detection that cites the law it enforces

*One PyPI package. Four DPA-grounded statutes. Lightweight by default. By Unpatterned Labs.*

!!! note "Archived — this announced v0.2.0a3, and is kept as written"

    The current release is **v0.3.0a1**, and the positioning has moved on: arche
    is now *the open engine for messy, multilingual data — detect, resolve,
    protect, attest*, with resolution as the lead capability rather than a
    future direction. African calibration remains the credential; it is no
    longer described as the scope.

    This post is left in place rather than rewritten. A blog is a record of what
    was believed when, and quietly editing an old announcement to match a newer
    story is the sort of tidying this project should not do. Read it as history.

    For where things actually stand: [The part intelligence doesn't make
    cheaper](the-part-intelligence-doesnt-make-cheaper.md) for the argument,
    [the roadmap](../concepts/roadmap.md) for the state, and
    [why arche, and when to use it](../tutorials/arche_vs_alternatives.md) for
    the comparison — which corrects a claim made below.

!!! warning "Status: pre-beta development"
    `arche-core` v0.2.0a3 was on PyPI for research, prototyping, evaluation, and contribution. APIs may change between alpha releases. Production use against real personal data is not recommended until beta.

arche started with a large ambition: an African-first identity workflow stack that could detect, resolve, link, verify, and govern records across messy documents and systems.

That is still the direction. But v0.2 narrows the first usable wedge:

> `arche-core` detects PII and local identity signals in African text, then attaches the policy evidence a reviewer needs to act on them.

That means government identifiers, names, phones, digital identifiers, addresses, document text, policy actions, statute citations, and audit records. It is not just a bundle of regexes for national IDs. It is the first layer of a larger African-context data understanding system.

## Three lines

```python
from arche import Pipeline

result = Pipeline(jurisdiction="NG").process(
    "Customer Adesola Okonkwo, NIN 12345678901, BVN 22156789012."
)

print(result.redacted_text)
# Customer NAME_..., NIN [NIN], BVN [BVN].
```

Same code, different jurisdictions:

```python
Pipeline(jurisdiction="ZA")   # POPIA
Pipeline(jurisdiction="KE")   # Kenya DPA
Pipeline(jurisdiction="GH")   # Ghana DPA
```

Each jurisdiction loads a statute YAML file. Each detection can carry a category, sensitivity tier, citation, policy action, and audit row.

## What v0.2 is really about

Most PII tools can find emails, credit cards, and common Western identifiers. That is useful, but it is not enough for African data.

African documents contain local identifiers, local names, local address forms, mixed-language text, informal landmarks, mobile-money and telecom patterns, public-record business identifiers, and jurisdiction-specific data protection obligations. A Nigerian BVN, South African ID, Ghana Card, Kenyan KRA PIN, Yoruba name variant, or Ghanaian landmark address should not be treated as an afterthought.

v0.2 makes that African-context layer explicit:

- Country detectors for Nigeria, Kenya, South Africa, and Ghana.
- Wider African ID patterns beyond the four launch countries.
- libphonenumber-backed phone normalization.
- African name equivalence data for culturally aware matching.
- Nigeria and South Africa address parser MVPs.
- Digital identifier detection for DIDs, crypto wallets, and IP addresses.
- Optional document parsing through `arche-core[doc]`.
- Optional GLiNER and Presidio composition for soft PII and broader NER.
- Optional Splink and DuckDB composition for entity resolution.

The important design choice is that detection does not stop at "we found a thing." It produces reviewable evidence: what was found, where, under which jurisdiction, with which sensitivity tier, and what policy action was applied.

## Why not just use Presidio, GLiNER, or Splink?

We are not replacing them. We are composing with them.

Presidio is strong infrastructure for recognizers and anonymization. GLiNER can widen neural NER coverage. Splink is a serious probabilistic record linkage engine. arche adds the African-context and statute-aware layer around those tools.

```bash
pip install "arche-core[presidio]"  # Presidio plus arche's African recognizers
pip install "arche-core[detect]"    # GLiNER soft PII plus statute classification
pip install "arche-core[resolve]"   # Splink at scale, fed by arche detections
pip install "arche-core[doc]"       # docling-backed document parsing
```

!!! warning "Correction — the Splink line above was wrong"

    "Splink at scale, fed by arche detections" was inaccurate when written and
    is still worth correcting rather than deleting. Splink is imported by
    exactly one function in the package — the legacy `resolve_entities()` path.
    Nothing in `pairwise`, `crosswalk`, the frequency tables or the name
    lexicon imports it, even with Splink installed.

    The honest relationship is that arche and Splink implement the *same*
    statistical framework, and Splink implements it better. arche's
    contribution is the representation that framework runs on. The
    [comparison page](../tutorials/arche_vs_alternatives.md) has the fifteen
    lines that demonstrate it.

This is the practical shape: start with `Pipeline`, then add heavier tools only when the workflow needs them.

## What is shipped in v0.2.0a3

- `Pipeline(jurisdiction=...)` for detection, policy, redaction, and audit in one call.
- Per-country detectors for NG, KE, ZA, and GH, with structural validation where available.
- 11 additional African country ID patterns.
- African phone normalization.
- Name detection and name equivalence data.
- Nigeria and South Africa address parsing MVPs.
- Statute YAML files for NDPA-2023, POPIA, Kenya DPA, and Ghana DPA.
- A SQLite-backed audit log that stores categories, spans, hashes, and policy decisions, not raw PII values.
- Optional extras for document parsing, neural soft-PII, Presidio, and entity resolution.
- Power-user workflows for signing, DSAR drafting, SD-JWT-VC envelopes, and verification.

That is enough for useful early workflows: KYC intake review, document scanning, regulator-ready redaction logs, civil-society dataset audits, journalist PII scans, and DSAR response processing.

## What comes next

v0.2 is the focused PII core. Future releases will continue improving name,
address, document, and resolution workflows as the evidence base matures.
We will document those capabilities as they become stable enough for users to
rely on.

## Get started

```bash
pip install arche-core
```

```python
from arche import Pipeline

result = Pipeline(jurisdiction="NG").process("Your text here...")
print(result.redacted_text)
```

- **Quick start**: [five-minute walkthrough](../getting-started/quickstart.md)
- **Pipeline API**: [reference](../api/resolve.md)
- **Name matching**: [how-to guide](../how-to/match-african-names.md)
- **Why arche and when to use it**: [persona guide](../tutorials/arche_vs_alternatives.md)
- **GitHub**: [github.com/unpatterned-labs/arche](https://github.com/unpatterned-labs/arche)

License: Apache-2.0 for the framework. Dataset licensing is documented separately in the repository.
