# arche examples

Copy-paste examples. All but `06_doc_pipeline.py` run with the base install
(`pip install arche-core`); the two ledger examples need `arche-core[ledger]`, and
the MCP chat needs `arche-core[mcp]` and an OpenAI key.

| # | File | What it shows |
|---|---|---|
| 01 | [`01_pipeline_ndpa.py`](01_pipeline_ndpa.py) | The `Pipeline` framework primitive — detection + jurisdiction-aware policy + audit in one call, with auto-loaded NDPA-2023. |
| 02 | [`02_sign_share_extract.py`](02_sign_share_extract.py) | The headline sign-share-extract chain. Issuer signs a document; recipient verifies offline and recovers the redacted text + policy outcomes. |
| 06 | [`06_doc_pipeline.py`](06_doc_pipeline.py) | docling-backed PDF/DOCX ingest → Pipeline → policy → signed export. Requires `pip install arche-core[doc]`. |
| — | [`quick_text_resolution.py`](quick_text_resolution.py) | Three texts, one person, five lines: `compare` with `store=`, then `ledger.entities()`, `explain` and `replay`. Offline, no model download. Walked through in [`notebooks/23_three_texts_one_person.ipynb`](notebooks/23_three_texts_one_person.ipynb). |
| — | [`association_analysis.py`](association_analysis.py) | Mary Smith became Mary Jones: four records, adjacent pairs compared, one entity. `ledger.path` explains why the first and last are one person; `weak_links` says what the entity rests on. Walked through in the docs guide *Keep, explain, replay*. |
| — | [`extract_to_schema.py`](extract_to_schema.py) | Four declarations over four texts: what fills, from where, and what stays unresolved, on `basic` and on `auto`. Walked through in the docs guide *Extract to your schema*. |
| — | [`telehealth_intake.py`](telehealth_intake.py) | The egress guard: a Lagos clinic's intake note, the statute overlay, and what may leave the machine for a model in another country. |
| — | [`mcp_demo.py`](mcp_demo.py) | What an agent gets from `arche mcp`, without an agent: the handlers called in the order a model would call them. |
| — | [`mcp_chat.py`](mcp_chat.py) | The real MCP server over stdio, with a model choosing the tools. Needs `OPENAI_API_KEY`. |
| — | [`identity_knowledge_graph.py`](identity_knowledge_graph.py) | One paragraph to an interactive graph: `extract` (GLiNER 2.5 + basic), ISBN-10 matched to ISBN-13, entities grouped around the people and organisations they sit next to, a NetworkX graph and a standalone vis.js page. |

Run any of them:

```bash
python examples/01_pipeline_ndpa.py
python examples/02_sign_share_extract.py
# ...
```

## Need OCR or document parsing?

Examples here use plain strings. For PDFs / DOCX / scanned forms, install
the `[doc]` extra:

```bash
pip install arche-core[doc]       # PDF, DOCX, PPTX, XLSX (docling-backed)
pip install arche-core[doc-ocr]   # adds RapidOCR for scanned PDFs / images
```

Then use `Pipeline.process_file(path)` instead of `Pipeline.process(text)`.
