# Accuracy and scope

arche is alpha software. A successful example is not evidence that a matching
rule is safe for a new population, domain, or decision.

## What to measure

Evaluate against labelled pairs that represent the data and risks of your use
case. Report at least:

- precision and false merges
- recall and missed matches
- review rate and the outcomes of reviewed cases
- blocking recall, when candidate generation is used
- performance by meaningful slices such as language, region, source system, or
  product category

False merges deserve separate attention. They are often more costly than
missed matches and can compound when pairwise links are clustered.

## Current limits

- A crosswalk score is not a calibrated probability.
- Review thresholds and review capacity must be set for the deployment, not
  inferred from a documentation example.
- The current product lane is experimental. It should not be presented as a
  general product-catalogue solution until it has an independently reproducible
  benchmark.
- No released arche MCP server exists. Agent integrations remain the
  responsibility of the calling system.
- Statute mappings are software artifacts, not legal advice or a determination
  of the law governing a deployment.

## What would make the thesis credible

The central hypothesis is that inspectable representation data, such as
equivalence packs, frequency tables, identifier grammars, and vocabularies,
improves record resolution in the cases where generic comparisons fail.

That hypothesis needs predeclared, independently reproducible evaluations on
the populations it claims to serve. It should be compared with plain string
matching, established probabilistic linkage, and model-assisted matching under
the same candidate set and decision policy.

See [places and products in action](places-and-products.md) for a runnable
place-resolution tour and an evaluation against the public Abt-Buy electronics
benchmark.
