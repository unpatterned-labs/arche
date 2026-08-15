# Product identity: which attributes actually identify a thing

*A product record carries a dozen fields. Two or three of them decide identity, several actively mislead, and which is which changes depending on a question most systems never ask.*

---

Hold a can of Coca-Cola. There is another one in the fridge. Same product?

Same brand, same recipe, same 330ml, same barcode. Obviously yes.

Except you cannot drink both. They are two cans. One is cold and one is not, one expires in March and one in June, and if the March one is recalled the other is fine. So they are also obviously two things.

Both answers are correct, and that is not a word game. It is the reason product matching fails in ways that person matching does not, and the reason a system that does not ask *same at what level* will confidently answer a question nobody asked.

## References, not things

The starting discipline comes from [John Talburt](https://doi.org/10.1016/C2009-0-63396-1), and it is the same one [the rest of this engine is built on](er-activities.md):

> **Entities do not exist in the information system. They exist in the real world.** Information systems store *references* to entities, never the entities themselves.

A row in a catalogue is not a product. It is somebody's description of a product, written for their own purposes, using whatever fields their system had. Two rows describing one product will disagree, because two retailers had different purposes.

Talburt's next move is the one this page is about. Among the attributes a reference carries, only some bear on identity. He calls those **identity attributes**. The rest describe, and describing is not identifying.

## The map

Here is a real electronics record with its fields sorted by the job each one does.

<div class="arche-attrmap">
<svg viewBox="0 0 760 380" role="img" aria-label="A product record with its attributes grouped by whether they carry identity, describe only, or depend on declared granularity.">
  <!-- subject -->
  <rect class="subject" x="300" y="132" width="164" height="112" rx="9"/>
  <text class="subject-label" x="382" y="176" text-anchor="middle">One catalogue row</text>
  <text class="subject-sub" x="382" y="196" text-anchor="middle">NETGEAR JGS516</text>
  <text class="subject-sub" x="382" y="212" text-anchor="middle">ProSafe 16-Port Switch</text>

  <!-- identity-bearing, left -->
  <g class="identity">
    <path class="lead" d="M300 152 H210"/>
    <rect class="chip" x="30" y="136" width="180" height="30"/>
    <text class="chip-text" x="44" y="155">GTIN / EAN barcode</text>
    <text class="chip-note" x="216" y="150">globally assigned, rarely shared</text>
  </g>
  <g class="identity">
    <path class="lead" d="M300 180 H210"/>
    <rect class="chip" x="30" y="182" width="180" height="30"/>
    <text class="chip-text" x="44" y="201">Manufacturer code</text>
    <text class="chip-note" x="216" y="196">JGS516 · rare, so it identifies</text>
  </g>
  <g class="identity">
    <path class="lead" d="M300 208 H210"/>
    <rect class="chip" x="30" y="228" width="180" height="30"/>
    <text class="chip-text" x="44" y="247">Brand</text>
    <text class="chip-note" x="216" y="242">weak alone, strong with a code</text>
  </g>

  <!-- granularity-dependent, top right -->
  <g class="depends">
    <path class="lead" d="M464 152 H556"/>
    <rect class="chip" x="556" y="30" width="176" height="30"/>
    <text class="chip-text" x="570" y="49">Capacity · size · weight</text>
    <path class="lead" d="M556 152 V45 H556"/>
  </g>
  <g class="depends">
    <path class="lead" d="M464 172 H556"/>
    <rect class="chip" x="556" y="76" width="176" height="30"/>
    <text class="chip-text" x="570" y="95">Colour · flavour · variant</text>
    <path class="lead" d="M556 172 V91"/>
  </g>
  <g class="depends">
    <path class="lead" d="M464 192 H556"/>
    <rect class="chip" x="556" y="122" width="176" height="30"/>
    <text class="chip-text" x="570" y="141">Edition · pack size</text>
    <path class="lead" d="M556 192 V137"/>
  </g>

  <!-- descriptive, bottom right -->
  <g class="describes">
    <path class="lead" d="M464 224 H556 V231"/>
    <rect class="chip" x="556" y="216" width="176" height="28"/>
    <text class="chip-text" x="570" y="234">Price</text>
  </g>
  <g class="describes">
    <path class="lead" d="M464 232 H548 V276"/>
    <rect class="chip" x="556" y="260" width="176" height="28"/>
    <text class="chip-text" x="570" y="278">Seller · stock · rating</text>
  </g>
  <g class="describes">
    <path class="lead" d="M464 240 H540 V320"/>
    <rect class="chip" x="556" y="304" width="176" height="28"/>
    <text class="chip-text" x="570" y="322">Marketing description</text>
  </g>
  <g class="describes">
    <path class="lead" d="M382 244 V348 H420"/>
    <rect class="chip" x="240" y="334" width="180" height="28"/>
    <text class="chip-text" x="254" y="352">Image URL · category path</text>
  </g>
</svg>
<div class="legend">
  <span><i class="k-identity"></i> carries identity</span>
  <span><i class="k-depends"></i> depends on the level you declared</span>
  <span><i class="k-describes"></i> describes only, never identifies</span>
</div>
</div>

Two of those groups are uncontroversial. A barcode identifies. A price does not, because the same tin costs different amounts in two shops on the same street, and two different tins can cost the same.

The middle group is where the trouble lives.

## The middle group is the whole problem

Stay with Coca-Cola for a moment, because it makes the middle group visible.

`Coca-Cola`, `Coke`, `Coca Cola` and `Coke Zero Sugar` are four strings. The first three are one drink written three ways, which is the spelling problem. The fourth is a different drink, and the only thing separating it from the others is a *variant* word that a similarity score will treat as a minor difference in a long title.

Meanwhile `330ml can`, `330ml bottle`, `500ml bottle` and `24 x 330ml multipack` are all Coca-Cola. Whether they are the *same product* has no answer until somebody says what they mean.

Ask whether **capacity** identifies a product and the honest answer is *it depends what you mean by product*.

A 16GB flash drive and a 32GB flash drive are the same **product line** and different **purchasable items**. If you are building a catalogue of what the manufacturer makes, capacity describes. If you are matching what a customer can actually add to a basket, capacity identifies, and treating it as descriptive will merge two things a shopper would be furious to receive.

Same attribute. Opposite job. The difference is a question that was never asked out loud.

This is why *is this the same product* is not a question with an answer. It is a question with a missing parameter. [UNTP's Digital Product Passport](https://uncefact.github.io/spec-untp/) carries an explicit granularity field for this reason, alongside model, batch and item numbers.

So before any matching happens, someone has to declare which of these they mean:

| Level | Two rows are the same when | An example of what merges |
|---|---|---|
| **Brand** | same maker | every NETGEAR switch |
| **Model line** | same design | the 16GB and 32GB drives |
| **Purchasable item** | same thing a buyer receives | only genuinely identical listings |
| **Batch** | same production run | one factory run, for a recall |
| **Individual item** | same physical object | one serial number, one tin |

Most catalogue work wants the third. Most systems silently implement the second and call it the third.

## Three categories, three different answers

The abstraction earns its keep when you look at what actually changes between kinds of product.

### Books

ISBN looks like a perfect identifier and is a trap. **A new edition gets a new ISBN.** The hardback and the paperback of one book have different ISBNs, and so do the US and UK printings. ISBN identifies an *edition*, not a *work*.

So *do these two rows describe the same book* has at least two reasonable answers, and a library catalogue and a bookshop want different ones. A reader searching for a title wants the work. A shop fulfilling an order wants the edition, because sending the paperback when someone bought the hardback is a return.

The attribute that most reliably wrecks book matching is one that looks harmless: the **publisher prefix**. Titles arrive as `Penguin Classics: Things Fall Apart` and `Things Fall Apart (Penguin Modern Classics)`, and a matcher that treats every token equally will find `Penguin` in both and count it as agreement. It is agreement, and it is worth nothing, because Penguin publishes thousands of titles.

### Food

Here the quantity **is** an identity attribute, and this is where the electronics intuition breaks.

A 415g tin and a 227g tin of the same beans are different products. Different barcode, different price, different shelf position, different thing to order. In electronics we deliberately treat a bare number as noise, because `32x32` in a jeans title is a waist and inside leg rather than a model. In food, a bare `415g` is the closest thing the record has to an identifier after the barcode.

That is not a hypothetical. This engine ships a per-category flag for exactly this, `quantities_are_specs`, set true for food and false for electronics, because a fix that made food work correctly measurably damaged electronics until it was scoped to the category that needed it.

Food adds a second wrinkle. The same product is sold as a single tin and a multipack of six, sometimes under one barcode and sometimes not. Whether the multipack is the same product is, again, a granularity question wearing a different hat.

### Electronics

The manufacturer's model code is the strongest signal available and the titles are chaos around it.

```text
Netgear ProSafe 16-Port Gigabit Switch JGS516
NETGEAR JGS516 ProSafe 16 Port Switch
```

Word order, capitalisation and hyphenation all differ. `JGS516` sits in both, and it is **rare**, which is the property that makes it identity-bearing. A code that appeared in thousands of listings would be a category, not an identifier.

Rarity is doing the work rather than shape. That distinction is measured on the Abt-Buy benchmark in [the product matching walkthrough](../tutorials/products.md), where the shipped rules reach precision 0.9707 and rarity-conditioned code matching reaches 0.9973, against 0.8865 for code matching without the rarity filter.

## What goes wrong, concretely

<details class="arche-examples" open>
<summary>The four failures worth knowing before you match a catalogue</summary>
<div class="arche-pairs">
<div class="pair match">
  <div class="pair-records">
    <code>Netgear ProSafe 16-Port Gigabit Switch JGS516</code>
    <code>NETGEAR JGS516 ProSafe 16 Port Switch</code>
  </div>
  <div class="pair-verdict">match</div>
</div>
<p class="pair-why"><strong>A rare code carries it.</strong> Nothing about the titles agrees in shape. <code>JGS516</code> agrees, and it is rare enough that the agreement means something.</p>
<div class="pair different">
  <div class="pair-records">
    <code>SanDisk Cruzer Blade USB Flash Drive 16GB</code>
    <code>SanDisk Cruzer Blade USB Flash Drive 32GB</code>
  </div>
  <div class="pair-verdict">different</div>
</div>
<p class="pair-why"><strong>One field decides it, and it is not the name.</strong> The titles are 95% identical. At the purchasable-item level these are different products, and a matcher scoring the whole string will merge them.</p>
<div class="pair review">
  <div class="pair-records">
    <code>Penguin Classics: Things Fall Apart</code>
    <code>Things Fall Apart (Penguin Modern Classics)</code>
  </div>
  <div class="pair-verdict">review</div>
</div>
<p class="pair-why"><strong>The shared token is a publisher.</strong> <code>Penguin</code> appears in both and identifies nothing, because Penguin publishes thousands of titles. Whether these are one product depends on whether Classics and Modern Classics are the same edition, which the record does not say.</p>
<div class="pair different">
  <div class="pair-records">
    <code>Heinz Baked Beans 415g</code>
    <code>Heinz Baked Beans 227g</code>
  </div>
  <div class="pair-verdict">different</div>
</div>
<p class="pair-why"><strong>A bare number, and here it identifies.</strong> In an electronics title a loose number is usually noise. In a grocery title it is often the second-strongest identifier on the row. The engine carries this as a per-category rule rather than a global one.</p>
</div>
</details>

## The rule that falls out of all this

Sorting attributes into identity and descriptive is not a modelling nicety. It changes which agreements count.

An agreement is worth something when it would have been **unlikely by chance**. `JGS516` clears that bar. `Penguin` does not. `£4.99` never will. And `415g` clears it in a grocery catalogue and fails it in an electronics one, which is why the answer has to be per category rather than global.

Three practical consequences:

**Declare the level before you match.** If nobody writes down whether you mean model or purchasable item, the system picks one by accident, usually the wrong one, and produces confident answers to an unasked question.

**A descriptive attribute must not be allowed to raise a score.** Price and marketing copy agreeing tells you two sellers use similar words. Feeding that into a similarity score manufactures confidence out of nothing.

**Some attributes should refute rather than confirm.** Capacity disagreeing is strong evidence of difference, while capacity agreeing is nearly worthless because thousands of drives are 32GB. That asymmetry is why the product pack declares specifications as refuting comparators, weighted low, rather than as ordinary scored fields.

## Where this stops

Stated plainly, because the page above reads tidier than the code is.

Only **electronics** ships as a calibrated pack today. Food, books and apparel register their own rules through the same machinery, and the machinery is shared, but the rules are not, and only electronics has a benchmark behind it.

There is no generic `product` pack, deliberately. Shipping one would be an overclaim, because what counts as a code and which specifications carry identity are properties of a *category*. Levi's `501` is a model that a length threshold would discard. `32x32` is not a model but looks like one. Reading `600mg` as a drug's model code would be dangerous.

And **granularity is not yet a declared parameter** in the engine. It is a decision you currently make by choosing a category and reading what its rules do, rather than by stating it. That is the honest gap between this page's framing and what the code enforces.

## Acknowledgements

The identity-attribute distinction, and the discipline that entities live in the world while systems hold only references, is [John Talburt's](https://doi.org/10.1016/C2009-0-63396-1), from *Entity Resolution and Information Quality* (2011). The five-activity decomposition his book sets out is [audited against this engine here](er-activities.md).

The granularity problem is not ours either. [UN/CEFACT's UNTP](https://uncefact.github.io/spec-untp/) carries an explicit identifier-granularity field in its Digital Product Passport alongside model, batch and item numbers, which is the standards world having reached the same conclusion first.

The measured results come from the [Leipzig Abt-Buy benchmark](https://dbs.uni-leipzig.de/research/projects/benchmark-datasets-for-entity-resolution), published under CC BY 4.0, whose complete ground-truth mapping is what makes a false-merge rate measurable at all.

## Notes

1. Every verdict in the expandable block was produced by running the pair, except the Heinz and Penguin rows, which illustrate category rules that ship without a labelled benchmark behind them. They are marked as illustrations rather than measurements.
2. "Rare" has a specific meaning here: measured against a population table rather than against the two records being compared. A table built from the two lists in front of you cannot know that `Penguin` is ordinary.
3. The `quantities_are_specs` flag exists because the first attempt applied one rule globally. It fixed food and measurably damaged electronics, and the damage is what produced the per-category design.

## Related

- [What matching looks like](what-matching-looks-like.md) for the same failure modes across people, places and organisations
- [Matching products](../tutorials/products.md) for the measured run and how to add a category
- [The five ER activities](er-activities.md) for where Talburt's decomposition maps onto this engine
- [Sameness and similarity](sameness-and-similarity.md) for why *same at what level* is a question rather than a quibble
