# Similar is not the same

*On embeddings, Fellegi-Sunter, and what a machine has to know before it is allowed to merge two records. By Dennis Irorere, August 2026.*

---

Here are two lines of output from arche's place engine. Both pairs are byte-identical names. Both pairs sit 4.45 km apart. Read them before you read anything else.

```text
match  0.8454  General Hospital      <-> General Hospital
match  0.8454  Gyaranya Health Post  <-> Gyaranya Health Post
```

Same score. Same evidence. Same decision. And they should not be. *Every Nigerian state has a General Hospital*; there is essentially one place called Gyaranya. Whatever the right answer is for each pair, it cannot be the same answer, arrived at the same way, with the same numbers attached.

That was our own engine, three weeks ago, and it was wrong in a way that no amount of better string matching would have fixed. Both name comparators returned 1.0, correctly. The strings *are* identical. The engine had no way to know that one agreement was worth almost nothing and the other was worth almost everything, because **that is not a fact about the two strings. It is a fact about the population they came from.**

This post is about that distinction, because it is the line between two technologies people keep conflating: the ones that measure whether two things are *similar*, and the ones that decide whether two records are *the same*. Embeddings are very good at the first. They cannot, in principle, do the second. And once you see why, you also see exactly where they belong, which turns out to be somewhere more interesting than the place people keep trying to put them.

## You have already met this, several times, without being told

Before the maths, it is worth noticing that this is not an abstract problem you need a benchmark to care about. It happened to you this week.

You called your bank and were told, after some silence, that they could not find your account. Your name is spelled two ways across their systems and only one of them was searched. A delivery went to a neighbour whose address differs from yours by a flat number. A payment was held for review because your surname partially matched a watchlist, and you spent twenty minutes proving you are not someone else. Your photos app put your cousin in an album of you. A test result was filed against a duplicate of your patient record, so the doctor looking at the other one saw nothing.

Every one of those is the same machine making the same category of mistake, in one of exactly two directions.

| What you experienced | The system decided | The truth | Which way it failed |
|---|---|---|---|
| "We cannot find your account" | different | same | **missed match** |
| Payment held, identity checked | same | different | **false merge** |
| Parcel at the neighbour's | same | different | **false merge** |
| Cousin in your photo album | same | different | **false merge** |
| Result filed on a duplicate record | different | same | **missed match** |
| Autocomplete emails the wrong Amara | same | different | **false merge** |

Two columns of consequence, and they are not symmetrical in the way people assume.

## The two failures land on different people

This is the part that gets lost when the problem is discussed as an accuracy number.

<div class="arche-split">
<div class="silent">
<h4>Missed match</h4>
<p class="verdict">You become invisible</p>
<p>The system holds your record and cannot reach it. You are told you are not in the file, that the account does not exist, that there is no history.</p>
<p>Nobody logs this as an error, because from inside the system nothing went wrong. A search returned zero rows, correctly.</p>
</div>
<div class="loud">
<h4>False merge</h4>
<p class="verdict">You become someone else</p>
<p>A stranger's history lands in your file. Their allergy, their debt, their watchlist entry, their parcel.</p>
<p>This one gets noticed, because two people complain and somebody has to unpick it.</p>
</div>
</div>

Notice which one generates a ticket. **A false merge is loud and a missed match is silent**, which means the second is under-counted everywhere it happens, and systems get tuned against the failure that produces complaints rather than the failure that produces exclusion.

And there is a pattern in who gets each. A missed match needs your name to be written more than one way, which happens most to people whose names crossed a language, a script, a border or a clerk's ear. The failure that nobody logs is also the failure that falls hardest on the people least likely to be in the room when the threshold is chosen.

That is the whole argument of this post, stated before any of the technical detail: **these are two different failures, they pull in opposite directions, and a single similarity threshold cannot be set to avoid both.** The rest of this piece is about why one popular tool for measuring similarity cannot tell them apart, and what has to be added before a machine is allowed to decide.

## What a cosine actually measures

Take two facility names, run them through a multilingual sentence encoder, take the cosine of the vectors. You get a number between -1 and 1 that means *these two strings occupy nearby regions of a space learned from a training corpus*. That is a real and useful measurement. It survives word order, it survives paraphrase, it survives "Centre" versus "Center", and with a decent multilingual model it survives crossing scripts.

It is also, in the form almost everyone deploys it, a function of exactly two strings and nothing else.

Hold onto that, because a weaker version of it is the whole argument.

Two more things worth knowing before you trust a cosine as evidence. Ethayarajh showed in 2019 that the upper layers of contextual encoders are strongly *anisotropic*. Vectors bunch into a narrow cone, so arbitrary pairs sit at high cosine and the number's dynamic range is much smaller than it looks. And Steck, Ekanadham and Kallus made a sharper point in 2024: for learned embeddings, cosine similarity can be governed by regularisation choices rather than by the data, so the same model trained two defensible ways yields "similarities" that are not comparable. Their phrasing is blunt. Cosine of learned embeddings can produce "arbitrary and therefore meaningless" values.

None of that makes embeddings bad. It makes a raw cosine a poor thing to put a threshold on.

## Measured: the same pairs, two systems

Abstractions are cheap, so here is the argument as measurements. Everything below was run locally on `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`. Mean-pooled, L2-normalised, cosine. Against arche's shipped place pack. It is CPU-only and reproducible; nothing here is a thought experiment.

### Rosetta and Roulette

Start with two person names that differ by a few letters. Would an encoder confuse them?

```text
cos=0.2546   'Rosetta' vs 'Roulette'
cos=0.5714   'Rosetta Adeyemi' vs 'Roulette Adeyemi'
```

It does not, and I want to be fair about that: 0.25 is a confident "different". The model gets this one right.

But look at *why*, because the reason does not generalise:

```text
Rosetta   -> ['▁Rose', 'tta']
Roulette  -> ['▁Roulette']
```

**"Roulette" is a whole token in the vocabulary. "Rosetta" is not.** One is a common English noun the tokenizer was given a dedicated slot for; the other gets split. They sit far apart because they have different lexical status in a mostly-European training corpus, not because the model knows one is a person and the other is a casino game. Give them a shared surname and the similarity climbs to 0.57. The surname pulls them together, which is the exact opposite of what Fellegi-Sunter would do with a shared name of unknown rarity.

The model got the right answer for a reason that has nothing to do with identity. Hold that thought.

### Sabon Gari and Sabon Giri

Now the same experiment in Hausa. *Sabon Gari* means "new town". The stranger's quarter, and there is one in Kano, one in Zaria, one in Kaduna, and dozens more. It is the "High Street" of northern Nigeria. *Sabon Giri* is a different string, one letter away.

```text
cos=0.9260   'Sabon Gari' vs 'Sabon Giri'      (different places)
cos=0.5551   'Kalahaddi'  vs 'Kalahadi'        (the SAME place, twice)
```

Read those two lines together, because this is the finding that matters most in this post.

**This encoder scores the false pair at 0.93 and the true pair at 0.56. The ordering is not merely imprecise. It is inverted.** No threshold on *that scalar* separates them, and no monotone rescaling of it does either, though a trained pair classifier, a hybrid lexical-plus-dense retriever, or a cosine combined with an explicit local-frequency feature could all fix it. What cannot fix it is a bigger threshold search.

`Kalahaddi Health Post` and `Kalahadi Health Post` are two records of one facility at identical coordinates, sitting in the Kano crosswalk right now. `Sabon Gari` and `Sabon Giri` are not the same place. A system that merges on cosine gets both of these exactly backwards.

The tokenizer explains it completely:

```text
Sabon Gari  -> ['▁Sab', 'on', '▁Gar', 'i']
Sabon Giri  -> ['▁Sab', 'on', '▁Gir', 'i']     3 of 4 pieces identical
Kalahaddi   -> ['▁Kala', 'had', 'di']
Kalahadi    -> ['▁Kala', 'hadi']               different segmentation
Gyaranya    -> ['▁Gy', 'ara', 'nya']
High Street -> ['▁High', '▁Street']            two whole words
```

`High Street` gets two clean tokens. `Gyaranya` gets shattered into three meaningless fragments. The doubled consonant in `Kalahaddi` pushes the segmentation onto a different path than `Kalahadi`, so one facility becomes two unrelated fragment-sequences, while `Gari` and `Giri` happen to land on adjacent pieces and fuse.

That is a plausible mechanism rather than a proven one, and I want to be careful about the difference. Segmentation happens at the input; the cosine comes out of twelve transformer layers, and I have not run the ablation that would show the segmentation is *causing* the ranking rather than merely correlating with it. What the tokenizer output does establish is the asymmetry of coverage: English place vocabulary appeared often enough in training to earn whole tokens, and Hausa place vocabulary did not.

The hypothesis I would test, if someone wants to falsify this: **for out-of-vocabulary names, subword overlap is driven by orthographic accident rather than by anything about the entity**, and orthographic accident is uncorrelated with identity.

### The same name in two cities: Kano, Zaria, Manchester, Birmingham

Here is the case an embedding cannot represent even in principle.

```text
cos=1.0000   'Sabon Gari'       vs 'Sabon Gari'        <- Kano and Zaria
cos=1.0000   'General Hospital' vs 'General Hospital'
```

Two different places, identical strings, therefore identical vectors. The distance is exactly zero because the difference between them **is not in the string**. No encoder recovers information the input does not contain.

Add context and it improves, but not enough:

```text
cos=0.8642   'Sabon Gari, Kano'        vs 'Sabon Gari, Zaria'       (different)
cos=0.8502   'High Street, Manchester' vs 'High Street, Birmingham' (different)
cos=0.8763   'Karfi Health Post'       vs 'Karfi Health Clinic'     (SAME)
```

`Karfi Health Post` and `Karfi Health Clinic` are one facility. `Sabon Gari, Kano` and `Sabon Gari, Zaria` are two towns 150 km apart. **They differ by 0.012 of cosine, and they are on the wrong sides of each other.** Nothing you do with a threshold recovers that.

The UK line is there to make a point about scope: this is not an African-data problem that better African training data would solve. `High Street, Manchester` and `High Street, Birmingham` are different streets in a country with a national address register, in the model's best-resourced language, and they still sit at 0.85. Higher than a true match we will meet in a moment.

### One address, written twice

```text
cos=0.7111   '31 Ribadu Road, Ikoyi' vs '31 Ribadu Rd, Ikoyi, Lagos'   (SAME)
cos=0.7705   'Sabon Gari Market, Kano' vs 'Sabon-Gari Mkt, Kano'       (SAME)
```

Both of those are one address written two ways. Both score **lower** than `High Street, Manchester` versus `High Street, Birmingham`, which is two different streets.

That is the second inversion, and it is the one that would show up as a failed delivery.

### What arche says about the same pairs

```text
match   0.758  Sabon Gari Market     vs Sabon-Gari Mkt          shared=0.786
match   0.717  Kalahaddi Health Post vs Kalahadi Health Post    resid=0.860
review  0.692  Sabon Gari            vs Sabon Giri              shared=0.741
review  1.000  General Hospital      vs General Hospital        resid=0.000
```

Four pairs, four correct behaviours, and the mechanism is legible in the numbers beside them.

The last line is my favourite thing in this post. The **score is 1.000**. The strings are identical, and the engine says so plainly. The **decision is `review`**, because what they share is `general` and `hospital`, and the residual distinctiveness is 0.000. The engine is capable of saying *these two strings are identical and that tells me nothing*, which is a sentence a single similarity number cannot express, because it needs two separate quantities to say it.

And the tokens it is reasoning over are inspectable:

```text
sabon     distinctiveness=0.74      hospital  distinctiveness=0.35
gari      distinctiveness=0.79      street    distinctiveness=0.61
giri      distinctiveness=1.00      high      distinctiveness=0.54
```

`high` and `street` score 0.54 and 0.61, which is uk_address_matcher's observation about LONDON arrived at independently: the words that appear in every address carry no evidence.

`giri` scores 1.00, and **that number is a bug in disguise, not a success.** It is essentially absent from a corpus of 160,000 place tokens, and an unseen token does not establish that a value is rare. It establishes that the table cannot estimate its frequency at all. Treating "never seen" as "maximally distinctive" is precisely the failure mode we hit earlier in this engine's life, when an orthographic key that appeared in no frequency table read as a rare token and cleared the gate for anything. Splink floors very small term frequencies for the same reason: a collision on a typo must not be handed enormous evidence. Our table has an unknown-token floor but no upper smoothing, and closing that is outstanding work rather than a solved problem. The honest reading of `giri = 1.00` is *this word is outside my competence*, and the right response to it is abstention, not confidence.

### Context is a comparator, not a suffix

There is a deeper difference hiding in the Kano/Zaria pair, and it is the one I would push hardest if someone asked where a "context layer" belongs.

When you write `Sabon Gari, Kano` and hand it to an encoder, the context becomes *more string*. It is pooled into the same vector as the name, at whatever weight the attention mechanism happened to learn, and it can be outvoted by the name, which is precisely what 0.8642 means. The context is present but it has no authority.

arche does not put context in the string. Administrative containment is its own comparator with its own evidence line, and a containment conflict does not lower a score. It sets `conflict`, which demotes the pair to `review` no matter how well the names agree. Same for distance: `veto_km` is a constraint, not a weight, because as a weighted signal geography was outvoted 4:1 and merged two facilities 143 km apart.

**Structure beats interpolation.** "These names are identical but they are in different states" has two clauses, and the second has to be able to override the first rather than be averaged with it. A vector can certainly *encode* both facts. That is not the problem. The problem is that a single similarity *score* collapses them into one quantity, and any quantity can be outvoted by a bigger quantity. Veto is not a large weight. It is a different kind of thing, and it has to live in the decision rule.

## What Fellegi-Sunter measures

Now the other tradition, which is older than the machine learning one by a long way.

In 1959, Newcombe and colleagues published a method for linking vital records in *Science* that contains the idea this whole field rests on: agreement on a value is worth what that value's **rarity** says it is worth. Fellegi and Sunter formalised it in 1969. The agreement weight for a matching value *v* is

    log( m_v / u_v )

where *m* is the probability the two records agree on *v* given they are the same entity, and *u* is the probability they agree on *v* given they are **not**, and *u* is essentially the frequency of *v* in the population. Agreeing on a rare value is strong evidence. Agreeing on a common one is nearly none.

Look at the shape of that expression. It takes a value and a **population**. It is not a comparison of two strings at all. The comparison already happened, and this is the pricing step that says what the comparison was worth.

One caveat before the numbers, because it matters and I glossed over it in a first draft. Fellegi-Sunter's likelihood ratio is defined over a *comparison pattern* `m(γ)/u(γ)`, not per token; value-specific agreement weights are an extension of it, associated with Newcombe and later Winkler, and `u_v` is only "the frequency of *v*" under assumptions about the two source distributions, about blocking, and about independence between fields. arche's `distinctiveness` is **not** an estimated `m/u` probability. It is `-log10(rel_freq)/5`, a bounded monotone transform of corpus frequency, with no uncertainty attached. It is in the Fellegi-Sunter *tradition*; it is not an implementation of the theorem, and calling it one would be borrowing authority I have not earned.

With that said, here is the same idea in arche's place table:

```text
hospital     rel_freq=1.76e-02   distinctiveness=0.35
general      rel_freq=1.52e-03   distinctiveness=0.56
karfi        rel_freq=2.29e-05   distinctiveness=0.93
gyaranya     rel_freq=5.00e-05   distinctiveness=0.86
```

`Gyaranya` is worth roughly two and a half times `hospital`, and the reason is not linguistic. It is demographic.

## The type error

Put the two side by side and the shapes differ:

    cosine(a, b)                    -> two strings in, one number out
    agreement_weight(v, population) -> a value and a population in, one number out

I first wrote this section claiming that a two-argument similarity *cannot in principle* express a frequency-weighted agreement weight, because it has nowhere to put the population. That is wrong, and a reviewer was right to kill it. Population statistics do not have to be arguments; they can be model state. IDF and SIF weighting put corpus frequency into the pooling step. Learned sparse retrievers like SPLADE keep an explicit lexical axis with learned term weights. A contrastively trained encoder can absolutely push rare and common values apart, and an unnormalised dot product can carry frequency in the vector norm. "Cannot in principle" was a nice sentence and a false one.

Here is the narrower claim I will defend:

> **A raw cosine from a fixed, text-only encoder is not a sufficient statistic for identity, and it cannot adapt to the population you are linking right now without either corpus-conditioning or side information.**

Two concrete consequences, and the second is the one that actually bites.

The first is the pooling problem. Mean-pooling weights tokens by presence, not by rarity, and it discards the token identities you would need in order to reprice afterwards. arche's comparator can reprice a name because it still knows which tokens were shared; a pooled vector has forgotten. That is a property of the *usual recipe*, not of embeddings as such, and IDF-weighted pooling fixes some of it.

The second has no fix at the encoder level: **`cos(E(x), E(x)) = 1` for every `x`.** A raw cosine cannot assign different evidential values to two different exact agreements. "General Hospital" agreeing with "General Hospital" and "Gyaranya" agreeing with "Gyaranya" are both 1.0, necessarily, in any embedding of the string alone. The population you are linking changes with every job, and the encoder's weights do not change with it.

That is a limitation of the *scoring function*, not of the technology. Put location, type and administrative context into the entity vector, or run a trained classifier over vector features plus explicit local-frequency features, and you defeat it, which is exactly what the production systems in this literature do, and what I will get to. What you cannot do is threshold a bare cosine and call the result evidence about identity.

There is a second, quieter problem. Pooling. The mean or CLS operation that turns token vectors into a sentence vector. Weights tokens by presence, not by rarity, and it destroys the token identities you would need in order to reweight afterwards. arche's token comparator can reprice a name because it still knows which tokens were shared. A pooled vector has forgotten.

And there is empirical support for exactly the failure this predicts. Sciavolino and colleagues found in 2021 that dense retrievers "drastically underperform BM25" on entity-rich queries, and generalise to *common* entities unless the question pattern was seen in training. A rare surname is a rare token; a dense encoder has no reason to have allocated it capacity. Which is a machine-learning way of restating Newcombe.

## The part nobody writes papers about

Now the unglamorous layer, which in practice decides more matches than the model choice does.

Nigerian health registries spell things out. In GRID3's national list of 51,022 facilities, the string `PHC` appears in **four** of them. Everything else says "Primary Health Care Centre". So when we built a frequency table over that corpus, it concluded. Correctly, from the evidence. That `PHC` is a rare token. Distinctiveness 0.87, comfortably over the 0.75 floor that permits a merge.

Which would mean that two unrelated records, "Danja PHC" and "Rimi PHC", could clear the distinctiveness gate on the strength of the abbreviation. The corpus cannot fix this. More corpus cannot fix it. It needs somebody who has read a Nigerian facility list to say *PHC stands for primary health care centre, and it is the most generic word on the page*.

The Ministry of Justice's [uk_address_matcher](https://github.com/moj-analytical-services/uk_address_matcher) has known this for years, and its data directory is the honest version of a matching system: `address_abbreviations.json` maps `AVE` to `AVENUE`, `BLDG` to `BUILDING`; `common_end_tokens.csv` records that LONDON appears **1,148,679** times and is therefore worth nothing as evidence; `address_token_frequencies.parquet` carries the rest. Three files, no model, and they encode most of what the system knows.

It is worth being specific about that lineage, because it is the closest thing this field has to a worked answer. Robin Linacre leads [Splink](https://github.com/moj-analytical-services/splink), the Ministry of Justice's implementation of the Fellegi-Sunter model, and Splink's [term-frequency adjustments](https://moj-analytical-services.github.io/splink/topic_guides/comparisons/term-frequency.html) do exactly the thing this post keeps returning to: they take the *m* and *u* probabilities of a comparison level and adjust them **per value**, so that agreement on a common surname and agreement on a rare one are priced differently within the same model. It is Newcombe's 1959 observation, still load-bearing seventy years later, implemented as a first-class feature rather than a footnote.

uk_address_matcher is what happens when you point that machinery at addresses specifically, and the design decisions transfer wholesale. Token frequency is computed **over the corpus being linked**, so "HIGH" and "STREET" price themselves out; abbreviations are expanded before comparison rather than being left for a fuzzy matcher to guess at; and the end tokens that identify a region rather than a building are handled as their own category. The reason it works on UK addresses without a neural network is not that UK addresses are easy. It is that the system knows which words carry evidence, and it knows that because somebody counted.

Our `place_tokens.yaml` is the same idea, and it exists because the Nigerian case forces the issue harder: the UK has a national address register to count over, and much of northern Nigeria does not, so the curated half carries proportionally more of the weight.

We now ship the same idea for places, as `place_tokens.yaml`:

```yaml
abbreviations:
  - {token: phc, expands_to: primary health care centre}
  - {token: gp,  expands_to: general practice}
  - {token: ss,  expands_to: substation}

generic_tokens:
  - hospital
  - surgery
  - substation
```

An abbreviation inherits the frequency of the rarest word in what it stands for, so it can never read as rarer than the phrase it replaces. `PHC` went from 0.87 to 0.70. From over the gate to under it, and that change is one line of YAML that a Nigerian health-data analyst can write, review, and be wrong about in public. No retraining. No weights. A diff.

That is the whole argument for shipping representation as data rather than as a checkpoint: **a wrong lexicon entry is a pull request, and a wrong embedding is a research project.**

## Two things I got wrong while building this

I want to record these, because both are more instructive than the parts that worked.

**The first: a threshold is not a property of the measure.** Once the frequency table existed, I made the gate consult it. If two names share only common words, do not merge them. Correct in principle. On the shipped table it worked. On a table self-calibrated over the two lists being linked, it returned **zero matches**, out of 907 candidate pairs.

The reason is arithmetic. Over a corpus of about 7,000 tokens, a token seen twice has relative frequency 2.9e-4, which scores 0.71. Under the 0.75 floor. Almost every token in a small corpus appears at least twice. So nothing could ever clear, and every user passing their own comparators would have got an empty result set and no explanation. Draisbach and Naumann made this point in 2013 and I had read it: thresholds depend on dataset size, not only on the similarity measure. Reading it and *believing* it turn out to be different things. Distinctiveness is now only consulted against a table that can support a rarity claim, and a self-calibrated table declares that it cannot.

**The second: literal overlap is too strict a test.** The first working version demoted 19 true matches. Here are four of them, all at zero distance:

```text
Kalahaddi Health Post  <-> Kalahadi Health Post
Yauwra Health Post     <-> Yaura Health Post
Danmadaki Health Post  <-> Danmaidaki Health Post
Dunbule Health Post    <-> Dumbule Health Post
```

The identifying word is right there, and it differs by one letter, so the two names share no *literal* token and the test fell back to pricing `health` and `post`. It read the most distinctive thing on the line as generic. The fix was to ask a different question. Strip the words the corpus says are common, and see whether each side still has a rare word left. Combined with the literal test using `max`, so it can only ever recover pairs, never demote them. Nineteen demotions became two.

That "combined with max" discipline is not fastidiousness. It is the lesson from an earlier experiment where an orthographic keying change recovered 13 true pairs and demoted 79, and only became worth shipping when it was made strictly additive. Any new signal in a matching system has to be structurally incapable of making things worse, because you will not notice when it does.

## So where do embeddings actually belong?

Everything above is an argument about the *decision*. It is not an argument against embeddings, and the industry has already worked out the answer.

OpenSanctions runs one of the most adversarial matching problems there is, and has an embeddings project of their own. Their published position, from September 2025, is worth quoting exactly:

> While newer deep learning approaches (like the use of embeddings for name matching, explored in project Eridu) are phenomenal at surfacing a wide set of match candidates, the technology is less suited to help discern false positives. The industry's main pain point.

The Foursquare location-matching competition says the same thing structurally. Every top solution generated candidates from **two** channels. Spatial proximity *and* nearest neighbours in a multilingual name-embedding space, because neither alone reached acceptable recall. Then they decided with gradient-boosted trees over explicit comparison features. (Two footnotes for anyone citing that competition: it had a platform-level data leak and was re-ranked, so the honest ceiling is about 0.93 IoU rather than the 0.977 you will see quoted; and Foursquare's own blog states the rankings incorrectly.)

And Overture. A foundation with Meta, Microsoft, Amazon and TomTom behind it. Conflates roughly 75 million places using embeddings in its blocking model, then makes the pairwise decision with a gradient-boosted classifier whose features include "spatial context (how distinctive a name is within its local area)".

That last phrase is a term-frequency comparator. A billion-dollar foundation and a Nigerian open-source project independently concluded that you need to know how distinctive a name is *locally*. I find that more persuasive than any benchmark.

And I should not over-claim the citation, because it cuts against my slogan as well as for it: Overture's pairwise classifier includes **text-embedding similarity as one of its features**, alongside the string comparison, the address, the phone, the category and the distance. That is hybrid entity resolution, not "embeddings propose, rules decide". A gradient-boosted classifier over explicit features is evidence-based too; it is just less inspectable than a written-down comparator, and it needs labels we do not have.

So the slogan I will actually defend is narrower: **a bare similarity should not be the thing that clears a gate.** Whether the rest of the decision is a written-down weighted mean or a trained classifier over legible features is a second question, and the honest answer is that we have not run the comparison that would settle it.

## The interesting part: explicit embeddings for agentic entity resolution

Here is where I think this goes, and it is not "add a vector to the scorer".

Everything arche does today assumes you arrive knowing what you want: two lists, a declaration, a `reconcile` call. That is the right shape for a pipeline and the wrong shape for a person, and it is completely the wrong shape for an agent. The question a human actually has is *"is the clinic in this delivery note the same one we paid last quarter?"*, and answering it requires finding the candidates before anything can be resolved.

That is a retrieval problem, and retrieval is the thing embeddings are genuinely best at.

So: give every resolved entity an **explicit vector**. An attribute of the entity, stored beside it, versioned like any other representation. Not a pair score. A coordinate that makes the entity *findable*. Then the loop looks like this:

1. A person or an agent asks in natural language.
2. `detect` finds the identifying data in the question and the statute that governs it, before anything leaves the process.
3. The vector index proposes candidate entities. Dozens, ranked, deliberately over-inclusive.
4. The deterministic engine scores each candidate the way it scores everything: per-field comparators, frequency-weighted agreement, the geographic veto, the distinctiveness gate.
5. What comes back is a decision *with its evidence*, and where the evidence is not enough, a `review`, which for an agent is not a failure but the most important message in the protocol.
6. `attest` signs the decision, and the signature covers the evidence and the pinned representation, not the vector that happened to surface the candidate.

**Latent space proposes. The ledger disposes.** The vector's job ends the moment the candidate list exists, and nothing downstream inherits its opacity. `decision_id` stays a content hash over evidence and representation versions, so a decision still replays byte-for-byte in five years even if the encoder is deleted tomorrow.

That slogan has a hole in it, though, and it is worth naming rather than discovering later. **It is only true for a positive decision.** If the retriever never surfaces the true entity, the deterministic engine never gets to consider it, and the system returns nothing. Cleanly, reproducibly, and wrongly. "Deliberately over-inclusive" is a hope, not a recall guarantee. A negative result is a joint claim about the decision *and* the coverage of the search that produced it, so for negatives the retrieval step is inside the boundary, not outside it.

Which means three things are non-negotiable if this ships. Retrieval recall has to be **measured end-to-end against a truth set**, per geography and per source, not asserted. The vector channel has to be a **union with the deterministic blockers**. Rare token, shared identifier, spatial cell, so a failure of the index is not a failure of the system. And "no match" has to be reported as what it actually is: **no match among the candidates retrieved**, with `k`, the index snapshot, the model hash and the filters recorded beside it. An ANN index is not a stable artefact; it varies with build parameters and library versions, and a decision that depends on its coverage has to say so.

Three constraints I would hold, and I would rather say them now than discover them later.

**Embed the entity, not the person.** Morris and colleagues showed in 2023 that text embeddings can be inverted. 92% of tested 32-token inputs recovered exactly, including sensitive clinical information. Under a threat model where the attacker has the embeddings and a model-specific inversion capability. An embedding of a name is not a de-identified artefact; it is personal data wearing a costume. So the vectors that make things findable should be built over descriptors that are already public. A facility's name, type, administrative hierarchy, and anything restricted stays out of the index under the same disclosure policy the declaration already enforces elsewhere. But "entity, not person" is a risk reduction, not a privacy boundary, and I do not want to oversell it: an index still leaks membership, attribute combinations, and query intent, so it needs access control, a retention and deletion story, and membership-inference testing before it goes anywhere near production.

**The agent gets evidence, never a cosine.** If a tool returns `0.83`, the agent will thread it into a sentence and the number will become a claim. If it returns `shared token "Gyaranya", distinctiveness 0.86; distance 0.4 km; facility tier disagrees`, the agent can *say what it knows* and, more importantly, say what it does not. This is the same reason a person reviewing a queue needs the factors and not the score.

**Abstention is the interface.** The most valuable thing an entity resolver can tell an autonomous agent is "I do not know, and here is precisely what is missing". An agent that receives `review` with the evidence attached can go and find the missing evidence. Ask the user, call a registry, check a phone number. An agent that receives 0.71 will round it. Three outcomes are not a hedge; they are the only honest protocol between two systems that both need to know how much to trust the answer.

## What this adds up to

Similarity and identity are different questions, and it took me a while to stop treating them as the same one at different resolutions.

Similarity is a property of two things. It is continuous, it is symmetric, it is learnable, and a model can get very good at it. Identity is a claim about the world, and it depends on what else exists in the world. On how many other places are called General Hospital, on whether anyone else in this district is named Gyaranya, on whether PHC means anything at all. That dependence on the population is not a detail. It is the entire content of the claim.

Which is why the machinery ends up looking the way it does. A frequency table, because rarity is a fact about a population. An abbreviation list, because someone who has read the registry knows something the corpus does not. A gate that refuses, because a wrong merge fuses two people's records and no confidence score undoes it. A signature, because a decision you cannot defend later is not a decision. And an embedding, sitting outside all of it, doing the one job it is unambiguously excellent at, which is helping you find the thing in the first place.

One last thing, because a post like this should say it out loud. Everything above argues for a design this project already built, using examples where that design wins, against one small encoder chosen partly because it runs on a laptop. That is not a comparative evaluation. The measured version. Entity-disjoint splits, real labels, BM25 and modern multilingual retrievers and a fine-tuned cross-encoder scored on the same fields as the rules engine, candidate recall reported separately from decision quality. Does not exist yet, for us or for anyone, on Nigerian place data. Until it does, treat this as a design rationale with worked examples, which is what it is.

The satellite sees space. The encoder sees similarity. Deciding that two records are the same person, or the same clinic, is still a claim someone has to be able to defend. We would rather ship the part that can be argued with.

---

## Reproducing the measurements

Every cosine in this post came from `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (Apache-2.0, 50 languages, 384 dimensions), mean-pooled over the last hidden state with the attention mask, L2-normalised, on CPU. The arche side is the shipped `place` pack at v0.3.0a1 with the `place` frequency table.

Two honest caveats about scope. **One encoder is not all encoders**. A larger multilingual model, or one fine-tuned on place names, would score these pairs differently, and I would expect it to do better on the Kalahaddi/Kalahadi case. What I do not expect any encoder to fix is the Kano/Zaria case, because identical strings produce identical vectors and no amount of training changes that. And **eleven pairs is an illustration, not a benchmark**. They were chosen after looking at the scores, to show specific failure modes, with no sampling frame and no independently established labels. They demonstrate that this model's raw cosine is inadequate here. They do not establish anything about embeddings in general. The measured, sampled version is the Nigerian place-resolution gold set, which does not exist yet and which is the next thing we are building.

## References

- H. B. Newcombe, J. M. Kennedy, S. J. Axford, A. P. James, "Automatic Linkage of Vital Records," *Science* 130(3381), 954-959, 1959.
- Ivan P. Fellegi and Alan B. Sunter, "A Theory for Record Linkage," *Journal of the American Statistical Association* 64(328), 1183-1210, 1969.
- Uwe Draisbach and Felix Naumann, "On Choosing Thresholds for Duplicate Detection," *ICIQ*, 2013. Thresholds depend on dataset size, not only on the similarity measure.
- Uwe Draisbach, Peter Christen, Felix Naumann, "Transforming Pairwise Duplicates to Entity Clusters for High-quality Duplicate Detection," *ACM JDIQ* 12(1), 2020. [10.1145/3352591](https://doi.org/10.1145/3352591)
- Kawin Ethayarajh, "How Contextual are Contextualized Word Representations?", *EMNLP-IJCNLP*, 2019. [10.18653/v1/D19-1006](https://doi.org/10.18653/v1/D19-1006)
- Harald Steck, Chaitanya Ekanadham, Nathan Kallus, "Is Cosine-Similarity of Embeddings Really About Similarity?", *WWW '24 Companion*. [arXiv:2403.05440](https://arxiv.org/abs/2403.05440)
- Christopher Sciavolino, Zexuan Zhong, Jinhyuk Lee, Danqi Chen, "Simple Entity-Centric Questions Challenge Dense Retrievers," *EMNLP*, 2021. [arXiv:2109.08535](https://arxiv.org/abs/2109.08535)
- John X. Morris, Volodymyr Kuleshov, Vitaly Shmatikov, Alexander M. Rush, "Text Embeddings Reveal (Almost) As Much As Text," *EMNLP*, 2023. [arXiv:2310.06816](https://arxiv.org/abs/2310.06816)
- Saravanan Thirumuruganathan et al., "Deep Learning for Blocking in Entity Matching: A Design Space Exploration," *PVLDB* 14(11):2459-2472, 2021.
- OpenSanctions, ["Rosetta, not Roulette"](https://www.opensanctions.org/articles/2025-09-11-logic-v2/), September 2025. (The URL is dated 2025-09-11; the page itself states a later publication date.)
- [Foursquare Location Matching](https://www.kaggle.com/competitions/foursquare-location-matching), Kaggle, 2022, and its [leak correction](https://www.kaggle.com/competitions/foursquare-location-matching/discussion/338035).
- [Overture Maps places guide](https://docs.overturemaps.org/guides/places/).
- Robin Linacre and the MoJ Analytical Services team, [Splink](https://github.com/moj-analytical-services/splink). An implementation of the Fellegi-Sunter model, and its [term-frequency adjustments](https://moj-analytical-services.github.io/splink/topic_guides/comparisons/term-frequency.html), which price agreement per value rather than per field.
- Robin Linacre and the MoJ Analytical Services team, [uk_address_matcher](https://github.com/moj-analytical-services/uk_address_matcher). Token frequency computed over the corpus being linked, abbreviations expanded before comparison, common end tokens handled as their own category.
- Nils Reimers and Iryna Gurevych, "Making Monolingual Sentence Embeddings Multilingual using Knowledge Distillation," *EMNLP*, 2020. The recipe behind the `paraphrase-multilingual-MiniLM` model measured here. [arXiv:2004.09813](https://arxiv.org/abs/2004.09813)
- Peter Christen, *Data Matching*, Springer, 2012.

*Related: [a representation engine, not an inference engine](../about/representation-engine.md) · [a place is not a point](../tutorials/a-place-is-not-a-point.md) · [the place benchmark](../about/place-benchmark.md) · [how arche works](../tutorials/how-it-works.md).*

## Acknowledgements

The embedding critique here is not original and should not be read as such.

[Ethayarajh (2019)](https://arxiv.org/abs/1909.00512) showed that the upper layers of contextual encoders are strongly anisotropic, so vectors bunch into a narrow cone and arbitrary pairs sit at high cosine. [Steck, Ekanadham and Kallus (2024)](https://arxiv.org/abs/2403.05440) made the sharper point that cosine similarity of learned embeddings can be governed by regularisation choices rather than by the data, and that the resulting numbers can be, in their words, arbitrary and therefore meaningless. Both papers predate this post and both are more careful than it is.

The decision-theoretic frame, including the third region, is [Fellegi and Sunter (1969)](https://www.tandfonline.com/doi/abs/10.1080/01621459.1969.10501049). The idea that token rarity should govern how much an agreement is worth is standard in record linkage, and is put especially clearly in [Robin Linacre's address-matching work](https://www.robinlinacre.com/address_matching/).

The model tested is `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, chosen because it is a common default rather than because it is the strongest available. A larger multilingual encoder would score some of these pairs differently, and that is said in the body rather than buried here.

## Notes

1. The frictions in the opening section are ordinary rather than exotic. Every one of them is a documented failure mode in production identity systems, and the reason they read as small is that the cost lands on one person at a time.
2. Eleven pairs is an illustration, not a benchmark. They were selected after looking at the scores, to show specific failure modes, with no sampling frame and no independently established labels.
3. The tokenizer explanation is a plausible mechanism, not a demonstrated cause. The ablation that would separate segmentation effects from twelve layers of transformer has not been run.
4. What the examples do establish is narrow and still worth stating: this model's raw cosine is inadequate as a merge signal on these names. They establish nothing about embeddings in general.
