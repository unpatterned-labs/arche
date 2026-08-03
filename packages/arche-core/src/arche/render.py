# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Redact-by-default rendering of resolved records.

:func:`render` turns a :class:`~arche.canonical.Reference` / ``Entity`` / plain
dict into a display dict with **all PII masked by default** — revealed only when
the caller explicitly names the fields. It is the local, in-process twin of the
on-wire SD-JWT ``present(disclose=[...])``: same field vocabulary, masked-by-
default in both.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from arche.canonical import is_pii_attribute

if TYPE_CHECKING:
    from arche.resolve.coreference import CoReferenceDecision

# Map an attribute name to a tokenizer id_type (its canonicalisers are a fixed set).
_TOKEN_ID_TYPE = {
    "phone": "phone", "phone_number": "phone",
    "email": "email",
    "full_name": "name", "name": "name",
}
_ID_LIKE = frozenset({
    "national_id", "nin", "bvn", "ghana_card", "kenya_id", "sa_id",
    "account_number", "passport", "passport_number", "swift_bic",
})


def _token_id_type(name: str) -> str:
    if name in _ID_LIKE:
        return "id"
    return _TOKEN_ID_TYPE.get(name, "text")


def _attributes(obj: Any) -> tuple[dict[str, str], set[str]]:
    """(``{name: value}``, restricted-names) from a Reference/Entity or dict.

    Restricted attributes (statute policy action ``drop``) are tracked so the
    renderer can refuse to reveal them regardless of caller flags.
    """
    attrs = getattr(obj, "attributes", None)
    if attrs is not None:
        values = {a.name: a.value for a in attrs}
        restricted = {a.name for a in attrs if getattr(a, "restricted", False)}
        return values, restricted
    if isinstance(obj, dict):
        return {str(k): str(v) for k, v in obj.items()}, set()
    raise TypeError(f"cannot render {type(obj).__name__!r}; pass a Reference/Entity/dict")


def _mask(name: str, value: str, style: str, key: str | bytes | None) -> str:
    if style == "label":
        return f"[{name.upper()}]"
    if style == "truncate":
        return (value[:3] + "***") if len(value) > 3 else "***"
    if style == "token":
        if not key:
            raise ValueError("style='token' requires a key (keyed masking)")
        from arche._tokens import token
        return token(value, _token_id_type(name), key)
    raise ValueError(f"unknown mask style {style!r}; use 'label', 'truncate', or 'token'")


def render(
    obj: Any,
    *,
    reveal: bool | list[str] = False,
    style: str = "label",
    key: str | bytes | None = None,
) -> dict[str, str]:
    """Render a record with PII masked by default.

    Parameters
    ----------
    reveal:
        ``False`` (default) masks every PII field; ``True`` reveals all; a list
        of attribute names reveals only those. Non-PII fields are always shown.
    style:
        How masked PII is displayed — ``"label"`` (``[NATIONAL_ID]``, the
        default, needs no key), ``"truncate"`` (``123***``), or ``"token"`` (a
        keyed, linkage-preserving token; requires ``key``).
    key:
        Masking key for ``style="token"``. With ``token`` masking, identical
        values render to the same token, so two masked records stay linkable
        without exposing the value.
    """
    reveal_all = reveal is True
    revealed = None if isinstance(reveal, bool) else {n.lower() for n in reveal}

    values, restricted = _attributes(obj)
    out: dict[str, str] = {}
    for name, value in values.items():
        if name in restricted:
            # Statute-`drop`ped value: NEVER revealed, no matter the flags
            # (the two-boundary rule — usable for matching, not for display).
            out[name] = f"[RESTRICTED:{name.upper()}]"
            continue
        if not is_pii_attribute(name):
            out[name] = value
            continue
        shown = reveal_all or (revealed is not None and name.lower() in revealed)
        out[name] = value if shown else _mask(name, value, style, key)
    return out


def resolved_view(
    decision: CoReferenceDecision,
    *,
    reveal: bool | list[str] = False,
    style: str = "label",
    key: str | bytes | None = None,
) -> dict[str, Any]:
    """A joined view of a co-reference decision — the two source records shown
    **together as one resolved entity**.

    Returns the decision (``decision`` = ``same_entity`` / ``review`` /
    ``different``, ``action`` = ``merge`` / ``hold`` / ``no_op``, ``score`` = the
    confidence the two records are the same), the ``entity_id`` that names the
    resolved person (``None`` for a fuzzy-only match), the ``decision_id``, and a
    ``records`` list — one entry per source record, each with its ``reference_id``,
    ``source`` system, and PII-masked (by default) attributes. ``reveal`` / ``style``
    / ``key`` behave exactly as in :func:`render`.
    """
    def _record(ref: Any, ref_id: str) -> dict[str, str]:
        rec = {"reference_id": ref_id, "source": getattr(ref, "source_system", "") or ""}
        rec.update(render(ref, reveal=reveal, style=style, key=key))
        return rec

    return {
        "entity_id": decision.entity_id,
        "decision": decision.identity,
        "action": decision.action,
        "score": decision.score,
        "decision_id": decision.decision_id,
        "records": [
            _record(decision.reference_a, decision.reference_id_a),
            _record(decision.reference_b, decision.reference_id_b),
        ],
    }


def resolved_table(
    decision: CoReferenceDecision,
    *,
    reveal: bool | list[str] = False,
    style: str = "label",
    key: str | bytes | None = None,
) -> list[dict[str, Any]]:
    """The resolved view as **table rows** — one row per source record.

    Leading columns carry the shared entity/decision (``entity_id``, ``decision``,
    ``action``, ``score``), so both rows visibly belong to the same resolved
    entity; then ``source`` / ``reference_id`` and the *union* of the two records'
    attribute columns (a value absent from one record shows as ``""``). PII is
    masked by default. Drop-in for a DataFrame or any table renderer.
    """
    view = resolved_view(decision, reveal=reveal, style=style, key=key)
    attr_cols: list[str] = []
    for rec in view["records"]:
        for col in rec:
            if col not in ("reference_id", "source") and col not in attr_cols:
                attr_cols.append(col)

    rows: list[dict[str, Any]] = []
    for rec in view["records"]:
        row: dict[str, Any] = {
            "entity_id": view["entity_id"],
            "decision": view["decision"],
            "action": view["action"],
            "score": view["score"],
            "source": rec["source"],
            "reference_id": rec["reference_id"],
        }
        for col in attr_cols:
            row[col] = rec.get(col, "")
        rows.append(row)
    return rows


__all__ = ["render", "resolved_view", "resolved_table"]
