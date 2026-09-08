# Extract to your schema

A declaration says what *your* fields mean. It already drives matching: a field declared `kind: id` lands in the identifier slot and inherits the exact-match gate, a field declared `restricted` never leaves. This page is the other half: the same declaration is the schema a model is asked to extract into, so a document becomes a record in your own field names, with the evidence behind every value and the fields it could not fill named.

## Declare once

```yaml
# fisheries.decl.yaml
arche_declaration: 1
name: fisheries-landings
version: "1.2.0"
entity: catch_lot
id_field: lot_id
statute: NDPA-2023
fields:
  supplier_name: {role: identifies, kind: [name, tftoken], weight: 2.0,
                  description: Trading name of the landing supplier.}
  vessel_id:     {role: identifies, kind: id, id_family: imo, weight: 3.0,
                  description: IMO vessel number, e.g. IMO-9074729.}
  skipper_phone: {role: identifies, kind: phone, statute_class: PII-3-PHONE}
  quota_licence: {role: identifies, kind: id, id_family: ng_quota, restricted: true}
  port:          {role: describes, kind: name, pii: false}
  landing_date:  {role: describes, kind: date}
  landed_kg:     {role: ignore}
```

```python
import arche

schema = arche.schema({                       # or arche.schema("fisheries.decl.yaml")
    "entity": "catch_lot", "id_field": "lot_id",
    "fields": {
        "supplier_name": {"role": "identifies", "kind": ["name", "tftoken"], "weight": 2.0,
                          "description": "Trading name of the landing supplier."},
        "vessel_id":     {"role": "identifies", "kind": "id", "id_family": "imo", "weight": 3.0,
                          "description": "IMO vessel number, e.g. IMO-9074729."},
        "skipper_phone": {"role": "identifies", "kind": "phone"},
        "quota_licence": {"role": "identifies", "kind": "id", "id_family": "ng_quota",
                          "restricted": True},
        "port":          {"role": "describes", "kind": "name", "pii": False},
        "landing_date":  {"role": "describes", "kind": "date"},
        "landed_kg":     {"role": "ignore"},
    },
})
print(schema.labels())
```

```text
{'supplier_name': 'Trading name of the landing supplier.', 'vessel_id': 'IMO vessel number, e.g. IMO-9074729.', 'skipper_phone': 'a phone number', 'quota_licence': 'an identifier code or number', 'port': 'a personal or organisation name', 'landing_date': 'a date'}
```

`labels()` is what a zero-shot extractor is asked for: your field names, with your descriptions where you wrote one and a description from the `kind` where you did not. `arche.schema` takes a YAML path, a dict, or a `Declaration`; a dict may leave out `arche_declaration` and `name`.

## Extract

```python
text = ("Landing report. Supplier: Kijani Fisheries Cooperative. Vessel IMO 9074729 under "
        "skipper Amina Wanjiru, phone +254 722 123456, landed 1,200 kg of yellowfin at "
        "Kilifi on 3 March 2026. Quota licence KQ-2026-0417.")

lot = arche.extract(text, schema=schema, backend="basic")
print(lot.record)
print(lot.unresolved)
```

```text
{'skipper_phone': '+254 722 123456', 'landing_date': '3 March 2026'}
['supplier_name', 'vessel_id', 'quota_licence', 'port']
```

That is the base install, no model: the phone came from the validator, the date from the basic extractor, and four fields are **named as unresolved** rather than guessed. Two of them, `supplier_name` and `port`, are both `kind: name`; the lexicon found one person in the text and the basic extractor cannot say which field it belongs to, so it fills neither. Two unresolved fields beat one wrong answer written twice.

With `arche-core[detect2]` installed, `backend="auto"` asks GLiNER 2.5 for your labels. The run below was made with the model; without it the same code runs the validators and says so once.

```python
lot = arche.extract(text, schema=schema, backend="auto")
for name, evidence in lot.fields.items():
    print(f"{name:14} {evidence.value!r:32} {evidence.source:9} {evidence.detail}")
print(lot.unresolved, lot.model)
```

```text
supplier_name  'Kijani Fisheries Cooperative'   extractor proposed by the model for supplier_name
vessel_id      'IMO 9074729'                    extractor proposed by the model for vessel_id
skipper_phone  '+254 722 123456'                detector  PHONE
quota_licence  'KQ-2026-0417'                   extractor proposed by the model for quota_licence
port           'Kilifi'                         extractor proposed by the model for port
landing_date   '3 March 2026'                   extractor proposed by the model for landing_date
[] fastino/gliner2.5-base-v1
```

Six fields, and every one says where it came from. The rule that decided each: **a validator that exists outranks the model** -- `skipper_phone` is `kind: phone`, arche validates phones, so the validated span wins even though the model also proposed it; **a family arche has no validator for is the model's to propose** -- there is no IMO checksum in arche and no `ng_quota` format, so `vessel_id` and `quota_licence` are the model's answers and the evidence says so. The model was asked for `vessel_id` *with its description*, which is why it returned the IMO number and not the quota code that sits three words away; asked for a bare "identifier" it offers both.

`lot.data` is a typed instance of `schema.model()`, a pydantic model with every declared field optional; `lot.to_dict()` masks values unless `reveal=True`; `lot.pins()` records the backend, the model and `reproducible: False` the moment a model proposed anything.

## The same declaration decides

```python
other = ("Catch lot from Kijani Fisheries Co-op, vessel IMO 9074729 (skipper A. Wanjiru, "
         "+254722123456), 1.1 t yellowfin, Kilifi, 3 Mar 2026.")
lot_b = arche.extract(other, schema=schema, backend="auto")

receipt = arche.compare(lot.reference("lot-1"), lot_b.reference("lot-2"),
                        schema=schema, extra_pins=lot.pins())
print(receipt.identity, receipt.action, receipt.factors)
print(receipt.pins["declaration"], "| reproducible:", receipt.pins["extraction"]["reproducible"])
```

```text
same_entity merge {'name': 0.8, 'phone': 1.0, 'national_id': 1.0, 'dob': 1.0, 'name_tf': 0.3932}
catch_lot@0:sha256:14cb209a5c8872b4 | reproducible: False
```

`reference()` turns the record into the canonical form the verbs compare, under the declaration's roles: `vessel_id` is the identifier (`national_id` is the slot's name, not a claim about the data), `quota_licence` is restricted and never disclosed. `schema=` on `compare`, `reconcile`, `dedupe` and `find` is the same argument as `decl=`, and the declaration's pin enters the decision hash beside the extraction pins -- so the receipt records that a model proposed the fields and the decision cannot be re-derived byte for byte from the text alone, only from the record.

## Tried on four declarations

[`examples/extract_to_schema.py`](https://github.com/unpatterned-labs/arche/blob/main/examples/extract_to_schema.py) runs the three shipped declarations (`person`, `place`, `artist`) and an organisation declared inline over four short texts, on `basic` and then on `auto`. What filled, from where, as of this release with GLiNER 2.5:

| declaration, text | `basic` | `auto` |
|---|---|---|
| **person**, a KYC note | all six: id, phone, email, address from the validators; name from the lexicon; date from the basic extractor | the same six; the model's name and date replace the basic ones |
| **place**, a facility survey | `address` from the address parser (the landmark anchor, *opposite the central mosque*); `name` and `admin_path` unresolved | `name` from the model (*Karfi Primary Health Centre*); `admin_path` from the generic extractor's nearest LOCATION, which is the wrong span (*Karfi village road*, not *Kumbotso LGA, Kano State*) |
| **artist**, a royalty line | `name` from the lexicon (*Ayodeji Balogun*, the legal name); `mbid` and `isni` unresolved — arche has no validator for either | all three from the model, `name` as *WIZKID* |
| **organisation**, an onboarding email | `rc_number`, `contact_email`, `contact_phone` from the validators; `supplier_name` unresolved | `supplier_name` from the model (*Kijani Tea Exporters Ltd*); the rest unchanged |

Two of those rows are the point. The organisation's `supplier_name` on `basic` was *Amina Wanjiru* in the first draft — the finance contact, from the lexicon, at a confident 0.70 — because a `name` field fell back to any PERSON the basic extractor found. The declaration says `entity: organisation`; a supplier's name is not the person who signed the email, so a `name` field now falls back to PERSON only when the declared entity is one (`person`, `customer`, `patient`, `artist`, …) and to ORGANIZATION otherwise, which the basic extractor does not find. Unresolved is the right answer. And the place's `admin_path` on `auto` shows the same fallback failing in the other direction: the model was asked for *a place this sits inside* and offered nothing, the generic LOCATION stood in, and it is wrong. A containment field wants the administrative path, which is a place lane concern (the plan's M4), not something a nearest-entity fallback can guess.

## What can go into a declaration

Every key, with what it does at extraction and at matching. Unknown keys are errors, not warnings: a misspelt key that silently meant "unrestricted" would fail open.

**Top level**

| key | required | meaning |
|---|---|---|
| `arche_declaration` | yes, `1` | the format version; a dict passed to `arche.schema` gets it filled in |
| `name` | yes | names the declaration in pins and reports; a dict defaults it to `entity` |
| `version` | no, `"0"` | your version; part of the pin, so a changed weight changes every decision id |
| `entity` | no, `name` | what a record is *of*. Decides whether a `name` field is a person's (`person`, `customer`, `patient`, `artist`, …) or an organisation's, and names the typed record |
| `id_field` | no, `id` | the record's own key; kept as `record_id`, never treated as an attribute |
| `statute` | no | a shipped pack (`NDPA-2023`, `POPIA`, `KENYA-DPA`, `GHANA-DPA`, `UK-GDPR`, `GDPR`, `HIPAA-SAFE-HARBOR`). Resolves each field's `statute_class` to a citation and an action; sets `jurisdiction` when you did not |
| `jurisdiction` | no, `default` | the priors for matching and the detector set for extraction (`NG`, `ZA`, `KE`, `GH`, …) |
| `on_unknown` | no, `warn` | what a record field the declaration does not name does at matching: `allow`, `warn`, or `error` |
| `tf` | no | the token-frequency table for `tftoken` fields: a shipped pack's (`organisation`, `place`, `artist`, …) or your own |
| `geo` | no | `{lat: <field>, lon: <field>, weight, decay_km}` — two of your fields are coordinates, scored by distance |
| `fields` | yes | the mapping below |

**Each field**

| key | meaning |
|---|---|
| `role` | `identifies` (scored, can mint an entity id; needs a `kind`), `describes` (scored if it has a `kind`, never binds identity), or `ignore` (not extracted, not scored, not disclosed) |
| `kind` | one or a list of: `name`, `placename`, `id`, `phone`, `email`, `address`, `date`, `tftoken`, `containment`, `postcode`, `type`. At matching it picks the comparator; at extraction it picks the source order — `phone`, `email`, `address` and an `id` of a family arche validates come from the validated detection first; everything else is the model's to propose, then the generic extractor's nearest entity type as a last resort |
| `weight` | comparator weight, default `1.0` |
| `id_family` | `kind: id` only. Names the identifier family so two declarations mint the same entity id for the same number, and tells extraction whether arche has a validator for it (`nin`, `bvn`, `passport`, `national_id`, `tin`, `rc`, `drivers_licence`, …). Reserved spellings (`nin`, `phone_number`, `passport_number`) are refused in favour of the canonical family, so a value cannot alias into the wrong one |
| `statute_class` | a category of the declared `statute` (`PII-3-PHONE`, `PII-2-NIN`, …). Must exist in the pack; gives the field its citation and action |
| `restricted` | never disclosed — not in reports, not in `as_record()`, not in a masked copy — but still usable for matching. A statute `drop` action sets it and cannot be overridden downward |
| `pii` | default `true`; `false` says the field is not personal data (a port, a product code) |
| `description` | the label the model sees, verbatim. *IMO vessel number, e.g. IMO-9074729* is the difference between the right identifier and the nearest one |
| `type_domain` | required with `kind: type`: the vocabulary of type words to score against (`health_facility`, …) |

Loading warns, and does not fail, when no field `identifies` (every match will be fuzzy), when several `id` fields compete for the one pairwise identifier slot (the first is used; batch verbs use all), and when a field is named like a built-in identity attribute but not declared `identifies` (the declaration wins; say so on purpose).

## What this is not

It is not a promise that the model is right. GLiNER 2.5 is a proposer; the declared kinds decide where a validator overrules it, and the evidence on every field says which happened. Until the detection benchmark exists, no recall number is quoted for it, and `backend="basic"` remains the deterministic, air-gapped path -- with fewer fields filled and every gap named.
