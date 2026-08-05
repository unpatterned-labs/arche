# Declare your schema — your fields, arche's guarantees

Splink wants structured, same-schema tables. Senzing wants its attribute dictionary. arche wants **your** schema — you just tell it what your fields *mean*. One YAML file assigns each of your fields a role, and from that single declaration arche derives comparators, masking policy, identity binding, an LLM extraction schema, and a pin that hashes into every signed decision.

No declaration? Everything works exactly as before, using arche's built-in naming conventions. The declaration is additive.

## The declaration

Save as `fisheries.decl.yaml` (this exact file ships in [`examples/declarations/`](https://github.com/unpatterned-labs/arche/tree/main/examples/declarations)):

```yaml
arche_declaration: 1
name: fisheries-landings
version: "1.2.0"
entity: catch_lot
id_field: lot_id
statute: NDPA-2023
geo: {lat: landing_lat, lon: landing_lon, weight: 1.0}
fields:
  supplier_name:  {role: identifies, kind: [name, tftoken], weight: 2.0}
  vessel_id:      {role: identifies, kind: id, id_family: imo, weight: 3.0}
  skipper_phone:  {role: identifies, kind: phone, statute_class: PII-3-PHONE, weight: 1.5}
  quota_licence:  {role: identifies, kind: id, id_family: ng_quota, restricted: true, weight: 2.0}
  port:           {role: describes, kind: name, pii: false}
  landing_date:   {role: describes, kind: date}
  landed_kg:      {role: ignore}
  observer_notes: {role: ignore}
```

The vocabulary is small and closed. **`role`** is Talburt's axis: `identifies` (this field can tell one entity from another), `describes` (carried, compared if it has a kind, never identifying), `ignore` (never enters arche at all — the clean escape hatch for free-text columns). **`kind`** picks the comparator. **`id_family`** links identifiers across systems (two declarations that both say `imo` mint the same entity id for the same vessel). **`restricted: true`** means usable as match evidence, *never* disclosable — even under `--reveal`. **`pii: false`** is the only route to clear-text rendering. **`statute_class`** attaches the governing law: the citation rides every attribute built from that field, and a statute `drop` action forces restriction no matter what the declaration says.

Validation is deliberately unforgiving: unknown keys, typo'd roles, reserved id families, and unknown statute classes are **errors**, each naming the offender. A typo in a file that governs disclosure must never silently mean "unrestricted."

```bash
arche schema validate fisheries.decl.yaml
# valid: fisheries-landings@1.2.0:sha256:28f13195e89a25e3
```

That string is the **pin** — a hash of the normalized declaration. Reformatting the YAML doesn't change it; changing a weight does. It enters every signed decision, so the same records under a different declaration produce a different `decision_id`.

## Use it everywhere

**Link two files** (masked-by-default report; the pin appears in the provenance footer):

```bash
arche compare landings_a.csv landings_b.csv --schema fisheries.decl.yaml --out report.html
```

**In Python** — the same declaration drives references, bulk linking, and signable pairwise decisions:

```python
from arche import resolve
from arche.canonical import Reference
from arche.declare import Declaration

decl = Declaration.from_yaml("fisheries.decl.yaml")

out = resolve.crosswalk(list_a, list_b, decl=decl)          # your fields, compared

ra = Reference.from_record(rec_a, decl=decl)                # vessel_id is now an
rb = Reference.from_record(rec_b, decl=decl)                # identity attribute
decision = resolve.pairwise(ra, rb, issuer_key=KEY, decl=decl)
# decision.pins["declaration"] == decl.pin()
```

Because `vessel_id` is declared `kind: id`, a shared vessel number clears the distinctive-evidence gate exactly the way a national ID does for a person — and a *conflicting* vessel number vetoes the merge. Your field names survive untouched on every output.

**Generate the LLM extraction schema** — this is the "bring your own model" contract:

```bash
arche schema gen fisheries.decl.yaml --format anthropic   # or openai | json-schema
```

The generated schema sets `additionalProperties: false` (a model cannot emit fields outside your declaration) and `required: []` on purpose: a *required* identifier is an instruction to a language model to invent one, and missing fields already route to review. Validate whatever comes back:

```python
ref, violations = decl.validate_record(llm_output)   # names any undeclared field
```

## The honest caveats

- **Schema freedom is not automatic calibration.** arche's scoring priors were fitted on person data; a fisheries decision is structurally sound (the gate, the veto, and corroboration all apply) but its score is not calibrated for your domain. The report's provenance block says which declaration produced every score. Declared schemas are also the signal for which calibration packs arche grows next.
- **Two `kind: id` fields**: the signable pairwise path uses the first (declaration order); bulk `crosswalk` uses all of them. The loader warns.
- The three built-in entity packs are just declarations arche wrote for you — [`person.decl.yaml`, `place.decl.yaml`, `artist.decl.yaml`](https://github.com/unpatterned-labs/arche/tree/main/examples/declarations) round-trip to `ENTITY_PACKS` exactly.

**Siblings:** [the design record](https://github.com/unpatterned-labs/arche/blob/main/docs/ARCHE_DECLARATION_LAYER_DESIGN.md) · [read crosswalk output](read-crosswalk-output.md) · [the data packs](../data-packs.md) · [the representation engine](../concepts/representation-engine.md) (why the declaration is data, not code).
