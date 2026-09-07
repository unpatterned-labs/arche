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

## What this is not

It is not a promise that the model is right. GLiNER 2.5 is a proposer; the declared kinds decide where a validator overrules it, and the evidence on every field says which happened. Until the detection benchmark exists, no recall number is quoted for it, and `backend="basic"` remains the deterministic, air-gapped path -- with fewer fields filled and every gap named.
