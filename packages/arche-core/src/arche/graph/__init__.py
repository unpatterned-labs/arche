# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Graph layer - audit log and canonical state.

Per Stage 1 PRD §8.2, the base install ships:

    arche.graph.audit          — SQLite-backed audit log (PRD §8.2)
    arche.graph.networkx_view  — NetworkX adjacency view (PoC / Stage 3 prep)

The full canonical graph store with Person/Organization/Document/Detection/
Provenance/AccessEvent/Consent/Address as first-class node types arrives in
Stage 3 via ``arche-core[graph]`` with Kuzu as the backend.

The audit log is regulator-ready by design:

    - Append-only by convention
    - Document hashes only, never PII values (FR-AUDIT-6)
    - Queryable via SQL or convenience API
    - Compliance report generation (Markdown)
    - Signed export via ``arche.sign`` (tamper-evident bundles for
      regulator handoff)

Public API:
    from arche.graph.audit import AuditLog, AuditEvent

Legacy v0.1 ``build_graph`` is still importable for backward compatibility:
    from arche.graph import build_graph
"""

# Re-export the v0.1 NetworkX surface so existing callers keep working.
# The shim emits DeprecationWarning when accessed via the old top-level
# import paths.
from arche.graph.networkx_view import *  # noqa: F401, F403

# v0.2 surface: the audit log is the primary public capability here.
from arche.graph import audit  # noqa: F401
