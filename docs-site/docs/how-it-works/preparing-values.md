# Preparing values before comparison

Two records about one company rarely spell it the same way. Before arche compares a pair, it cleans each value, standardises the tokens that have a standard form, and splits values that hold several facts into parts it can compare one at a time. This page lists what it does at each step today, where the rules live, and what it does not do yet.

The three steps follow the usual order for data matching: clean, standardise, segment. Peter Christen's *Data Matching* (Springer, 2012), chapter 3, describes it in detail. What arche adds is that each rule is data you can read and change, and that a rule which would merge two different things is a refuter, not a rewrite.

```python
from arche.resolve import reconcile

r = reconcile([{"id": "a", "name": "Brindle Foods"}],
              [{"id": "b", "name": "BRINDLE FOODS LTD"}],
              entity="legal_entity", id_field="id")
m = r["matches"][0]
print(m["decision"], m["score"], m["evidence"])
```

```text
match 1.0 {'name': 1.0, 'name_tftoken': 1.0}
```

Case and the legal form were set aside before the names were compared, so the two names agree exactly.

## 1. Cleaning

Every text value, before any comparison:

| What | How |
|---|---|
| Case | lower-cased |
| Accents | removed (`é` to `e`), by Unicode decomposition |
| Hidden characters | zero-width spaces, direction overrides and control characters dropped, so they cannot split one name into two or change what is displayed |
| Spaces | runs of spaces, tabs and line breaks become one space; ends trimmed |
| Identifiers and phone numbers | everything but letters and digits removed (`045-768-2231` is `0457682231`) |
| Phone numbers | a country code and a leading `0` are one number for Nigeria, Ghana, Kenya, South Africa, Côte d'Ivoire and Senegal (`2348031234567` is `08031234567`) |
| Email addresses | lower-cased and trimmed |

Nothing is removed from a name at this step. Words that carry little information are handled by weighting (step 2), not by deletion, because a word that is noise in one list ("Holdings") is the only difference between two companies in another.

## 2. Standardisation, with look-up tables

Each table is a file in the package, so adding a synonym or a language is a data edit, not a code change.

| Table | What it standardises | Example |
|---|---|---|
| Legal forms (`type_tokens.yaml`, `organization`) | the legal form of a company, recognised and compared on its own | `Ltd` = `Limited`; `PLC` = `Public Limited Company`; `Ltd/Gte` = `Limited by Guarantee`; SARL |
| Facility types (`type_tokens.yaml`, `health_facility`) | the kind of facility, set apart from its proper name | `PHC` = `Primary Health Centre` |
| Spelling (`orthography.yaml`) | spellings of one word in Hausa, Yoruba and other languages | `Mai Tsidau` = `Maitsidau` |
| Name equivalence (the names lexicon) | renderings of one personal name | `Fatima` and `Fatouma`; place names are compared without it, because two facilities named after two people are two facilities |
| Word frequency (`*_frequencies.json.gz`, `organisation_tokens.yaml`) | how common each word is in a domain, so a shared rare word counts and a shared common one does not | `Farmers`, `Central` and `Holdings` are common; a curated layer corrects the counts where the source corpus is wrong |
| Country words | the country in a name | `Birds Eye UK` and `Birds Eye Ireland` are held apart |
| Designators | numbered units, halls and plants | `Hall A102` and `Hall A103` are held apart |
| Group words | words that separate companies of one group | `Pondwell Ltd` and `Pondwell Holdings Ltd` are held apart |
| Organisation name forms (`name_standards.yaml`) | the same word written two ways in a company name, before anything else reads it | `Marks & Spencer` = `Marks and Spencer`; `P.L.C.` = `PLC`; `Co` = `Company`; `Bros` = `Brothers`. Initials (`M & S`, `M&M`) and hyphenated words (`Co-operative`) are left alone |
| Address words (`address_tokens.yaml`) | words that introduce a landmark, and kinds of landmark | `behind`, `opposite`; `filling station`, `motor park` |

The last three are refuters: when they disagree, the pair is held for a person, whatever the rest of the score says.

## 3. Segmentation

A value that holds several facts is split, and each part is compared with its own comparator.

| Value | Parts |
|---|---|
| Address (`arche.addr.parse_address`) | plot, unit, street number, street, landmark, neighbourhood, area, city, region, postcode, country |
| Organisation name | the name, its legal form, its type word |
| Place name | the name and a qualifier (`Petra (Jordan)` is `Petra` with `Jordan`) |
| Postcode | outward and inward parts, so a different district and a different street are told apart |
| Time expressions (`arche.time`) | each expression and the interval it means |

## Not done yet

These are known, and each needs measuring before it changes a decision:

- **Street types** (`Rd` and `Road`, `St` and `Street`) are known to be generic words, but are not made equal.
- **Brackets and quotes** of different kinds are not unified.
- **Site words in a supplier's name** (`- Leeds`, `(London Office)`, `Plant 2`) are compared as part of the company name.
- **Personal names** are compared as words; they are not split into title, given name and family name.
