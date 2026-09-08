# Detection benchmark data — sources & attribution

The set arche's detection numbers are measured on, and why it is the shape it is.

## `african_context_v0.jsonl` — constructed, CC-BY-4.0

240 short texts (60 per jurisdiction: NG, KE, ZA, GH) over eight templates — a KYC note, a clinic referral, an HR onboarding, a bank complaint, a school register, a delivery note, a chat message, an invoice — carrying **908 personal-data spans** and **540 negatives**. Built by `build_african_context_v0.py` from a seeded generator; the file is reproducible byte for byte.

Every span is computed by construction, never searched for. Every identifier passes arche's own validator at build time (a South African ID with its Luhn digit, a Ghana Card with its check digit, a Luhn-valid card number), so a miss is the detector's, not the data's. Names come from two pools, and each name span records which: **`lexicon`**, names the shipped 13,342-name lexicon holds, and **`heldout`**, names it does not, checked with `is_known_african_name` at build time. That split is what lets the results say how much of the name recall is the lexicon and how much is a model.

The negatives are the point of the file. An order number (`INV-97880932`), a bare ten-digit reference, an ISBN, an amount, a time, a plain date: shapes that look like identifiers and are not. A detector that reads `PO 82141621` as a phone number has somewhere to be caught, and the result file says which negative each false positive landed on.

**What this set is not.** It is not text from the wild. Its recall says the detectors read what they were built to read, on the formats the templates use. It does not say what they do on a clinic's actual referral notes, a bank's actual complaints, or a WhatsApp export — the set that still has to be made by hand, adjudicated, and kept with negatives. Every number published from this file is labelled *constructed*. Licence: CC-BY-4.0, unpatterned.org.

## Sets considered and not used

- **ai4privacy `pii-masking-300k`** (Hugging Face). 225k rows in six European languages with span labels — the obvious public set, and the one GLiNER2-PII's own card reports against. Its licence grants academic, non-commercial use only and forbids redistribution and derivative works without a written licence from AI4Privacy. arche is developed by a company; the provenance rule (every benchmark row must come from an open class) treats this the way it treats OpenSanctions Pairs: a licence to acquire on purpose, not a default. Nothing from it is in this repository, and no number measured on it is published. `benchmark_pii.py --format ai4privacy` reads a local copy for a private measurement and refuses to write to the committed result file; a licence request has been recommended so the numbers can be published properly.
- **i2b2 / n2c2 2014 de-identification.** The standard clinical set; needs a data-use agreement. Worth applying for — OpenMed reports on it — and out of reach until then.
- **CoNLL-2003 and the general NER sets.** Names only, no identifiers, no statute categories; not what a redaction is measured on.

## Reproducing

```bash
python data/pii_bench/build_african_context_v0.py
python data/scripts/benchmark_pii.py --backend basic,gliner2-pii
```

The second writes `benchmark_pii_result.json`, which the benchmarks page quotes. `gliner2-pii` needs `arche-core[detect2]` and downloads the model on first use.
