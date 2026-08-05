# Bring your own LLM — arche grades it

You want the best model doing your extraction and matching. arche's position is not "don't" — it's **"models propose, curators accept, the engine executes"**, and this page is that division of labour as working code. Your declaration generates the model's contract; the deterministic engine acts as the oracle; every divergence is flagged, not hidden; and the decision that comes out the other side is signed with an honest account of the model's role.

Everything below runs offline — the "model" is any callable, which is the point: bring OpenAI, Anthropic, a local Ollama model via `LLMConfig`, or your own client as a plain function.

## 1. Extract into *your* schema

The declaration from [Declare your schema](declare-your-schema.md) generates the prompt, the JSON Schema (`additionalProperties: false`, `required: []` — a model told a field is required will invent it), and the validation:

```python
from arche.declare import Declaration
from arche.llm.declarative import extract_declared

decl = Declaration.from_yaml("fisheries.decl.yaml")

ex = extract_declared(
    "Landing sheet: Acme Fisheries, vessel IMO-9074729, Lagos",
    decl,
    complete_fn=my_model,      # any callable(messages) -> str; or config=LLMConfig(...)
    model="my-model@2026-08",
)
ex.reference      # a canonical Reference — your field names, declared roles
ex.violations     # e.g. ["undeclared field 'captain_ssn'"] — excluded, never coerced
```

A hallucinated field becomes a **violation**, not a value. Unparseable output fails loud. The model proposes; the declaration is the contract.

## 2. Decide deterministically, sign honestly

The extracted references flow into the same gated, signable path as everything else — with provenance pins that tell the truth about the model:

```python
from arche import resolve
from arche.attest import attest

decision = resolve.pairwise(ex_a.reference, ex_b.reference,
                            issuer_key=KEY, decl=decl,
                            extra_pins=ex_a.pins(decl))

decision.pins["extraction"]
# {"model": "my-model@2026-08", "prompt_sha256": "…",
#  "declaration": "fisheries-landings@1.2.0:sha256:…", "reproducible": False}

signed = attest(decision, issuer, mode="jws")
```

Read that pin carefully, because it is the whole philosophy in one dict: the *extraction* is not reproducible (a hosted model's output never is), but the *representation* (the declaration pin) and the *decision math* (the engine, the gate, the canonical form) are — and the signature covers the honest split.

## 3. Grade the model against the engine

The harness is the DSPy-shaped piece: the deterministic engine is the oracle, and the model's judgment is measured against it.

```python
from arche.llm.harness import grade_pairs

report = grade_pairs(decl, candidate_pairs, judge=my_llm_judge)
# judge(rec_a, rec_b) -> "same" | "different" | "unsure"

report.agreement_rate        # None if nothing was scorable — no grade over zero pairs
report.engine_abstained      # engine said `review`: the model is neither right nor wrong there
report.divergences           # every disagreement, WITH the engine's evidence
```

Three honesty rules are built in. Engine `review` outcomes are **abstentions** — the engine deliberately doesn't know, so those pairs don't count for or against the model. The judge's vocabulary is closed (`"probably"` raises). And each divergence carries the engine's factor-by-factor evidence, so "the model disagreed" is always inspectable, never a summary statistic.

For extraction quality there is no oracle for fields arche has never seen, so `grade_extractions` reports the honest contract metrics instead: violation rate and per-field coverage, stamped with the declaration pin.

## 4. From your agent

The MCP `compare_files` tool accepts your declaration too — `schema="fisheries.decl.yaml"` — always masked, pin on the report.

## The boundary, stated plainly

The model never becomes the decider. Its knowledge is real where you need it least (famous entities) and a guess where identity actually lives (the tail); its decisions can't be replayed once the model version retires. So arche gives it the two jobs it is genuinely best at — reading messy text into your schema, and proposing judgments the engine then grades — and keeps the gate, the veto, and the signature deterministic. If the model is good, the harness will show it, with numbers. If it isn't, the harness will show that too.

