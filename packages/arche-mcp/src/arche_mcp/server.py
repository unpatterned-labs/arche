# Copyright 2026 unpatterned.org
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""arche MCP server.

Thin registration layer over :mod:`arche_mcp.handlers`. Every tool returns
projections, offsets or ids — never raw PII.

Configuration is a **ceiling, not a default**. Environment variables set the
strictest policy the server will operate under; a per-call argument may narrow
it and cannot widen it. That distinction matters because moving jurisdiction
from a setting to an argument otherwise hands the choice of governing law to
the agent, and an agent that can pick its own statute can pick a weaker one.

  ARCHE_JURISDICTION      ceiling jurisdiction; a call may not override it
  ARCHE_STATUTE           ceiling statute id; a call may not override it
  ARCHE_HASH_KEY          required for guarded_scan; no key, no tokens
  ARCHE_ALLOWED_PROVIDERS comma-separated model-provider allow-list
  ARCHE_TRANSFER_BASIS    declared cross-border transfer basis

With none of them set, jurisdiction becomes a per-call argument and the
intended flow is `infer_jurisdiction` then `plan_protection` then
`guarded_scan`. That is the arrangement for a mixed document stream. Pin the
ceiling when a deployment handles one jurisdiction and an agent has no business
choosing.

Run: ``arche-mcp`` (stdio). HTTP/SSE transport and auth are a follow-up.

NOTE: no ``from __future__ import annotations`` here — the server introspects
the real annotation objects to build tool schemas, and stringized annotations
break it.
"""

import os
from typing import Literal

from arche.resolve import ENTITY_PACK_PURPOSE, ENTITY_PACKS
from mcp.server import MCPServer

from arche_mcp import handlers

# The entity packs, as a schema enum rather than a bare string.
#
# Built from the live `ENTITY_PACKS` so it cannot drift: add a pack and the
# tool schema gains it with no edit here.
#
# This is not cosmetic. Watching a model drive these tools, it called
# `describe_pack(entity="ng")` — a *jurisdiction* code — because the schema
# said `entity: string` and nothing in it said which strings were legal. The
# model had no way to know, guessed from nearby context, and got a runtime
# error it then had to recover from. An enum is the difference between a tool a
# model can use and one it has to discover by failing.
EntityPack = Literal[tuple(sorted(ENTITY_PACKS))]  # type: ignore[valid-type]

# The same packs with each one's purpose, for the tool descriptions.
#
# An enum says which values are legal and nothing about which to pick, and
# picking wrong here is not a harmless error. Asked whether two "General
# Hospital" records were the same *place*, a model chose `organisation` and got
# `match` at distinctive_max 0.862. `place` returns `review` at 0.564, because
# its frequency table knows those are ordinary facility words and the
# organisation table does not. Same engine, same refusal logic, opposite
# answer, decided entirely by a choice the tool surface gave no basis for.
#
# Built from the live purposes so it cannot drift from the packs.
_PACK_MENU = "\n".join(
    f"      {name} - {ENTITY_PACK_PURPOSE[name]}"
    for name in sorted(ENTITY_PACKS) if ENTITY_PACK_PURPOSE.get(name)
)

# `MCPServer`, not `FastMCP`. The MCP Python SDK removed `mcp.server.fastmcp`
# in 2.0 and this code was written against 1.x, which the migration surfaced:
# the package imported cleanly in its old repo only because that repo's lock
# still held an SDK generation behind. The decorator API is unchanged.
mcp = MCPServer("arche", version=handlers._core_version())

_JURISDICTION = os.environ.get("ARCHE_JURISDICTION") or None
_STATUTE = os.environ.get("ARCHE_STATUTE") or None
_HASH_KEY = os.environ.get("ARCHE_HASH_KEY", "")
_ALLOWED_PROVIDERS = (
    [p.strip() for p in os.environ["ARCHE_ALLOWED_PROVIDERS"].split(",") if p.strip()]
    if os.environ.get("ARCHE_ALLOWED_PROVIDERS") else None
)
_TRANSFER_BASIS = os.environ.get("ARCHE_TRANSFER_BASIS") or None


def _jurisdiction(requested):
    """The configured ceiling if there is one, otherwise what was asked for.

    Deliberately not "the argument wins". An operator who pinned this server to
    Nigeria did so to stop anything else happening, and letting a tool call
    replace it would make the setting advisory. When no ceiling is set the
    caller chooses, which is the mixed-stream case this whole flow exists for.
    """
    return _JURISDICTION or requested


def _statute(requested):
    """Same rule as `_jurisdiction`: a pinned statute cannot be argued away."""
    return _STATUTE or requested


# ── orientation ──────────────────────────────────────────────────────────────

@mcp.tool()
def capabilities() -> dict:
    """What this arche installation can actually do: which statutes ship, which
    jurisdictions can be inferred, which entity packs exist, and which optional
    extras are installed. Call this first. It is the difference between "this
    document is clean" and "nothing here could read this document" — several
    tools return empty results rather than errors when an extra is missing."""
    return handlers.capabilities()


@mcp.tool()
def infer_jurisdiction(text: str) -> dict:
    """Work out which jurisdiction governs a document from evidence inside it —
    identifiers, registrars, regulators, currency, phone shapes — and report
    whether a statute pack actually covers the result.

    Returns `country`, `confidence`, `margin`, the `evidence` behind it, and
    `policy_available`. Read `policy_available` before going further: a country
    can be inferred with full confidence and still have no pack, either because
    none ships or because no such law exists (the United States has no omnibus
    federal privacy statute). When it is false, `policy_alternatives` names what
    you can pass explicitly instead.

    Abstains rather than guessing. `abstained: true` means nothing in the
    document said where it came from, which is an answer and not a failure."""
    return handlers.infer_jurisdiction(text)


@mcp.tool()
def plan_protection(jurisdiction: str | None = None,
                    statute: str | None = None) -> dict:
    """Before handing over a document: what could this pipeline find, and what
    could it not?

    Compares the categories a statute governs against the categories the
    installed detectors can emit. `uncovered` means no detector exists for that
    category. `degraded_categories` means one exists and was built for somewhere
    else — a name detector calibrated on West African names runs for the UK and
    misses most British names.

    Expect `partial`. It is the normal answer, including for Nigeria, whose
    statute governs health, religion and biometric categories arche ships no
    detector for. `none` is the one to stop on: it means a clean result would
    mean nothing was looked for."""
    return handlers.plan_protection(
        jurisdiction=_jurisdiction(jurisdiction), statute=_statute(statute))


@mcp.tool()
def describe_pack(entity: EntityPack) -> dict:
    """Which record fields an entity pack reads, how much each one counts, and
    what it does with them.

    Call this before `compare_records` to map your columns. A field the pack
    does not name is IGNORED, not rejected: no error, no warning, no effect on
    the score. Silent and correct, and impossible to diagnose from outside."""
    return handlers.describe_pack(entity)


# ── detection ────────────────────────────────────────────────────────────────

@mcp.tool()
def detect_pii(text: str, jurisdiction: str | None = None) -> dict:
    """Detect personal data as offset spans with category, legal citation and
    sensitivity tier. Returns offsets into the ORIGINAL text, never raw values.

    Carries a `coverage` block. `count: 0` on its own does not mean the document
    is clean — it may mean nothing installed can read this kind of document."""
    return handlers.detect_pii(
        text, jurisdiction=_jurisdiction(jurisdiction), statute=_statute(None))


@mcp.tool()
def detect_entities(text: str, entity_types: list[str] | None = None) -> dict:
    """Detect named entities (people, places, organizations) as typed offset
    spans into the ORIGINAL text.

    Needs a NER backend. Without one this finds pattern-shaped identifiers and
    no personal names at all, and says so in `ner_backend_installed` rather than
    erroring — so check that field before reading an empty result as clean."""
    return handlers.detect_entities(text, entity_types=entity_types)


# ── guarded egress ───────────────────────────────────────────────────────────

@mcp.tool()
def guarded_scan(text: str, jurisdiction: str | None = None,
                 provider: str | None = None, crosses_border: bool = False) -> dict:
    """Redact personal data to deterministic hashed IDs with legal citations,
    fail-closed. The tool to put in front of a model.

    Five refusals, all deny by default: no statute governs this jurisdiction,
    the provider is not allow-listed, a cross-border transfer has no declared
    basis, anything raised, or no installed detector can find a single category
    the statute governs.

    Read `coverage` even when `denied` is false. A clean result from a pipeline
    with no detector for this locale looks identical to a clean document.

    Offsets from `detect_pii` and `extract_places` index the original text and
    do NOT line up with `redacted_text` — replacement tokens are a different
    length. Slicing one with the other can expose an adjacent value.

    The same input value produces the same token across calls, so you can
    correlate an entity across documents without this server storing anything."""
    return handlers.guarded_scan(
        text, key=_HASH_KEY, jurisdiction=_jurisdiction(jurisdiction),
        statute=_statute(None), provider=provider, crosses_border=crosses_border,
        allowed_providers=_ALLOWED_PROVIDERS, transfer_basis=_TRANSFER_BASIS,
    )


# ── resolution ───────────────────────────────────────────────────────────────

def compare_records(list_a: list[dict], list_b: list[dict],
                    entity: EntityPack | None = None,
                    comparators: list[dict] | None = None,
                    threshold: float = 0.7, id_field: str = "id") -> dict:
    """Reconcile two independent record lists into matches with scores and evidence.

    REQUIRED: pass either `entity` (a shipped pack) or `comparators` (your own
    spec). Not both, and not neither.

    CHOOSE THE PACK BY WHAT THE RECORDS ARE, not by what is nearest to hand.
    The pack decides which vocabulary rarity is measured against, so the same
    pair can come back `match` under one pack and `review` under another. Two
    records both called "General Hospital" are `review` under `place` and
    `match` under `organisation`, and only one of those is the right question.

{PACKS}

    Call `describe_pack` first to see which record fields your choice reads.

    For two facility registries, or a register against a survey. Returns ids
    and numeric evidence, never record values.

    A `review` decision is a real answer and usually the interesting one: the
    records agree, and nothing they agree on is distinctive enough to assert a
    match. Two hospitals both called "General Hospital" land here."""
    return handlers.compare_records(
        list_a, list_b, entity=entity, comparators=comparators,
        threshold=threshold, id_field=id_field,
    )


@mcp.tool()
def check_name_equivalence(name_a: str, name_b: str) -> dict:
    """Are two names the same person's, accounting for African name variation
    and transliteration?

    Returns `match`, `review` or `no_match` with the score and the band
    thresholds. `review` means close and not close enough to assert."""
    return handlers.check_name_equivalence(name_a, name_b)


# `{PACKS}` in the docstring above is filled in here, then the function is
# registered. It cannot be done with a docstring concatenation: `"""a""" + x`
# as the first statement is an expression, not a string literal, so Python
# does not treat it as `__doc__` at all and the tool ships with no description.
compare_records.__doc__ = (compare_records.__doc__ or "").replace(
    "{PACKS}", _PACK_MENU)
compare_records = mcp.tool()(compare_records)


# ── places ───────────────────────────────────────────────────────────────────

@mcp.tool()
def extract_places(text: str) -> dict:
    """Extract place mentions from free text with their spatial role (origin /
    destination / location / via / unknown) and the linguistic cue that decided
    it.

    Returns offsets into the ORIGINAL text, cue rule ids, and confidence — never
    the address text; slice the offsets from your own copy. Roles with absent or
    conflicting cues come back as `unknown` at floor confidence rather than
    guessed: an agent that swaps pickup and drop-off has a much worse day than
    one that asks."""
    return handlers.extract_places(text)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
