# Installation

arche supports Python 3.11 or later on Linux, macOS, and Windows.

```bash
pip install arche-core
python -c "import arche; print(arche.__version__)"
```

The core installation is enough for `compare`, `reconcile`, `dedupe` and `find`. Add `[ledger]` to keep and replay decisions.

## Optional extras

Install an extra only when you need its capability.

| Capability | Install |
|---|---|
| The decision ledger (`arche.attach`) | `pip install "arche-core[ledger]"` |
| Document parsing | `pip install "arche-core[doc]"` |
| OCR for scanned documents | `pip install "arche-core[doc-ocr]"` |
| GLiNER PII detection | `pip install "arche-core[detect]"` |
| Microsoft Presidio integration | `pip install "arche-core[presidio]"` |
| Legacy Splink-backed resolver | `pip install "arche-core[resolve]"` |
| LLM extraction integrations | `pip install "arche-core[llm]"` |

`reconcile()` and `compare()` do not require the `resolve` extra. That extra is for the older Splink-backed resolver path.

## Install from this repository

```bash
git clone https://github.com/unpatterned-labs/arche
cd arche
uv sync --all-packages
uv run pytest packages/arche-core/tests -q
```

The repository is under active alpha development. Pin a released package version for any evaluation that needs to be repeatable.
