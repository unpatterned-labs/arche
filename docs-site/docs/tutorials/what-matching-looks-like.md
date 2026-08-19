# What matching actually looks like

Every verdict and every number on this page was produced by running the pair through arche, not written by hand. Reproduce any of them with the snippet at the bottom.

The point of showing them together is that the hard cases rhyme across entity types. A hospital in Birmingham, a cooperative in Sefwi Wiawso and a flash drive on a retail site fail in the same four ways: the names agree and the things differ, the names differ and the things agree, everything agrees except one field that turns out to decide it, or nothing decides it and the honest answer is *look at this one*.

That third outcome. **review**. Is a first-class answer here, not a failure to reach one. Roughly a third of the examples below land on it, and most of those are cases where a matcher that only says yes or no would have to say something false.

---

## Organisations, and the case that breaks every signal at once

<details class="arche-examples" open>
<summary>Cocoa, coffee and tea supplier reconciliation</summary>
<div class="arche-pairs">
<div class="pair review">
  <div class="pair-records">
    <code>Kuapa Kokoo Cooperative Society</code>
    <code>Kuapa Kokoo Farmers Union</code>
  </div>
  <div class="pair-verdict">review</div>
</div>
<p class="pair-why"><strong>name 1.00 · tftoken 1.00 · entity_class conflict</strong>, strip the legal form from both and the names are <em>identical</em>: <code>kuapa kokoo</code>. A society and the union above it are different parties, and nothing in the strings can tell you so. Only the declared class refutes it.</p>
<div class="pair review">
  <div class="pair-records">
    <code>Nyeri Hill Factory                    (site)</code>
    <code>Nyeri Hill Tea Factory Co Ltd         (operator)</code>
  </div>
  <div class="pair-verdict">review</div>
</div>
<p class="pair-why"><strong>name 0.95 · geo 1.00 at 0.0 km · entity_class conflict</strong>, the largest false-merge risk in supply-chain data. The site and the company that operates it share a name <em>and</em> a coordinate, so every string and spatial signal points the wrong way at once, and stripping the shared form leaves them <em>more</em> alike, not less. Merging them destroys the link between a plot and the party accountable for it, which is the only thing a due-diligence chain exists to establish.</p>
<div class="pair match">
  <div class="pair-records">
    <code>Sefwi Wiawso Cooperative Society</code>
    <code>Sefwi Wiawso Co-operative Society Ltd</code>
  </div>
  <div class="pair-verdict">match</div>
</div>
<p class="pair-why"><strong>score 1.00</strong>. <code>Co-operative Society</code> and <code>Cooperative Society Ltd</code> are two spellings of one legal form. Both reduce to <code>sefwi wiawso</code>, and the form carries none of the score.</p>
<div class="pair match">
  <div class="pair-records">
    <code>Touton Negoce SARL        RC-88421</code>
    <code>Touton Negoce             RC-88421</code>
  </div>
  <div class="pair-verdict">match</div>
</div>
<p class="pair-why"><strong>registration_id 1.00</strong>, a company number is the one exact identity signal most supplier files carry, and it settles the pair without the names having to agree on a format.</p>
<div class="pair review">
  <div class="pair-records">
    <code>Central Cooperative Society</code>
    <code>Central Cooperative Society</code>
  </div>
  <div class="pair-verdict">review</div>
</div>
<p class="pair-why"><strong>score 1.00 but distinctive_max 0.59</strong>, byte-identical strings, and still not a merge. The score says the names agree; the distinctiveness says agreeing on <code>Central</code> is not evidence of identity, because a population table knows how ordinary that word is. Before the table shipped, this pair merged at 1.00.</p>
</div>
</details>
---

## Places, in two countries

The same three failure modes, on health facilities in the UK and Nigeria.

<details class="arche-examples" open>
<summary>Facility and place matching</summary>
<div class="arche-pairs">
<div class="pair match">
  <div class="pair-records">
    <code>Queen Elizabeth Hospital</code>
    <code>Queen Elizabeth Hospital Birmingham</code>
  </div>
  <div class="pair-verdict">match</div>
</div>
<p class="pair-why"><strong>name 0.94 · 0.06 km apart · type match</strong>, one register appends the city, the other does not. The coordinates make the qualifier redundant rather than contradictory.</p>
<div class="pair review">
  <div class="pair-records">
    <code>Royal Infirmary          (Edinburgh)</code>
    <code>Royal Infirmary          (Manchester)</code>
  </div>
  <div class="pair-verdict">review</div>
</div>
<p class="pair-why"><strong>name 1.00 · 282.31 km apart · geo conflict</strong>, identical names, and two different hospitals. Distance is a physical constraint rather than a preference, so it refutes here instead of merely scoring low. Note it demotes to <em>review</em>, never to <em>no</em>: distance says a human must look.</p>
<div class="pair review">
  <div class="pair-records">
    <code>An Nur Specialist Hospital</code>
    <code>Al Noury Specialist Hospital</code>
  </div>
  <div class="pair-verdict">review</div>
</div>
<p class="pair-why"><strong>name 0.93 · 0.03 km apart · tftoken 0.25</strong>, the same Arabic name transliterated two ways, 30 metres apart, and arche still declines to merge it automatically. Character overlap is weak and the shared tokens are not rare enough to carry it alone. This is the honest version of a result often quoted as a win: the pair reaches a human with the evidence attached, rather than being silently fused or silently dropped.</p>
</div>
</details>
---

## People

<details class="arche-examples" open>
<summary>Person matching</summary>
<div class="arche-pairs">
<div class="pair review">
  <div class="pair-records">
    <code>Oluwaseun Adebayo     +234 801 234 5678</code>
    <code>Olusegun Adebayo      +234 801 234 5678</code>
  </div>
  <div class="pair-verdict">review</div>
</div>
<p class="pair-why"><strong>name 0.91 · phone 1.00</strong>, a shared phone number is strong, and <code>Oluwaseun</code> and <code>Olusegun</code> are two different Yoruba given names, not two spellings of one. A household phone is shared; a name is not. Review is the correct answer and a confident merge would be a wrong one.</p>
<div class="pair review">
  <div class="pair-records">
    <code>Amara Nwosu     12 Awolowo Road, Ikoyi, Lagos</code>
    <code>Chidi Nwosu     12 Awolowo Road, Ikoyi, Lagos</code>
  </div>
  <div class="pair-verdict">review</div>
</div>
<p class="pair-why"><strong>address 1.00 · name 0.70</strong>, same surname, same address, different people. Address is a supporting signal: it amplifies a decision, it never manufactures one.</p>
</div>
</details>
---

## Products

<details class="arche-examples" open>
<summary>Product matching</summary>
<div class="arche-pairs">
<div class="pair match">
  <div class="pair-records">
    <code>Netgear ProSafe 16-Port Gigabit Switch JGS516</code>
    <code>NETGEAR JGS516 ProSafe 16 Port Switch</code>
  </div>
  <div class="pair-verdict">match</div>
</div>
<p class="pair-why"><strong>code 1.00 · name 0.80</strong>, word order, capitalisation and hyphenation all differ. <code>JGS516</code> is a rare code shared by both, and rarity is what makes it identity-bearing rather than merely common ground.</p>
</div>
<p class="arche-note">Not every pair reaches a comparator. <code>SanDisk Cruzer Blade 16GB</code> against the same drive at <code>32GB</code> is never proposed as a candidate at all, they share no rare token, so blocking drops the pair before scoring. The right answer for the wrong reason, and worth knowing when you read a recall figure.</p>
</details>
---

## One messy record against several plausible answers

Pairwise matching assumes you already know which two records to compare. Often you do not. You have one string and a shortlist, which is a different problem with a different failure mode.

<details class="arche-examples" open>
<summary>Ranking candidates</summary>
<div class="arche-candidates">
<p class="cand-label">Messy record</p>
<code>FLAT 3 ST LEGER HOUSE GREAT LINFORD MK14 5HA</code>
<p class="cand-label">Candidates</p>
<ol>
<li><code>GREAT LINFORD HOUSE 1 ST LEGER COURT GREAT LINFORD MK14 5HA</code></li>
<li class="chosen"><code>3 ST LEGER HOUSE <mark>4A</mark> ST LEGER COURT GREAT LINFORD MK14 5HA</code></li>
<li><code>3 ST LEGER COURT GREAT LINFORD MK14 5HA</code></li>
</ol>
</div>
<p class="arche-note">All three share the postcode, and the postcode therefore decides nothing. Candidate 3 is a <em>different building</em> on the same court; candidate 1 shares almost every token in a different arrangement. What separates them is which tokens are rare and which structural role each one plays. <code>HOUSE</code> versus <code>COURT</code> is the distinction the ranking turns on, and it is one token wide.</p>
</details>
---

## Reproduce any of these

```python
from arche.resolve import crosswalk

a = [{"id": "a", "name": "Nyeri Hill Factory",
      "entity_class": "SITE", "lat": -0.42, "lon": 36.95}]
b = [{"id": "b", "name": "Nyeri Hill Tea Factory Co Ltd",
      "entity_class": "OPERATOR", "lat": -0.42, "lon": 36.95}]

result = crosswalk(a, b, entity="organisation", id_field="id")
edge = result["matches"][0]
print(edge["decision"], edge["score"], edge["distinctive_max"])
print(edge["evidence"])
```

Swap `entity=` for `place`, `person`, `product_electronics` or `artist`. Every edge carries its evidence, a reproducible `decision_id`, and can be [signed and re-verified by someone who does not trust you](../how-to/re-verify-a-decision.md).

---

## The pattern underneath

Read the five sections together and the same three rules are doing the work each time.

**A shared string is not a shared identity.** `Central` and `Central` are identical and prove nothing; `JGS516` and `JGS516` are identical and prove almost everything. The difference is rarity, and rarity is a fact about a population rather than about the two records in front of you.

**A supporting signal may amplify a decision and may never manufacture one.** Geography, address and containment can lift a well-evidenced pair over the line. None of them can carry a weak name across it, which is why two people at one address stay unmerged, and why a site sitting exactly on top of its operator is still two parties.

**Refusal is an answer.** Every `review` above is a case where the available evidence genuinely does not settle it. Saying so, with the numbers attached, is more useful than a confident verdict that happens to be wrong, and it is the difference between a queue a person can work through and a merge nobody can defend.
