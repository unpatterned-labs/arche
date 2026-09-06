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

"""arche's canonical object model.

This module fixes the entity-resolution vocabulary so the object model is the pluggable
spine the whole engine hangs off. It is **additive**: the legacy
``extract.Entity`` mention type keeps working unchanged. New code should prefer
the names here.

The vocabulary (and the name inversion this fixes)::

    Term                 Meaning                              Legacy code
    ─────────────────    ──────────────────────────────────  ──────────────────
    EntityReference      One surface-form mention that        ``extract.Entity``
                         *refers* to an entity.               (INVERTED name)
    Entity               The distinct real-world thing        (0.8.0: none)
                         references resolve *to*.
    Attribute            A property of an entity/reference    scattered fields
                         (name, DOB, address) with value +
                         confidence + provenance.
    IdentityAttribute    The *distinguishing* subset of       ``identifiers``
                         attributes (NIN, BVN, phone, email)  list[dict]
                         that establishes identity.
    ProvenanceCitation   Where an attribute/decision came     ``Detection.
                         from + the law governing it.         regulatory_citation``

The distinction that carries the whole engine: **identity attributes vs
descriptive attributes.** Agreement on a *common* name (a descriptive
attribute) is weak evidence; agreement on a *distinctive* identifier (an
identity attribute) is strong.

Collision resolution
--------------------
``Entity`` is overloaded: ``extract.Entity`` has always meant a *mention*, but
the canonical ``Entity`` is the *resolved thing*. Rather than a risky big-bang
rename, the migration is additive:

* :class:`EntityReference` is the forward name for a mention. ``extract.Entity``
  is aliased to it (``extract.Entity is EntityReference``) so both spellings
  keep working and keep meaning "a reference".
* The canonical resolved :class:`Entity` lives **here**, in ``arche.canonical``,
  and is reached via ``from arche.canonical import Entity``. It deliberately
  does *not* clobber ``extract.Entity`` or ``arche.Entity`` (both still resolve
  to the reference type for backward compatibility).

Usage::

    from arche.canonical import Entity, EntityReference, Reference
    from arche.extract import extract

    refs = extract("Janet Okafor, NIN 12345678901")   # EntityReference[]
    record = Reference.from_mentions(refs)            # one record for the verbs
    person = Entity(canonical_name="Janet Okafor", entity_type="person",
                    references=refs, attributes=[])
    person.identity_attributes     # -> [IdentityAttribute(name='national_id', ...)]
    person.descriptive_attributes  # -> [Attribute(name='full_name', ...)]
    person.regulatory_citations    # -> flattened governing-law citations
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # imported lazily in adapters to avoid import cycles
    from .extract import Entity as _LegacyMention


# ── PII-safe display ─────────────────────────────────────────────────────────
# Mirrors ``extract._PII_TYPES`` so an EntityReference masks the same
# sensitive surface forms in repr/logs. Kept local to avoid an import cycle
# (extract imports this module).
_PII_TYPES = {"PHONE", "EMAIL", "NATIONAL_ID"}


def _mask(text: str, entity_type: str) -> str:
    """Mask PII-sensitive text for safe repr/logging."""
    if entity_type in _PII_TYPES and len(text) > 3:
        return text[:3] + "***"
    return text


# ── Attribute-name taxonomy ──────────────────────────────────────────────────
# Which attribute names are *identity* attributes (distinctive identifiers that
# establish identity) vs descriptive attributes (that describe but don't
# identify). This is the load-bearing distinction of the whole engine.
IDENTITY_ATTRIBUTE_NAMES: frozenset[str] = frozenset({
    "national_id", "nin", "bvn", "ghana_card", "kenya_id", "sa_id",
    "tin", "pvc", "aadhaar", "passport_number", "ssn",
    "phone", "phone_number", "email", "account_number", "swift_bic",
})

# Map a legacy ``Entity.entity_type`` (a MENTION type) onto a canonical
# attribute name for the resolved Entity it contributes to.
_MENTION_TYPE_TO_ATTRIBUTE: dict[str, str] = {
    "PERSON": "full_name",
    "ORGANIZATION": "legal_name",
    "LOCATION": "address",
    "NATIONAL_ID": "national_id",
    "PHONE": "phone",
    "EMAIL": "email",
    "DATE": "date",
    "MONEY": "amount",
}

# Map a mention ``entity_type`` token onto the canonical entity taxonomy:
# person | place | organization | thing.
_ENTITY_TYPE_TO_CANONICAL: dict[str, str] = {
    "PERSON": "person",
    "ORGANIZATION": "organization",
    "LOCATION": "place",
}


def canonical_entity_type(legacy_type: str) -> str:
    """Map a legacy entity_type token to the canonical taxonomy.

    ``PERSON -> person``, ``ORGANIZATION -> organization``,
    ``LOCATION -> place``; anything else is lowercased and treated as a
    ``thing`` subtype (its own lowercase token is returned so no information
    is lost).
    """
    return _ENTITY_TYPE_TO_CANONICAL.get(legacy_type, legacy_type.lower())


def is_identity_attribute_name(name: str) -> bool:
    """True if *name* names a distinguishing identity attribute."""
    return name.lower() in IDENTITY_ATTRIBUTE_NAMES


# Attributes known to be non-PII descriptors — shown by default. Everything not
# here is treated as PII (an allowlist / fail-safe default: an unrecognised
# attribute is masked, never leaked). This is the SINGLE source of truth for the
# PII decision used by ``render`` and ``attest``.
SAFE_DESCRIPTOR_NAMES: frozenset[str] = frozenset({
    # NB: no "nationality" — it is a quasi-identifier in migration/refugee
    # contexts, so it is masked by default like other PII.
    "country", "source_system", "entity_type", "category",
    "jurisdiction", "type", "id_type",
})


def is_pii_attribute(name: str) -> bool:
    """True unless *name* is a known non-PII descriptor (fail-safe allowlist).

    Unlike :func:`is_identity_attribute_name` (only the strong identifiers), this
    also covers quasi-identifiers (name, address, DOB, gender, city, …) and —
    because it is an allowlist — any *unrecognised* attribute, so a field the
    detector doesn't know can never render in the clear by default.
    """
    return name.lower() not in SAFE_DESCRIPTOR_NAMES


# ═════════════════════════════════════════════════════════════════════════════
# Detection-category ↔ attribute vocabulary — the single mapping table shared by
# the Pipeline→Reference bridge and the masking layers.
# ═════════════════════════════════════════════════════════════════════════════

# PII-2 subtypes that identify a PERSON. Only these may feed person-identity
# matching. Category-precise on purpose: the legacy `PII-2-* -> national_id`
# prefix rule would have turned a company registration number (PII-2-RC — a
# public-register value under GDPR) into a person identifier, producing false
# merges and a person entity_id minted from public data.
PERSON_ID_CATEGORIES: frozenset[str] = frozenset({
    "PII-2-NIN", "PII-2-BVN", "PII-2-PVC", "PII-2-DRIVERS_LICENCE",
    "PII-2-GHANA_CARD", "PII-2-NATIONAL_ID", "PII-2-PASSPORT",
    "PII-2-SA_ID", "PII-2-KENYA_ID",
    "PII-2-NID", "PII-2-NIDA", "PII-2-CNI", "PII-2-CNIE", "PII-2-BI",
    "PII-2-KEBELE_ID", "PII-2-SSNIT", "PII-2-NHIF",
})

# NON-person PII-2 subtypes (companies, ambiguous tax ids, unverified digital
# ids). They become plain attributes under their own names — never a person
# identifier, never binding-eligible.
_NON_PERSON_PII2: frozenset[str] = frozenset({
    "PII-2-RC", "PII-2-TIN", "PII-2-KRA_PIN", "PII-2-TAX_REFERENCE", "PII-2-DID",
})

# Explicit category -> canonical attribute name. Categories NOT in this table do
# not enter a resolution Reference at all (special-category PII-6 data, PII-7
# biometric refs, PII-8 device/network identifiers, passwords): they are either
# non-identity or must never ride in a resolution record.
CATEGORY_TO_ATTRIBUTE: dict[str, str] = {
    "PII-1-NAME": "full_name",
    "PII-3-PHONE": "phone",
    "PII-3-EMAIL": "email",
    "PII-4-ADDRESS": "address",
    "PII-4-LOCATION": "location",
    "PII-5-BANK_ACCOUNT": "account_number",
    # person-id subtypes -> their own lowercase attribute name
    **{c: c.rsplit("-", 1)[-1].lower() for c in PERSON_ID_CATEGORIES},
    # non-person subtypes -> their own names (plain attributes, never person ids)
    **{c: c.rsplit("-", 1)[-1].lower() for c in _NON_PERSON_PII2},
}


def attribute_for_category(category: str) -> str | None:
    """Canonical attribute name for a detection ``category`` — or ``None`` when
    the category must not enter a resolution reference."""
    return CATEGORY_TO_ATTRIBUTE.get(category)


# ═════════════════════════════════════════════════════════════════════════════
# ProvenanceCitation — per-field source + governing law
# ═════════════════════════════════════════════════════════════════════════════


@dataclass
class ProvenanceCitation:
    """Where an attribute (or decision) came from, and the law governing it.

    Threads the existing ``Detection.regulatory_citation`` — carried on
    ``Entity.metadata['regulatory_citation']`` by the pipeline — into the
    canonical model as a first-class object, alongside the detector that
    produced the value and the span it came from.

    Edge cases: every field is optional. A citation built from a bare mention
    with no legal annotation carries only ``source`` (the detector); its
    ``regulatory_citation`` is ``""``. This never raises — absence of law is
    represented, not an error.
    """

    source: str = ""              # detector: "gliner", "african", "regex", "llm", "fhir"
    regulatory_citation: str = ""  # governing law, e.g. "NDPA-2023 s.2.2"
    statute_id: str = ""
    statute_version: str = ""
    span: tuple[int, int] | None = None
    document_id: str = ""

    def __repr__(self) -> str:
        law = self.regulatory_citation or "-"
        return f"ProvenanceCitation(source={self.source!r}, law={law!r})"

    @classmethod
    def from_reference(cls, ref: EntityReference) -> ProvenanceCitation:
        """Build a citation from an :class:`EntityReference`'s metadata.

        Reads ``regulatory_citation``/``statute_id``/``statute_version`` off
        the reference metadata (threaded there by the pipeline) plus the
        detector source and span.
        """
        meta = ref.metadata or {}
        return cls(
            source=ref.source,
            regulatory_citation=meta.get("regulatory_citation", ""),
            statute_id=meta.get("statute_id", ""),
            statute_version=meta.get("statute_version", ""),
            span=(ref.start, ref.end),
            document_id=meta.get("patient_id", "") or meta.get("document_id", ""),
        )


# ═════════════════════════════════════════════════════════════════════════════
# Attribute / IdentityAttribute — a property with value + confidence + provenance
# ═════════════════════════════════════════════════════════════════════════════


@dataclass
class Attribute:
    """A property of an entity or reference: value + confidence + provenance.

    ``name`` is the canonical attribute name (e.g. ``full_name``, ``address``,
    ``date_of_birth``). Descriptive attributes describe an entity but don't
    distinguish it; the identifying subset is modelled by
    :class:`IdentityAttribute`.
    """

    name: str
    value: str
    confidence: float = 0.0
    provenance: list[ProvenanceCitation] = field(default_factory=list)
    identifying: bool = False
    # Structured components (e.g. a parsed address's street/city/anchor dict) so
    # bridging from a detector never flattens structure a comparator depends on.
    components: dict | None = None
    # True when the governing statute's policy action for this value was `drop`:
    # the value stays USABLE for matching inside the trust boundary, but must
    # NEVER be disclosed (attest subject claims, SD-JWT disclosures, or
    # render(reveal=...) all refuse it — enforced at those boundaries).
    restricted: bool = False

    def __repr__(self) -> str:
        display = _mask(self.value, self.name.upper())
        kind = "IdentityAttribute" if self.identifying else "Attribute"
        flag = ", restricted=True" if self.restricted else ""
        return (
            f"{kind}(name={self.name!r}, value={display!r}, "
            f"confidence={self.confidence:.2f}{flag})"
        )

    @property
    def regulatory_citations(self) -> list[str]:
        """Ordered, de-duplicated governing-law citations for this attribute."""
        seen: list[str] = []
        for p in self.provenance:
            if p.regulatory_citation and p.regulatory_citation not in seen:
                seen.append(p.regulatory_citation)
        return seen


@dataclass
class IdentityAttribute(Attribute):
    """A distinguishing identity attribute (NIN, BVN, phone, email, …).

    The distinctive subset of :class:`Attribute` that *establishes* identity.
    ``identifying`` defaults to ``True`` here; construction otherwise mirrors
    :class:`Attribute`.
    """

    identifying: bool = True


def make_attribute(
    name: str,
    value: str,
    confidence: float = 0.0,
    provenance: list[ProvenanceCitation] | None = None,
    identifying: bool | None = None,
    restricted: bool = False,
) -> Attribute:
    """Construct an :class:`Attribute` or :class:`IdentityAttribute` by name.

    ``identifying=None`` (the default) keeps today's behaviour exactly:
    dispatch on :data:`IDENTITY_ATTRIBUTE_NAMES`. An explicit ``True``/``False``
    — supplied by a user declaration — overrides the naming convention: the
    declaration wins, which is the point of the declaration layer.
    """
    prov = provenance if provenance is not None else []
    is_identity = (
        is_identity_attribute_name(name) if identifying is None else identifying
    )
    if is_identity:
        return IdentityAttribute(
            name=name, value=value, confidence=confidence, provenance=prov,
            restricted=restricted,
        )
    return Attribute(name=name, value=value, confidence=confidence,
                     provenance=prov, restricted=restricted)


# ═════════════════════════════════════════════════════════════════════════════
# EntityReference — a mention / surface form (forward name for extract.Entity)
# ═════════════════════════════════════════════════════════════════════════════


@dataclass
class EntityReference:
    """One surface-form occurrence that *refers* to an entity.

    This is the canonical, forward-facing name for a mention. It is
    structurally identical to the legacy ``arche.extract.Entity`` (same fields,
    same defaults, same PII-masking repr) — ``extract.Entity`` is aliased to
    this class so both names keep working and keep meaning "a reference".

    Fields mirror the detector output: the surface ``text``, its ``entity_type``
    (PERSON, PHONE, NATIONAL_ID, …), detector ``confidence``, character span
    (``start``/``end``), the producing ``source`` (gliner/regex/african/llm),
    and free-form ``metadata`` (country, id_type, regulatory_citation, …).
    """

    text: str
    entity_type: str
    confidence: float
    start: int
    end: int
    source: str = "regex"
    metadata: dict = field(default_factory=dict)

    def __repr__(self) -> str:
        display = _mask(self.text, self.entity_type)
        return (
            f"EntityReference(text={display!r}, type={self.entity_type!r}, "
            f"confidence={self.confidence:.2f}, source={self.source!r})"
        )

    @property
    def provenance(self) -> ProvenanceCitation:
        """The provenance citation for this single mention."""
        return ProvenanceCitation.from_reference(self)

    # ── adapters ────────────────────────────────────────────────────────────
    @classmethod
    def from_mention(cls, mention: _LegacyMention | EntityReference) -> EntityReference:
        """Adapt a legacy ``extract.Entity`` (or another reference) into an
        :class:`EntityReference`.

        Duck-typed on the mention's fields so it works whether given a legacy
        ``Entity`` or an ``EntityReference``. Because ``extract.Entity`` is
        aliased to this class the round-trip is lossless.
        """
        return cls(
            text=mention.text,
            entity_type=mention.entity_type,
            confidence=mention.confidence,
            start=mention.start,
            end=mention.end,
            source=mention.source,
            metadata=dict(mention.metadata) if mention.metadata else {},
        )

    def to_mention(self) -> _LegacyMention:
        """Adapt this reference back to a legacy ``extract.Entity`` instance.

        Imported lazily to avoid an import cycle (``extract`` imports this
        module). Since ``extract.Entity is EntityReference`` the result is the
        same type; the method exists for explicit, self-documenting round-trips.
        """
        from .extract import Entity as _Mention

        return _Mention(
            text=self.text,
            entity_type=self.entity_type,
            confidence=self.confidence,
            start=self.start,
            end=self.end,
            source=self.source,
            metadata=dict(self.metadata) if self.metadata else {},
        )


# ═════════════════════════════════════════════════════════════════════════════
# Reference — a record: the collection of attribute values ER operates on
# ═════════════════════════════════════════════════════════════════════════════


@dataclass
class Reference:
    """A single record that *refers* to one entity — a collection of attribute
    values.

    This is the **unit of entity resolution**. Where an
    :class:`EntityReference` is one *mention* (a single surface form — e.g. the
    span ``"Fatima"`` inside a sentence), a ``Reference`` is the whole *record*:
    the set of attribute values gathered about one thing
    (``full_name="Fatima Abdullahi"``, ``nin="12345678901"``,
    ``address="12 Ahmadu Bello Way"``). ER is the decision process that judges
    whether two references are to the *same* entity or to *different* ones —
    when they are to the same, they are said to **co-refer**.

    A ``Reference`` obeys the **unique reference assumption**: it is created to
    refer to one, and only one, entity — even when its attribute values look
    ambiguous (the common real-world case). Resolution's job is to recover that
    one entity, not to let a reference fan out to several.

    From a **structured** source a reference already exists as a record
    (:meth:`from_record`). From **unstructured** text it must be assembled by
    *entity reference extraction* — turning detected mentions into attribute
    values (:meth:`from_mentions`). Either way :meth:`as_record` yields the plain
    ``{field: value}`` dict that :func:`arche.resolve.reconcile` compares.
    """

    attributes: list[Attribute] = field(default_factory=list)
    record_id: str = ""
    source_system: str = ""

    def __repr__(self) -> str:
        return (
            f"Reference(id={self.record_id!r}, "
            f"attributes={len(self.attributes)}, "
            f"identity_attrs={len(self.identity_attributes)}, "
            f"source={self.source_system!r})"
        )

    @property
    def identity_attributes(self) -> list[IdentityAttribute]:
        """The distinguishing subset that, *taken together*, identifies the
        entity this reference is to (name + id + address + DOB …)."""
        return [a for a in self.attributes if a.identifying]

    @property
    def descriptive_attributes(self) -> list[Attribute]:
        """The attributes that describe but don't distinguish the entity."""
        return [a for a in self.attributes if not a.identifying]

    def get(self, name: str) -> str | None:
        """The value of the named attribute, or ``None`` if this reference
        carries no value for it."""
        for a in self.attributes:
            if a.name == name:
                return a.value
        return None

    def as_record(self, *, include_restricted: bool = False) -> dict:
        """Flatten to the ``{field: value}`` record that
        :func:`arche.resolve.reconcile` consumes. The ``record_id`` (if any) is
        emitted under the ``id`` key.

        **Fails closed on restricted values**: a plain dict carries no
        restriction metadata, so once flattened a statute-``drop``ped value
        could reach any renderer or egress unguarded. Restricted attributes are
        therefore EXCLUDED by default; pass ``include_restricted=True`` only
        when the record stays inside the trust boundary (matching). An address
        attribute with structured :attr:`Attribute.components` is emitted as a
        ``{"text": ..., **components}`` dict so the landmark anchor survives.
        """
        record: dict = {}
        for a in self.attributes:
            if a.restricted and not include_restricted:
                continue
            if a.name == "address" and a.components:
                record[a.name] = {"text": a.value, **a.components}
            else:
                record[a.name] = a.value
        if self.record_id:
            record.setdefault("id", self.record_id)
        return record

    # ── adapters ────────────────────────────────────────────────────────────
    @classmethod
    def from_record(
        cls, record: dict, *, id_field: str = "id", decl=None,
    ) -> Reference:
        """Build a reference from a plain ``{field: value}`` record — the
        structured-source path, where no extraction is needed.

        ``id_field`` names the record's own identifier (kept as
        :attr:`record_id`, not treated as an attribute). Empty / ``None`` values
        are dropped. Attribute names dispatch through :func:`make_attribute`, so
        identifier fields (nin, bvn, phone, …) become :class:`IdentityAttribute`.

        ``decl`` (an :class:`arche.declare.Declaration`) makes the user's
        annotations win over the naming conventions: declared roles assign
        ``identifying``/``restricted``, ``role: ignore`` fields never enter the
        reference, statute citations attach as provenance, and undeclared
        fields follow the declaration's ``on_unknown`` policy (``allow`` |
        ``warn`` | ``error``) before falling back to today's behaviour.
        Without ``decl`` this method is byte-identical to its previous self.
        """
        if decl is not None and id_field == "id":
            id_field = decl.id_field
        record_id = ""
        attrs: list[Attribute] = []
        for name, value in record.items():
            if value is None or value == "":
                continue
            if name == id_field:
                record_id = str(value)
                continue
            if decl is None:
                attrs.append(make_attribute(name=name, value=str(value)))
                continue
            if decl.ignored(name):
                continue
            identifying = decl.identifying_for(name)
            if identifying is None:  # undeclared field
                if decl.on_unknown == "error":
                    from arche.declare import DeclarationError

                    raise DeclarationError(
                        f"undeclared field {name!r} (declaration "
                        f"{decl.name!r} has on_unknown: error)"
                    )
                if decl.on_unknown == "warn":
                    import warnings

                    warnings.warn(
                        f"field {name!r} is not in declaration {decl.name!r}; "
                        "falling back to built-in conventions",
                        stacklevel=2,
                    )
                attrs.append(make_attribute(name=name, value=str(value)))
                continue
            citation, statute_id = decl.citation_for(name)
            prov = (
                [ProvenanceCitation(source="declaration",
                                    regulatory_citation=citation,
                                    statute_id=statute_id)]
                if citation else []
            )
            attrs.append(
                make_attribute(
                    name=name, value=str(value), provenance=prov,
                    identifying=identifying,
                    restricted=decl.restricted_for(name),
                )
            )
        return cls(attributes=attrs, record_id=record_id)

    @classmethod
    def from_mentions(
        cls,
        mentions: list[_LegacyMention | EntityReference],
        *,
        record_id: str = "",
        source_system: str = "",
    ) -> Reference:
        """Assemble a reference from extracted mentions — the unstructured-source
        path (*entity reference extraction*).

        Each mention's type maps to a canonical attribute name (identifier types
        become :class:`IdentityAttribute`), carrying the mention's confidence and
        provenance onto the attribute. Repeated mentions of the same
        ``(attribute, value)`` merge, accumulating provenance — so three mentions
        of one phone number collapse to a single identity attribute citing all
        three sources.
        """
        by_key: dict[tuple[str, str], Attribute] = {}
        for mention in mentions:
            ref = EntityReference.from_mention(mention)
            attr_name = _MENTION_TYPE_TO_ATTRIBUTE.get(
                ref.entity_type, ref.entity_type.lower()
            )
            key = (attr_name, ref.text)
            citation = ProvenanceCitation.from_reference(ref)
            existing = by_key.get(key)
            if existing is None:
                by_key[key] = make_attribute(
                    name=attr_name,
                    value=ref.text,
                    confidence=ref.confidence,
                    provenance=[citation],
                )
            else:
                existing.provenance.append(citation)
                existing.confidence = max(existing.confidence, ref.confidence)
        return cls(
            attributes=list(by_key.values()),
            record_id=record_id,
            source_system=source_system,
        )

    @classmethod
    def from_detections(
        cls,
        result: object,
        *,
        record_id: str = "",
        source_system: str = "",
    ) -> Reference:
        """Bridge a Pipeline ``Result`` into a canonical reference — the
        compliance-aware structured path (recon plan §3.2).

        Consumes ``result.detections`` (raw values, **pre-egress, inside the
        trust boundary**) with the compliance provenance attached, under four
        hard rules:

        1. **The drop rule (two-boundary model).** A detection whose statute
           policy action was ``drop`` becomes a **``restricted``** attribute:
           still usable for matching (so a true match is never lost to it), but
           never disclosable — ``attest`` and ``render`` refuse it regardless of
           caller flags.
        2. **Category-precise mapping** via :data:`CATEGORY_TO_ATTRIBUTE` — a
           company registration number is never a person identifier; unmapped
           categories (special-category data, device ids, passwords) never
           enter the reference at all.
        3. **Structure survives**: a parsed address's components (landmark
           anchor included) ride on ``Attribute.components``.
        4. **Single-subject contract**: >1 distinct ``PII-1-NAME`` triggers a
           ``UserWarning`` — one reference refers to one entity; a multi-person
           document must be segmented first.
        """
        detections = getattr(result, "detections", None) or []
        outcomes = getattr(result, "policy_outcomes", None) or []
        dropped_ids = {
            o.detection_id for o in outcomes
            if getattr(o, "action", "") == "drop"
        }
        meta = getattr(result, "metadata", None) or {}
        statute_id = meta.get("statute_id") or ""
        statute_version = meta.get("statute_version") or ""
        document_id = getattr(result, "document_hash", "") or ""

        name_spans: list[tuple[int, int, str]] = []
        by_key: dict[tuple[str, str], Attribute] = {}
        for det in detections:
            attr_name = attribute_for_category(det.category)
            if attr_name is None:
                continue  # never rides in a resolution reference
            if det.category == "PII-1-NAME":
                name_spans.append((det.start, det.end, det.text.strip().lower()))
            citation = ProvenanceCitation(
                source=getattr(det, "detector", "") or "pipeline",
                regulatory_citation=getattr(det, "regulatory_citation", None) or "",
                statute_id=statute_id,
                statute_version=str(statute_version or ""),
                span=(det.start, det.end),
                document_id=document_id,
            )
            key = (attr_name, det.text)
            existing = by_key.get(key)
            if existing is None:
                attr = make_attribute(
                    name=attr_name,
                    value=det.text,
                    confidence=float(getattr(det, "confidence", 0.0) or 0.0),
                    provenance=[citation],
                )
                if attr_name == "address" and getattr(det, "metadata", None):
                    attr.components = dict(det.metadata)
                if det.id in dropped_ids:
                    attr.restricted = True
                by_key[key] = attr
            else:
                existing.provenance.append(citation)
                existing.confidence = max(
                    existing.confidence, float(getattr(det, "confidence", 0.0) or 0.0)
                )
                if det.id in dropped_ids:
                    existing.restricted = True

        # Distinct-person heuristic. Detectors split one person's name into
        # adjacent/overlapping detections ("Fatima" + "Abdullahi") and re-detect
        # sub-forms ("Fatima" inside "Fatima Abdullahi") — so first cluster
        # spans with a gap <= 1 char (a space), then merge token-subset repeats.
        name_spans.sort()
        clusters: list[tuple[int, int, set[str]]] = []
        for start, end, text in name_spans:
            toks = set(text.split())
            if clusters and start <= clusters[-1][1] + 1:
                cs, ce, ctoks = clusters[-1]
                clusters[-1] = (cs, max(ce, end), ctoks | toks)
            else:
                clusters.append((start, end, toks))
        distinct: list[set[str]] = []
        for _s, _e, toks in clusters:
            if any(toks <= d or d <= toks for d in distinct):
                continue
            distinct.append(toks)
        if len(distinct) > 1:
            import warnings
            warnings.warn(
                f"from_detections: {len(distinct)} distinct person names in one "
                "document — a Reference refers to ONE entity (unique-reference "
                "assumption); segment multi-person documents before bridging.",
                UserWarning,
                stacklevel=2,
            )

        return cls(
            attributes=list(by_key.values()),
            record_id=record_id or document_id,
            source_system=source_system,
        )


# ═════════════════════════════════════════════════════════════════════════════
# Entity — the distinct real-world thing
# ═════════════════════════════════════════════════════════════════════════════


@dataclass
class Entity:
    """A distinct real-world thing that references resolve *to*.

    Carries a canonical
    name, the entity taxonomy type (``person``/``place``/``organization``/
    ``thing``), the :class:`EntityReference` mentions that were merged, and the
    resolved :class:`Attribute` set — split into distinguishing
    :meth:`identity_attributes` and :meth:`descriptive_attributes`.
    """

    canonical_name: str
    entity_type: str  # canonical taxonomy: person | place | organization | thing
    references: list[EntityReference] = field(default_factory=list)
    attributes: list[Attribute] = field(default_factory=list)
    confidence: float = 0.0
    match_reasons: list[str] = field(default_factory=list)

    def __repr__(self) -> str:
        return (
            f"Entity(canonical={self.canonical_name!r}, type={self.entity_type!r}, "
            f"references={len(self.references)}, "
            f"identity_attrs={len(self.identity_attributes)}, "
            f"confidence={self.confidence:.2f})"
        )

    @property
    def identity_attributes(self) -> list[IdentityAttribute]:
        """The distinguishing identity attributes (NIN, BVN, phone, email, …)."""
        return [a for a in self.attributes if a.identifying]

    @property
    def descriptive_attributes(self) -> list[Attribute]:
        """The non-distinguishing descriptive attributes (name, address, DOB, …)."""
        return [a for a in self.attributes if not a.identifying]

    @property
    def provenance(self) -> list[ProvenanceCitation]:
        """All provenance citations across every attribute of this entity."""
        out: list[ProvenanceCitation] = []
        for a in self.attributes:
            out.extend(a.provenance)
        return out

    @property
    def regulatory_citations(self) -> list[str]:
        """Ordered, de-duplicated governing-law citations for this entity.

        Flattens per-attribute provenance citations.
        """
        seen: list[str] = []
        for a in self.attributes:
            for cite in a.regulatory_citations:
                if cite not in seen:
                    seen.append(cite)
        return seen
__all__ = [
    "ProvenanceCitation",
    "Attribute",
    "IdentityAttribute",
    "EntityReference",
    "Reference",
    "Entity",
    "make_attribute",
    "canonical_entity_type",
    "is_identity_attribute_name",
    "is_pii_attribute",
    "attribute_for_category",
    "CATEGORY_TO_ATTRIBUTE",
    "PERSON_ID_CATEGORIES",
    "SAFE_DESCRIPTOR_NAMES",
    "IDENTITY_ATTRIBUTE_NAMES",
]
