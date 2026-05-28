# arche-core v0.2.0a2 — *African PII detection that cites the law it enforces*

**Released:** 2026-05-28
**PyPI:** `pip install arche-core==0.2.0a3`
**Tests:** 980 passing · **License:** Apache 2.0

> [!WARNING]
> **Status:** pre-beta (development),  `arche-core` is under active development. APIs may change between alpha  releases.
---

## What this is

`arche-core` is a Python SDK for detecting personally identifying information in African text and grounding every detection in the data protection statute that governs it. NDPA, POPIA, Kenya DPA, Ghana DPA. Six closed policy actions. Designed to compose with Presidio, GLiNER, and Splink, not to replace them.

```python
from arche import Pipeline

result = Pipeline(jurisdiction="NG").process(
    "Fatima Abdullahi, NIN 12345678901, BVN 22100987654."
)

for d in result.detections:
    print(f"{d.category:11} tier={d.sensitivity_tier.value:9} {d.regulatory_citation}")
# PII-2-BVN   tier=high      NDPA-2023 s.30, CBN BVN policy 2014
# PII-2-NIN   tier=high      NDPA-2023 s.30, NIMC Act s.27
# PII-1-NAME  tier=moderate  NDPA-2023 s.30

print(result.redacted_text)
# NAME_... NAME_..., NIN [NIN], BVN [BVN].
```

Same code works for `jurisdiction="ZA"` (POPIA), `"KE"` (Kenya DPA), `"GH"` (Ghana DPA). Four launch jurisdictions, four DPA-grounded statute YAML files, one composable framework.

---

## What's new since v0.2.0a1

### The big one: every detection now cites the statute behind it

This is the headline. Until this release, the `Pipeline` would detect PII and apply policy, but the `Detection` object carried only the category. v0.2.0a2 adds two fields to every `Detection`:

- **`sensitivity_tier`** — one of `high` / `moderate` / `low` per jurisdiction.
- **`regulatory_citation`** — the specific statute section that classifies it, e.g. `"NDPA-2023 s.30, CBN BVN policy 2014"`.

These are derived from the statute YAML, applied per detection, and surface in the audit log. A compliance officer can replay any decision back to the exact rule that produced it.

### MVP address parser for Nigeria and South Africa

`arche.addr.parse_addresses` and the `Address` dataclass ship a 633-line parser MVP for landmark-anchored African address formats. The kind of addresses libpostal does not handle:

- *"behind Total filling station, Madina Junction, Accra"*
- *"14 Yaba Road, opposite UBA bank, Surulere, Lagos"*
- *"No. 5 Park Lane, near Engen petrol station, Sandton"*

Wired into `Pipeline` as part of the default detector chain. Kenya and Ghana coverage is the next quarter's work.

### Places resolver — `resolve_places` and `list_places`

Two new public functions for jurisdictional place lookup with verifiable JWS audit receipts:

```python
from arche import resolve_places, list_places

# Anchored: find places near a free-text reference
report = resolve_places(
    "My mum lives near St Thomas' Hospital in SW1 — find her a dentist."
)
for place in report.places:
    print(place.name, place.distance_m, "m away")
report.save_receipt("audit.jws")

# Directory: paginate every instance of a category in a jurisdiction
dirreport = list_places(category="physiotherapy", jurisdiction="GB")
```

Ships with fixture-mode by default; set `DEMO_LIVE_API=true` to enable live OSM / NHS / openchargemap backends. Categories in v0.2.0a2: physiotherapy, dentist, ev_charger.

### Web fetch helper — `arche.ingest.from_url`

SSRF-guarded HTTP fetch for ingesting text from public URLs. Built on `httpx` with tight redirect and timeout controls so the helper can be used in agent / pipeline contexts where the URL is user-supplied.

### New detectors

- **`arche.detect.ip`** — IPv4, IPv6, private-range, Tor-exit detection with policy mapping.
- **`arche.detect.digital_id`** — decentralized identifier (DID) and verifiable credential reference detection. Emits the new  `PII-2-DID` category.

### Taxonomy growth

Three new categories in the Pan-African PII Taxonomy with statute mappings in NDPA-2023:

- `PII-4-LOCATION` — geographic locations (cities, regions, landmarks)
- `PII-2-DID` — decentralized identifiers
- `PII-5-CRYPTO_WALLET` — cryptocurrency wallet addresses

---

## Install

```bash
pip install arche-core           # ~310 KB base
pip install arche-core[all]      # everything (GLiNER + Presidio + Splink + docling + LLM)
```

Or with `uv`:

```bash
uv add arche-core
```

Opt-in extras for composing with the incumbent tools:

| Extra | Adds |
|---|---|
| `arche-core[detect]` | GLiNER2-PII via ONNX runtime |
| `arche-core[presidio]` | Microsoft Presidio recognizer plugin |
| `arche-core[resolve]` | Splink + DuckDB for entity resolution |
| `arche-core[doc]` | docling for PDF / DOCX / PPTX / XLSX ingest |

---

## Experimental features (WIP)

These are real, tested, and supported — but they are not the headline. The headline is one job: African PII detection grounded in statute.

- **`arche.sign`** — Ed25519 + JWS + did:key signing for `Pipeline.Result` envelopes. Useful when an audit-log entry needs to be portable across trust boundaries.
- **`arche.credentials.sd_jwt`** — SD-JWT-VC issue / verify with selective disclosure. The EUDI Wallet ARF reference format.
- **`arche.workflow.dsar`** — citizen-side DSAR draft generation with per-jurisdiction statute citations. See `examples/03_dsar_workflow.py`.
- **`arche.graph.audit`** — SQLite-backed audit log. PII values never stored.
- **`arche.match`** and **`arche.link`** — lightweight Fellegi-Sunter matcher with jurisdiction-specific priors. Useful for record comparison; for large-scale entity resolution, install `arche-core[resolve]` and feed Splink.
- **`arche.resolve_places`** / **`arche.list_places`** — jurisdictional place lookup with verifiable receipts.

If you need any of these, the SDK has you covered. If you don't, ignore them and use `Pipeline` directly.

---

## What's not in this release

- **No fine-tuned PII model.** The detectors are rule-based + check-digit-validated. Multilingual soft-PII is GLiNER via the `[detect]` extra. Model fine-tuning is post-v1.0 work.
- **No production DPI adapters.** MOSIP / OpenCRVS / DHIS2 integration is Stage 2 work tied to real partner deployments. The v0.2.0a1 scaffolds were deleted in this release for that reason.
- **No MCP server.** The agent-integration surface is downstream of framework adoption.
- **No POPIA / Kenya DPA / Ghana DPA at v1.0.** Those statute YAMLs are v0.1 scaffolds — usable, but pending DPA consultation. NDPA-2023 is the only v1.0 statute today.
- **No address parsing for Kenya or Ghana.** Nigeria and South Africa ship with the MVP parser; KE and GH are next quarter.

---

## Credits

`arche-core` is built by [Unpatterned Labs](https://unpatterned.org) with contributions from the broader African open-source community. The [Pan-African PII Taxonomy](../../datasets/pan-african-pii-taxonomy/v0.1.yaml) is CC-BY-4.0 and welcomes external review.

The 114-group name equivalence lexicon began as Wikidata-linked curation and grows from contributor pull requests. See [`datasets/`](../../datasets/) for the contribution guide.

---

## Links

- **Repository:** https://github.com/unpatterned-labs/arche
- **PyPI:** https://pypi.org/project/arche-core/
- **Issues:** https://github.com/unpatterned-labs/arche/issues
- **Changelog:** [CHANGELOG.md](./CHANGELOG.md)
- **Positioning doc:** `docs/new/arche-core-simplified.md` (internal, source of truth for product positioning)

---

— Dennis Irorere, on behalf of Unpatterned Labs
