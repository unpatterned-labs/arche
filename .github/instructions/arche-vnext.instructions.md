---
applyTo:
  - "packages/arche-core/src/**/*.py"
  - "packages/arche-core/tests/**/*.py"
  - "packages/arche-core/pyproject.toml"
---

# Arche vNext architecture guidance

## North star

Arche is an open runtime for Entity Intelligence: it makes real-world entities reliable enough for humans, software, and AI agents to act on.

```text
Observation → Reference → Candidate Generation → Evidence → Hypothesis → Inference → Uncertainty → Policy → Decision Receipt → Entity Ledger
```

The agentic control plane wraps this kernel. It does not replace it.

## Repository and migration rules

- Keep `unpatterned-labs/arche` and `packages/arche-core` as the canonical runtime.
- Evolve the existing implementation additively. Preserve public APIs unless an accepted migration explicitly changes them.
- Keep `arche-mcp` separate because its interface and runtime lifecycle differ from the SDK.
- Follow `Wrap → measure → migrate`: adapt working algorithms to stable contracts instead of rewriting them.

## Identity and layer invariants

- Observations are immutable. References are not entities. Entity IDs are opaque, stable, source-independent handles.
- Entity IDs never encode names, embeddings, external IDs, model versions, or representation hashes.
- Claims are revisable beliefs. Representations are plural, versioned, replaceable, and derived.
- Keep Representation, Candidate Generation, Evidence, Inference, Uncertainty, and Policy separate.
- Graphs are projections, not canonical identity state.
- Hard identifier conflicts cannot be averaged away. Missing evidence is not refuting evidence. High-risk defaults prefer review or abstention over a false merge.
- Every consequential accepted link must have a Decision Receipt traceable to evidence and provenance.

## Execution and storage

- Keep the reference runtime CPU-first. Use DuckDB, Parquet, Arrow, and CPU for local execution.
- Canonical state is relational/event-based. Graph and vector systems are optional projections or adapters.
- Candidate pairs, not raw row count, are the scale metric. Never default to all-pairs comparison at production scale.
- New research dependencies require a stated baseline, dataset, metric, measured lift, cost, failure modes, and maintenance implications.

## Agentic boundary

- Do not make every record agentic. Route schema/rules → deterministic methods → probabilistic/domain methods → uncertainty → optional LLM planner → human review.
- Agents may select permitted methods or acquire evidence; they never mutate canonical identity state directly.
- Tool outputs become new Observations and return through Evidence → Inference → Policy.
- LLMs, graph engines, GPU execution, new embedding systems, and agent frameworks are optional and benchmark-gated, never core requirements.

## Immediate milestone

M0 establishes stable domain contracts, `ArcheStore`, `arche.attach()`, a DuckDB reference store, a vNext DecisionReceipt, resolution-run metrics, and adapters around the existing resolver. It does not implement the planner, active evidence tools, graph storage, or warehouse execution.
