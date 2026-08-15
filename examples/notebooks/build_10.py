"""Build 10_reconciling_suppliers.ipynb.

    python examples/notebooks/build_10.py
"""

import json
from pathlib import Path

MD, CODE = "markdown", "code"
cells: list[tuple[str, str]] = []


def md(text: str) -> None:
    cells.append((MD, text.strip("\n")))


def code(text: str) -> None:
    cells.append((CODE, text.strip("\n")))


md("""
# Reconciling suppliers across parties

**Cocoa, coffee and tea. One cooperative, three systems, no agreed identifier.**

An EU importer filing a Due Diligence Statement receives farmer and supplier data
from several upstream parties in several formats. The same cooperative appears in
each of them under a different name. Before anything can be filed, those records
have to be joined — and that join is the thing no traceability vendor sells,
because each of them owns one silo and optimises inside it.

This notebook runs that join. It takes about five minutes and needs no
configuration:

```
pip install arche-core
```

By the end you will have produced a reconciliation with evidence on every edge,
seen the one failure case that breaks every signal at once, and understood
exactly which claims the output does and does not support.
""")

md("""
## 1. The three systems

Three real-shaped supplier extracts. Deliberately messy in the ways real ones
are: different legal-form spellings, a site listed where an operator was meant,
a shared generic name, and one party whose only reliable link is a registration
number.
""")

code('''
lbc_ledger = [                      # a licensed buying company's own ledger
    {"id": "L1", "name": "Kuapa Kokoo Cooperative Society",
     "entity_class": "COOPERATIVE", "registration_id": "CS-11420"},
    {"id": "L2", "name": "Sefwi Wiawso Co-operative Society Ltd",
     "entity_class": "COOPERATIVE", "registration_id": "CS-20881"},
    {"id": "L3", "name": "Central Cooperative Society",
     "entity_class": "COOPERATIVE", "registration_id": "CS-33012"},
    {"id": "L4", "name": "Touton Negoce SARL",
     "entity_class": "OPERATOR", "registration_id": "RC-88421"},
    {"id": "L5", "name": "Nyeri Hill Tea Factory Co Ltd",
     "entity_class": "OPERATOR", "lat": -0.42, "lon": 36.95},
]

certifier_registry = [              # a certification scheme's member list
    {"id": "C1", "name": "Kuapa Kokoo Farmers Union",
     "entity_class": "UNION"},
    {"id": "C2", "name": "Sefwi Wiawso Cooperative Society",
     "entity_class": "COOPERATIVE", "registration_id": "CS-20881"},
    {"id": "C3", "name": "Central Cooperative Society",
     "entity_class": "COOPERATIVE", "registration_id": "CS-77901"},
    {"id": "C4", "name": "Touton Negoce",
     "entity_class": "OPERATOR", "registration_id": "RC-88421"},
    {"id": "C5", "name": "Nyeri Hill Factory",
     "entity_class": "SITE", "lat": -0.42, "lon": 36.95},
]

print(f"{len(lbc_ledger)} ledger rows against {len(certifier_registry)} registry rows")
''')

md("""
## 2. One call

`entity="organisation"` selects a comparator pack calibrated for companies,
cooperatives, unions and institutional bodies. There is no model to train and no
configuration to write.
""")

code('''
from arche.resolve import crosswalk

result = crosswalk(lbc_ledger, certifier_registry,
                   entity="organisation", id_field="id")

for edge in result["matches"]:
    print(f"{edge['a_id']} <-> {edge['b_id']}  {edge['decision']:<8} "
          f"score={edge['score']:<7} distinctive={edge['distinctive_max']}")
''')

md("""
## 3. Read the verdicts, not just the count

Three outcomes, and the middle one is the point. `review` is a first-class
answer here — it means the evidence genuinely does not settle the pair, and
saying so beats a confident verdict that happens to be wrong.

Look at each edge with its evidence.
""")

code('''
def explain(edge):
    a = next(r for r in lbc_ledger if r["id"] == edge["a_id"])
    b = next(r for r in certifier_registry if r["id"] == edge["b_id"])
    print(f"  {a['name']}")
    print(f"  {b['name']}")
    print(f"    -> {edge['decision'].upper()}  score={edge['score']}  "
          f"distinctive_max={edge['distinctive_max']}")
    ev = {k: v for k, v in edge["evidence"].items() if isinstance(v, (int, float))}
    print(f"    {ev}\\n")

for edge in result["matches"]:
    explain(edge)
''')

md("""
## 4. The case that breaks every signal at once

Find the `Nyeri Hill` pair above.

`Nyeri Hill Factory` is a tea factory. `Nyeri Hill Tea Factory Co Ltd` is the
company that operates it. They share a name, and they share a coordinate
**exactly**, because one sits on the other.

Watch what the usual moves do here:

- **Name similarity** says match — 0.95.
- **Geography** says match — 0.0 km apart.
- **Stripping the shared legal form**, the standard trick, leaves `Nyeri Hill`
  against `Nyeri Hill Tea`. It makes them *more* alike, not less.

Every signal points the wrong way simultaneously. And merging them would destroy
the link between a plot and the party legally accountable for it, which is the
only thing a due-diligence chain exists to establish.

The one thing that separates them is the declared `entity_class`. Run it with
the class removed and watch the verdict move.
""")

code('''
def strip_class(rows):
    return [{k: v for k, v in r.items() if k != "entity_class"} for r in rows]

site_op_a = [r for r in lbc_ledger if r["id"] == "L5"]
site_op_b = [r for r in certifier_registry if r["id"] == "C5"]

for label, ra, rb in (("with entity_class", site_op_a, site_op_b),
                      ("without entity_class",
                       strip_class(site_op_a), strip_class(site_op_b))):
    r = crosswalk(ra, rb, entity="organisation", id_field="id")
    e = r["matches"][0]
    print(f"  {label:<22} -> {e['decision']:<8} score={e['score']}")
''')

md("""
The class comparator is declared with `weight: 0.0` and `refutes_below: 1.0` — a
pure discriminator. Agreement adds nothing; disagreement demotes to `review`.
And a **missing** class refutes nothing, so a file without the field degrades to
"cannot tell" rather than silently merging.

It is also deliberately *not* a distinctive signal: two records agreeing that
both are a `SITE` is not evidence they are the **same** site.
""")

md("""
## 5. Why identical strings are sometimes not a match

Find the `Central Cooperative Society` pair. The names are byte-identical and
the verdict is still `review`.

`score` says the names agree. `distinctive_max` says agreeing on `Central` is
not evidence of identity — because a **population frequency table** knows how
ordinary that word is across organisation names generally.

Before that table shipped, this pair merged at 1.00. It was the `Central
Dispensary` over-merge, in a new costume.
""")

code('''
from arche.resolve._tokenfreq import TokenFrequencyTable

tf = TokenFrequencyTable.default("organisation")
total = sum(tf._counts.values())

print(f"population-scale table: {len(tf._counts):,} distinct tokens\\n")
for token in ["central", "cooperative", "farmers", "limited",
              "kuapa", "sefwi", "wiawso"]:
    n = tf._counts.get(token, 0)
    print(f"  {token:<12} {int(n):>6}   relative {n / total:.5f}")
''')

md("""
`kuapa`, `sefwi` and `wiawso` sit at zero. That is correct and it is the whole
mechanism: those tokens are what tells one cooperative from another, so they
must stay rare. `central` and `cooperative` are ordinary, so agreeing on them
proves nothing.

**Where those numbers come from, and their limit.** The measured half is built
from GLEIF (CC0) — 52,875 organisation names. But LEI registration follows
financial-market participation, and cooperatives do not register LEIs: GLEIF
lists **51** entities for Côte d'Ivoire, the world's largest cocoa producer, and
counts `farmers` exactly **once** in 52,875 names.

So the table has a second, hand-edited half, `organisation_tokens.yaml`, where
someone who has read a supplier list asserts what the corpus cannot observe.
Editing it is a data change, not a code change.
""")

md("""
## 6. Sign the edges, so someone else can check them

A reconciliation nobody can audit is a spreadsheet with extra steps. Every edge
carries a reproducible `decision_id` hashed over its evidence and the pinned
versions, and can be signed.
""")

code('''
from arche.resolve.reconcile import sign_edges
from arche.sign import generate_keypair, verify as jws_verify
from arche.ids import content_hash

kp = generate_keypair()
signed = sign_edges(result, private_key=kp.private_key, kid=kp.did_key)
print(f"signed {len(signed)} edge(s)\\n")

# Now be the recipient: only the JWS and a public key.
r = jws_verify(signed[0]["jws"], public_key=kp.public_key)
print(f"signature valid={r.valid}  trusted={r.trusted}  source={r.key_source}")

payload = r.payload
body = {k: v for k, v in payload.items() if k != "decision_id"}
pins, schema = body.pop("pins"), body.pop("schema")
recomputed = content_hash({"schema": schema, **body, "pins": pins}, prefix="xwd")
print(f"id recomputed from the evidence matches: "
      f"{recomputed == payload['decision_id']}")
''')

md("""
Two independent checks, and they fail differently. The signature establishes
*who* and *unaltered since signing*. Recomputing the id from the payload — with
the id removed — establishes that the id is the honest address of *this*
evidence, not one lifted from a more favourable decision.

An attacker with their own keypair can always produce a valid signature. What
they cannot do is make the arithmetic agree.
""")

md("""
## 7. What this output does and does not support

The honest part, and the reason to trust the rest.

**Supported.** Every edge carries its evidence, its verdict and a reproducible
id. `review` edges are a work queue with the reasoning attached. Nothing here
required a model, an API key, or a network call.

**Measured.** The organisation pack scores **F1 0.9493** on ER_Magellan
Fodors-Zagats (946 labelled pairs) against a token-sort baseline's 0.8898 —
while cutting false merges from **21 to 4**. Criteria were declared before the
run.

**Not supported.** That benchmark is small, near-saturated, and made of
Anglophone US restaurant listings. **It says nothing about African organisation
names.** No adjudicated African organisation-name dataset exists — including in
this repository, where 259 rows sit staged for adjudication with zero labelled.

Until that changes, treat this as a capability with a measured floor on
English-language business names, and treat any claim about cocoa cooperative
matching accuracy as unevidenced — including ours.

**Where to go next**

- [What matching looks like](https://unpatterned-labs.github.io/arche/concepts/what-matching-looks-like/) — the same failure modes across places, people and products
- [Re-verify a decision](https://unpatterned-labs.github.io/arche/how-to/re-verify-a-decision/) — the full third-party verification path
- [The join nobody sells](https://unpatterned-labs.github.io/arche/blog/the-join-nobody-sells/) — why this problem exists and what is blocking it
""")

nb = {
    "cells": [
        {"cell_type": t, "metadata": {}, "source": (s + "\n").splitlines(True),
         **({"execution_count": None, "outputs": []} if t == CODE else {})}
        for t, s in cells
    ],
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python",
                       "name": "python3"},
        "language_info": {"name": "python", "version": "3.11"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}

out = Path(__file__).resolve().parent / "10_reconciling_suppliers.ipynb"
out.write_text(json.dumps(nb, indent=1), encoding="utf-8")
print(f"wrote {out.name}: {len(cells)} cells "
      f"({sum(1 for t, _ in cells if t == CODE)} code)")
