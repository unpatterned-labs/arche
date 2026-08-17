# arche-core

**Know what's real.**

An open engine for messy data from sources that never agreed on anything. It finds the entities, works out which records are about the same real-world thing, and gives you a decision you can defend six months later: the evidence, the rule that produced it, and a signature someone who does not trust you can re-check.

```bash
pip install arche-core
```

## The problem

Your records came from different systems, written by different people, at different times. A supplier list, a registry export, six PDFs, a partner's spreadsheet. The same hospital, cooperative, product or person appears in all of them under different names, with no shared identifier anywhere.

Nothing in those files says which rows are about the same thing. That fact lives in the world, not in the data, so somebody has to **decide** it, and a decision that cannot be explained later is not much use in a system that pays people, ships medicine, or files a regulatory statement.

Most tools give you a similarity score. arche gives you a decision, the evidence behind it, and permission to say *I don't know*.

| | |
|---|---|
| **detect** | Find the entities and identifying data in text, documents and records. |
| **resolve** | Decide which real-world thing each reference points at, and abstain when the evidence does not support a verdict. |
| **protect** | Apply the statute that governs the data, citing the section it came from. |
| **attest** | Sign the decision together with the evidence and the exact representation that produced it. |

## What it resolves

One engine, five calibrated packs. A pack is configuration and data, never a fork.

| Pack | For | The hard case it handles |
|---|---|---|
| `person` | people | *Diallo* and *Jallow* are one name; two *Ibrahim Musa* are two men |
| `place` | facilities, addresses, settlements | identical names 282 km apart are two hospitals |
| `organisation` | companies, cooperatives, unions | a site and the company operating it share a name **and** a coordinate |
| `product_electronics` | catalogue items | a rare model code identifies; `Black T-Shirt` does not |
| `artist` | creative works and performers | one act, many stage names and transliterations |

```python
from arche.resolve import crosswalk

result = crosswalk(supplier_list, certifier_registry,
                   entity="organisation", id_field="id")

for edge in result["matches"]:
    print(edge["decision"], edge["score"], edge["evidence"])
```

Three answers, not two: `same_entity`, `review`, `different`. The middle one is the point. It is Fellegi and Sunter's third region from 1969, which most production systems discard because a review queue costs money, and discarding it is where systems start asserting things they have not earned.

## From documents to decisions

Unstructured input is a first-class entry point, not a preprocessing step you bolt on.

```python
from arche import resolve_documents

report = resolve_documents("statements/*.pdf")
print(report.table())
```

That parses each file, detects the identifying data with the governing statute attached, builds a record per document, and resolves them against each other. Every decision carries the extraction that produced it: the hash of the input bytes, the parser and its version, the digest of the rendering its spans point into. Upgrade the parser next year, re-run, and you can tell whether the answer changed or only the machinery did.

## Decisions you can hand to someone who does not trust you

Every decision has a reproducible `decision_id`, hashed over the rounded evidence and the pinned versions. No timestamp, no raw float. Same inputs, same id, byte for byte.

```python
from arche.resolve.reconcile import sign_edges
from arche.sign import generate_keypair

signed = sign_edges(result, private_key=key.private_key, kid=key.did_key)
```

A recipient checks two independent things: the signature, which establishes who issued it and that nothing changed since, and the recomputed id, which establishes that the id is the honest address of *this* evidence rather than one lifted from a more favourable decision. They fail differently, which is what makes the pair useful. See [re-verify a decision](https://unpatterned-labs.github.io/arche/how-to/re-verify-a-decision/).

## What is measured

Published whichever way it falls, with the caveats attached rather than in a footnote.

| What | Baseline | arche | Read it as |
|---|---|---|---|
| **Leipzig DBLP–ACM** | out of the box, precision 0.8500, 391 false merges | precision **0.9506**, recall 0.9960 | Complete ground truth, so false merges are counted rather than estimated. The gain is not default: it needs one declared discriminator on `year` |
| **Leipzig Abt-Buy** (products) | name only, F1 0.3443 | F1 **0.7883**, precision 0.9707 | 62 false merges down to 22 |
| **Organisation lane** | token-sort F1 0.8898 | F1 **0.9493** | False merges 21 → 4. Anglophone restaurant listings, so it says nothing about African organisation names |
| **Name frequency** *(ablation)* | the same engine with the frequency signal off: precision 0.162, 7,705 false merges | precision **0.946**, 41 false merges | 1,114 real same-surname pairs from a public voter register. Recall is the cost: **48%** on same-person pairs differing by a dropped middle name |
| **Multilingual detection** | Presidio 37/48 | **47/48** | **Not re-runnable.** The 48-case set is not in this repo and nothing here computes the number. Unverified until rebuilt |

The honest ledger, in full, is in [the whole picture](https://unpatterned-labs.github.io/arche/concepts/the-whole-picture/), including the benchmarks that are too small, the abstention policy that is not yet precommitted, and the head-to-head against frontier models that has not been run.

## Why the calibration comes from where it does

The engine is general. The organisation frequency table is built from company registrations across 65 jurisdictions, the product work is benchmarked on US retail catalogues, and the place work runs on UK hospitals and Nigerian clinics alike.

What is unusual is where the defaults were tested first. Jaro-Winkler, the string comparator underneath most record linkage, pays a bonus for a shared prefix, because it was tuned on US Census surnames where clerical typos land at the end of a word. *Diallo* and *Jallow* are one Fula family name split by a colonial spelling border, and they share no prefix at all. That assumption fails identically on Arabic transliteration, on Cantonese romanisation, and on any register where one name has three spellings.

So: **general-purpose entity resolution that ships its representation data, built by people who met the defaults first where the defaults break hardest.** Six statute packs ship, covering NDPA (Nigeria), POPIA (South Africa), Kenya DPA, Ghana DPA, GDPR and HIPAA Safe Harbor, alongside a baseline floor that applies where no pack exists.

## Install

```bash
pip install arche-core                   # ~3 MB, CPU only, no ML dependencies
pip install "arche-core[doc]"            # PDF, DOCX, PPTX, XLSX, HTML
pip install "arche-core[detect]"         # GLiNER2-PII soft-PII detection
pip install "arche-core[presidio]"       # Microsoft Presidio integration
pip install "arche-core[resolve]"        # Splink + DuckDB at scale
```

Runs offline by default. Nothing leaves the machine unless you configure a backend that does, and an `EgressGuard` has to be cleared before it can.

> [!WARNING]
> `arche-core` is pre-beta. Suitable for research, prototyping, evaluation, benchmarking and contribution. APIs may change between alpha releases. Do not use it against real personal data until you have completed your own legal, privacy and security review.

## If your problem is inference, use Splink

We mean this literally. Entity resolution has two halves. The mathematics of combining evidence is solved, has a founding paper from 1969, and has excellent free software in [Splink](https://moj-analytical-services.github.io/splink/). arche is about the other half: what the records look like when they are compared, what counts as agreement, and what agreement is worth. Every gain claimed here is a gain in representation, and none of it is a better estimator.

## Source and issues

[github.com/unpatterned-labs/arche](https://github.com/unpatterned-labs/arche)

## Documentation

| | |
|---|---|
| [The whole picture](https://unpatterned-labs.github.io/arche/concepts/the-whole-picture/) | what is built, what is measured, what is not proven |
| [Sameness and similarity](https://unpatterned-labs.github.io/arche/concepts/sameness-and-similarity/) | why a matcher cannot observe identity, and whether frontier models change that |
| [arche in practice](https://unpatterned-labs.github.io/arche/concepts/arche-in-practice/) | what changes about your working day |
| [What matching looks like](https://unpatterned-labs.github.io/arche/concepts/what-matching-looks-like/) | the failure modes side by side, with real verdicts |
| [Entities](https://unpatterned-labs.github.io/arche/concepts/entities/) | which attributes identify a person, place, product or organisation |
| [Runnable notebooks](https://github.com/unpatterned-labs/arche/tree/main/examples/notebooks) | ten, from first call to supplier reconciliation |

## Contributing

The representation data is open on purpose. A pack that everyone corrects is a better pack, and the corrections are the point. If you know an equivalence, a vocabulary or a frequency we do not, that is the highest-value contribution there is. See [CONTRIBUTING.md](https://github.com/unpatterned-labs/arche/blob/main/CONTRIBUTING.md).

## License

Apache-2.0. The datasets carry their own licences, recorded beside them.
