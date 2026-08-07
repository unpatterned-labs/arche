# Extract places from free text, with their role — and grade any extractor

"Pick up from X and send it to Y" contains two addresses and one catastrophic failure mode: swapping them. An agent that books a courier with the roles flipped sends the rider to the pickup with the package. `extract_places` labels each place span with its **spatial role** and returns the **linguistic cue** that decided it, so the assignment is inspectable — and when cues are absent or conflicting it answers `unknown` rather than guessing.

The academic name is [spatial role labeling](https://aclanthology.org/S12-1048.pdf) (SemEval-2012; ISO-Space): `origin`/`destination`/`via` are the MOVELINK `source`/`goal`/`midPoint` of the standard, `location` is the ground of a static relation, and `unknown` mirrors SpRL's own explicit `undefined` value.

## 1. Extract

```python
from arche import extract_places

mentions = extract_places(
    "Can you come pick up this package from 123 Maple Street, London "
    "and send it to 3 Sherborne Place, Birmingham?"
)
for m in mentions:
    print(m.role, "|", m.text, "| cue:", m.cue, "|", m.confidence)
# origin      | 123 Maple Street, London      | cue: from | 0.95
# destination | 3 Sherborne Place, Birmingham | cue: to   | 0.95
```

Every mention carries `span` (character offsets), `cue`/`cue_span` (with the invariant `text[cue_span] == cue`), `cue_rule` (the pack rule id), `evidence` (e.g. `("span:parsed", "cue:adjacent")`), and a normalized `Address` from the [address pipeline](../tutorials/place_resolution_at_scale.md). Confidence is a small table of **ordinal labels** tied to evidence tiers, not an invented probability.

Informal forms are first-class: `"The workshop is behind the central mosque, Ungwan Rimi, Kaduna"` yields a `location` whose cue (`behind`) lives *inside* the span, and Pidgin/Hausa/Swahili cues (`carry am go`, `zuwa`, `kwenda`) ship in the vocabulary.

## 2. The refusal is the feature

```python
extract_places("The consignment was picked up at and delivered to 7B Allen Avenue, Ikeja.")
# [.. role="unknown", evidence includes "cue_conflict:deliver_destination|pickup_origin" ..]

extract_places("Don't deliver to 31 Ribadu Road, Kano anymore.")
# [.. role="unknown", evidence includes "cue:negated" ..]
```

Conflicting cues, negation, and cue-less mentions all abstain with floor confidence. The cue vocabulary is data, not code — [`place_roles.yaml`](https://github.com/unpatterned-labs/arche/blob/main/packages/arche-core/src/arche/addr/place_roles.yaml), contributor-extensible, with a content-hash pin so every result names the vocabulary that produced it.

## 3. From your agent

The MCP tool `extract_places(text)` returns **offsets only** — roles, cue rule ids, confidence, and component *names*, never the address text. The agent already holds the text and slices the offsets; the raw value stays on the caller's side of the trust boundary. No reveal option exists on this path.

## 4. Bring your own LLM — verified, not trusted

When the deterministic core abstains too often for your text, route a model through the same discipline with `arche.llm.extract_places_llm` — any callable or an `LLMConfig`, exactly like [extract_declared](bring-your-own-llm.md):

```python
from arche.llm import extract_places_llm

ex = extract_places_llm(text, complete_fn=my_model, model="my-model@2026-08")
ex.mentions      # PlaceMentions — same shape as the deterministic path
ex.violations    # hallucinated spans: dropped, never coerced into values
ex.downgrades    # committed roles whose cue failed verification -> unknown
ex.pins()        # {"place_extraction": {model, prompt_sha256, pack, reproducible: False}}
```

The constraint is non-negotiable: **a model-proposed role is only accepted when its cue can be located in the source text, adjacent to the span, and matched against the cue pack for that role.** A cue the model made up, placed elsewhere, or mapped to the wrong role downgrades the mention to `unknown` — kept, but stripped of the guess. The `cue` field stays what it claims to be: the linguistic evidence, never a post-hoc rationalization. And because the output is `PlaceMention`s, the same `grade_places` referee below scores the model's proposals with no adapter.

## 5. Grade your own extractor — the referee

The durable asset is not our cue engine; it is the labeled test set plus the scorer, shipped **in the wheel**. `pip install arche-core` is the whole setup for evaluating *your* LLM, prompt, or model on spatial role labeling — including the African-address and Pidgin slices no other benchmark covers:

```python
from arche.addr import extract_places, grade_places, load_gold

gold = load_gold()                    # 54 labelled sentences, v1 probe
preds = {s.id: extract_places(s.text) for s in gold}   # or YOUR extractor's dicts
grade = grade_places(gold, preds)
grade.per_role["destination"]["f1"]   # per-role F1
grade.abstentions                     # the honesty numbers
```

`grade_places` accepts plain dicts (`{"start", "end", "role", ...}`), so a non-Python extractor's JSON grades against the identical set. Scoring inherits the [harness](bring-your-own-llm.md) discipline: predicting `unknown` where gold committed is a *non-answer* (counted as `missed_by_abstention`, never a false positive); predicting a role where gold is `unknown` is an **over-guess** and a false positive — that is the failure mode this eval prices. Empty denominators return `None`, never a fake zero. 

The shipped deterministic extractor is the transparent baseline row: on the v1 set it scores span F1 0.99, per-role F1 0.97–1.0, cue accuracy 1.0, with exactly one documented over-guess (the attributive trap: "the invoice **from our Lagos office**" has a movement-shaped cue and no movement — the known blind spot of cue-based labeling, and a sentence type we deliberately kept in the gold set).

**Honest scope:** the v1 set is a 54-sentence *probe*, not a citable benchmark — per-role confidence intervals at this size are wide. The citable version (300+ items, dual-annotated with reported agreement) is the tracked next step. Cross-sentence references ("return it to the first address"), anaphora, and non-cue-decidable roles are out of scope for the deterministic core by design: those are exactly where it abstains and where a graded LLM may earn its keep.


