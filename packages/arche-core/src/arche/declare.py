# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The declaration layer — users say what their fields MEAN.

One YAML file names the user's fields and annotates each with arche's fixed
role vocabulary (``identifies | describes | ignore``, plus the orthogonal
``restricted`` axis). From that single artifact arche derives comparators,
masking policy, identity binding, LLM tool-definitions, and a pin that hashes
into every signed decision. In its absence, every code path behaves exactly
as it does without this module (the declaration is additive).

The schema belongs to the user; only the role vocabulary and the decision object are arche's.
Validation is fail-loud with a closed key vocabulary: a typo in a
security-relevant config file that silently means "unrestricted" is the worst
failure this format can have.
"""

from __future__ import annotations

import hashlib
import warnings
from dataclasses import dataclass, field
from pathlib import Path

from arche.ids import _ID_FAMILY as _RESERVED_ID_FAMILIES
from arche.ids import canonical_json

_ROLES = frozenset({"identifies", "describes", "ignore"})
_KINDS = frozenset(
    {"name", "id", "phone", "email", "address", "date", "tftoken", "containment"}
)
# Kinds that participate in Tier-1 identity binding (entity_id minting).
_BINDING_KINDS = ("id", "phone", "email")
_TOP_KEYS = frozenset(
    {"arche_declaration", "name", "version", "entity", "id_field", "statute",
     "jurisdiction", "on_unknown", "tf", "geo", "fields"}
)
_FIELD_KEYS = frozenset(
    {"role", "kind", "weight", "id_family", "statute_class", "restricted",
     "pii", "description"}
)
_GEO_KEYS = frozenset({"lat", "lon", "weight", "decay_km"})
_ON_UNKNOWN = frozenset({"allow", "warn", "error"})
# Kind -> the person-shaped pairwise matcher slot (coreference._FIELD_MAP targets).
KIND_TO_SLOT = {
    "name": "name", "id": "national_id", "phone": "phone",
    "email": "email", "address": "address", "date": "dob",
}


class DeclarationError(ValueError):
    """A declaration failed validation. The message names the offending key."""


@dataclass(frozen=True)
class FieldDecl:
    """One declared field: the user's name plus arche's role annotations."""

    name: str
    role: str
    kinds: tuple[str, ...] = ()
    weight: float = 1.0
    id_family: str | None = None
    statute_class: str | None = None
    restricted: bool = False
    pii: bool = True
    description: str = ""
    # Whether `restricted:` was written explicitly (an explicit `false` may
    # conflict with a statute `drop`; a defaulted False silently unions up).
    restricted_set: bool = False
    # Resolved from the statute at load time (never user-supplied directly).
    citation: str = ""
    action: str = ""


def _err(msg: str) -> DeclarationError:
    return DeclarationError(msg)


def _check_keys(mapping: dict, allowed: frozenset[str], where: str) -> None:
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        raise _err(
            f"{where}: unknown key(s) {unknown} — valid keys: {sorted(allowed)}. "
            "Typos are errors, not warnings: a misspelled key that silently "
            "changes disclosure would fail open."
        )


def _parse_field(name: str, spec: dict) -> FieldDecl:
    if not isinstance(spec, dict):
        raise _err(f"fields.{name}: expected a mapping, got {type(spec).__name__}")
    _check_keys(spec, _FIELD_KEYS, f"fields.{name}")
    role = spec.get("role")
    if role == "restricted":
        raise _err(
            f'fields.{name}: "restricted" is not a role; use `restricted: true` '
            "alongside `role: identifies|describes` (a field can be both "
            "identifying and restricted — that case must stay expressible)."
        )
    if role not in _ROLES:
        raise _err(
            f"fields.{name}: role must be one of {sorted(_ROLES)}, got {role!r}"
        )
    raw_kind = spec.get("kind")
    kinds: tuple[str, ...] = ()
    if raw_kind is not None:
        kinds = tuple(raw_kind) if isinstance(raw_kind, list) else (raw_kind,)
        bad = sorted(set(kinds) - _KINDS)
        if bad:
            raise _err(
                f"fields.{name}: unknown kind(s) {bad} — valid: {sorted(_KINDS)}"
            )
    if role == "identifies" and not kinds:
        raise _err(
            f"fields.{name}: role `identifies` requires a kind — without one the "
            "field would contribute nothing to matching, silently."
        )
    id_family = spec.get("id_family")
    if id_family is not None:
        if "id" not in kinds:
            raise _err(f"fields.{name}: id_family is only valid with kind `id`")
        if id_family in _RESERVED_ID_FAMILIES:
            canonical = _RESERVED_ID_FAMILIES[id_family]
            raise _err(
                f'fields.{name}: id_family "{id_family}" is reserved (it would '
                f'silently alias into the built-in "{canonical}" family and '
                f'cross-link unrelated entities); use "{canonical}" explicitly '
                "or a distinct name."
            )
    return FieldDecl(
        name=name,
        role=role,
        kinds=kinds,
        weight=float(spec.get("weight", 1.0)),
        id_family=id_family,
        statute_class=spec.get("statute_class"),
        restricted=bool(spec.get("restricted", False)),
        pii=bool(spec.get("pii", True)),
        description=str(spec.get("description", "")),
        restricted_set="restricted" in spec,
    )


@dataclass(frozen=True)
class Declaration:
    """A validated user declaration. Construct via :meth:`from_yaml`/:meth:`from_dict`."""

    name: str
    version: str = "0"
    entity: str = ""
    id_field: str = "id"
    statute_id: str | None = None
    jurisdiction: str = "default"
    on_unknown: str = "warn"
    tf: str | None = None
    geo: dict | None = None
    fields: dict[str, FieldDecl] = field(default_factory=dict)
    load_warnings: tuple[str, ...] = ()

    # ── construction ─────────────────────────────────────────────────────────
    @classmethod
    def from_yaml(cls, path: str | Path) -> Declaration:
        import yaml

        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise _err(f"{path}: a declaration must be a YAML mapping")
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: dict) -> Declaration:
        _check_keys(raw, _TOP_KEYS, "declaration")
        if raw.get("arche_declaration") != 1:
            raise _err(
                "declaration: `arche_declaration: 1` is required "
                f"(got {raw.get('arche_declaration')!r}); unknown format "
                "versions are a hard error, not a guess."
            )
        name = raw.get("name")
        if not name or not isinstance(name, str):
            raise _err("declaration: `name` is required (identifies the "
                       "declaration in pins and reports)")
        fields_raw = raw.get("fields")
        if not isinstance(fields_raw, dict) or not fields_raw:
            raise _err("declaration: `fields` is required and must be a "
                       "non-empty mapping of field name -> annotations")
        on_unknown = raw.get("on_unknown", "warn")
        if on_unknown not in _ON_UNKNOWN:
            raise _err(f"declaration: on_unknown must be one of "
                       f"{sorted(_ON_UNKNOWN)}, got {on_unknown!r}")
        geo = raw.get("geo")
        if geo is not None:
            if not isinstance(geo, dict):
                raise _err("declaration: `geo` must be a mapping")
            _check_keys(geo, _GEO_KEYS, "geo")
            if "lat" not in geo or "lon" not in geo:
                raise _err("geo: both `lat` and `lon` field names are required")

        fields = {n: _parse_field(str(n), s) for n, s in fields_raw.items()}

        warns: list[str] = []
        statute_id = raw.get("statute")
        jurisdiction = raw.get("jurisdiction")
        if statute_id:
            fields, statute_jur = _apply_statute(str(statute_id), fields)
            jurisdiction = jurisdiction or statute_jur

        identifying = [f for f in fields.values() if f.role == "identifies"]
        if not identifying:
            warns.append(
                "no field has role `identifies`: every match will be fuzzy-only "
                "and no entity_id can ever be minted from these records."
            )
        id_kind_fields = [f.name for f in identifying if "id" in f.kinds]
        if len(id_kind_fields) > 1:
            warns.append(
                f"fields {id_kind_fields} all map to the single pairwise "
                f"identifier slot; only {id_kind_fields[0]!r} is used on the "
                "pairwise path (crosswalk uses all of them)."
            )
        from arche.canonical import IDENTITY_ATTRIBUTE_NAMES

        collisions = [
            f.name for f in fields.values()
            if f.name.lower() in IDENTITY_ATTRIBUTE_NAMES
            and f.role != "identifies"
        ]
        if collisions:
            warns.append(
                f"fields {collisions} match built-in identity-attribute names "
                "but are not declared `identifies`; the declaration wins at "
                "runtime — confirm this is intentional."
            )

        decl = cls(
            name=str(name),
            version=str(raw.get("version", "0")),
            entity=str(raw.get("entity", name)),
            id_field=str(raw.get("id_field", "id")),
            statute_id=str(statute_id) if statute_id else None,
            jurisdiction=str(jurisdiction or "default"),
            on_unknown=str(on_unknown),
            tf=str(raw["tf"]) if raw.get("tf") is not None else None,
            geo=dict(geo) if geo else None,
            fields=fields,
            load_warnings=tuple(warns),
        )
        for w in warns:
            warnings.warn(f"declaration {decl.name!r}: {w}", stacklevel=2)
        return decl

    # ── the pin (hashes into decision_id) ────────────────────────────────────
    def pin(self) -> str:
        """``name@version:sha256:<16 hex>`` over the *normalized* declaration.

        Hashed from the defaults-applied dict, not the raw file bytes:
        reformatting the YAML or editing a comment must not change a decision
        id; changing a weight must.
        """
        payload = {
            "arche_declaration": 1,
            "name": self.name,
            "version": self.version,
            "entity": self.entity,
            "id_field": self.id_field,
            "statute": self.statute_id or "",
            "jurisdiction": self.jurisdiction,
            "tf": self.tf or "",
            "geo": self.geo or {},
            "fields": {
                f.name: {
                    "role": f.role, "kinds": list(f.kinds),
                    "weight": f.weight, "id_family": f.id_family or "",
                    "statute_class": f.statute_class or "",
                    "restricted": f.restricted, "pii": f.pii,
                }
                for f in self.fields.values()
            },
        }
        digest = hashlib.sha256(
            canonical_json(payload).encode("utf-8")
        ).hexdigest()[:16]
        return f"{self.name}@{self.version}:sha256:{digest}"

    # ── consumers ────────────────────────────────────────────────────────────
    def comparators(self) -> list[dict]:
        """The generated entity pack (``ENTITY_PACKS`` shape) for crosswalk."""
        specs: list[dict] = []
        for f in self.fields.values():
            if f.role != "identifies" and not (f.role == "describes" and f.kinds):
                continue
            for kind in f.kinds:
                if kind == "containment":
                    specs.append({"kind": "containment", "field": f.name,
                                  "weight": f.weight})
                else:
                    specs.append({"field": f.name, "kind": kind,
                                  "weight": f.weight})
        if self.geo:
            spec = {"kind": "geo", "lat": self.geo["lat"], "lon": self.geo["lon"],
                    "weight": float(self.geo.get("weight", 1.0))}
            if "decay_km" in self.geo:
                spec["decay_km"] = float(self.geo["decay_km"])
            specs.append(spec)
        return specs

    def declared(self, name: str) -> FieldDecl | None:
        return self.fields.get(name)

    def ignored(self, name: str) -> bool:
        f = self.fields.get(name)
        return f is not None and f.role == "ignore"

    def identifying_for(self, name: str) -> bool | None:
        """True/False for declared fields; ``None`` = undeclared (caller falls
        back to the built-in naming conventions)."""
        f = self.fields.get(name)
        if f is None or f.role == "ignore":
            return None
        return f.role == "identifies"

    def restricted_for(self, name: str) -> bool:
        f = self.fields.get(name)
        return bool(f and f.restricted)

    def pii_for(self, name: str) -> bool | None:
        """False only when explicitly declared ``pii: false``; ``None`` when
        undeclared (caller falls back to the fail-safe allowlist)."""
        f = self.fields.get(name)
        if f is None:
            return None
        return f.pii

    def kind_for(self, name: str) -> str | None:
        f = self.fields.get(name)
        return f.kinds[0] if f and f.kinds else None

    def slot_for(self, name: str) -> str | None:
        """The person-shaped pairwise matcher slot for a declared field."""
        kind = self.kind_for(name)
        return KIND_TO_SLOT.get(kind) if kind else None

    def binding_fields(self) -> list[tuple[str, str]]:
        """``(field name, id family)`` for identity binding, declaration order
        = priority. Only binding-capable kinds (id, phone, email) qualify."""
        out = []
        for f in self.fields.values():
            if f.role != "identifies":
                continue
            kind = next((k for k in f.kinds if k in _BINDING_KINDS), None)
            if kind is None:
                continue
            family = f.id_family or (f.name if kind == "id" else kind)
            out.append((f.name, family))
        return out

    def citation_for(self, name: str) -> tuple[str, str]:
        """(regulatory_citation, statute_id) for a declared field, or ("", "")."""
        f = self.fields.get(name)
        if f and f.citation:
            return f.citation, self.statute_id or ""
        return "", ""

    # ── the LLM tool-definition generator ────────────────────────────────────
    def json_schema(self) -> dict:
        """JSON Schema for extraction into this declaration.

        ``additionalProperties: false`` stops a model emitting fields outside
        the declaration at decode time; ``required`` is deliberately always
        empty — a required identifier is an instruction to a language model to
        invent one, and missing fields already route to review.
        """
        props = {
            f.name: {"type": "string", **({"description": f.description}
                                          if f.description else {})}
            for f in self.fields.values() if f.role != "ignore"
        }
        return {"type": "object", "additionalProperties": False,
                "required": [], "properties": props}

    def tool_def(self, format: str = "json-schema") -> dict:
        schema = self.json_schema()
        desc = (f"Extract one {self.entity} record. Emit only the declared "
                f"fields; omit anything you cannot find. Declaration: "
                f"{self.pin()}")
        if format == "json-schema":
            return schema
        if format == "anthropic":
            return {"name": self.entity, "description": desc,
                    "input_schema": schema}
        if format == "openai":
            return {"type": "function",
                    "function": {"name": self.entity, "description": desc,
                                 "parameters": schema, "strict": True}}
        raise _err(f"unknown tool-def format {format!r}; "
                   "use json-schema | anthropic | openai")

    def validate_record(self, record: dict):
        """Validate an (LLM-)extracted record against this declaration.

        Returns ``(Reference, violations)`` where violations name every field
        in the record that the declaration does not know.
        """
        from arche.canonical import Reference

        violations = [
            f"undeclared field {k!r}" for k in record
            if k != self.id_field and k not in self.fields
        ]
        ref = Reference.from_record(
            {k: v for k, v in record.items()
             if k == self.id_field or k in self.fields},
            id_field=self.id_field, decl=self,
        )
        return ref, violations


def _apply_statute(
    statute_id: str, fields: dict[str, FieldDecl]
) -> tuple[dict[str, FieldDecl], str]:
    """Resolve statute classes to citations/actions; enforce the union rule."""
    from dataclasses import replace

    from arche.policy import load_statute

    statute = load_statute(statute_id)  # fails loud on an unknown statute
    out: dict[str, FieldDecl] = {}
    for name, f in fields.items():
        if not f.statute_class:
            out[name] = f
            continue
        mappings = getattr(statute, "policy_mappings", {}) or {}
        if f.statute_class not in mappings:
            # action_for() silently falls back to the statute's default action
            # for unknown categories — acceptable for detections, fail-open for
            # a declaration: a typo'd class must not silently mean "default".
            close = sorted(k for k in mappings if k[:6] == str(f.statute_class)[:6])
            hint = f" Did you mean one of {close[:4]}?" if close else ""
            raise _err(
                f"fields.{name}: statute_class {f.statute_class!r} is not in "
                f"statute {statute_id}.{hint}"
            )
        action, citation, _rationale = statute.action_for(f.statute_class)
        must_restrict = action == "drop"
        if must_restrict and f.restricted_set and not f.restricted:
            raise _err(
                f"fields.{name}: declared `restricted: false` but statute "
                f"{statute_id} maps {f.statute_class} to action `drop` "
                f"({citation}). Restriction unions with the statute and can "
                "never be overridden downward."
            )
        out[name] = replace(
            f,
            citation=citation or "",
            action=action or "",
            restricted=f.restricted or must_restrict,
        )
    return out, getattr(statute, "jurisdiction", "") or ""
