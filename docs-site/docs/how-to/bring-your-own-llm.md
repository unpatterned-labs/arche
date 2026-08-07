# Bring your own LLM — arche grades it

You want the best model doing your extraction. arche's position is not "don't"
— it's **models propose, the engine decides, and the signature tells the truth
about which was which**.

This page is that division of labour as working code. Every snippet below was
executed against `arche-core` 0.3.0a1 and the output is what it actually
printed. Nothing here needs an API key: the model is any callable, which is
the point.

## What plugging in a model gets you

| The model does | arche does |
|---|---|
| Reads messy text into *your* declared fields | Generates the prompt and the JSON Schema from your declaration |
| Proposes values | Rejects fields you never declared, as violations rather than values |
| Proposes judgments (`same` / `different` / `unsure`) | Decides deterministically, and grades the model against that decision |
| — | Signs the result, recording that an unreproducible model was involved |

## 1. Your declaration is the model's contract

Start from a [declaration](declare-your-schema.md). It generates the prompt,
the JSON Schema, and the validation — you do not write a prompt by hand.

```python
from arche.declare import Declaration
from arche.llm.declarative import extract_declared

decl = Declaration.from_yaml("examples/declarations/fisheries.decl.yaml")
```

The generated system prompt names only the fields you declared, and only the
ones that carry meaning. Fields marked `role: ignore` are excluded — the model
is never asked for them:

```text
You extract one catch_lot record from text.
Fields (emit ONLY these; omit any you cannot find — never invent):
- supplier_name: Trading name of the landing supplier.
- vessel_id: IMO vessel number, e.g. IMO-9074729.
- skipper_phone: (identifies)
- quota_licence: (identifies)
- port: (describes)
- landing_date: (describes)

Respond with a single JSON object matching this schema exactly:
{
  "type": "object",
  "additionalProperties": false,
  "required": [],
  ...
```

Two details in that schema are deliberate. `additionalProperties: false` says
your fields are the whole world. `required: []` is there because **a model told
a field is required will invent one** — arche would rather have a gap than a
fabrication.

## 2. Extract

`complete_fn` is any callable taking a list of messages and returning a string.
That is the entire integration surface — bring an SDK client, an HTTP call, a
local model, or a stub.

```python
ex = extract_declared(
    "Landing sheet: Acme Fisheries, vessel IMO-9074729, Lagos",
    decl,
    complete_fn=my_model,            # callable(messages) -> str
    model="my-model@2026-08",        # recorded in the provenance pin
)

print(ex.reference)
print(ex.violations)
```

```text
Reference(id='', attributes=3, identity_attrs=2, source='')
[]
```

Three attributes were extracted, two of them identifying. `ex.record` holds the
raw dict; `ex.reference` is the canonical form that feeds resolution.

### A hallucinated field is a violation, not a value

Give the same call a model that invents `captain_ssn`:

```python
print(ex2.violations)
# ["undeclared field 'captain_ssn'"]

print("captain_ssn" in str(ex2.reference))
# False
```

The invented field is recorded and **excluded**. It never reaches the
reference, and it is never coerced into a field that looks similar.

### Unparseable output fails loud

```python
extract_declared("...", decl, complete_fn=lambda m: "I think it's Acme?")
# ValueError: model did not return valid JSON: Expecting value: line 1 column 1 (char 0)
```

## 3. Decide deterministically, and pin the model's role

Extracted references flow into the same gated path as everything else. Pass
`extra_pins=ex.pins(decl)` so the decision records what produced it:

```python
from arche import resolve

decision = resolve.pairwise(
    ex_a.reference, ex_b.reference,
    issuer_key=KEY, decl=decl,
    extra_pins=ex_a.pins(decl),
)

print(decision.identity, decision.score)
print(decision.pins["extraction"])
```

```text
same_entity 1.0
{'model': 'my-model@2026-08', 'prompt_sha256': '71bbbf4ee7f6dd6e',
 'declaration': 'fisheries-landings@1.2.0:sha256:28f13195e89a25e3',
 'reproducible': False}
```

Read that pin carefully, because it is the whole philosophy in one dict. The
*extraction* is not reproducible — a hosted model's output never is. The
*representation* (the declaration hash) and the *decision maths* (the engine,
the gate, the canonical form) are. The signature covers the honest split.

### The attestation inherits that honesty

```python
from arche.attest import attest, verify_attestation
from arche.sign import generate_keypair

kp = generate_keypair()
signed = attest(decision, kp, mode="jws")
v = verify_attestation(signed.compact, public_key=kp.public_key)

print(v.valid, v.trusted, v.reproducible)
```

```text
True True False
```

`reproducible=False` because a model was in the chain. The same two references
resolved by the engine alone attest as `reproducible=True`. A verifier can
tell the two apart without trusting anyone's word for it.

!!! note "Fixed in 0.3.0a1"

    `reproducible` was previously computed from the *signing mode*, so every
    JWS attestation claimed `True` — including ones built from LLM extractions
    whose own pin said `False`, with both claims inside the same artifact. It
    is now derived from the decision's pins.

## 4. Grade the model against the engine

The deterministic engine is the oracle. `grade_pairs` measures the model's
judgment against it.

```python
from arche.llm.harness import grade_pairs

decl = Declaration.from_yaml("examples/declarations/person.decl.yaml")

pairs = [
    ({"name": "Fatima Abdullahi", "national_id": "12345678901"},
     {"name": "Fatuma Abdulahi",  "national_id": "12345678901"}),
    ({"name": "Khalid Mehmood", "national_id": "AA1111111"},
     {"name": "Khalid Mehmood", "national_id": "BB2222222"}),
    ({"name": "Ngozi Okonkwo", "national_id": "55500011122"},
     {"name": "Chidi Eze",     "national_id": "99900044455"}),
]

report = grade_pairs(decl, pairs, judge=my_judge)   # judge(a, b) -> "same"|"different"|"unsure"
```

With a judge that decides on surname similarity alone — the classic failure:

```text
total_pairs     : 3
scored_pairs    : 3
engine_abstained: 0
judge_unsure    : 0
agreements      : 2
agreement_rate  : 0.6666666666666666
by_engine       : {'same_entity': 1, 'different': 2}
divergences     : 1

Divergence(a_id='', b_id='', engine='different', judge='same', score=0.0843,
           evidence={'name': 1.0, 'national_id': 0.0, 'name_tf': 1.0})
```

That single divergence is the two men named Khalid Mehmood. The judge saw
identical names and said `same`. The engine scored 0.0843 and said `different`
— and the divergence carries **why**: `name: 1.0` (a perfect match) alongside
`national_id: 0.0` (a direct contradiction). You are never told only that the
model disagreed; you are told what it disagreed with.

### Three honesty rules are built into the harness

**Engine `review` outcomes are abstentions.** Where the engine deliberately
does not know, the model is neither right nor wrong, and the pair is excluded
from `scored_pairs`. `agreement_rate` is `None` rather than `0.0` when nothing
was scorable — there is no grade over zero pairs.

**The judge's vocabulary is closed.**

```python
grade_pairs(decl, pairs, judge=lambda a, b: "probably")
# ValueError: judge returned 'probably'; expected one of ['different', 'same', 'unsure']
```

**Every divergence carries the engine's evidence**, factor by factor, as above.

For extraction there is no oracle — arche has never seen your fields, so it
cannot know the right answer. `grade_extractions` reports the honest contract
metrics instead: violation rate and per-field coverage, stamped with the
declaration pin.

## 5. Using a hosted provider instead of a callable

`LLMConfig` covers the common providers. `complete_fn` and `config` are
alternatives — pass one.

```python
from arche.llm import LLMConfig

ex = extract_declared(text, decl, config=LLMConfig(
    provider="anthropic",           # openai | anthropic | ollama | litellm
    model="claude-sonnet-4-5",
    api_key=...,                    # or the provider's usual env var
    temperature=0.0,                # the default, and the right one here
))
```

Providers load lazily — the base install has no LLM dependencies, and nothing
is imported until you call one. Errors name the fix:

```text
ValueError:   Unknown LLM provider: 'gpt5'. Supported: anthropic, litellm, ollama, openai
RuntimeError: openai package not installed. Install with: pip install arche-core[llm]
RuntimeError: Ollama request failed (http://localhost:11434/api/chat): ...
```

| Provider | Install |
|---|---|
| `openai`, `anthropic` | `pip install "arche-core[llm]"` |
| `litellm` (100+ backends) | `pip install "arche-core[litellm]"` |
| `ollama` (local) | no extra dependency — plain HTTP |

`temperature` defaults to `0.0`. Leave it there. Extraction is not a task where
you want sampling variety, and a lower-variance model makes the harness numbers
mean something.

## The boundary, stated plainly

The model never becomes the decider. Its knowledge is real where you need it
least — famous entities — and a guess where identity actually lives, in the
tail. Its judgments cannot be replayed once a model version retires.

So arche gives it the two jobs it is genuinely best at: reading messy text into
your schema, and proposing judgments the engine then grades. The gate, the
veto, and the signature stay deterministic. If the model is good, the harness
shows it, with numbers. If it isn't, the harness shows that too.

## Next

- [Declare your schema](declare-your-schema.md) — where the contract comes from
- [Read the crosswalk output](read-crosswalk-output.md) — what the engine returns at scale
- [Extract places with spatial roles](extract-places-with-roles.md) — the same
  grade-your-own-extractor pattern, with a labelled gold set shipped in the wheel
