# Jurisdictions and statutes

At the end of this page you know how a two-letter country code becomes a statute, why the statute and not the caller decides what happens to each span, how arche works out the country from the text and when it refuses to, and how to read a clean result honestly: as "nothing was found" or as "nothing was looked for".

```python
from arche.policy import statute_for

for code in ("NG", "US"):
    choice = statute_for(code)
    print(code, "|", choice.statute_id, choice.available, "|", choice.reason[:60], "|", choice.alternatives)
```

```text
NG | NDPA-2023 True |  | ()
US | None False | the United States has no omnibus federal privacy statute, so | ('HIPAA-SAFE-HARBOR', 'BASELINE')
```

Nigeria has a pack, so `available` is `True` and the statute is NDPA-2023. The United States has none, and the reason is a fact about US law rather than a gap in arche: there is no omnibus federal privacy statute to write a pack for. `alternatives` names what a caller can pass explicitly instead, most specific first. `statute_for` exists so that an agent can find this out before it hands over a document, instead of meeting a refusal afterwards that reads like a bug.

## How a country becomes a statute

A jurisdiction is an ISO 3166-1 alpha-2 code. A statute is a YAML file under `arche/policy/statutes/`, versioned and editable without a code change. `STATUTE_FOR_JURISDICTION` in `arche.policy` maps the first to the second, and that table is the whole of the routing.

```python
from arche.policy import list_available_statutes

print(list_available_statutes())
for code in ("GB", "FR", "EU", "IN", "BR", None):
    choice = statute_for(code)
    print(str(code).ljust(4), "|", choice.statute_id, "|", choice.reason)
```

```text
['BASELINE', 'GDPR', 'GHANA-DPA', 'HIPAA-SAFE-HARBOR', 'KENYA-DPA', 'NDPA-2023', 'POPIA', 'UK-GDPR']
GB   | UK-GDPR |
FR   | GDPR |
EU   | GDPR |
IN   | None | India's DPDP Act 2023 is in force but its rules were still being finalised when this shipped, and a pack citing sections that may move would be worse than none
BR   | None | no LGPD pack ships yet
None | None | no jurisdiction given, so no statute can be chosen
```

Eight statute files ship. Six are reached from a country code:

| Statute | Governs | Authority | Pack version |
|---|---|---|---|
| `NDPA-2023` | `NG` | Nigeria Data Protection Commission | v1.0 |
| `POPIA` | `ZA` | Information Regulator (South Africa) | v0.1-scaffold |
| `KENYA-DPA` | `KE` | Office of the Data Protection Commissioner | v0.1-scaffold |
| `GHANA-DPA` | `GH` | Data Protection Commission | v0.1-scaffold |
| `GDPR` | the EU-27 and the EEA (`IS`, `LI`, `NO`), and `EU` itself | EDPB and national supervisory authorities | v1.0 |
| `UK-GDPR` | `GB` | Information Commissioner's Office | v0.1 |

The other two are reachable only by naming them with `statute=`. `HIPAA-SAFE-HARBOR` is the sectoral US rule for health data, and `statute_for("US")` offers it. `BASELINE` is arche's own floor: it applies category actions with no statutory citation and says in every citation that it is not the law of any country. The section on the floor below is where it is applied without being asked for.

The UK is its own row, not a GDPR alias, because the retained UK GDPR plus the DPA 2018 is a different instrument with a different regulator, and citing the EU one would cite the wrong law. `EU` is a row of its own because inference emits it from a VAT number or a euro amount, which identifies the regime without identifying the member state, and GDPR is the Union-wide answer rather than a fallback.

Every pack carries a `review_status`. All eight are `self-reviewed`: arche's own mapping of categories to sections, with no regulator having reviewed it. A pack may not claim `regulator-reviewed` without naming who and when, and the loader refuses one that tries.

## The six actions, and who picks them

An action is what happens to a span. The set is closed and small so that each one is unambiguous and testable, and the statute maps each PII category to one of them.

```python
from arche.policy import ACTIONS, load_statute

print(sorted(ACTIONS))
ndpa = load_statute("NDPA-2023")
print(ndpa.statute_id, ndpa.version, ndpa.jurisdiction, "|", ndpa.authority, "|", ndpa.review_status)
for category in ("PII-1-NAME", "PII-2-NIN", "PII-2-RC", "PII-4-ADDRESS", "PII-9-UNMAPPED"):
    action, reference, rationale = ndpa.action_for(category)
    print(category.ljust(15), action.ljust(10), reference)
```

```text
['audit', 'drop', 'generalize', 'mask', 'retain', 'tokenize']
NDPA-2023 v1.0 NG | Nigeria Data Protection Commission (NDPC) | self-reviewed
PII-1-NAME      tokenize   NDPA-2023 s.30
PII-2-NIN       mask       NDPA-2023 s.30, NIMC Act s.27
PII-2-RC        retain     NDPA-2023 s.31 (legitimate interests)
PII-4-ADDRESS   generalize NDPA-2023 s.30
PII-9-UNMAPPED  mask       NDPA-2023 s.30
```

| Action | What it does to the span |
|---|---|
| `mask` | replace with a category label: `[NIN]`, `[NAME]` |
| `tokenize` | replace with a keyed digest that is the same for the same value under the same salt: `PHONE_d3100c11` |
| `drop` | remove it |
| `generalize` | replace with something less specific: a date becomes its year, an IPv4 address its /24 |
| `audit` | leave it in place and record an audit event |
| `retain` | leave it in place, no event |

Read the NDPA rows as a data protection act, not as a redaction preset. A name is tokenised because the act permits a pseudonymous form that keeps records linkable. A NIN is masked because the NIMC Act restricts its disclosure. A company registration number is retained because CAC publishes them, and hiding a public fact would be theatre. An address is generalised. A category the pack does not map falls to the pack's `default_action`, which is `mask` for every shipped pack, cited to the pack's default section.

Each action comes with a citation, and the citation is per category: `NDPA-2023 s.30, NIMC Act s.27` on the NIN, `s.31 (legitimate interests)` on the registration number. That citation travels with the detection into `detect_pii`, into the `Deidentified` receipt, and into the ledger. It is the reason the span counts, and it is what a reviewer checks.

The caller does not pick the action. `deidentify(method="mask" | "token" | "drop")` changes the rendering for every governed span, and the citations stay the statute's, because the statute still decided what was personal data; only how it is drawn changed. When two detections overlap, a name inside an address for instance, the whole region is replaced once using the most restrictive action any member asked for, ordered `drop`, `mask`, `tokenize`, `generalize`, `audit`, `retain`. Letting the outer span win would emit a generalised address still holding a NIN the pack said to mask; letting the inner win would leave the rest of the address in clear.

## Inference: the text says where it is from

`Pipeline(jurisdiction=...)` used to make the caller type a country code, and typing the wrong one is not a subtle mistake. The Nigerian detector set run over a British bank statement reported 36 tax identification numbers, every one a ride reference or a transaction id, because a Nigerian TIN is ten digits and so are they. `infer_jurisdiction` reads the document's own evidence and proposes a country. It decides nothing: an explicit `jurisdiction=` always wins, and the proposal is recorded beside the result so a reviewer can see both.

```python
from arche.jurisdictions.infer import infer_jurisdiction

note = "Patient Casey Example (NIN 12345678901) called from 08035557890 about a bill of NGN 45,000."
ng = infer_jurisdiction(note)
print(ng.country, round(ng.confidence, 2), round(ng.margin, 2), ng.abstained, "|", ng.reason)
for e in ng.evidence:
    print(" ", e.signal, e.tier, e.country, e.count, e.weight)

gb = infer_jurisdiction("Invoice from Monzo Bank Limited, 5 Appold Street, London EC2A 2AG.")
print(gb.country, round(gb.confidence, 2), "|", gb.reason)
```

```text
NG 1.0 1.0 False | strongest signal id.nin, 100% of total evidence weight
  id.nin A NG 1 1.0
  currency.ngn B NG 1 0.35
  phone.ng B NG 1 0.35
GB 1.0 | strongest signal postcode.uk, 100% of total evidence weight
```

Signals come in three tiers, and the tiers are the rule. Tier A is near-unique: a registration identifier, a regulator's name, a UK postcode, `NIN` or `BVN`, `Registered in England and Wales`. One of these names a country almost by itself and weighs `1.0`. Tier B is moderate: a currency, a company-form suffix, a phone shape, each worth `0.35`. Several agreeing is meaningful; one alone is not. Tier C is corroborating only: a date format, a PDF timestamp's UTC offset, worth `0.10`. A Tier C signal can never move a country from abstain to chosen. It breaks ties between candidates that already hold stronger evidence, and nothing more, because a UK user printing a US invoice produces a UK timestamp and that must not decide which law a reviewer sees. One signal type contributes at most three occurrences, so a statement with 166 dd/mm dates does not swamp everything else in it.

A country is named when its evidence is earned (a Tier A signal, or two independent non-corroborating signals), holds at least 60% of the total weight, and leads the runner-up by at least 15%. Otherwise the inference abstains, and abstaining is a result rather than a failure.

```python
thin = infer_jurisdiction("Total due: $120.00, payable on 03/14/26.")
print(thin.country, thin.abstained, "|", thin.reason)

split = infer_jurisdiction("Registered in England and Wales. Employee Social Security Number on file.")
print(split.country, split.abstained, round(split.confidence, 2), split.runner_up)
```

```text
None True | US leads but only on weak or corroborating evidence; a registration identifier or two independent signals are needed to name a country
None True 0.5 US
```

The first text has a dollar sign and a US-shaped date: one Tier B signal and one Tier C, which is not earned. The second has a British registrar and an American identifier at equal weight, so the leader holds 50% of the evidence and the 60% floor is not met. Both are the right answer. A detector that always answers is not confident, it is unfalsifiable.

Inference cannot establish that a country's law applies to your processing. That turns on establishment, on where your data subjects are, on sector and on transfers. A jurisdiction code selects a policy template; nothing here performs a legal applicability analysis. `RULESET_VERSION` enters the pins, so a decision made under a different signal set is distinguishable from one made now.

## The refusal

`detect_pii` and `deidentify` with no `jurisdiction` run the inference. When it names a country, the call proceeds under that country's statute and the receipt says the jurisdiction was `inferred` and with what confidence. When it abstains, the call raises rather than guessing.

```python
import arche
from arche.protect import JurisdictionRequiredError

safe = arche.deidentify("Invoice from Monzo Bank Limited, 5 Appold Street, London EC2A 2AG. Contact jane.smith@monzo.com.", backend="basic")
print(safe.statute, safe.pins["jurisdiction_source"], safe.pins["jurisdiction_confidence"])
try:
    arche.deidentify("Total due: $120.00, payable on 03/14/26.", backend="basic")
except JurisdictionRequiredError as exc:
    print(type(exc).__name__, "|", str(exc)[:70])
```

```text
UK-GDPR inferred 1.0
JurisdictionRequiredError | the text does not say which jurisdiction governs it, and arche will no
```

A redaction under the wrong statute looks finished and is not, which is why the guess is refused. The message names every jurisdiction that has a pack, so the fix is in the error. `JurisdictionRequiredError` is a `ValueError`, so an existing `except ValueError` catches it. Passing `statute=` explicitly skips inference too, which is how `HIPAA-SAFE-HARBOR` is reached.

## The ceiling: a call cannot widen what the operator set

Over MCP, configuration is a ceiling rather than a default. `ARCHE_JURISDICTION` and `ARCHE_STATUTE` set the strictest policy the server operates under; a per-call `jurisdiction` argument is used only when no ceiling is set, and it can never replace one.

```sh
ARCHE_JURISDICTION=NG arche mcp
```

The reason is who would otherwise choose the governing law. Moving jurisdiction from a setting to an argument hands the choice to the agent, and an agent that can pick its own statute can pick a weaker one. An operator who pinned the server to Nigeria did so to stop anything else happening, and letting a tool call argue it away would make the setting advisory. With no ceiling set, the caller chooses, and the intended flow is `infer_jurisdiction`, then `plan_protection`, then `guarded_scan`: the arrangement for a mixed document stream. Pin the ceiling when a deployment handles one jurisdiction and an agent has no business choosing. `arche serve` takes `jurisdiction` per request and has no ceiling; put the choice in the proxy in front of it if it should not be the client's. [The MCP server](../guides/mcp-server.md) has the tool list.

## The floor: a country with no pack

A `Pipeline` given a jurisdiction no pack covers has no statute, and a pipeline with no statute returns the text unchanged. Measured on a British bank statement: `jurisdiction="NG"` produced 36 false TIN detections but did mask the email; `jurisdiction="GB"`, before the UK pack existed, produced none and masked nothing. Correcting the jurisdiction took false positives from 36 to 0 by switching protection off. So `detect_pii` and `deidentify` construct their pipeline with `on_uncovered="baseline"`: a jurisdiction with no pack gets `BASELINE`, which is a conservative floor and says so.

```python
import warnings

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    us = arche.deidentify("Jane Smith, SSN 123-45-6789, jane@example.com", jurisdiction="US", backend="basic")
print(us.statute, "|", us.text)
print(us.detections[0].regulatory_citation)
```

```text
BASELINE | NAME_12e5b93d NAME_87d56402, SSN 123-45-6789, EMAIL_ac4d2000
no statute pack for this jurisdiction: arche baseline floor, not law
```

Two things to notice. The citation on every span says the floor is not law, so a report made under it cannot be mistaken for compliance with anything. And the social security number is still in the text. No shipped detector finds an SSN, so no action was taken on it, and the next section is how you find that out before you rely on a clean result. The pipeline warns once when the floor is applied; the fence silences that warning only to keep the output short.

`Pipeline` itself keeps `on_uncovered="silent"` as its default so that no existing caller's output changes; `"warn"` names the uncovered jurisdiction, `"baseline"` applies the floor.

## Coverage: "nothing found" against "nothing looked for"

A statute pack and a detector set are chosen independently, and until `arche.coverage` existed nothing compared them. A pipeline for `GB` with every fail-closed check satisfied returned a British note about Jane Smith in Manchester untouched, with zero findings, because the detectors that ran were built for somewhere else and the ones that would have found the identifiers did not run at all. Zero findings meant either "nothing here" or "nothing here that anything installed can see", and no caller could tell which.

```python
from arche.coverage import coverage
from arche.workflow import Pipeline

ng = coverage(Pipeline(jurisdiction="NG", backend="basic"))
print(ng["verdict"], len(ng["governed"]), "governed,", len(ng["covered"]), "covered,", len(ng["uncovered"]), "uncovered")
print(ng["note"])

gb = coverage(Pipeline(jurisdiction="GB", backend="basic"))
print(gb["verdict"], gb["detector_packages"])
print(gb["uncovered"])
print(gb["degraded_categories"])
```

```text
partial 27 governed, 14 covered, 13 uncovered
13 categories NDPA-2023 governs have no detector installed: PII-5-BANK_ACCOUNT, PII-5-CARD, PII-5-MPESA_REF, PII-6-BIOMETRIC and 9 more. A clean result does not mean those are absent, only that nothing looked for them.
partial ['names', 'locations', 'emails', 'ip', 'digital_id', 'addr', 'core']
['PII-2-DRIVERS_LICENCE', 'PII-2-NIN', 'PII-2-RC', 'PII-2-TIN', 'PII-5-BANK_ACCOUNT', 'PII-5-CARD']
['PII-1-NAME', 'PII-3-PHONE', 'PII-4-LOCATION']
```

`coverage` compares two exactly known sets: the categories the statute maps and the categories the detectors that will actually run can emit. `verdict` is `full` when every governed category has a detector, `none` when not one does, `partial` in between, and `no-statute` when nothing is governed at all. Expect `partial`, including for Nigeria: NDPA-2023 governs health, religion, biometric and device categories arche ships no detector for, and saying so is the point. `none` is the one to stop on.

`uncovered` is the list to worry about: the statute names them, nothing installed can find them. `degraded_categories` is one level down. A name detector calibrated on West African names runs for `GB` and reports `PII-1-NAME` as covered, and it will still miss most British names. That was measured rather than assumed: the phone detector finds `+234` and misses `+44` and `+49`; the location detector finds `Kano State` and misses `Manchester` and `Munich`. A degraded category stays in `covered`, because a detector did run, and is named separately rather than moved to `uncovered`, which would claim more than is known.

Coverage is about capability, not recall. `covered` means a detector for that category ran, not that it found everything. It is a floor on honesty, not a guarantee of completeness. The per-country category lists are read out of the detector packages' own pattern tables rather than written by hand, so adding an identifier cannot silently leave the report claiming coverage that does not exist.

The same report rides on every `Deidentified` as `.coverage`, on the `detect_pii` and `guarded_scan` MCP tools, and on `plan_protection`, which is the MCP tool for asking before a document is handed over.

## Where to read next

| You want to | Read |
|---|---|
| the two verbs this page sits under, and a masked copy you can compare | [Find and mask](../guides/find-and-mask.md) |
| the fields on a receipt and what each means | [The decision](the-decision.md) |
| the same verbs from an agent, and the ceiling in practice | [The MCP server](../guides/mcp-server.md) |
| a signed answer someone who does not trust you can verify | [Attested answers](attestation.md) |
| the whole Python surface | [Python API](../reference/python-api.md) |
