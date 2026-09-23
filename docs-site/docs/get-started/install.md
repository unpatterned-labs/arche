# Install

At the end of this page you have `arche` on the command line and `import arche` in Python, and you know which extra to add for the thing you want next.

arche runs on Python 3.11 or later, on Linux, macOS and Windows, on CPU, and offline. The base package is a 3.7 MB wheel with no machine-learning dependency.

```sh
pip install arche-core
arche --version
```

```text
arche 0.9.0
```

That is enough for `compare`, `reconcile`, `detect_pii`, `deidentify`, `resolve_place_request` and `arche studio`. Everything else is an extra you add when you need it.

## Extras

| You want to | Install |
|---|---|
| Keep decisions and replay them (`arche.attach`, `explain`, `replay`) | `pip install "arche-core[ledger]"` |
| Read PDF, DOCX, PPTX, XLSX and HTML | `pip install "arche-core[doc]"` |
| Read scanned pages too | `pip install "arche-core[doc-ocr]"` |
| Find names and addresses the rules do not know (GLiNER2-PII, GLiNER 2.5) | `pip install "arche-core[detect2]"` |
| Hand large batches to Splink (`backend="auto"` above 1,000 records) | `pip install "arche-core[resolve]"` |
| Serve the verbs over HTTP (`arche serve`) | `pip install "arche-core[service]"` |
| Let an agent call them (`arche mcp`) | `pip install "arche-core[mcp]"` |
| Ask an LLM to propose, with arche deciding (`arche.llm`) | `pip install "arche-core[llm]"` |
| The models, Splink, the LLM clients, MCP and the PDF and DOCX readers in one go | `pip install "arche-core[all]"` |

Extras combine: `pip install "arche-core[ledger,doc,detect2]"` is a common first set. The models download once, on first use, to the Hugging Face cache; nothing is sent anywhere. [Extras](../reference/extras.md) has the full table with sizes and licences.

The `[detect2]` extra installs `gliner2[local]`, and the `[local]` marker matters: the bare `gliner2` package is a client that posts text to a hosted service. arche never installs that one.

## From a checkout

For the tests, the benchmarks and the synthetic worlds:

```sh
git clone https://github.com/unpatterned-labs/arche
cd arche
uv sync --all-packages
uv run pytest packages/arche-core/tests -q
```

`uv sync --group full` adds every extra, including the document parsers and both models. The container image in [Docker and deploy](docker.md) is that environment already built.

## Check it works

```sh
arche redact --text "Call Ada on 0803 555 7890" --backend basic
```

```text
arche: the text does not say which jurisdiction governs it, and arche will not
guess: a redaction under the wrong statute looks finished and is not. Pass
jurisdiction=... -- packs exist for AT (GDPR), ... NG (NDPA-2023), ... ZA (POPIA)
```

That refusal is the first thing arche does right. A phone number alone does not say which law applies, so it asks rather than picks. Tell it:

```sh
arche redact --text "Call Ada on 0803 555 7890" --backend basic --jurisdiction NG
```

```text
2 span(s) under NDPA-2023 (NG, basic, statute)  decision_id red:sha256:6fdfe05198...
Call NAME_37f6086c on PHONE_d3100c11
```

Two spans, not one: *Ada* is in the name lexicon, and the statute's rendering for a name is a stable token, so the same person gets the same token in every document.

If that prints, everything on [Five minutes](five-minutes.md) will.
