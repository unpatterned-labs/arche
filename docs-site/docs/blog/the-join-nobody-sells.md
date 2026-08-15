# The join nobody sells

*On cocoa, coffee, tea, and the record-matching problem that sits underneath supply-chain compliance. What we built, what it measures, and the three things currently blocking it.*

---

An EU importer filing a Due Diligence Statement is personally accountable for it. Fines reach 4% of turnover; product gets seized at the port. To file, they assemble an account of where a commodity came from out of records produced by parties who have never agreed on identifiers — a licensed buying company's spreadsheet, a certifier's registry, an exporter's ERP, six upstream suppliers in six formats.

The same cooperative appears in all of them under different names. Nobody sells the join.

That last sentence is the thesis, and this post is partly about how nearly it is wrong.

## The status quo is not "nothing"

It is a funded, crowded field. Meridia, TraceX, Koltiva, Farmerline, Satelligence, plus the certification schemes — Rainforest Alliance, Fairtrade, ARS-1000. They sell polygon mapping, farmer registries, and DDS generation, and they sell it well.

What none of them sells is reconciliation *across* them. Each vendor owns a silo and optimises inside it, which is a rational thing to build and leaves the join to the compliance lead and a spreadsheet.

Ask why, and the answer is more interesting than "nobody thought of it." **The industry has an answer to mismatched identifiers, and it is standardisation.** GS1 gives you GTINs for products, GLNs for locations, SSCCs for logistics units; EPCIS carries the events; the UN Transparency Protocol sits above them. It is well-designed and it works.

It works when parties can be compelled to adopt a scheme. Retail, pharma, batteries, textiles — the UNTP pilot domains — are exactly those.

Ghana has 800,000+ cocoa smallholders with no digital records and no formal land titles. They cannot be compelled to adopt anything.

**At the smallholder edge, reconciliation is not a degraded substitute for standardisation. It is the only mechanism that runs.** That is the gap, stated more precisely than "nobody sells the join," and it is narrow enough to be worth something.

## What the problem actually looks like

Three commodities, and the structure repeats. The node where the commodity is aggregated and a lot first acquires an identity differs — a **society** for cocoa, a **washing station** for coffee, a **factory or estate** for tea — but its shape does not: a named site, operated by a legal entity, aggregating from many smallholders.

Which means one capability covers all three, and a cocoa-specific data model would have been a mistake.

Here is what the matching looks like. Every verdict below came from running the pair, not from writing it down.

<details class="arche-examples" open>
<summary>The four cases that decide whether this works</summary>
<div class="arche-pairs">
<div class="pair review">
  <div class="pair-records">
    <code>Kuapa Kokoo Cooperative Society</code>
    <code>Kuapa Kokoo Farmers Union</code>
  </div>
  <div class="pair-verdict">review</div>
</div>
<p class="pair-why"><strong>name 1.00 · tftoken 1.00</strong> — strip the legal form and the names are <em>identical</em>. A society and the union above it are different parties, and nothing in the strings says so.</p>
<div class="pair review">
  <div class="pair-records">
    <code>Nyeri Hill Factory                (site)</code>
    <code>Nyeri Hill Tea Factory Co Ltd     (operator)</code>
  </div>
  <div class="pair-verdict">review</div>
</div>
<p class="pair-why"><strong>name 0.95 · geo 1.00 at 0.0 km</strong> — the site and the company operating it share a name <em>and</em> a coordinate. Every string and spatial signal points the wrong way at once.</p>
<div class="pair match">
  <div class="pair-records">
    <code>Sefwi Wiawso Cooperative Society</code>
    <code>Sefwi Wiawso Co-operative Society Ltd</code>
  </div>
  <div class="pair-verdict">match</div>
</div>
<p class="pair-why"><strong>score 1.00</strong> — two spellings of one legal form; both reduce to <code>sefwi wiawso</code>.</p>
<div class="pair review">
  <div class="pair-records">
    <code>Central Cooperative Society</code>
    <code>Central Cooperative Society</code>
  </div>
  <div class="pair-verdict">review</div>
</div>
<p class="pair-why"><strong>score 1.00, distinctive_max 0.59</strong> — byte-identical, and still not a merge. Agreeing on <code>Central</code> is not evidence of identity.</p>
</div>
</details>

Two of those four are the same failure wearing different clothes, and it is the one that decides whether any of this is usable.

## A site is not its operator

`Nyeri Hill Factory` is a tea factory in Nyeri County. `Nyeri Hill Tea Factory Co Ltd` is the company that operates it. They share a name. They share a coordinate exactly, because one sits on the other. They are different legal parties, and merging them destroys the link between a plot and the entity accountable for it — which is the only thing a due-diligence chain exists to establish.

Now notice what does *not* help. Stripping the shared legal form, the standard move, leaves `Nyeri Hill` against `Nyeri Hill Tea`: **more** similar, not less. Geography is worse than useless because the distance is zero. Every signal a name matcher has points the wrong way simultaneously.

The only thing that separates them is a declared entity class, and it has to *refute* rather than merely score — weighted at zero, so agreement adds nothing and disagreement demotes to review. It has to be missing-value-safe, so a file without the field degrades to "cannot tell" instead of silently merging. And it must never count as a distinctive signal, because two records agreeing they are both a `SITE` is not evidence they are the *same* site.

Writing that down took a day and was worth more than the code. The definition it belongs to — six entity classes, four outcomes, ten named failure cases — is the artifact a competitor cannot derive by reading the source.

## What is measured

The organisation lane ships with a first number, against criteria written down *before* the run, on ER_Magellan Fodors-Zagats (946 labelled pairs):

| | precision | recall | F1 | false merges | missed |
|---|---|---|---|---|---|
| **organisation pack** | 0.9626 | 0.9364 | **0.9493** | **4** | 7 |
| person pack | 0.9863 | 0.6545 | 0.7869 | 1 | 38 |
| token-sort baseline | 0.8333 | 0.9545 | 0.8898 | 21 | 5 |

The token-sort row is the one that matters: **+0.0595 F1 while cutting false merges from 21 to 4.** Beating the person pack only shows the pack is genuinely calibrated rather than renamed.

**Now the caveats, which are larger than the result.** 946 pairs is small. The set is near-saturated — published learned baselines report ~100 F1 on it. And it is Anglophone US restaurant listings. **It says nothing whatsoever about African organisation names**, and we will not cite it as if it did.

## Three constraints, named

**1. There is no adjudicated African organisation-name data. Anywhere.**

Not "we haven't got to it." It does not exist. Our own facility crosswalk holds 259 rows staged for adjudication with **zero labelled**, and the Kano sample is drawn only from pairs arche already called `match` — so even fully labelled it could measure precision-on-predicted-matches and never a miss.

We know what that costs, because we have already paid it once. When a benchmark with a complete mapping first arrived, measured precision was **0.85 against the ~0.95 the recall figures had implied.**

The fix is 150–300 stratified, adjudicated pairs including negatives, with two annotators. That is adjudicator time, and no amount of compute substitutes for it.

**2. The benchmark that would settle this costs money.**

OpenSanctions Pairs is 755,540 analyst-labelled pairs across 293 sources and 31 countries, organisations and persons separated, cross-script names. It is this problem, at scale, already labelled. It is **CC-BY-NC**, and businesses must acquire a data licence. That is a purchase decision, not an engineering one.

**3. The population table knows corporate naming and not cooperative naming.**

The generic-name failure above — two `Central Cooperative Society` records merging at 1.00 — is fixed by a frequency table that knows how ordinary a word is. We built one from GLEIF (CC0): 52,875 organisation names.

Then we looked at what it had learned:

```
limited   5223        central        40
holdings   750        society        19
company   1420        cooperative    10
gmbh      1389        farmers         1
```

**One occurrence of `farmers` in 52,875 organisation names.** LEI registration follows financial-market participation, and cooperatives do not register LEIs — 51 registered entities for Côte d'Ivoire, the world's largest cocoa producer. Measured alone, the table concludes `farmers` is a *rare, identifying* token.

No larger pull fixes that. The corpus does not contain cooperatives. So the table has a second, hand-edited half where someone who has read a supplier list asserts what the corpus cannot observe — the same mechanism the facility pack needed when `PHC` appeared 4 times in 51,022 Nigerian facility names.

One rule keeps that file from doing harm: never mark a distinctive name generic. `cocoa` is generic. `sefwi` is not. Tests enforce both directions.

## The constraint we have not mentioned

There is no demand evidence. No budget, no named waiting organisation, not one interest conversation. An independent review of the plan put it plainly: *"right now this is a technically elegant story looking for a buyer."*

Everything above is a capability. Whether anyone wants it is a separate question that code cannot answer, and the honest sequence is five emails to five named compliance leads before another week of building. We are saying so here because a post that described the engineering and quietly omitted this would be the more polished and less useful document.

## What is next

**Adjudicate.** 150–300 stratified African pairs with negatives and two annotators. Everything downstream is blocked on it, and it is the only item here that is not engineering.

**Trase.** Ghanaian and Ivorian cocoa exporters, CC BY, attribution only — the population GLEIF provably cannot cover. It is the natural second frequency table and we were initially too cautious about its licence.

**Decide on OpenSanctions.** The benchmark exists and has a price.

**Tea, deliberately.** Tea is **not** in EUDR scope — cattle, cocoa, coffee, oil palm, rubber, soya and wood are. That makes it the cleanest available test of whether this is a capability or a compliance artefact. If a tea buyer wants the same reconciliation with no regulation compelling them, the primitive stands on its own. If only cocoa and coffee respond, this business is regulation-dependent and a fourth EUDR delay stops being an inconvenience.

We would rather find that out from a tea buyer than from a slide.

---

*Reproduce anything here with [what matching looks like](../concepts/what-matching-looks-like.md), or check a decision yourself with [re-verify a decision](../how-to/re-verify-a-decision.md). The organisation pack, its frequency table and the curated vocabulary all ship in `arche-core` under Apache-2.0.*
