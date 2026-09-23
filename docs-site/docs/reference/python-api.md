# Python API

Every public name in `arche`, grouped by what you do with it: the signature as it is in the source, one sentence, what comes back, and the guide that shows it in use. At the end of this page you know which name answers which question and where its full walkthrough is.

This page and `arche.__all__` are the same list, and a test holds them together. That is the 1.x promise: these names keep working, with these meanings, through every 1.x release.

```python
import arche

print(arche.__version__)
print(sorted(arche.describe()["verbs"]))
```

```text
0.9.0
['compare', 'dedupe', 'find', 'reconcile']
```

| You want to | Names | Guide |
|---|---|---|
| find the personal data in a text, make a copy you can hand on | `detect_pii`, `deidentify`, `Deidentified`, `Pipeline` | [Find and mask](../guides/find-and-mask.md) |
| decide whether records are the same thing | `compare`, `reconcile`, `dedupe`, `find`, `describe`, `Receipt`, `AUTO_SPLINK_FLOOR` | [Compare two records](../guides/compare-two-records.md), [Resolve a batch](../guides/resolve-a-batch.md) |
| PDFs and text files in, linked records out | `resolve_documents`, `DocumentReport` | [Resolve documents](../guides/resolve-documents.md) |
| places in free text, a delivery request against your own sheet | `extract_places`, `resolve_place_request`, `SpatialMention`, `MasterSheet`, `Nominatim`, `Policy` | [Resolve a delivery address](../guides/resolve-a-delivery-address.md) |
| your own field names, once, for extraction and matching | `schema`, `Declaration`, `extract` | [Extract to your schema](../guides/extract-to-your-schema.md) |
| keep a decision, explain it, make it again | `attach`, `Ledger` | [Keep, explain, replay](../guides/keep-and-replay.md) |
| sign an answer, verify one | `arche.sign`, `arche.attest` | [Attestation](../how-it-works/attestation.md) |
| build your own comparator | `arche.resolve.compare_geo` and the helpers beside it | [Evidence, gates and distinctiveness](../how-it-works/evidence.md) |

Every verb that makes a decision takes `store=`, a `Ledger` from `attach`. The return value is the same with or without it; the receipt is additionally recorded with the inputs it was made from. Every name below is importable as `arche.<name>` unless its module is given.

## Find and mask

<!-- docs-test: fragment -->
```python
def detect_pii(text: str, jurisdiction: str | None = None, *,
               backend: str = "auto", statute: str | None = None) -> list[Detection]
```

The personal data in `text` as spans: category, offsets, confidence, detector and the statute section each falls under. Never the value. `backend` is `auto` (rules, plus the model when the `detect` extra is installed), `basic` (rules only) or `gliner2-pii`. `jurisdiction=None` infers the country from the text and raises `JurisdictionRequiredError` when the evidence is thin.

<!-- docs-test: fragment -->
```python
def deidentify(text: str, jurisdiction: str | None = None, *,
               backend: str = "auto", method: str = "statute", statute: str | None = None,
               salt: str = "", store: Any | None = None) -> Deidentified
```

A copy of `text` with its personal data removed, as a decision with an id. `method` is `statute` (the pack decides per category), `mask`, `token` or `drop`; `salt` keys the tokens so two deployments never mint the same one.

<!-- docs-test: fragment -->
```python
@dataclass(frozen=True)
class Deidentified:
    text: str
    detections: tuple[Detection, ...]
    outcomes: tuple[Any, ...]
    decision_id: str
    document_hash: str
    jurisdiction: str | None
    statute: str | None
    backend: str
    method: str
    pins: dict[str, Any]
    coverage: dict[str, Any]

    count: int                                  # property
    def by_category(self) -> dict[str, int]
    def spans(self) -> list[dict]               # value-free span report
    def record(self) -> dict[str, str]          # the tokenised fields a copy can be compared on
```

`decision_id` starts `red:sha256:` and is a content hash over the spans and the pins, so the same text under the same statute and method gives the same id.

<!-- docs-test: fragment -->
```python
class Pipeline:
    def __init__(self, jurisdiction: str | None = None, statute: str | None = None,
                 detectors: list[str] | None = None, address_parsing: bool = False,
                 audit: bool = True, tokenize_salt: str = "", overlays: list[str] | None = None,
                 transparency_notice: str | None = None, on_uncovered: str = "silent",
                 backend: str = "basic")
    def process(self, text: str) -> Result
    def process_file(self, source: str | Any) -> Result
    def describe(self) -> dict[str, Any]
    def effective_detectors(self, *, warn: bool = False) -> list[str]
```

The detection primitive underneath `detect_pii` and `deidentify`: detectors, a statute, and the redaction it requires. `Result` carries `document_hash`, `detections`, `addresses`, `policy_outcomes`, `redacted_text`, `audit_log` and `metadata`; `Detection` carries `category`, `text`, `start`, `end`, `confidence`, `detector`, `identity_class`, `sensitivity_tier`, `regulatory_citation` and `metadata`. Reach for `Pipeline` when you need the audit log or a custom detector list; otherwise the two verbs are the surface.

## Compare and resolve

<!-- docs-test: fragment -->
```python
def compare(a, b, *, entity: str = "person", store=None, **kwargs) -> Receipt
```

Are these two the same thing? `a` and `b` are two dicts with your own field names, two `Pipeline` results, two canonical references, or two strings (with `jurisdiction=` and `backend=` so the fields can be read out first). `entity` picks the pack: `person`, `organisation`, `place`, `product_electronics`, `product_grocery`, `product_home_goods`, `artist`. `person` runs the Fellegi-Sunter engine; every other pack runs the pack engine, and the two do not share a score.

<!-- docs-test: fragment -->
```python
@dataclass
class Receipt:
    identity: str            # same_entity | review | different
    action: str              # merge | hold | no_op
    basis: str               # single_identifier, corroborated, pack:<name>, ...
    score: float
    factors: dict[str, float]
    field_weights: dict[str, dict[str, float]]
    explanation: str
    gate: dict[str, Any]
    vetoes: dict[str, Any]
    reference_id_a: str
    reference_id_b: str
    decision_id: str
    entity_id: str | None
    reference_a: Reference
    reference_b: Reference
    jurisdiction: str
    pins: dict[str, Any]
```

What `compare` returns. `identity` is the belief and `action` the recommendation, and they can disagree. `decision_id` is a content hash over the rounded evidence and the pins. [The decision](../how-it-works/the-decision.md) reads every field.

<!-- docs-test: fragment -->
```python
def reconcile(list_a, list_b, comparators: list[dict] | None = None, *,
              entity: str | None = None, tf=None, decl=None, schema=None,
              store=None, **kwargs) -> dict
```

Which of these are the same as those? Two lists of records with a stable `id` each; pass `entity=` for a shipped pack or `comparators=` for your own spec, not both. The batch result is a dict: `matches` (each edge `a_id`, `b_id`, `decision` of `match` or `review`, `score`, `evidence`, `distinctive_max`, `decision_id`), `count`, `pins`, `blocking` and `backend`. Pairs below `threshold - review_margin` are not returned; their absence is not a claim that they differ. Options in `**kwargs` include `threshold`, `review_margin`, `id_field`, `distinctive_floor`, `block`, `backend`, `splink_settings`, `candidate_pairs`, `candidate_pins` and `truth_pairs`.

<!-- docs-test: fragment -->
```python
AUTO_SPLINK_FLOOR = 1000
```

`backend="auto"` (the default) runs arche's own engine below this many records. At or above it, a shipped Splink recipe scores the batch when the entity has one, `arche-core[resolve]` is installed, and the records carry the recipe's columns; otherwise the engine again. `result["backend"]` says which was chosen and why. Three recipes ship in `arche.resolve.recipes`: `person/febrl-v1` (reads `given_name` and `surname` as two columns, so a `person` caller with one `name` blob stays on the engine at every size), `place/name-coords-v1`, and `product/identity-v1`, which `auto` never picks because the engine's product pack measures better. `backend="arche"` is the engine regardless of size; `backend="splink"` is Splink regardless and needs `splink_settings=`. [Backends](../how-it-works/backends.md) has the measurement behind the floor.

<!-- docs-test: fragment -->
```python
def dedupe(records, comparators: list[dict] | None = None, *,
           entity: str | None = None, tf=None, decl=None, schema=None,
           store=None, **kwargs) -> dict
```

Collapse one list. Returns the same edge shape as `reconcile` plus `clusters`, the transitive closure over `match` edges only, each with `members`, `size` and `held_together_by` (`direct` when every pair was itself compared and matched, `transitive` when some pair never was), `cluster_count` and `review`. Self-pairs and mirrored edges are dropped. Ids must be unique.

<!-- docs-test: fragment -->
```python
def find(query: dict, within: list[dict], comparators: list[dict] | None = None, *,
         entity: str | None = None, tf=None, decl=None, schema=None,
         ambiguity_margin: float = 0.05, store=None, **kwargs) -> dict
```

Which of these is this one? One record against a list. Returns a `verdict` of `found`, `ambiguous` or `not_found`, the `match` when found, `rivals` and `would_resolve` when ambiguous, `candidates` (what was compared, best first), `reason`, `query`, `blocking` and `pins`. `ambiguous` is not a match: two or more candidates are within `ambiguity_margin` of each other.

<!-- docs-test: fragment -->
```python
def describe(entity: str | None = None) -> dict
```

What arche can be asked, and about what, as data: the `verbs`, the `entities`, `outcomes`, `comparators`, and for each pack in `packs` the fields it reads and what each comparator does. Pass `entity` for one pack.

<!-- docs-test: fragment -->
```python
from arche.resolve.reconcile import sign_edges

def sign_edges(result: dict[str, Any], *, private_key: Any, kid: str,
               decisions: tuple[str, ...] = ("match", "review")) -> list[dict[str, str]]
```

JWS-sign the edges of a batch result with a key from `arche.sign.generate_keypair`. Each signed payload carries the edge and the run pins, so a recipient can verify it and recompute the `decision_id`.

## Documents

<!-- docs-test: fragment -->
```python
def resolve_documents(source: str | os.PathLike | Iterable[str | os.PathLike], *,
                      entity: str = "person", jurisdiction: str = "auto",
                      candidates: Iterable[Mapping[str, Any]] | None = None,
                      max_candidate_pairs: int = 1000, quiet: bool = True,
                      progress: ProgressHandler | bool | str | None = True,
                      extraction_backend: str = "auto",
                      store: Any | None = None) -> DocumentReport
```

A path, a directory, a glob or a list of paths in. Each document is parsed (plain text natively; PDF, DOCX and scanned pages through the `doc` and `doc-ocr` extras), its jurisdiction inferred or taken from `jurisdiction=`, its fields proposed, and every document resolved against the others or against `candidates`.

<!-- docs-test: fragment -->
```python
@dataclass
class DocumentReport:
    records: dict[str, dict[str, Any]]
    decisions: list[dict[str, Any]]
    detections: dict[str, dict[str, int]]
    record_provenance: dict[str, dict[str, str]]
    metadata: dict[str, Any]
    provenance: dict[str, dict[str, Any]]
    errors: dict[str, str]
    jurisdiction: str
    entity: str
    jurisdictions: dict[str, Any]
    jurisdiction_conflicts: dict[str, tuple[str, str]]
    timing: Timing
    review_fields: dict[str, dict[str, dict[str, object]]]

    def to_dicts(self, reveal: bool = False) -> list[dict[str, Any]]
    def to_rows(self, reveal: bool = False) -> tuple[list[str], list[list[str]]]
    def to_csv(self, path: str | os.PathLike | None = None, *, reveal: bool = False) -> str | Path
    def table(self, reveal: bool = False) -> str
    def review(self, *, reveal: bool = False) -> dict[str, Any]
    def unlinked(self) -> list[str]
    def to_json(self, reveal: bool = False, indent: int = 2) -> str
    def save_json(self, path: str | os.PathLike, reveal: bool = False) -> Path
```

Everything `resolve_documents` found, keyed by file name. Values are masked in every output unless `reveal=True`. `read_metadata` in the same module reads a document's own metadata without resolving it.

## Places

<!-- docs-test: fragment -->
```python
def extract_places(text: str, *, rules: RolePack | None = None) -> list[PlaceMention]
```

Place mentions in free text with their spatial role (`origin`, `destination`, `location`, `via`, `unknown`) and the cue that decided it. `PlaceMention` carries `role`, `text`, `span`, `cue`, `cue_span`, `cue_rule`, `cue_phrase`, `confidence`, `evidence`, `address`, `jurisdiction` and `jurisdiction_confidence`; `to_dict(reveal=False)` gives the value-free form the MCP server returns.

<!-- docs-test: fragment -->
```python
def resolve_place_request(text: str, *, action: str, sources: Sequence[PlaceSource],
                          policy: Policy | None = None, now: datetime.date | None = None,
                          store: Any | None = None) -> PlaceRequest
```

Read the request, resolve each endpoint against the sources, apply the policy. `PlaceRequest` carries `action`, `text`, `time_window`, `endpoints` (a dict of `Endpoint`: `role`, `status`, `mention`, `candidates`, `question`, `question_kind`, `decision_id`, `pins`), `policy` and `mentions`, plus `origin`, `destination` and `status` as properties. An endpoint's `status` is `verified`, `clarification_required` (a question, with the likely answer first), `refused` (with what was tried) or `missing`.

<!-- docs-test: fragment -->
```python
@dataclass(frozen=True)
class SpatialMention:
    action_role: str
    target_text: str
    span: tuple[int, int]
    confidence: float
    relation_kind: str | None = None
    reference_text: str | None = None
    reference_qualifier: str | None = None
    access_hint: str | None = None
    street_number: str | None = None
    street: str | None = None
    street_suffix_known: bool = True
    cue: str | None = None
    evidence: tuple[str, ...] = ()
```

One endpoint as the sentence gave it: role, target, relation to a landmark, access hint. It is what a `PlaceSource` receives in `candidates(mention, *, limit=5)`.

<!-- docs-test: fragment -->
```python
from arche.addr.request import MasterSheet, Nominatim, Policy

class MasterSheet:       # the caller's own places
    def __init__(self, records: Sequence[Mapping[str, Any]], name: str = "master_sheet",
                 id_field: str = "id", landmark_radius_m: float = 250.0)

class Nominatim:         # OpenStreetMap's geocoder, opt-in, rate-limited, off when offline
    def __init__(self, name: str = "nominatim",
                 user_agent: str = "arche-core (https://github.com/unpatterned-labs/arche)",
                 endpoint: str = "https://nominatim.openstreetmap.org/search",
                 country_codes: str | None = None)

@dataclass(frozen=True)
class Policy:
    verified_at: float = 0.85
    clarify_margin: float = 0.15
    minimum: float = 0.4
    require: tuple[str, ...] = ("origin", "destination")
    candidates_shown: int = 3
    confirm_typo_matches: bool = True
```

`MasterSheet` records need an id, a name and an address, and may carry `lat`, `lon` and `kind` (`landmark`). `Policy` says when an endpoint is verified, when it becomes a question, and when it is refused.

## Schema

<!-- docs-test: fragment -->
```python
def schema(source: Declaration | str | Path | dict) -> Declaration
```

Load a declaration from a YAML path, a dict, or a `Declaration` as is. Pass the result as `schema=` to `reconcile`, `dedupe`, `find` and `extract`, so extraction and matching read the same field names.

<!-- docs-test: fragment -->
```python
@dataclass(frozen=True)
class Declaration:
    name: str
    version: str = "0"
    entity: str = ""
    id_field: str = "id"
    statute_id: str | None = None
    jurisdiction: str = "default"
    on_unknown: str = "warn"
    tf: str | None = None
    geo: dict | None = None
    fields: dict[str, FieldDecl]
    load_warnings: tuple[str, ...] = ()

    @classmethod
    def from_yaml(cls, path: str | Path) -> Declaration
    @classmethod
    def from_dict(cls, raw: dict) -> Declaration
    def comparators(self) -> list[dict]
    def json_schema(self) -> dict
    def tool_def(self, format: str = "json-schema") -> dict
    def validate_record(self, record: dict)
    def pin(self) -> str
```

A validated declaration. `comparators()` is the pack it implies; `tool_def(format=)` is the same declaration as a `json-schema`, `anthropic` or `openai` tool definition, which is what `arche schema gen` prints.

<!-- docs-test: fragment -->
```python
def extract(text: str, entity_types: list[str] | None = None, backend: str = "auto",
            llm_config: object | None = None, *, schema=None)
```

Entities in `text` as a list of `Entity` (`text`, `entity_type`, `confidence`, `start`, `end`, `source`, `metadata`), or with `schema=` one record in your own fields. `backend="basic"` needs no model.

## The ledger

<!-- docs-test: fragment -->
```python
def attach(uri: str) -> Ledger
```

Open a ledger: `duckdb:///:memory:` for scratch, `duckdb:///file.duckdb` to keep. DuckDB loads on this call, not on `import arche`. Nothing leaves the machine.

<!-- docs-test: fragment -->
```python
class Ledger:
    def decision(self, decision_id: str) -> Decision
    def explain(self, decision_id: str) -> dict[str, Any]
    def replay(self, decision_id: str) -> Replay
    def entities(self, entity_type: str | None = None) -> list[EntityView]
    def path(self, record_a: str, record_b: str) -> list[Decision]
    def cases(self, entity_type: str | None = None) -> list[Case]
    def observe(self, record_id: str, evidence: Mapping[str, Any]) -> list[Decision]
    def resolve(self, record: Mapping[str, Any] | str, *, entity_type: str,
                jurisdiction: str = "default", backend: str = "basic") -> Resolution

    def record_compare(self, receipt: Any, a: Any, b: Any, *, call: Mapping[str, Any],
                       source: str = "compare", caller_ids=(None, None),
                       supersedes: str | None = None, record_ids=(None, None)) -> Decision
    def record_batch(self, result: Mapping[str, Any], list_a: list[Mapping[str, Any]],
                     list_b: list[Mapping[str, Any]], *, call: Mapping[str, Any],
                     verb: str = "reconcile", link: bool = True) -> list[Decision]
    def record_deidentify(self, deid: Any, text: str, *, call: Mapping[str, Any]) -> Decision
    def record_place_request(self, result: Any, *, sources: Sequence[Any], now: Any = None) -> list[Decision]

    def record(self, record_id: str) -> Record
    def entity(self, entity_id: str) -> EntityView
    def entity_of(self, record_id: str) -> str | None
    def history(self, record_id: str) -> tuple[Decision, ...]
    def events(self, limit: int | None = None) -> tuple[Event, ...]
    def read(self, source: str, *, limit: int | None = None) -> list[dict[str, Any]]
    def graph(self, entity_id: str | None = None)
    def close(self) -> None
```

| Method | Answers |
|---|---|
| `decision` | the receipt as recorded; `KeyError` if the ledger never saw the id |
| `explain` | `supporting`, `refuting`, `missing`, `shared` and `gate` for one decision |
| `replay` | the decision made again with the engine installed now: `reproduced`, `then`, `now`, `changed` |
| `entities` | every entity the linked decisions have built, largest first, with `held_together_by`, `weak_links` and `bridges` |
| `path` | the chain of decisions that makes two records one entity; empty when they are not |
| `cases` | pairs still at `review`, each with `would_resolve` |
| `observe` | add evidence about a record and decide its open pairs again; new receipts name what they supersede |
| `resolve` | a new record against the entities the ledger holds: `found`, `review`, `ambiguous`, `conflict` or `not_found` |
| `record_*` | what `store=` calls for you: one receipt, a batch, a redaction, a place request |
| `read` | a table or view from the same DuckDB file, as dicts, for your own analysis |

`record_a`, `record_b` and `record_id` are content addresses of the form `rec:sha256:...`; `ledger.record(id)` gives the label the caller supplied.

## Signing and attestation

<!-- docs-test: fragment -->
```python
from arche.sign import generate_keypair, load_private_key_pem, load_public_key, sign, verify

def generate_keypair() -> Keypair                       # .private_key, .public_key, .did_key
def load_private_key_pem(data: bytes | str, password: bytes | None = None) -> Keypair
def load_public_key(source: str | bytes) -> Ed25519PublicKey   # a did:key, PEM, or 32 raw bytes
def sign(payload: bytes | str | dict, private_key: Ed25519PrivateKey, *,
         kid: str | None = None, typ: str = "JWT", detached: bool = False,
         extra_header: dict[str, Any] | None = None) -> str
def verify(jws_compact: str, *, public_key: Ed25519PublicKey | None = None,
           resolver: Callable[[str], Ed25519PublicKey | None] | None = None,
           detached_payload: bytes | str | None = None,
           allow_did_key_from_kid: bool = False) -> VerificationResult
```

Ed25519 signatures, `did:key` identifiers and JWS envelopes. arche never stores a key. `verify` needs a key you already trust, or a `resolver`; without one it fails rather than falling back to the key the token names for itself. `VerificationResult` carries `valid`, `trusted`, `header`, `payload`, `kid`, `key_source` and `error`. The module also exports `encode_did_key`, `decode_did_key`, `export_private_pem`, `export_public_pem`, `save_private_key`, `document_hash`, and the `SignWorkflow` / `VerifyExtractWorkflow` pair that signs a `Pipeline` result and recovers it.

<!-- docs-test: fragment -->
```python
from arche.attest import attest, verify_attestation, signing_key, decision_ids_in

def attest(tool: str, inputs: Any, response: Any, *, keypair: Any, caller: str | None = None,
           decision_ids: list[str] | None = None, issued_at: datetime | None = None) -> dict[str, Any]
def verify_attestation(envelope: dict[str, Any], *, inputs: Any = None, response: Any = None,
                       public_key: Any = None, resolver: Any = None) -> AttestationCheck
def signing_key(path: str | Path | None = None) -> Any       # the installation's key, or None
def decision_ids_in(response: Any) -> list[str]
```

An attestation is a JWS over one answer: the tool called, a hash of the inputs, a hash of the response, who asked, and every decision id the response carried. `AttestationCheck` carries `valid`, `trusted`, `signer`, `tool`, `decision_ids`, `inputs_match`, `response_match` and `problems`. `trusted` is true only when the verifier supplied the key. `arche serve` and `arche mcp` attach one to every answer when `ARCHE_SIGNING_KEY` is set; `arche attest verify` checks it from the shell.

## Comparator helpers

The pieces a comparator is made of, on `arche.resolve`. They are not in `arche.__all__`: you reach for them when writing your own comparator or reading why one scored what it did, and they are not part of the vocabulary. They are importable from `arche` too, for code written before 1.0.

<!-- docs-test: fragment -->
```python
from arche.resolve import (compare_geo, compare_place_qualifiers, load_type_vocab,
                           normalize_type_token, split_place_name, to_match_record)

def compare_geo(lat_a: float, lon_a: float, lat_b: float, lon_b: float, *,
                decay_km: float = 1.5) -> float
def split_place_name(name: str) -> tuple[str, str]                  # (core, qualifier)
def compare_place_qualifiers(name_a: str, name_b: str) -> float | None
def normalize_type_token(text: str, vocab: dict[str, str]) -> tuple[str | None, str]
def load_type_vocab(domain: str) -> dict[str, str]
def to_match_record(detections: Any) -> dict[str, Any]
```

`compare_geo` turns a distance into a similarity that decays with `decay_km`. `split_place_name` separates *Kano Central* from *(Annex)*; `compare_place_qualifiers` scores the second half and answers `None` rather than `0.0` when one side has no qualifier, which is how an absent field stays absent. `normalize_type_token` reads *PHC* and *Primary Health Centre* as one type and hands back `(type, residual name)`, with `None` for the type when it recognises none; `load_type_vocab(domain)` is the table you pass it. `to_match_record` turns `Pipeline` detections into a record the matcher can take.

## Not part of the 1.x promise

These import and are unchanged. They are out of `__all__` because a recommended verb should do its job on a plain install, and these ship fixtures only: without them the report comes back empty.

<!-- docs-test: fragment -->
```python
from arche import resolve_places, list_places          # the v0.1 directory lane
```

For places you hold yourself, [resolve a delivery address](../guides/resolve-a-delivery-address.md) is the lane that is promised.

## What a promise about names does not cover

The list above promises names and their meanings. It does not promise numbers, and three kinds of number move on their own schedule.

**Scores and confidences are calibration, not contract.** `Receipt.score`, a candidate's `confidence`, `distinctive_max`: each is produced by weights that are measured and re-measured against the benchmarks. A release that improves a lane changes them, and that is the point of having benchmarks. What is promised is the shape (`[0, 1]`, higher is more agreement) and the meaning of the verdict they feed.

**Evidence strings are a growing vocabulary.** `'street-number match'`, `'typo-tolerant street match'`, `'relation geometry agrees'`: a new comparator adds a new one. Read `evidence` as a list to show a person, not as an enum to branch on; the fields in `factors` and the verdict are what a program should decide by.

**A `decision_id` is only stable against the engine that made it.** Every id hashes the pinned versions, so a release that changes a comparator, a frequency table or a statute pack moves the ids that depended on it, by design. That is what `replay` reports: `reproduced` false with `changed` naming the pin. An id is an address for one decision under one engine, not a permanent name for a pair.

This is why `arche.addr.request` puts only two names in `__all__`, `resolve_place_request` and `SpatialMention`. Its `Policy` numbers, its evidence strings and its `PLACE_ENGINE` pin are all in the moving category above, and the module is four days younger than the freeze; `Policy`, `MasterSheet`, `Endpoint`, `PlaceCandidate` and `PlaceSource` are importable and documented in [Resolve a delivery address](../guides/resolve-a-delivery-address.md), and they are not frozen for 1.x.

## Where to read next

| You want to | Read |
|---|---|
| the same verbs from the shell | [Command line](cli.md) |
| the same verbs over a socket | [HTTP API](http-api.md) |
| the same verbs from an agent | [MCP tools](mcp-tools.md) |
| what each field on a receipt means | [The decision](../how-it-works/the-decision.md) |
| which extras unlock which names | [Extras](extras.md) |
