# How arche works

arche has related capabilities, but they answer different questions. Keeping
them separate prevents a useful score or extraction from becoming an unsupported
identity claim.

| Capability | Question it answers | Main entry point |
|---|---|---|
| Pipeline | What sensitive or identifying information is in this text or file? | `Pipeline.process()` |
| Document resolution | Which document records may refer to the same person? | `resolve_documents()` |
| Record resolution | Which rows from two lists are candidates for the same entity? | `crosswalk()` |
| Direct person comparison | Do these two specific person references describe one entity? | `pairwise()` |
| Address and spatial roles | What address or place is mentioned, and what role does it play? | `arche.addr`, `extract_places()` |

## The record-resolution path

`crosswalk()` works in four stages:

1. **Candidate generation.** Blocking avoids scoring every possible pair.
2. **Comparison.** Entity-specific comparators inspect names, identifiers,
   coordinates, types, and other available fields.
3. **Decision gate.** Supporting signals can strengthen a candidate, but a
   distinctive signal is required for an automatic `match`.
4. **Evidence artifact.** Each returned edge includes its evidence, run pins,
   and a reproducible `decision_id`.

The result labels are `match` and `review`. Candidates below the review floor
are omitted. A returned score is a decision signal, not a calibrated
probability.

## The maths, stated plainly

Record linkage combines several pieces of evidence. A shared rare identifier is
more informative than a shared common name; a facility type or coordinate can
support the decision but should not create identity by itself.

arche uses comparison scores, thresholds, a review band, and entity-specific
representation data such as frequency tables and vocabularies. The key product
choice is not to collapse every candidate into yes or no. `review` remains a
first-class output when the evidence is insufficient.

For large-scale probabilistic model training and distributed execution, use
Splink. arche's current focus is the representation, evidence, and decision
boundary around a match.

## Pipeline and documents

`Pipeline` processes text or a file for detection and policy handling. It is not
the same as a table crosswalk. `resolve_documents()` composes document parsing,
detection, record assembly, and direct comparisons into a report for a set of
documents.

This distinction matters: a document can be correctly parsed yet still be too
ambiguous to link, and two records can be matchable even when no document
pipeline is involved.

## Addresses are not just strings

`arche.addr` parses addresses, landmarks, and jurisdiction clues. `extract_places()`
also identifies spatial roles such as origin, destination, location, and via.
The role label carries the cue that supported it and returns `unknown` when the
text does not justify a committed role.

Address parsing and place resolution are complementary. Parsing turns text into
structured signals; resolution evaluates whether two records refer to the same
place. Neither alone establishes that an address is authoritative or current.

## Agents and automation

Agents can propose fields, call the API, explain returned evidence, and route
`review` candidates. They should not make an unreviewed identity claim, silently
upgrade a review, or treat an LLM answer as a substitute for provenance.
