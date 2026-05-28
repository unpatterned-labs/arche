## arche

arche is the open-source engine that resolves who someone is across messy, multilingual, regulated data, and proves it.


# arche — The Identity Intelligence Engine

> *"Solve the hardest version of the problem. Everything easier becomes a free feature."*

**arche** is an open-source identity intelligence engine. Extract, match, and link entity identities across any document, system, or format. Names, addresses, national IDs, businesses, financial identifiers — detected, resolved, and linked into unified identity graphs.

Think: **GliNER + Presidio + Splink + Nominatim — unified, opinionated, and works out of the box.**

Like Tesseract is to OCR, or spaCy is to NLP — arche is to identity resolution. Works everywhere. Happens to be the *only* one that also handles the hardest cases on earth.

---

---

## 1. The atomic problem

Identity is fragmented and nobody owns the layer that fixes it.

The same person is "Mohammed," "Muhammad," "Mamadou," "ميسي." The same business
is "Acme Ltd," "ACME LIMITED," "Acme Nig. Ltd." The same patient sits in three
clinic systems under three spellings. Every system that touches people or
organizations has an identity-resolution problem hiding inside it, and almost
everyone hand-rolls a brittle version: regex, fuzzy match, a spreadsheet of name
variants, a junior engineer's weekend.

That is the unglamorous plumbing. It is real, it is everywhere, and it is
unowned. That is the opportunity.

## 2. Why now

Three forces are converging:

1. **AI agents hallucinate identity.** An LLM will assert "Leo" is Lionel Messi
   or a retired midfielder with equal confidence. Agents touching real-world
   entities need a deterministic, validated layer underneath that says "these
   two are the same, here is why, here is the proof." That primitive does not
   exist yet.
2. **Data-protection law grew teeth, globally.** NDPA, POPIA, Kenya DPA, GDPR.
   You can no longer just *detect* PII. You must *act* on it under a specific
   statute and *prove* you did. Detection is a commodity; statute-grounded
   action plus an audit trail is not.
3. **The Global South is digitizing identity but missing the resolution layer.**
   MOSIP enrolls, OpenCRVS registers, NIN/BVN/Ghana Card exist. The dedup /
   match / verify layer is absent, and Western tools do not know that
   Diallo = Jallow = Jalloh or how to checksum a BVN.

Solve the hard version (multilingual, regulated, messy, Global-South) and the
easy version (clean Western data) comes for free. African-first is not charity.
It is the hardest market with the least competition and the most defensible
moat.

## 3. What arche is

The thing that does not exist anywhere else is the **triad**:

```
   cultural-naming intelligence   +   deterministic ID validation   +   statute-grounded policy
   (Mohammed = Mamadou = ميسي)        (NIN/BVN/Ghana Card checksums)     (act + cite the law, audit it)
```

- Senzing has resolution, no African naming, no statute engine.
- Splink has matching, no PII, no compliance, no validators.
- Presidio has PII detection, no resolution, no cultural naming.

arche is the only one holding all three, in one `pip install`, offline, no API
key. **Sell the triad, not the entity resolution.** Positioning arche as "another
ER library" is a death race against Splink and Senzing. Positioning it as the
missing identity-resolution-plus-compliance-plus-verifiability verb for the
Global South and for AI agents is a category you can own.

## 4. Why people use it (honest, per buyer)

```
arche-core   →  DEVELOPERS + DPI programs    bottom-up, pip install, the wedge
arche-graph  →  BUSINESSES (KYB/compliance)  top-down, verifiable, the revenue
arche-live   →  BUILDERS needing enrichment  glue
```

- A developer with a messy CSV of African names + NINs who must dedup and redact
  under NDPA. Today: a two-week brittle project. With arche: five minutes and a
  `pip install`. That person does not get a sales call, they get a result.
  **For core, you do not sell. You distribute.** Open source + a five-minute
  quickstart + the football demo for virality + the grant for credibility.
- A fintech doing Know-Your-Business that must prove "this company is real, here
  is a signed credential anchored to Companies House" to a regulator. That person
  pays. **That is graph, and that is Plehthore revenue.** Sold top-down.

**The honest disqualifier:** if someone needs to dedup a clean list of English
names, Splink is fine, send them there. arche wins specifically when names are
multilingual, when compliance matters, or when a verifiable receipt is needed.
Own that lane completely instead of pretending to be a general-purpose Splink.

## 5. Three packages, one loop

```
        RESOLVE                ENRICH                 PROVE
       arche-core      →      arche-live      →      arche-graph
   who is this, under       what does the          a signed, verifiable
   what law?                authoritative           claim, anchored to an
   detect + match +         world know?             authoritative registry
   statute policy
```

Resolve → Enrich → Prove is a complete identity loop. Each layer is
independently useful (so they ship separately); together they are a moat nobody
copies in a weekend.

**The release order is right, and the reason should be explicit:** core is the
trojan horse, graph is the business. Lead with the open-source developer wedge
to build an installed base and credibility (and to feed the grant). Layer the
monetizable verifiable-business product on top of people who already trust the
engine. Ship the enrichment glue last because it is least urgent.

- **This weekend:** `arche-core` (the wedge).
- **Next month:** `arche-graph` (the revenue).
- **After:** `arche-live` (the glue).

## 6. How to sell it

- **The demo sells it, not the deck.** Paste a messy multilingual feed, watch
  every entity resolve to one canonical, validated, statute-classified identity
  with a verifiable receipt. The football demo is the fun version (viral, 2026
  tournament timing). The KYB demo is the serious version (revenue). Same engine,
  two skins.
- **Proof points, concrete:** 981 tests, 114 cultural-naming groups across 50+
  traditions, 4 DPA statute packs, 50 African ID validators, runs offline,
  sub-second import, Apache-2.0. The numbers do the selling.
- **Two threads, never blurred.** Core + cultural naming = the grant narrative
  (multilingual identity for the Global South). Graph + verifiable credentials =
  the Plehthore revenue narrative (KYB / compliance). Same engine, two audiences,
  two stories. Mixing them muddies both.

## 7. What it can become

Three honest 5-to-10-year outcomes, in order of ambition:

1. **The default identity-resolution layer for Global-South DPI.** The "resolve"
   verb sits permanently next to OpenCRVS and MOSIP.
2. **The trust layer under AI agents that touch real-world entities.** Every
   agent that asserts "same person / same company" calls arche to validate,
   cite, and sign. Bigger market, arriving fast.
3. **The open standard for verifiable entity resolution.** Signed resolution
   credentials that other parties publish and consume (the did-doc registry in
   the VESGA roadmap). The network-effect endgame.

Think "Presidio for the Global South" or "the Splink you don't need a data
scientist to run." Smaller and credible beats a Stripe analogy you can't yet
earn as a solo builder. Become infrastructure by being the obvious default for
one painful job, not by claiming the throne on day one.

## 8. The one risk that kills it

Focus. Three packages, three buyers, three go-to-markets is a lot for a small
lab in a June that already has a grant deadline and a PyPI release.

The discipline this weekend: **core has to be excellent; graph and live can be
rough.** Do not polish graph before core's quickstart nails the five-minute
"messy CSV in, compliant resolved output out" moment. That moment is the entire
bottom-up engine. Get it clean and core sells itself.

---

*Companion docs: `ARCHE-BLUEPRINT.md` (architecture + roadmap),
`docs/designs/entity-graph-2026.md` (the football demo as a worked example of
the resolve → enrich → prove loop).*

---

## Pressure-test (2026-05-26): the launch playbook

This vision survived a hard premise challenge plus an independent outside voice.
Both converged on the same verdict: a solo builder shipping a three-package
platform vision the same weekend as a grant deadline will under-deliver on all
of it. Ship one spear. Corrections locked:

**Launch spear (this weekend, arche-core only):** "Resolve and redact identity
data that works on African names, with the statute citation on every detection."
One sentence. The launch hero is a 5-line code snippet that fixes one exact pain,
not a platform vision.

**Launch buyer:** a developer at a *global* company drowning in messy
African-name data, remittance (Wise, Chipper), marketplaces, payroll / EOR,
airlines. They move fast and adopt bottom-up. African-first is the *technical
edge* (the names data); the buyer can be anywhere on earth that has African data.
African fintech / DPI agencies are the *grant + credibility* narrative, not the
pip-install GTM, they run 18-month procurements and won't put a solo-maintained
alpha in a KYC path.

**Cut from launch day:** every word about arche-graph, arche-live, "open
standard," and "trust layer under AI agents." Rough alphas and platform vision
subtract credibility from the one excellent thing (arche-core, 981 tests). Tease
the loop later. Ship the spear now.

**Compliance claim → audit trail.** Do not say "arche proves you're
NDPA-compliant" (that is a liability conversation: "you said it was compliant and
it wasn't"). Say "arche produces an audit trail your DPO can accept." Same value,
no legal exposure.

**Distribution is a plan, not a vibe.** "Distribute, don't sell" only works with
an actual plan: (1) a 5-line hero snippet for one exact pain, (2) one sharp
launch post (Show HN / r/Python / African dev communities), (3) the football
demo for virality, (4) the grant as credibility. A solo OSS launch with no
distribution plan = 30 stars from your network and silence in six weeks.

**Sustainability + moat (non-profit reframe).** arche is a non-profit lab
(Unpatterned Labs CIC). It does not need a VC defensibility moat and should NOT
close its open datasets, publishing them IS the mission and a community /
credibility engine. The honest model: the open stack builds distribution +
credibility; revenue is the hosted **Plehthore** service (KYB, verifiable-
credential issuance, billing); the durable edge is distribution + curated
naming/statute data + the verifiable-credential network effect, NOT the
copyable triad. The triad is the wedge, not the wall.

**Grant sequencing:** launch core narrow this weekend, then spend two weeks on
the LINGUA grant reusing the launch as traction evidence ("shipped, X installs,
981 tests"). Grant and launch must tell the *same* single story (core, African
names, audit trail). A grant application backed by a real launch beats one
backed by a vision deck.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 1 | clean | HOLD mode; 2 forks resolved (spear A, buyer A); 6 corrections adopted |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | clean | (FIFA demo design, separate plan) |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | n/a (strategy doc) |

- **CROSS-MODEL:** Outside voice (Claude subagent) and the premise challenge converged: one spear, cut the stack from launch, focus. One reframe rejected (close the dataset, misfires on a non-profit). One tension resolved by the user: launch buyer = global devs with African data.
- **UNRESOLVED:** 0.
- **VERDICT:** Positioning sharpened and locked. Ship arche-core this weekend on the single spear; defer everything else.
