# Resolve people across documents

Documents often contain partial and inconsistent references to the same person:
a bank statement, invoice, and payslip may use different formats, different
name forms, and no shared customer identifier.

The [same person across documents notebook](https://github.com/unpatterned-labs/arche/blob/main/examples/notebooks/02_same_person_across_documents.ipynb)
uses the repository's sample PDFs to run the document path from file discovery
to an inspectable resolution report.

## What the workflow does

```python
from arche import resolve_documents

report = resolve_documents("data/docs/*.pdf", jurisdiction="NG")
print(report.table())
```

The report masks values by default, retains extracted records and decisions, and
shows the evidence behind each verdict. A high score can still be `review` when
the evidence does not justify an automatic identity claim.

## Run it locally

Install document support, then open the notebook from `examples/notebooks` so
its relative paths resolve to the repository data.

```bash
pip install "arche-core[doc]"
cd examples/notebooks
uv run --package arche-core jupyter notebook 02_same_person_across_documents.ipynb
```

The sample PDFs are a demonstration, not a person-resolution benchmark. Review
the extraction results before relying on a linkage decision. Resolution can only
be as reliable as the identifiers and references extracted from the documents.

## Use agents carefully

An agent may prepare document inputs, summarize a masked report, or present a
review candidate to an authorised person. It must not turn `review` into a
match, reveal data outside the approved boundary, or treat a document-derived
decision as independent evidence without checking source provenance.

See the [notebook release evidence](https://github.com/unpatterned-labs/arche/blob/main/examples/notebooks/RELEASE_EVIDENCE.md)
for the execution check and limitations of this example.
