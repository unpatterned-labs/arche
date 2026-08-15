# Entities: what kind of thing are you resolving?

*Every entity type breaks differently. This is the index to how, and the shared vocabulary underneath.*

---

The engine is one engine. What changes between people, places, products and organisations is not the mathematics, it is **which attributes carry identity and which only look like they do**. Get that wrong and you get confident answers to a question nobody asked.

## The one rule that applies to all of them

From [John Talburt](https://doi.org/10.1016/C2009-0-63396-1), and it sounds obvious until you notice how many systems violate it:

> **Entities do not exist in the information system. They exist in the real world.** Information systems store *references* to entities, never the entities themselves.

A row is not a person. A row is a claim somebody made about a person, using the fields their system had, for their own purposes. Two rows about one thing will disagree, because the two authors wanted different things.

Which is why there is no `Entity` object anywhere in this codebase, no registry of who is who, and why the working object is a `Reference`. arche decides whether two references co-refer and hands you the evidence. It never claims to hold the entity.

## Three jobs an attribute can do

Every page below sorts the fields of a record into the same three groups, because the sorting is what determines the answer.

<div class="arche-attrmap">
<div class="legend">
  <span><i class="k-identity"></i> <strong>carries identity</strong> · agreeing here is real evidence</span>
  <span><i class="k-depends"></i> <strong>conditional</strong> · depends on something you must declare</span>
  <span><i class="k-describes"></i> <strong>describes only</strong> · agreeing here is worth nothing</span>
</div>
</div>

The middle group is where the work is, and it means something different for each entity type. That difference is the reason these are separate pages rather than one.

| Entity | The conditional group is | And the question you must answer first |
|---|---|---|
| [**People**](person-identity.md) | credentials lent by a relationship | who assigned this, and is the relationship still alive? |
| [**Places**](place-identity.md) | geometry and landmarks | is this proposing a candidate, or deciding one? |
| [**Products**](product-identity.md) | size, colour, edition, pack | same at what level: model, item, or batch? |
| **Organisations** | legal form and site-versus-operator | is this the party, or the place the party operates? |

## The four pages

**[Person identity](person-identity.md)** is where the philosophy is unavoidable, because a database is a committed bundle theorist with no substance to hold the attributes together. It covers the three tiers of identity data, why most of your record is borrowed rather than yours, self-sovereign identity and Solid, and the uncomfortable fact that **Customer 360 is the same technical operation as a patient record** with a different beneficiary.

**[Place identity](place-identity.md)** is where space is the trap. Coordinates for one facility routinely sit kilometres apart between surveys, so geometry proposes candidates and is never allowed to decide one. It also carries the address-as-identity-attribute argument and the unaddressed majority.

**[Product identity](product-identity.md)** is where the question itself is malformed until you fix a granularity. Two tins of tomatoes are the same product and two different things, both correctly. Books, food and electronics each break differently, and the differences are shipped as per-category rules rather than one global one.

**Organisation identity** has a shipped [entity pack](../how-to/read-crosswalk-output.md) and no concept page yet. The hard case is already documented in [the join nobody sells](../blog/the-join-nobody-sells.md): a site and the company that operates it share a name *and* a coordinate, so every string and spatial signal points the wrong way at once, and only a declared class refutes it.

## What is not on this list, and why

Naming these because the absences are decisions rather than oversights.

**Flows: lots, consignments, containers.** Two hundred farms' cocoa goes into one container. The question is not *are these the same* but *did this become that*, which is directed and non-symmetric and **not an equivalence relation**. Under commingling, identity genuinely does not survive: the referent becomes a mass balance rather than an object. Treating it as co-reference forces a system either to assert false precision or to collapse into uselessness. This belongs to transformation-event standards, not here. The reasoning is in [sameness and similarity](sameness-and-similarity.md).

**Documents.** A document has an issuer, a subject, and a self-declared origin that is trivially forgeable. That is a provenance ladder rather than a co-reference problem, and it is written up in [who made this document?](../blog/who-made-this-document.md).

**Events, accounts, vessels, works.** Each is a real entity type with its own conditional group, and none has been worked through. A financial account is Tier 2 identity in Durand's sense and expires with its relationship. A vessel has an IMO number that survives renaming and reflagging, which makes it the rare case where a durable identifier actually exists. A creative work versus its editions is the books problem generalised. If one of these is your problem, the vocabulary above should transfer, and we would rather hear that it did not.

## Related

- [The five ER activities](er-activities.md) for Talburt's decomposition and where arche sits against each
- [Sameness and similarity](sameness-and-similarity.md) for why sameness is decided rather than measured
- [What matching looks like](what-matching-looks-like.md) for the failure modes side by side, with real verdicts
