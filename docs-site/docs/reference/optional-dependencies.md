# Optional dependencies

`pip install arche-core` gives you **20 packages** and no machine-learning stack. Everything heavier is an extra you ask for, and this page says what each one costs and what it buys.

The counts below are resolved from scratch with `uv pip compile` against Python 3.12, not estimated. "Added" is over the base wheel.

## The two ways arche reads a document

This is the distinction people trip over most, because both extras read PDFs and they are not interchangeable.

| | `arche-core[pdf]` | `arche-core[doc]` |
|---|---|---|
| **installs** | `pypdf` — BSD-3-Clause, pure Python | `docling` — which pulls `docling-parse`, `pypdfium2`, `torch`, `transformers`, `scipy`, `pandas`, `shapely` |
| **added packages** | **+1** (21 total) | **+92** (112 total) |
| **reads** | the text layer | layout, tables, reading order, optional OCR |
| **entry point** | `arche.extract_text` → `arche.doc.assess_residence` | `arche.doc.parse` → `resolve_documents` |
| **use it when** | you need the words on the page | you need the *structure* of the page |

`[doc]` more than quintuples the install. That is not a criticism of docling — reading a scanned table properly is a machine-learning problem and it solves one. It is a reason to know which of the two you actually need.

The proof-of-address check (`assess_residence`) deliberately sits on the light one. A KYC check that needs a two-gigabyte ML stack to read an energy bill is a check that does not get deployed.

**If you install only `[pdf]` and hand `resolve_documents` a PDF, it raises** rather than returning an empty report. Every document would fail for the same missing parser, and a report of zero records reads as "these documents contain nothing" — which is a different statement from "I could not read them".

Plain text is the exception, and needs neither extra: `.txt` and `.md` are read directly, because a file whose bytes already are its text has nothing for a converter to recover. The provenance records `parser: "text"` rather than `parser: "docling"`, so a decision made from one is still distinguishable from a decision made from the other.

### The AGPL reader

`[pdf]` used to install `pymupdf`, which is **AGPL-3.0**. It now installs `pypdf`, which is BSD-3-Clause; the AGPL reader is still available and now has a name that says so:

```bash
pip install 'arche-core[pdf]'        # pypdf, BSD-3-Clause  (the default)
pip install 'arche-core[pdf-mupdf]'  # pymupdf, AGPL-3.0    (opt in)
```

Both read a text layer well enough for what arche does with one, so the tie is broken on the licence you acquire. Copyleft is a thing to choose on purpose, not to inherit from an extra called `pdf`. `_extract_pdf` prefers `pypdf` and falls back to `pymupdf`, so an existing `[pdf]` environment keeps working.

## Every extra, measured

| extra | added | total | notable dependencies | licence notes |
|---|---:|---:|---|---|
| *(base)* | — | 20 | — | Apache-2.0 |
| `pdf` | +1 | 21 | `pypdf` | BSD-3-Clause |
| `pdf-mupdf` | +1 | 21 | `pymupdf` | **AGPL-3.0** |
| `docx` | +2 | 22 | `python-docx` | MIT |
| `parquet` | +1 | 21 | `pyarrow` | Apache-2.0 |
| `geo` | +3 | 23 | `shapely`, `duckdb` | BSD-3-Clause |
| `llm` | +8 | 28 | `openai`, `anthropic` | Apache-2.0 / MIT |
| `resolve` | +20 | 40 | `splink`, `duckdb`, `pandas` | MIT |
| `detect2` | +24 | 44 | `gliner2[local]`, **torch**, `transformers` | Apache-2.0 |
| `detect` | +24 | 44 | an alias of `detect2` since 0.9.0 | Apache-2.0 |
| `presidio` | +40 | 60 | `presidio-analyzer`, `spacy` | MIT |
| `litellm` | +44 | 64 | `litellm` | MIT |
| `doc` | +92 | 112 | `docling`, **torch**, `transformers` | MIT |
| `doc-ocr` | +96 | 116 | `[doc]` + `rapidocr-onnxruntime` | MIT / Apache-2.0 |

Two things in that table are worth noticing.

**`detect` and `detect2` are the same install.** GLiNER v1 (`gliner` + `onnxruntime`, 31 packages) was removed in 0.9.0; `detect` is kept as a name so an existing install line resolves, and it installs the GLiNER 2 family.

**Three extras pull `torch`**: `detect2` (and its alias), `doc`, `doc-ocr`. If your deployment cannot carry it, those are the ones to avoid, and the base wheel plus `[pdf]`, `[parquet]`, `[geo]` and `[resolve]` still covers record resolution, blocking, addresses, proof of address, Splink -- and the `basic` detector path, which needs no model at all.

## Which backend

One word says what proposes the soft spans -- names the lexicon does not hold, addresses written as prose. The validators, the statute pack and the merge rule run after every one of them, and a checksummed identifier always outranks a model span.

| `backend=` | what runs | extra | download |
|---|---|---|---|
| `basic` | the name lexicon (13,342 names), the address parser, the identifier, phone and email patterns with their checksums and cue gates | none | none |
| `gliner2` | GLiNER 2.5 (`fastino/gliner2.5-base-v1`), the general extractor -- `extract()` only, labels are the caller's | `detect2` | ~0.5 GB |
| `gliner2-pii` | GLiNER2-PII (`fastino/gliner2-privacy-filter-PII-multi`): 42 personal-data labels, seven European languages -- `Pipeline`, `detect_pii`, `deidentify` | `detect2` | ~0.5 GB |
| `auto` | `basic` plus the model when the extra is installed; a one-line notice when it is not | — | — |

`regex` is accepted as a spelling of `basic`. `gliner` (v1) raises and names its replacement.

Measured on the [detection benchmark](benchmarks.md#detection) (a constructed set, 908 spans): `basic` recalls 0.818 at 3 ms a text and finds no dates of birth, bank accounts or passwords, because it has no rule for them; `gliner2-pii` recalls 0.990 at ~0.65 s a text and adds false positives on order numbers the validators do not govern. GLiNER2-PII's own card reports precision 0.35–0.37 on the SPY set with a tendency to over-predict names, which is why it proposes and never decides: a checksummed identifier outranks it, and for a redaction an over-masked name is the cheap failure and a missed identifier the expensive one.

!!! warning "`gliner2[local]`, not `gliner2`"
    The `[local]` marker is load-bearing. Bare `gliner2` installs an **API client that posts text to a hosted service**. Declaring it without `[local]` would ship a code path that looks exactly like on-device extraction while sending text off the machine. `arche-core[detect2]` pins `gliner2[local]`, and a test asserts it.

`arche-core[presidio]` installs Microsoft Presidio's recognisers via `spacy` (+40 packages). It is not yet a `backend=`: the extra installs the packages and nothing in arche calls them. It stays listed because a caller may use Presidio beside arche; it is not a claim that arche does.

## Convenience aliases

| alias | expands to |
|---|---|
| `gliner` | `[detect]`, itself an alias of `[detect2]` |
| `pii` | `[presidio]` |
| `splink` | `[resolve]` |
| `all` | `[pdf,docx,detect,presidio,resolve,llm]` |
| `ng` `ke` `za` `gh` `africa` | nothing — the African detectors are in the **base** wheel |

The country extras are deliberately empty and kept for compatibility. Nigerian, Kenyan, South African and Ghanaian identifier detection needs no dependency, so `pip install 'arche-core[ng]'` installs exactly what `pip install arche-core` does. They exist so that a `requirements.txt` written against an earlier expectation still resolves.

## Reproducing this table

```bash
python - <<'EOF'
import re, subprocess, tempfile, pathlib
for extra in ["", "pdf", "doc", "detect", "detect2", "presidio", "resolve"]:
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

Re-run it when a dependency moves. A number in a document is a claim about the world, and this one goes stale on somebody else's release schedule.
