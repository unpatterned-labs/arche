# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The ledger arm (B9 S5) — resolution as records arrive, not as a batch.

Every other arm is handed all 1,198 records at once and asked which are the
same. That is not how a vendor master is built. Records arrive over years: the
ERP row is typed in 2019, the registry is checked in 2022, an invoice is filed
in 2025, and in between the supplier moves. So this arm feeds the world into
:func:`arche.attach`'s ledger **in `observed_at` order**, calling
``resolve()`` on each new record against everything already stored, and reads
the entities the ledger has formed at the end.

Why this is the arm that matters. S3 measured `arche/pack` at **0.088 recall on
relocated suppliers** with **0.978 coverage** -- it is not missing them, it is
refusing them, because the `organisation` pack's `premises` comparator is
declared ``refutes_below: 0.5`` and a wholly changed address demotes the pair
to `review`. The question this arm asks is whether the ledger's second
mechanism -- evidence arriving later, decisions superseded rather than
overwritten -- recovers what the one-shot batch comparison declines.

Two variants are measured and reported separately, because one of them uses an
outside lookup and the other does not:

``arche/ledger``
    Pure incremental resolution. No oracle, no truth, nothing the records do
    not already carry.

``arche/ledger+observe``
    The same, then the operator's move: for each pair the ledger left open,
    look up the **registry record carrying the same RC number** and feed its
    address in with ``observe()``. That is a real workflow -- an open case
    sends somebody to the companies register -- and it uses an identifier
    present in the data rather than the answer key. It is still an *assisted*
    number and is labelled as one: two records sharing an RC number are
    already strong evidence of one supplier, so this measures whether
    ``observe`` propagates and re-decides correctly, not whether arche can find
    the link unaided.
"""

from __future__ import annotations

import time
from typing import Any

from arche_synthetic.evaluate import Predictions, pair
from arms import _as_arche_record

#: Our record id, carried through the ledger as an ordinary attribute so the
#: entities it forms can be mapped back. `resolve` drops the `id_field`, and
#: the `organisation` pack declares `ignores_everything_else`, so an extra
#: column is stored and never compared.
PASSTHROUGH = "source_record_id"


def _record(observation: dict[str, Any]) -> dict[str, Any]:
    return {**_as_arche_record(observation),
            PASSTHROUGH: observation["record_id"]}


def _clusters(book, entity_type: str = "organisation") -> list[list[str]]:
    """The ledger's entities, in our record ids."""
    out = []
    for view in book.entities(entity_type):
        members = [r.attributes.get(PASSTHROUGH) for r in view.records]
        members = [m for m in members if m]
        if members:
            out.append(members)
    return out


def _pairs(clusters: list[list[str]]) -> set[tuple[str, str]]:
    """Every within-cluster pair: the ledger's positive claims, at entity level.

    The ledger links transitively -- A matched B and B matched C groups all
    three -- so its claim is the entity, and the pairwise form of that claim is
    the clique. `held_together_by` records which clusters were never fully
    compared; that is reported in the notes rather than silently flattened.
    """
    out: set[tuple[str, str]] = set()
    for members in clusters:
        members = sorted(members)
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                out.add(pair(a, b))
    return out


def ledger_arm(observations: list[dict[str, Any]], *, observe: bool = False,
               entity_type: str = "organisation",
               truth_pairs=None) -> Predictions:
    """Ingest in arrival order; optionally run the operator's lookup afterwards."""
    import arche

    ordered = sorted(observations, key=lambda o: (o["observed_at"], o["record_id"]))
    started = time.perf_counter()
    notes: dict[str, Any] = {"ingested_in": "observed_at order",
                             "records": len(ordered)}

    with arche.attach("duckdb:///:memory:") as book:
        for observation in ordered:
            book.resolve(_record(observation), entity_type=entity_type)
        notes["open_cases_after_ingest"] = len(book.cases(entity_type))

        if observe:
            notes.update(_observe_pass(book, ordered, entity_type))

        clusters = _clusters(book, entity_type)
        held = [v.held_together_by for v in book.entities(entity_type)]

    seconds = time.perf_counter() - started
    notes["clusters"] = len(clusters)
    notes["transitive_clusters"] = sum(1 for h in held if h == "transitive")
    return Predictions(
        arm="arche/ledger+observe" if observe else "arche/ledger",
        pairs=_pairs(clusters), clusters=clusters, seconds=seconds, notes=notes)


def _observe_pass(book, ordered: list[dict[str, Any]],
                  entity_type: str) -> dict[str, Any]:
    """The operator's move: an open case sends somebody to the register.

    For each still-open case, find the **registry** record sharing the RC
    number of one of its records and feed that record's address in. The lookup
    key is an identifier the data carries, never the truth mapping -- but it is
    still an assisted result, because two records sharing an RC number are
    already strong evidence, and the number is labelled accordingly.
    """
    by_rc: dict[str, dict[str, Any]] = {}
    for observation in ordered:
        if observation["source"] == "registry" and observation.get("rc_number"):
            by_rc[observation["rc_number"].upper()] = observation

    looked_up = observed = 0
    for case in book.cases(entity_type):
        # `Case.record_a` / `.record_b` are Record objects, not ids.
        for record in (case.record_a, case.record_b):
            if record is None:
                continue
            rc = (record.attributes.get("registration_id") or "").upper()
            authority = by_rc.get(rc)
            if not authority:
                continue
            looked_up += 1
            address = ", ".join(
                x for x in (authority.get("address"), authority.get("city")) if x)
            if address and address != record.attributes.get("address"):
                book.observe(record.record_id, {"address": address})
                observed += 1
            break
    return {"cases_with_a_registry_lookup": looked_up,
            "records_updated_by_observe": observed,
            "open_cases_after_observe": len(book.cases(entity_type)),
            "assisted": ("addresses were re-fetched from the registry record "
                         "sharing each record's RC number; an identifier in the "
                         "data, not the answer key, but an assist")}


def arche_ledger(observations, truth_pairs=None) -> Predictions:
    return ledger_arm(observations, observe=False)


def arche_ledger_observe(observations, truth_pairs=None) -> Predictions:
    return ledger_arm(observations, observe=True)


__all__ = ["PASSTHROUGH", "arche_ledger", "arche_ledger_observe", "ledger_arm"]
