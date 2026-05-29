# Installation

```bash
pip install arche-core
```

Verify:

```bash
python -c "import arche; print('arche', arche.__version__, 'ok')"
# arche 0.2.0a1 ok
```

---

## System requirements

- **Python 3.11+** (3.12 and 3.13 supported)
- Linux, macOS, and Windows
- No GPU required — base install runs entirely on CPU
- No API keys required — works offline

The base install is ~106 MB and includes per-country PII detectors, policy engine, four jurisdiction packs (NDPA-2023, POPIA, Kenya DPA, Ghana DPA), the `Pipeline` framework primitive, `arche.sign` (Ed25519 + did:key + JWS), `arche.credentials.sd_jwt` (SD-JWT-VC), and the SQLite audit log.

No heavy ML/DPI dependencies are loaded by `import arche` — enforced by CI (see `.github/workflows/arche-core-budget.yml`).

---

## Optional extras

The base install is the framework. Heavy capabilities ship as opt-in extras so a Nigerian fintech doesn't pay the cost of an OCR stack they'll never use.

=== "Document ingest"

    ```bash
    pip install arche-core[doc]       # docling — PDF, DOCX, PPTX, XLSX, HTML
    pip install arche-core[doc-ocr]   # adds easyocr for scanned PDFs / images
    pip install arche-core[doc-vlm]   # adds transformers for VLM backends
    ```

    Enables `Pipeline.process_file(path)` for non-text inputs.

=== "Detector backends"

    ```bash
    pip install arche-core[detect]    # GLiNER2-PII via ONNX (~250 MB)
    pip install arche-core[presidio]  # Microsoft Presidio recognizer plug-in
    pip install arche-core[resolve]   # Splink + DuckDB for billion-row ER
    ```

    Soft-PII (`detect`), Western-only PII corpus baseline (`presidio`), and probabilistic entity resolution (`resolve`). All optional — arche's African-context detectors live in the base install.

=== "LLM router"

    ```bash
    pip install arche-core[llm]       # openai + anthropic SDKs
    pip install arche-core[litellm]   # LiteLLM proxy router
    ```

    Powers the LLM-anchored extraction path; not required for any of the headline v0.2 workflows.

=== "Per-country bundles"

    ```bash
    pip install arche-core[ng]        # currently no-op; placeholder
    pip install arche-core[ke]
    pip install arche-core[za]
    pip install arche-core[gh]
    pip install arche-core[africa]
    ```

    Forward-compatible namespaces. All launch-country detectors ship in the base install today; these extras exist so a Nigerian fintech can pin to NG-only changes in v0.3+.

=== "Everything"

    ```bash
    pip install arche-core[all]
    ```

    Pulls `[pdf,docx,detect,presidio,resolve,llm]`. ~1 GB on disk.

---

## Using uv (recommended)

[uv](https://docs.astral.sh/uv/) is a fast Python package manager. Install uv itself first if you haven't:

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
# Windows (PowerShell)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### Pick the right uv command for the job

| You want to… | Use | Result |
|---|---|---|
| Add arche-core as a **project dependency** (writes `pyproject.toml` + `uv.lock`) | `uv add 'arche-core[detect]'` | Pinned in your project; collaborators get the same version |
| Install into the **active environment** ad-hoc | `uv pip install 'arche-core[detect]'` | Works inside any active venv / conda env, no project file edits |
| **Run once** without polluting any environment | `uvx --from 'arche-core[detect]' python -m my_script` | Ephemeral env; deps disappear after the process exits |
| Install as a **global CLI tool** with extras | `uv tool install 'arche-core[detect]'` | `arche` (when v0.2.0a2 ships the CLI back) available everywhere |
| Develop **inside this monorepo** | `uv sync --all-packages` | Resolves the whole workspace including arche-core, arche-graph, arche-live |

!!! warning "Shell quoting"

    The `[extra]` syntax must be **quoted** in zsh, bash, and fish — unquoted brackets are interpreted as glob patterns and either silently expand to nothing or error out.

    ```bash
    uv add 'arche-core[detect]'          # ✓ all shells
    uv add "arche-core[detect]"          # ✓ all shells
    uv add arche-core[detect]            # ✗ zsh: "no matches found"
    ```

    PowerShell does not need the quotes but accepts them.

### Installing with extras

The base install (no extras) is the framework only. Each extra layers on optional capabilities. Combine multiple in one bracket pair:

```bash
# One extra
uv add 'arche-core[detect]'                # GLiNER soft-PII (~250 MB)
uv add 'arche-core[doc]'                   # docling for PDF / DOCX / PPTX / XLSX / HTML
uv add 'arche-core[presidio]'              # Microsoft Presidio recognizer plug-in
uv add 'arche-core[resolve]'               # Splink + DuckDB (billion-row ER)
uv add 'arche-core[llm]'                   # openai + anthropic SDKs
uv add 'arche-core[litellm]'               # LiteLLM proxy router

# Several at once — single resolve, one transaction
uv add 'arche-core[detect,doc]'
uv add 'arche-core[detect,doc,llm]'

# The convenience superset — pdf, docx, detect, presidio, resolve, llm
uv add 'arche-core[all]'

# Deprecated v0.1 names still resolve (with a DeprecationWarning):
uv add 'arche-core[gliner]'                # → use [detect] in v0.3
uv add 'arche-core[pii]'                   # → use [presidio] in v0.3
uv add 'arche-core[splink]'                # → use [resolve] in v0.3
```

### Workspace development (this monorepo)

```bash
git clone https://github.com/Plehthore/arche
cd arche
uv sync --all-packages
uv run pytest packages/arche-core/tests
```

`uv sync --all-packages` resolves the workspace's full dependency graph including arche-core, arche-graph, arche-adapters, and the api / demo members. Extras defined inside each member's `pyproject.toml` are part of the resolve.

To add an extra at sync time without editing pyproject:

```bash
uv sync --all-packages --extra detect
uv sync --all-packages --extra detect --extra doc
uv sync --all-packages --all-extras                 # pull every extra of every member
```

To run a one-off command with the extras available:

```bash
uv run --extra detect python -c "from arche.extract import extract; print(extract('Jane at +234 803...', backend='gliner'))"
```

### Picking the right extra for your use case

| Use case | Install |
|---|---|
| Resolve names + IDs from text (Pan-African PII Taxonomy) | base install — nothing extra needed |
| Run on PDFs / DOCX / scanned invoices | `uv add 'arche-core[doc]'` (add `[doc-ocr]` for image PDFs) |
| Soft-PII / job-titles / orgs / unknown places via NER | `uv add 'arche-core[detect]'` |
| Western PII corpora baseline (US SSN, IBAN, etc.) | `uv add 'arche-core[presidio]'` |
| Million-row entity resolution / dedup | `uv add 'arche-core[resolve]'` |
| LLM-anchored extraction with provider fallback | `uv add 'arche-core[llm]'` |
| Everything at once (~1 GB) | `uv add 'arche-core[all]'` |

---

## What's next

- [Quick Start](quickstart.md) — five minutes from install to a signed
  redacted document.
- [Sign, share, extract tutorial](../tutorials/sign_share_extract.md) —
  the headline verifiability workflow.
<!-- - [Citizen DSAR tutorial](../tutorials/citizen_dsar.md) — generate a
  signed Data Subject Access Request letter. -->
