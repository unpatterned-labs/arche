# Addresses & spatial roles: `arche.addr`

Address parsing, landmark anchors, spatial role labeling, and the shipped evaluation set. Everything here is offline and CPU-only.

## Parsing

### `parse_address(text) -> Address | None`

Parse the first address-like span in `text`. `parse_addresses(text) -> list[Address]` returns every non-overlapping span (longest-wins), which is what the role labeler consumes.

```python
from arche.addr import parse_address

addr = parse_address("7B Allen Avenue, Ikeja, Lagos")
addr.components.street      # "Allen Avenue"
addr.components.city        # "Lagos"
addr.country_inferred       # "NG"
addr.span                   # (0, 29)
```

`Address` carries `raw`, `span`, `components` (an `AddressComponents`: `plot`, `street_number`, `street`, `anchor`, `neighborhood`, `city`, `region`, `country`, `postal_code`, …), `country_inferred`, `country_confidence`, and `confidence`.

### `extract_anchor(text) -> tuple[str, str] | None`

Recover a standalone landmark anchor and its type, the informal-address case that dominates in much of Africa, where `parse_address` alone would return `None`.

```python
from arche.addr import extract_anchor, normalize_landmark

extract_anchor("behind the Total filling station, Madina Junction")
# ("behind the Total filling station", "commercial")
normalize_landmark("nyuma ya Total filling station")   # "Total filling station"
```

Relation words come from `addr/address_tokens.yaml` (English, Pidgin, Hausa, Yoruba, Igbo, Swahili, French, Portuguese), extending it is a data contribution, not a code change.

### `infer_jurisdiction(text) -> tuple[str, float, str]`

`(ISO alpha-2, confidence, trigger substring)`. Never silently defaults: callers that need certainty check for `"XX"`.

## Spatial role labeling

### `extract_places(text, *, rules=None) -> list[PlaceMention]`

Find place spans in free text and label each with the role it plays, returning the linguistic cue that decided it. Sorted by span start; spans never overlap.

```python
from arche import extract_places

for m in extract_places("Pick up from 7B Allen Avenue, Ikeja and deliver to "
                        "12 Adeola Odeku Street, Victoria Island."):
    print(m.role, m.text, m.cue, m.confidence)
# origin      7B Allen Avenue, Ikeja              from        0.95
# destination 12 Adeola Odeku Street, Victoria Island  deliver to  0.95
```

`PlaceMention` fields:

| Field | Meaning |
|---|---|
| `role` | `"origin"` / `"destination"` / `"location"` / `"via"` / `"unknown"` |
| `text`, `span` | the verbatim span and its `(start, end)` offsets |
| `cue`, `cue_span` | the deciding evidence; invariant: `text[cue_span] == cue` |
| `cue_phrase`, `cue_rule` | the canonical pack phrase and the rule id that fired |
| `confidence` | ordinal label from a 9-cell table (cue tier × span tier), **not** a probability |
| `evidence` | e.g. `("span:parsed", "cue:adjacent")`, or `("span:gazetteer", "cue_conflict:…")` |
| `address` | the normalized `Address` (or a minimal one for gazetteer/postcode spans) |
| `jurisdiction`, `jurisdiction_confidence` | inferred per mention |

`to_dict(reveal=False)` is the masked shape: offsets, canonical cue phrase, and component *names*, never address text or component values. This is the shape to hand an agent or any other caller across a trust boundary, since it holds the source text and can slice the offsets itself.

!!! warning "`reveal` defaults to `True`"

    `to_dict()` with no argument returns the **unmasked** shape, including the address text. Pass `reveal=False` explicitly when the output crosses a trust boundary.

**Abstention is structural.** No cue, cues conflicting at equal priority, or a negated cue (`"don't deliver to X"`) all yield `role="unknown"` at floor confidence 0.25, the extractor never guesses a role it cannot evidence.

### `load_role_pack(path=None) -> RolePack`

Load and validate the cue vocabulary (module-cached; malformed packs raise `RolePackError` naming the offending key). `pack.pin` is `arche.place_roles@v1:sha256:<16 hex>`, cite it with any result. `pack.vocabulary()` is the closed set of phrases a cue may be reported as, useful when you need a caller's output constrained to a fixed vocabulary rather than free text.

## The referee

### `load_gold(name="place_roles_v1") -> list[GoldSentence]`

The labelled gold set shipped **inside the wheel**, 54 sentences (UK + Nigerian, formal + informal + Pidgin, adversarial expected-`unknown` items, and negatives). Entries reference substrings; the loader resolves them to spans and raises on an absent or ambiguous fragment, so the data validates itself.

### `grade_places(gold, predictions, *, match="overlap", pack=None) -> PlaceGrade`

Score **any** extractor. `predictions` maps gold sentence id → mentions, accepting `PlaceMention`s *or* plain dicts (`{"start", "end", "role", "cue_start"?, "cue_end"?}`), so a non-Python extractor's JSON grades identically. Alignment is greedy one-to-one by span Jaccard (`>0` for `"overlap"`, `==1.0` for `"exact"`).

```python
from arche.addr import extract_places, grade_places, load_gold

gold = load_gold()
grade = grade_places(gold, {s.id: extract_places(s.text) for s in gold})
grade.per_role["destination"]["f1"]   # per-role precision/recall/F1
grade.span_f1, grade.cue_accuracy     # detection, and rationale faithfulness
grade.abstentions                     # correct_unknown / over_guess / missed_by_abstention
grade.summary()                       # all of the above as a dict
```

Refusal-aware scoring: predicting `unknown` where gold committed counts as a false negative and `missed_by_abstention`, **never** a false positive, because a non-answer is not a wrong answer. Predicting a role where gold is `unknown` counts as `over_guess` **and** a false positive: that is the failure this evaluation exists to price. Empty denominators return `None`, never a fake zero.

## LLM proposals

### `arche.llm.extract_places_llm(text, *, config=None, complete_fn=None, model="", rules=None)`

Have a model propose spans/roles/cues; the engine verifies each. Hallucinated spans become `violations` (dropped, never coerced into values); a committed role survives only if its cue is locatable in the source, adjacent to (or inside) the span, and pack-consistent with that role, otherwise the mention is kept and **downgraded** to `unknown`, recorded in `downgrades`. Returns `LLMPlaceExtraction` with `.mentions`, `.violations`, `.downgrades`, and `.pins()` (`model`, `prompt_sha256`, `pack`, `reproducible: False`).

Because the output is `PlaceMention`s, `grade_places` scores a model with no adapter code.
