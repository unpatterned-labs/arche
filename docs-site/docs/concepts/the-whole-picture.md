# The whole picture

*Where this came from, what is actually built, what has been measured, and what we have not proven. The shortest complete account. Start here.*

<div class="arche-path">
<span class="path-label">Reading path</span>
<span class="here">1. The whole picture</span>
<span class="sep">&rsaquo;</span>
<a href="../sameness-and-similarity/">2. Sameness and similarity</a>
<span class="sep">&rsaquo;</span>
<a href="../arche-in-practice/">3. arche in practice</a>
</div>

---

## The problem, in one sentence

You have records about people, places, or things. They came from different systems, written by different people, at different times. The same real-world thing appears in them under different names, and you have to decide which records are about which thing, in a way you can defend six months later.

Most tools give you a score. arche gives you a decision, the evidence behind it, the rule that produced it, and a signature, so someone who does not trust you can check it.

---

## How this got here

It started with a narrow, unglamorous observation.

Matching African names with off-the-shelf tools produced a false-merge rate around 40%. Not because the tools were badly built, but because their assumptions were made somewhere else. Jaro-Winkler, the string comparator underneath most of this work, gives a bonus when two names share an opening. That choice makes sense, because it was tuned on US Census surnames, where clerical typos usually happen at the end of a word. It falls apart on Diallo and Jallow, which are one family name and share no opening at all.

The first attempt was the obvious one: tune the threshold. It failed in a way that turned out to be the whole insight. Loosening it to catch Diallo and Jallow started merging unrelated people who happened to share a common name. Tightening it to stop that lost the spelling variants again. The dial was not badly set. The dial was the wrong instrument.

What fixed it was not a better algorithm. It was two pieces of data that nobody was shipping: a list of which spellings mean the same name, and a table of how common each name actually is.

Everything since has been finding out how far that generalises. Health facilities in Nigeria, where "Primary Health Centre" appears in thousands of names and carries no information. Places, where "High Street" does the same job. Products, where "Black T-Shirt" does. Then organisations, where a cooperative and the union above it can reduce to identical strings once you remove the legal form.

The pattern held every time. **The failures were in what the records looked like when they were compared, not in the mathematics that compared them.** That is the whole thesis, and it was discovered rather than designed.

---

## The one idea

Entity resolution has two halves, and the attention is on the wrong one.

**Inference** is the maths: given evidence of agreement, how likely is a match? This half is solved. It has a founding paper from 1969 and excellent free software. If this is your problem, use [Splink](https://moj-analytical-services.github.io/splink/). We mean that literally.

**Representation** is everything before the maths: what do the records look like when compared? What counts as agreement, and what is agreement *worth*?

A matcher compares "Diallo" and "Jallow" and finds almost nothing. It is not calculating wrong. It is calculating correctly on a representation that never contained the fact that these are one Fula family name split by a colonial spelling border. **No better probability model conjures a fact that is not there.** Someone has to put it there.

!!! note "Where that framing overreaches, and the version that survives"

    A reviewer pushed back hard: *"representation and inference are not cleanly separable. The comparison vector, blocking, missingness handling, priors and m/u estimates jointly define the effective representation. Claiming all real error lives before inference is false."*

    Correct. Calibration error, dependence violations and dataset shift are real and live on the inference side. The defensible claim is narrower and still worth making:

    **The fixes that work on this data are shipped data, not better estimators.** That is an empirical statement about where the repairs live, not a theorem about where error lives. It is why arche ships tables and vocabularies in the wheel, and why the roadmap says *consume, don't build* about the maths.

---

## Two problems, pulling opposite ways

This is the crux and it takes thirty seconds.

```mermaid
flowchart LR
    P1["<b>Problem 1</b><br/>One person,<br/>many spellings"]
    E1["Diallo · Jallow · Jalloh<br/>Mohammed · Mamadou"]
    R1["Matcher says DIFFERENT<br/>Truth: SAME<br/><b>→ missed match</b>"]
    P1 --> E1 --> R1

    P2["<b>Problem 2</b><br/>Many people,<br/>one name"]
    E2["Ibrahim Musa<br/>vs Ibrahim Musa"]
    R2["Matcher says SAME<br/>Truth: probably DIFFERENT<br/><b>→ false merge</b>"]
    P2 --> E2 --> R2

    F1["<b>Equivalence packs</b><br/>which spellings<br/>mean the same name"] -.-> R1
    F2["<b>Frequency tables</b><br/>how common each name is,<br/>so common ≠ strong evidence"] -.-> R2

    style R1 fill:#b42318,color:#fff,stroke:#b42318
    style R2 fill:#b42318,color:#fff,stroke:#b42318
    style F1 fill:#1a56db,color:#fff,stroke:#1a56db
    style F2 fill:#1a56db,color:#fff,stroke:#1a56db
```

Turn the threshold up and you fix problem 2 while making problem 1 worse. Turn it down and the reverse. **One dial cannot fix both**, and the two fixes are different kinds of object.

That is why arche ships data, not just code. The [full argument, including where it is contestable](sameness-and-similarity.md), is a page of its own. A single well-specified frequency-aware model could in principle address both, and the honest claim is about what is shippable and measurable rather than what is mathematically irreducible.

---

## What is actually built

Version **0.4.0a1**. Five entity packs ship: `person`, `place`, `artist`, `product_electronics`, and `organisation`. A pack is configuration over one engine, never a fork.

| Layer | What it answers |
|---|---|
| **Detect** | what is in this data — names, IDs, phones, addresses, with the governing statute attached |
| **Declare + policy** | what may be compared — your fields mapped to slots, jurisdiction rules applied |
| **Represent** | what counts as agreement and what it is worth — packs, frequency tables, vocabularies |
| **Resolve** | same or not — score, then the distinctive-signal gate |
| **Attest** | can this be proven later — signed, recomputable by a third party |

Three answers, not two: `same_entity`, `review`, `different`. And a second axis. Believing two records match and *fusing* them are different acts, so `same_entity + hold` is a valid outcome.

`review` is not a cop-out. It is Fellegi and Sunter's third region A₂, in the founding paper since 1969, discarded by most production systems because a review queue costs salaries.

---

## What has been measured

Four results, four different things. **Read the caveats column as part of the number, not as a footnote.**

| What | Baseline | arche | Read it as |
|---|---|---|---|
| **Name equivalence**<br/>58 pairs, 18 categories | Jaro–Winkler @ 0.80<br/>F1 **0.8493** | F1 **0.9880** | Recall 0.738 → **0.976**, precision held at 1.000. **A demo, not a benchmark** — 58 pairs, and from v0.1.0. Needs re-running. |
| **Name frequency**<br/>60 positives, 60 hard negatives | arche **minus the frequency signal** | false merges **40% → 0%** | The safety result. But zero observed errors means the test did not observe one, and **we built the negatives**. |
| **Scale (Febrl 4)**<br/>10,000 records, truth known | — (absolute) | precision **1.0** | Bought by sending ~12% to `review`. **Precision on the cases we chose to answer.** |
| **Multilingual detection**<br/>48 cases, 6 languages | Presidio **37/48** | **47/48** | On African government IDs specifically, Presidio scored **2/25**. n=48 is not superiority. |
| **Organisation lane**<br/>946 labelled pairs | token-sort F1 **0.8898** | F1 **0.9493** | False merges **21 → 4**. Public set, criteria declared before the run. Anglophone restaurant listings — **says nothing about African organisation names**. |

### How the baselines were chosen

This matters more than the numbers, because a benchmark with a badly chosen baseline proves nothing.

**The rule: change exactly one thing.** The frequency benchmark is the clearest case. The baseline is not a strawman, it is **arche with the frequency signal switched off**. Same data, same comparator, same threshold. So the 40 → 0 result cannot be explained by anything else in the pipeline.

The hard negatives are hard on purpose: pairs sharing a *common* surname exactly with different given names, against positives sharing a *distinctive* surname. Both classes share one token and differ on another, so a frequency-blind matcher literally cannot separate them.

---

## What we have not proven

A page of wins with no losses is marketing. This section is the reason to trust the rest.

- **The sets are small.** 58 and 120 pairs. Real benchmarks are orders of magnitude larger.
- **We built the hardest ones ourselves.** When the same team designs the negatives and the solution, the benchmark is vulnerable to target leakage and favourable case construction. Independent construction would be better.
- **`review` is not precommitted.** Abstention is only principled under a selective-risk policy: thresholds fixed on validation data, review budget fixed in advance, and end-to-end performance reported *including* deferred cases. We report precision 1.0 without costing the 12%. Until that is fixed, the number is narrower than it reads.
- **No head-to-head against frontier models.** The most important missing experiment, and the one most likely to prove us wrong.
- **The `score` is not a probability.** It assumes a uniform prior that is never right, and it is carried into signed artifacts. A project arguing for honest assertions cannot ship a field that overclaims.
- **The equivalence packs have no measured false-equivalence rate.** They convert uncertain linguistic resemblance into deterministic evidence. That needs provenance, scope, versioning and an error rate, not just an F1.
- **No African organisation-name ground truth exists.** Anywhere. Including here, where 259 rows sit staged for adjudication with zero labelled.

---

## Where the data comes from

The shipped frequency tables are built from public sources with checked licences:

| Table | Source | Licence |
|---|---|---|
| Person names | US Census 2010 surnames (162,253) + African names lexicon via Wikidata/ParaNames (13,342) | public domain · CC BY 4.0 |
| Places | Nigerian facility registries | open data |
| Organisations | GLEIF LEI Level 1 — 52,875 name forms | **CC0 1.0** |

Census counts run to millions and African counts top out near a thousand, so each source is normalised to a common total before merging. Otherwise Census drowns the African signal.

Every table has a curated half beside it, because **a corpus only knows the words that are in it.** GLEIF counts `farmers` exactly **once** in 52,875 organisation names, since cooperatives do not register LEIs. Measured alone, the table concludes `farmers` is a rare, identifying token. No larger pull fixes that. Someone who has read a supplier list has to assert it, and the YAML is where they do.

The packs and tables are open. CC BY 4.0, and take pull requests. An open pack that everyone corrects is a better pack, and the corrections are the flywheel.

---

## Where this sits against the field

Three projects have independently converged on the same architectural bet: **ship the representation data, keep the algorithm simple.**

| Project | Domain | Ships |
|---|---|---|
| [`uk_address_matcher`](https://www.robinlinacre.com/address_matching/) | UK addresses | the technique — and explicitly *rejects* Fellegi–Sunter for addresses |
| [`whereabouts`](https://github.com/ajl2718/whereabouts) | AU / US addresses | prebuilt country databases |
| **arche** | people, places, products, organisations | frequency tables, equivalence packs and vocabularies in the wheel |

That three groups reached "the data is the product, the algorithm is nearly trivial" from UK addresses, Australian addresses and personal names is the strongest support this thesis has that we did not generate ourselves.

### What arche covers, stated accurately

It is worth being precise here, because "an African name matcher" undersells what is shipped and oversells what is special.

The **scope** is general. The organisation table is built from company registrations across 45 jurisdictions. The product work is benchmarked on US retail catalogues. The place work runs on UK hospitals and Nigerian clinics alike, and the person tables merge US Census surnames with a multilingual name lexicon. Nothing in the engine is region-specific, and the examples throughout these pages are deliberately drawn from Britain, Kenya, Ghana, Nigeria and the United States.

The **differentiator** is narrower and worth naming plainly: arche is calibrated for the cases where standard tools assume a population they were not built for. Jaro-Winkler rewards a shared prefix because it was tuned on US Census surnames. Default frequency priors assume a name distribution that does not hold in a lot of the world. Those assumptions fail on Diallo and Jallow, and they also fail on Cantonese romanisation, on Arabic transliteration, and on any register where one family name has three spellings.

So the honest sentence is: **general-purpose entity resolution that ships its representation data, built by people who noticed the defaults first where the defaults break hardest.**

That framing also explains the remaining gap in the field. `whereabouts` ships Australia and the US, Linacre's work is the UK, and nobody ships the majority world. The problem is not that Africa needs a special engine. It is that the reference data everyone else takes for granted does not exist there yet, and reference data is the part that actually decides the answer.

And the strongest case against us, in its own words: **the defensible core may be Fellegi–Sunter plus a curated alias table, frequency features and a review queue. Every component standard.** The honest answer is not rhetoric. It is independent, out-of-domain, longitudinal results, and evidence that curation scales without becoming bespoke consulting. We do not have those yet.

---

## Where we are going

In dependency order, and the first item is not engineering.

**1 · Adjudicated African ground truth.** 150–300 stratified pairs including negatives, two annotators, false merges reported separately from misses. Every claim about African name or organisation matching is blocked on this, and no amount of compute substitutes for it.

**2 · Precommit the abstention policy.** Fixed review budget, thresholds set on validation data, deferred cases costed into the headline number. This turns `review` from a defensible design choice into a measured one.

**3 · The head-to-head.** Frontier models against both blades of the scissors. The prediction is stated in advance: strong on dispersion, weak on concentration. If they win on both, we are wrong about something important.

**4 · Close the honest defects.** Rename or re-derive `score`. Measure the packs' false-equivalence rate. Build a threat model before any deployment that decides benefits.

**5 · The contestability surface.** A signature that a regulator can check is not accountability if the person whose records were merged cannot see or challenge it. This is simultaneously the largest gap and the most on-mission thing available to build.

---

## Where to go from here

| If you want | Read |
|---|---|
| Why a matcher can never say *same*, and whether AI changes that | [Sameness and similarity](sameness-and-similarity.md) |
| What changes about your working day | [arche in practice](arche-in-practice.md) |
| The failure modes, side by side, with real verdicts | [What matching looks like](what-matching-looks-like.md) |
| How someone else checks your decision | [Re-verify a decision](../how-to/re-verify-a-decision.md) |
| To just use it | `pip install arche-core` |

## Acknowledgements

Most of the ideas here are borrowed, and it is worth being specific about which.

The three-region decision rule, including the *fail to designate* region that most production systems throw away, is [Fellegi and Sunter's](https://www.tandfonline.com/doi/abs/10.1080/01621459.1969.10501049) from 1969. We did not invent abstention. We declined to discard it.

[Splink](https://moj-analytical-services.github.io/splink/), from the UK Ministry of Justice, is the tool we point people to when their problem is inference rather than representation. That recommendation is sincere and it costs us nothing, because the two projects solve different halves.

[Robin Linacre's writing on UK address matching](https://www.robinlinacre.com/address_matching/) reached the token-frequency conclusion first, from addresses rather than names, and says plainly that Fellegi-Sunter is the wrong model for that domain. [`whereabouts`](https://github.com/ajl2718/whereabouts) reached the same architectural bet from Australian and US addresses. Three groups converging on "the data is the product" from three unrelated starting points is stronger evidence than anything we could assemble on our own.

[Shahbazi et al. (VLDB 2023)](https://arxiv.org/abs/2307.02726) established that entity-matching error rates differ across demographic groups and that standard benchmarks do not measure it. We try to propose a mechanism. The finding is theirs.

The name data builds on [ParaNames](https://arxiv.org/abs/2104.00558) and Wikidata, the US Census 2010 surname file, and [GLEIF's](https://www.gleif.org/en/about/open-data) CC0 release of legal-entity reference data. The benchmark sets come from the [Database Group at Leipzig](https://dbs.uni-leipzig.de/research/projects/benchmark-datasets-for-entity-resolution) and the ER_Magellan collection.

## Notes

1. Every figure on this page came from running the code. Where a number is stale, and the name-equivalence result predates the current version, it is labelled stale rather than quietly refreshed.
2. "Representation" is used narrowly here: the comparison vector and the data feeding it. A reviewer correctly pointed out that blocking, missingness handling and the m/u estimates also shape it, which is why the claim is about where the *fixes* live rather than where all error lives.
3. The organisation figures come from a public benchmark of Anglophone restaurant listings. They say nothing about the African organisation names the project is aimed at, and the roadmap treats closing that gap as adjudicator work rather than engineering.

## Where to go next

Next in this path: **[Sameness and similarity](sameness-and-similarity.md)**, on why the hard part is hard and whether a frontier model dissolves it.
