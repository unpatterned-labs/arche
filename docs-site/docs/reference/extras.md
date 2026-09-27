# Extras

At the end of this page you know which `pip install "arche-core[...]"` line buys which capability, what each one costs in packages and licence, and which names exist only so an old install line still resolves. `pip install arche-core` is 14 packages and no machine-learning stack; everything heavier is an extra you ask for by name.

```sh
pip install "arche-core[ledger]"          # the base verbs plus a decision ledger
pip install "arche-core[resolve,detect2]" # Splink above the floor, a model in the detection path
```

The package counts below were resolved from scratch with `uv pip compile` against Python 3.12 on 2026-09-20, not estimated. "Added" is over the base wheel's 14. A number in a table is a claim about somebody else's release schedule, so re-run the script at the end when a dependency moves.

| extra | installs | enables | licence | added |
|---|---|---|---|---:|
| *(base)* | `rapidfuzz`, `jellyfish`, `networkx`, `pydantic`, `h3`, `phonenumbers`, `pyyaml`, `cryptography` | `detect_pii`, `deidentify`, `compare`, `reconcile` with arche's own engine, `resolve_place_request`, every African identifier validator, `arche studio`, `arche redact`, `arche compare` | Apache-2.0 | 14 total |
| `pdf` | `pypdf` | the text layer of a PDF: `extract_text`, `arche.doc.assess_residence` | BSD-3-Clause | +1 |
| `pdf-mupdf` | `pymupdf` | the same text layer through the copyleft reader, opt in | **AGPL-3.0** | +1 |
| `docx` | `python-docx` | `.docx` in `extract_text` and `arche redact`; `resolve_documents` reads `.docx` through `[doc]` instead | MIT | +2 |
| `doc` | `docling`, which pulls `torch`, `transformers`, `pandas` | layout, tables and reading order: `arche.doc.parse`, `resolve_documents`, `POST /documents` | MIT | +99 |
| `doc-ocr` | `[doc]` plus `rapidocr-onnxruntime` | scanned pages, through docling's ONNX OCR backend, no tesseract | MIT / Apache-2.0 | +103 |
| `parquet` | `pyarrow` | parquet review packs in `arche.review.read_pack`; CSV and JSONL need nothing | Apache-2.0 | +1 |
| `detect2` | `gliner2[local]`, which pulls `torch`, `transformers` | `backend="gliner2-pii"` for `detect_pii`, `deidentify`, `Pipeline`; `backend="gliner2"` for `extract`; two model downloads of about 0.5 GB each on first use | Apache-2.0 | +26 |
| `detect` | `[detect2]` | the same, under the name an older install line used | Apache-2.0 | +26 |
| `presidio` | `presidio-analyzer`, `presidio-anonymizer`, which pull `spacy` | nothing in arche calls them yet; see below | MIT | +46 |
| `service` | `fastapi`, `uvicorn`, `python-multipart` | `arche serve`: the verbs over HTTP, file upload on `/documents` | MIT / BSD-3-Clause | +9 |
| `mcp` | `mcp` (2.x) | `arche mcp`: the verbs as tools an agent runtime calls, on stdio or streamable HTTP | MIT | +21 |
| `resolve` | `splink`, `duckdb`, which pull `pandas` | `reconcile(backend="splink")`, and `backend="auto"` handing scoring to Splink at 1,000 records and above; about 200 MB | MIT | +20 |
| `ledger` | `duckdb` | `arche.attach("duckdb:///...")`: the decision ledger, `explain`, `replay`, `store=` on every verb | MIT | +1 |
| `runtime` | `[ledger]` | the same, under its earlier name | MIT | +1 |
| `geo` | `shapely`, `duckdb` | polygon joins (`annotate_admin`) and the Overture Places pull; H3 blocking is in the base wheel | BSD-3-Clause, MIT | +3 |
| `llm` | `openai`, `anthropic` | `arche.llm` providers `openai` and `anthropic`; `ollama` needs nothing | Apache-2.0 / MIT | +11 |
| `litellm` | `litellm` | the `litellm` provider, one client for many hosted models | MIT | +50 |
| `ng` `ke` `za` `gh` `africa` | nothing | nothing: the African detectors are in the base wheel | | +0 |
| `all` | `[pdf,docx,detect,presidio,resolve,llm,mcp]` | everything above except `doc`, `doc-ocr`, `pdf-mupdf`, `parquet`, `geo`, `service` and `litellm` | mixed, no AGPL | 108 total |

Three extras pull `torch`: `detect2` (and `detect`), `doc` and `doc-ocr`. If a deployment cannot carry it, those are the ones to leave out, and the base wheel plus `[pdf]`, `[ledger]`, `[resolve]` and `[service]` still covers record resolution, the ledger, proof of address, Splink and the `basic` detector path, which needs no model at all.

A line of Python says which of these an environment has. The output below is from the machine this page was written on, so yours will differ.

```python
import importlib.util

extras = [
    ("ledger", "duckdb"), ("resolve", "splink"), ("detect2", "gliner2"),
    ("doc", "docling"), ("pdf", "pypdf"), ("service", "fastapi"), ("mcp", "mcp"),
]
for extra, module in extras:
    state = "installed" if importlib.util.find_spec(module) else "not installed"
    print(f"{extra:<8} {state}")
```

```text
ledger   installed
resolve  installed
detect2  installed
doc      not installed
pdf      installed
service  installed
mcp      installed
```

## `gliner2[local]`, not `gliner2`

The `[local]` marker on the `detect2` extra is load-bearing. Bare `gliner2` installs an API client that posts text to a hosted service. Declaring it without `[local]` would ship a code path that looks exactly like on-device extraction while sending customer text off the machine. `arche-core[detect2]` pins `gliner2[local]`, the on-device stack, and a test in the suite asserts the marker is there. If you install the model backend by hand rather than through the extra, write the marker yourself.

## `detect` is `detect2`, and GLiNER v1 is gone

`detect` used to install GLiNER v1 (`gliner` with ONNX runtime, 31 packages). That model was removed in 0.9.0. The name is kept so an existing `pip install "arche-core[detect]"` still resolves, and it now installs the GLiNER 2 family: GLiNER 2.5 (`fastino/gliner2.5-base-v1`) as the general extractor behind `extract()`, and GLiNER2-PII (`fastino/gliner2-privacy-filter-PII-multi`), 42 personal-data labels in seven European languages, as the proposer behind `detect_pii`, `deidentify` and `Pipeline`.

The model proposes; it never decides. The validators, the statute pack and the merge rule run after every backend, and a checksummed identifier always outranks a model span. `backend="gliner"` raises and names its replacement.

| `backend=` | what runs | extra |
|---|---|---|
| `basic` | the name lexicon (13,342 entries), the address parser, the identifier, phone and email patterns with their checksums and cue gates | none |
| `gliner2-pii` | GLiNER2-PII proposing, the validators deciding | `detect2` |
| `gliner2` | GLiNER 2.5, `extract()` only, labels are the caller's | `detect2` |
| `auto` | `basic` plus the model when the extra is installed; a one-line notice when it is not | none required |

What the model buys and costs is measured on the [detection benchmark](benchmarks.md#detection): `basic` recalls 0.818 at 4 ms a text and has no rule for dates of birth, bank accounts or passwords; `gliner2-pii` recalls 0.990 at 618 ms a text and adds false positives on order numbers the validators do not govern.

## `resolve`, and the 1,000-record floor

`[resolve]` installs Splink and DuckDB. It is behind an extra because the base wheel is a library, and the pair scoring for a batch under a thousand records does not need a trained model. Two things change once it is installed.

`reconcile(backend="splink", splink_settings=..., threshold=...)` hands the scoring to Splink and keeps everything arche puts around a score: decision ids, pins, evidence, refusal and the review pack. `splink_settings` and `threshold` are required rather than inferred, because a derived configuration orders pairs about as well as a hand-written one and cannot calibrate them.

`backend="auto"`, the default, chooses. Below `AUTO_SPLINK_FLOOR` (1,000 records) it is arche's engine, exactly as without the extra. At the floor and above, when the entity has a shipped recipe that is enabled for auto and the records carry the recipe's columns, it is Splink; otherwise the engine again. The choice and its reason come back as `result["backend"]`, on the result and not in the pins, so no frozen decision id moves. The floor is a measurement: below it the engine makes fewer false merges than Splink, above it the engine's precision turns while Splink's holds. [The size floor](benchmarks.md#the-size-floor) has the four sizes.

## `doc` and `doc-ocr`: two ways to read a document

Both `[pdf]` and `[doc]` read PDFs and they are not interchangeable.

| | `arche-core[pdf]` | `arche-core[doc]` |
|---|---|---|
| installs | `pypdf`, pure Python | `docling`, with `torch`, `transformers`, `pandas` |
| added packages | +1 | +99 |
| reads | the text layer | layout, tables, reading order |
| entry point | `arche.extract_text`, `arche.doc.assess_residence` | `arche.doc.parse`, `resolve_documents` |
| use it when | you need the words on the page | you need the structure of the page |

The proof-of-address check sits on the light one on purpose: a KYC check that needs a two-gigabyte stack to read an energy bill is a check that does not get deployed. If you install only `[pdf]` and hand `resolve_documents` a PDF, it raises rather than returning an empty report, because a report of zero records reads as "these documents contain nothing", which is a different statement from "I could not read them". Plain text needs neither: `.txt` and `.md` are read directly, and the provenance records `parser: "text"` rather than `parser: "docling"`.

`[doc-ocr]` adds `rapidocr-onnxruntime` for scanned pages. It is docling's ONNX OCR backend, chosen because it needs no system tesseract. `[pdf-mupdf]` is the AGPL reader that `[pdf]` used to install; it moved to a name that says what it is, `_extract_pdf` prefers `pypdf` and falls back to `pymupdf`, so an older environment keeps working and simply stops being the one that pulls copyleft.

## `service` and `mcp`: the two front doors that are not Python

`arche studio` needs no extra. It is the standard library's `http.server` and one HTML file, in the base wheel, bound to `127.0.0.1`.

`arche serve` needs `[service]`: the same verbs behind FastAPI for a container, a sidecar or a tool that speaks HTTP. `python-multipart` is what lets `POST /documents` take a file upload. It has no authentication of its own; [Serve over HTTP](../guides/serve-over-http.md) says so and what to put in front of it.

`arche mcp` needs `[mcp]`, new in 0.9.0. The server used to be a second package, `arche-mcp`, with its own release, changelog and a closed pin on `arche-core` that had to be moved by hand every minor. It was one module and an optional import, so it is `arche.mcp` now, behind this extra the way `serve` is behind `service`. The `arche-mcp` command remains for configurations written against the old name. The pin is `mcp>=2.0,<3` because the SDK removed `mcp.server.fastmcp` in 2.0 and the server uses `mcp.server.MCPServer`. [MCP server](../guides/mcp-server.md) is the guide; [MCP tools](mcp-tools.md) lists the tools.

## `ledger` and `runtime`

`[ledger]` is one package, `duckdb`, and it is what `arche.attach("duckdb:///...")` needs: `store=` on any verb, `explain`, `replay`, the review queue and the entities the decisions have linked. The file is on your disk; nothing leaves the machine. `[runtime]` is the earlier name for the same extra and installs the same thing. [Keep, explain, replay](../guides/keep-and-replay.md) is what you do with it.

## `presidio` installs packages nothing calls

`[presidio]` installs Microsoft Presidio's analyzer and anonymizer, and `spacy` beneath them, 46 packages. It is not a `backend=`. The extra installs the packages and nothing in arche calls them: `arche.detect.presidio` is an empty module. It stays listed because a caller may want Presidio beside arche in one environment; it is not a claim that arche uses it.

## `llm` and `litellm`

`[llm]` installs the `openai` and `anthropic` SDKs for the `arche.llm` providers of the same names. A language model is an additional proposer in the same position as GLiNER: it proposes entities and the validators decide, so the output is typed evidence with a validator status whatever the source. The `ollama` provider talks HTTP to a local Ollama and needs no extra. `[litellm]` installs `litellm` for its provider, which fronts many hosted models behind one client; it is the largest extra that does not pull `torch`.

## Names kept for compatibility

| name | installs | since |
|---|---|---|
| `detect` | `[detect2]` | GLiNER v1 removed in 0.9.0 |
| `runtime` | `[ledger]` | earlier name |
| `ng`, `ke`, `za`, `gh`, `africa` | nothing | forward-compatible namespaces, empty |

Both aliases keep working through 1.x.

The v0.1 names `gliner`, `pii` and `splink` were removed at 1.0. They had been aliases since v0.3, no page here used them, and an install command that names one now fails at resolution instead of quietly installing something else. Use `[detect2]`, `[presidio]` and `[resolve]`.

The country extras are empty on purpose. Nigerian, Kenyan, South African and Ghanaian identifier detection needs no dependency, so `pip install "arche-core[ng]"` installs exactly what `pip install arche-core` does. They exist so a `requirements.txt` written against an earlier expectation still resolves, and so a caller can pin to one country's changes if those bundles ever carry something.

## Reproducing the counts

```sh
python - <<'EOF'
import re, subprocess, tempfile, pathlib
for extra in ["", "pdf", "ledger", "service", "mcp", "resolve", "detect2", "presidio", "doc"]:
    spec = f"./packages/arche-core[{extra}]" if extra else "./packages/arche-core"
    with tempfile.NamedTemporaryFile("w", suffix=".in", delete=False) as fh:
        fh.write(spec + "\n"); req = fh.name
    out = subprocess.run(["uv", "pip", "compile", req, "--quiet", "--no-header",
                          "--python-version", "3.12"],
                         capture_output=True, text=True).stdout
    pathlib.Path(req).unlink()
    print(f"{extra or '(base)':<10} {len(re.findall(r'^[A-Za-z0-9_.-]+==', out, re.M)):>4}")
EOF
```

```text
(base)       14
pdf          15
ledger       15
service      23
mcp          35
resolve      34
detect2      40
presidio     60
doc         113
```

## Where to read next

| You want to | Read |
|---|---|
| the install lines in order, with what each one unlocks | [Install](../get-started/install.md) |
| what `backend="auto"` decides and why | [Backends](../how-it-works/backends.md) |
| the numbers behind the floor and the model | [Benchmarks](benchmarks.md) |
| the verbs over HTTP | [Serve over HTTP](../guides/serve-over-http.md) |
| the verbs as tools for an agent | [MCP server](../guides/mcp-server.md) |
