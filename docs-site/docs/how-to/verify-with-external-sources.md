# Verify a merge against an external source

*A provider fetches references. arche resolves. The adapter layer exists to keep those two things apart.*

---

After a crosswalk merges two facility records, their claimed coordinates are an average of two sources that may both be wrong. Asking an independent gazetteer where the name actually resolves is a cheap check on that merge.

What comes back is **evidence, not a decision**. `arche.adapters` has one rule that shapes everything else on this page: no adapter is entitled to an opinion about identity.

Every snippet below was executed against `arche-core` 0.3.0a1 and the output is what it printed. None of it touches the network: `fetch=` is injectable, which is how the adapter is meant to be used against a recorded response.

## The verdict vocabulary, and what is missing from it

```python
from arche.adapters import verify_place

# A recorded Nominatim response for "Karfi, Kano" - the payload that came back
# from a live call, kept so the check replays.
KARFI = [
    {
        "display_name": "Karfi, Bunkure, Kano, Nigeria",
        "lat": "11.62192",
        "lon": "8.49279",
        "category": "place",
        "type": "village",
        "osm_id": 1234,
        "importance": 0.35,
    }
]

ev = verify_place(
    "Karfi Health Post",
    11.62192, 8.49279,                       # the position the merge claims
    retrieved_at="2026-08-08T12:00:00Z",     # you supply the clock, not arche
    user_agent="my-project/0.1 (me@example.org)",
    fetch=lambda url, params, headers: KARFI,   # omit for a live call
)

print(ev.verdict)
print(ev.detail)
print(ev.candidates[0]["name"])
```

```text
corroborates
{'candidate_count': 1, 'tolerance_km': 10.0, 'nearest_km': 0.0, 'nearest_index': 0}
Karfi, Bunkure, Kano, Nigeria
```

The rest of this page reuses that recorded payload:

```python
WHEN = "2026-08-08T12:00:00Z"
UA = "my-project/0.1 (me@example.org)"

def recorded(payload):
    return lambda url, params, headers: payload
```

There are exactly three verdicts:

| Verdict | Means |
|---|---|
| `corroborates` | a candidate falls within `tolerance_km` of the claimed position |
| `contradicts` | candidates were found and all lie beyond it |
| `inconclusive` | nothing was found, or no position was claimed |

```python
print("== the three verdicts ==")
for label, lat, lon, payload in [
    ("claim agrees with the gazetteer", 11.62192, 8.49279, KARFI),
    ("claim is 186 km away           ", 12.90000, 9.60000, KARFI),
    ("gazetteer has never heard of it", 11.62192, 8.49279, []),
]:
    ev = verify_place("Karfi Health Post", lat, lon, retrieved_at=WHEN,
                      user_agent=UA, fetch=recorded(payload))
    print(f"{label} -> {ev.verdict:14} {ev.detail}")
```

```text
== the three verdicts ==
claim agrees with the gazetteer -> corroborates   {'candidate_count': 1, 'tolerance_km': 10.0, 'nearest_km': 0.0, 'nearest_index': 0}
claim is 186 km away            -> contradicts    {'candidate_count': 1, 'tolerance_km': 10.0, 'nearest_km': 186.2, 'nearest_index': 0}
gazetteer has never heard of it -> inconclusive   {'candidate_count': 0, 'tolerance_km': 10.0, 'reason': 'gazetteer returned no candidates'}
```

**There is deliberately no `match` and no `different`.** A geocoder can agree or disagree with a claim about where something is. It cannot know whether two registry records denote one clinic. The evidence object carries no score and no decision field either:

```python
print("has .decision:", hasattr(ev, "decision"), " has .score:", hasattr(ev, "score"))
```

```text
has .decision: False  has .score: False
```

Two consequences worth stating. **Silence is not disagreement**: a gazetteer that has never heard of a rural health post says nothing about whether your merge is right, which is why an empty result is `inconclusive` rather than `contradicts`. And **`contradicts` is not a claim that the merge is wrong**. It means an independent source disagrees about the location, which is grounds for a human to look. It takes the same posture as the geographic veto: demote to review, never refuse outright.

`tolerance_km` defaults to 10.0, which is the place pack's `veto_km`. Set it tighter for dense urban work.

## The provenance firewall

OpenStreetMap data is ODbL. A derived database inherits ODbL. If provider responses were allowed to feed arche's name lexicons, frequency tables, or benchmark rows, those assets would inherit the most restrictive licence in the chain and stop being redistributable.

So every evidence object carries a licence class, and pack ingestion accepts open classes only.

```python
from arche.adapters import OPEN_LICENCE_CLASSES

print("licence           :", ev.licence)
print("in open classes   :", ev.licence in OPEN_LICENCE_CLASSES)
print("may_enter_packs   :", ev.may_enter_packs)
```

```text
licence           : odbl-attribution
in open classes   : False
may_enter_packs   : False
```

`OPEN_LICENCE_CLASSES` is `{"cc0", "gers", "user-owned"}`. Everything else, including ODbL, is usable as evidence for a single decision and must never be retained into anything durable. Read `may_enter_packs` before you cache a response anywhere that outlives the decision.

A licence class is required, not optional, and an unknown one is refused at construction:

```python
ProviderEvidence(provider="x", query="q", verdict="inconclusive",
                 retrieved_at=WHEN, licence="whatever-i-like",
                 response_sha256="0" * 64)
```

```text
ValueError: unknown licence class 'whatever-i-like'; expected one of ['cc0',
'odbl-attribution', 'cc-by', 'gers', 'user-owned', 'proprietary', 'unknown'].
A licence class is not optional - it is what the provenance firewall checks.
```

## The pin says the decision is not reproducible

A decision resting on a live API response cannot be world-replayed. Re-running it tomorrow re-asks a live service, and the service may have changed its mind. The pin records exactly what was asked, of whom, when, under what licence, and what came back:

```python
import json
print(json.dumps(ev.pin(), indent=2))
```

```text
{
  "provider": "nominatim",
  "query": "Karfi Health Post",
  "retrieved_at": "2026-08-08T12:00:00Z",
  "licence": "odbl-attribution",
  "response_sha256": "424d4b4aa5541ca7a79d046031227b48be85b2a5702f84f6de37252c76ecb729",
  "verdict": "corroborates",
  "reproducible": false
}
```

`reproducible: false`, for the same reason an LLM extraction pins `reproducible: False` in [bring your own LLM](bring-your-own-llm.md). The observation is *witnessed*, not derived.

arche stores nothing. **The caller keeps the payload that hashes true**, and the attestation pins the digest, so a verifier holding your recorded response can confirm the derivation even though they cannot re-derive the observation. The hash is canonical, so provider key ordering does not change it.

`retrieved_at` is a required argument rather than a call to `datetime.now()`. That is what lets a recorded response replay identically in a test and in a re-verified attestation.

## The egress guard

Sending a place name to a third-party service is a cross-border transfer. A facility name is usually fine. A patient's home address usually is not, and the statute pack should be the thing that decides, not the adapter.

`verify_place(guard=...)` calls `guard.check(value, provider="nominatim")` before anything leaves the process and lets whatever it raises propagate.

!!! note "You supply the shim in 0.3.0a1"

    `arche.guard.EgressGuard` exposes `guarded(text, provider=..., crosses_border=...)`, not `check(...)`. It is not directly compatible with the `guard=` parameter yet. The adapter accepts any object with a `check(value, *, provider)` method, so a five-line shim connects them. A native `EgressGuard.check` is outstanding work.

```python
from arche import Pipeline
from arche.adapters import verify_place
from arche.guard import EgressGuard, GuardDenied


class StatuteEgress:
    """Adapt an EgressGuard to the `.check(value, provider=...)` protocol."""

    def __init__(self, guard: EgressGuard) -> None:
        self._guard = guard

    def check(self, value: str, *, provider: str) -> None:
        projection = self._guard.guarded(
            value, provider=provider, crosses_border=True
        )
        if projection.fields:            # the query carried personal data
            raise GuardDenied(
                f"{len(projection.fields)} personal field(s) in a query bound "
                f"for {provider}: {[f.category for f in projection.fields]}"
            )


guard = StatuteEgress(EgressGuard(
    Pipeline(jurisdiction="NG"),
    key="demo-key",
    allowed_providers={"nominatim"},
    transfer_basis="explicit_consent",
))

sent = []


def spy(url, params, headers):
    sent.append(params["q"])
    return KARFI


ev = verify_place("Karfi Health Post", 11.62192, 8.49279,
                  retrieved_at=WHEN, user_agent=UA, guard=guard, fetch=spy)
print(ev.verdict, "| sent:", sent)

try:
    verify_place("Adesola Okonkwo, 08031234567", 11.6, 8.5,
                 retrieved_at=WHEN, user_agent=UA, guard=guard, fetch=spy)
except GuardDenied as exc:
    print("GuardDenied:", exc)
print("sent:", sent)
```

```text
== a facility name is fine ==
corroborates | sent: ['Karfi Health Post']

== a patient's details are not ==
GuardDenied: 1 personal field(s) in a query bound for nominatim: ['PII-3-PHONE']
sent: ['Karfi Health Post']

== a provider outside the allow-list ==
GuardDenied: provider 'nominatim' is not in the allow-list ['my-own-nominatim']
sent: ['Karfi Health Post']
```

`sent` never grows past the first call. When the guard refuses, nothing leaves. The guard is consulted before the request is built, not after.

The transfer basis has to be one the statute actually permits. Under the NDPA pack, `"consent"` is refused and names the alternatives:

```text
GuardDenied: cross-border transfer without a permitted basis
(declared='consent', permitted=['binding_corporate_rules', 'explicit_consent',
 'ndpc_adequacy_assessment', 'standard_contractual_clauses'])
```

## Usage policy, enforced rather than documented

The public Nominatim instance is a donated service with a published policy: a genuine identifying `User-Agent`, no more than one request per second, and no bulk geocoding. An adapter that gets the project banned is worse than no adapter, so two of those are enforced in code.

**A `User-Agent` is required and must not be blank.** There is no default, because a default would make every arche user look like one abusive client.

```python
verify_place("Karfi", retrieved_at=WHEN, user_agent="", fetch=recorded(KARFI))
```

```text
ValueError: user_agent is required: Nominatim's usage policy asks for a real identif ...
```

**One request per second is held process-wide** by a module-level lock, and the interval is a constant rather than a tuning parameter.

!!! warning "Injecting `fetch=` bypasses the throttle"

    The rate limiter runs only when `fetch` is `None`, on the assumption that an injected fetcher is a recorded cassette or your own client. If you pass a live HTTP fetcher, you own the rate limiting.

For anything beyond spot verification, run your own Nominatim instance and pass `base_url=`. The public endpoint is not a bulk geocoder and this adapter will not turn it into one.

Malformed candidates are dropped rather than fatal, since partial evidence is still evidence. A response that is not a JSON array is fatal, because it usually means an error page or a rate-limit notice:

```text
NominatimError: expected a JSON array, got dict
```

## Where this fits

Nominatim is the right first adapter because it is free, keyless, and genuinely independent of the government registries arche reconciles. That last property is worth checking rather than assuming: see [the place benchmark](../about/place-benchmark.md#the-independence-test) for a test that catches a "independent" source which is really a re-publication, and for the measurement showing OSM's Kano health facilities are *not* independent of GRID3.

Which is the honest caveat on this whole page. Nominatim serves OSM data. For Nigerian health facilities specifically, a Nominatim corroboration of a GRID3-derived coordinate may be corroborating a shared ancestor rather than providing a second opinion. It is a stronger check for settlements and landmarks, where OSM's lineage is genuinely community survey, than for facilities imported from a registry.

## Next

- The place benchmark for the independence test and the geographic veto this adapter's `tolerance_km` mirrors
- [Read the crosswalk output](read-crosswalk-output.md) for the evidence structure a verdict attaches to
- Bring your own LLM for the same evidence-not-decisions contract applied to a model
