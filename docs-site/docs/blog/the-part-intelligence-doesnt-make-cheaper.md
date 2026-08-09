# The part intelligence doesn't make cheaper

*Reasoning is collapsing in price. Knowing which real thing you are talking about is not.*

---

Two records. The same four words in each.

```text
Kauyen Adam Health Post  <->  Kauyen Adam Health Post     match    0.00 km
Kauyen Adam Health Post  <->  Kauyen Adam Health Post     review  11.06 km
```

Both pairs come from Kano State's health facility registry, reconciled against OpenStreetMap. Every name comparator scores 1.0 on both. One pair is a clinic recorded twice. The other is two clinics eleven kilometres apart that happen to share a name.

Nothing in the language tells you which is which.

## This is not a language problem

Ask the best model available whether those records describe the same clinic and it will answer. Fluently, with a confidence score, and correctly about as often as the phrasing happens to favour.

We tested this rather than assuming it. On thirty pairs drawn from a real reconciliation, a frontier model was **better** than our engine at one thing: spotting that `Sari Girin` and `Sarigarin` are one Hausa name written two ways. That is a genuine strength, and we [fixed our own gap](../concepts/place-benchmark.md) because of it.

On five other pairs — records with **identical names at identical coordinates** — the same model returned `different` or `unsure`, one of them at 0.90 confidence. Asked the same question five times at temperature zero, it gave two different answers.

None of that is a failure of intelligence. The model was asked a question, and producing an answer is what it is for. The information required to answer correctly was never in the text.

> Which real thing a name refers to is not a fact you can reason your way to. It is a fact about the world that somebody has to establish, record, and be willing to stand behind.

## The bottleneck moves

When inference was expensive, the scarce thing was reasoning. Every system was designed around getting the most from a small budget of thought.

That constraint is dissolving. Cost per token has fallen by orders of magnitude in a handful of years and will keep falling. Reasoning is becoming something you can spend freely.

So the scarcity moves — to the thing reasoning consumes. **Grounding.** Not facts in the encyclopaedic sense, which models absorb well, but the unglamorous, constantly-shifting binding between a symbol and a thing: which clinic, which supplier, which person, which batch, which account.

That binding cannot be derived. It has to be established from evidence, recorded somewhere durable, corrected when it turns out to be wrong, and vouched for by someone who will still be there when it is questioned. No quantity of cheap reasoning produces it, because it is not a conclusion. It is an observation about the world.

This is the part that does not get cheaper on its own. It gets cheaper only if somebody builds the shared thing.

## Why agents make this urgent rather than easier

An agent that reasons is interesting. An agent that **acts** is consequential, and every action touching the world runs into an identity question. Pay this supplier. Ship to this clinic. Merge these two customers. Flag this person against a sanctions list.

Two men named Khalid Mehmood appear on the same sanctions programme, in the same country, with different fathers and different national identity numbers. Every production matcher we have tried treats them as one person. An agent inheriting that answer does not fail gracefully — it acts, immediately, on a merged identity that never existed.

The failure mode is worth naming precisely. **A model that is uncertain still produces output.** It does not stop. Give it authority to act and uncertainty converts silently into consequence, at machine speed, with a confidence score attached that carries no information about whether it was right.

So an agent needs something underneath it willing to do the one thing the model will not: stop, and say *this needs a person*.

| | |
|---|---|
| **What a model is good at** | Reading messy text into structure. Proposing candidates. Spotting that two spellings might be one word. Generating explanations a human can check. |
| **What it cannot supply** | The same answer twice. A verdict it declines to give. Evidence you can audit six months later. Any signal distinguishing a good guess from a bad one. |
| **What has to exist** | A deterministic layer that decides what can be decided, refuses what cannot, and signs the result so the decision survives the argument about it. |

## Representation, not inference

The insight arche is built on is small and, once seen, hard to unsee.

The mathematics of record linkage was settled in 1969. Fellegi and Sunter gave us the model, and open tools implement it better than we do — [Splink](../tutorials/arche_vs_alternatives.md) runs it with properly estimated parameters, and we do not try to compete.

What no engine ships is the **input** that mathematics requires. Whether `Diallo` agreeing with `Jallow` counts as agreement. Whether agreeing on `Ibrahim` is worth as much as agreeing on `Gyaranya`. Whether eleven digits are a national identity number or a phone number. Whether *behind the central mosque, Ungwan Rimi* is an address.

That layer is the representation. It is what makes a generic engine work on real names, and every generic engine is silently wrong without it.

And here is why it matters beyond one library: **representation is data, and data can be shared.** A model's knowledge lives in weights nobody can inspect, correct, or fork. A representation layer ships as files you can read, diff, cite, argue with, and send a correction to. When a Hausa speaker tells us our vowel rule is wrong, that is a pull request, not a retraining run.

> A model you cannot correct is a claim. A file you can correct is infrastructure.

## What it looks like built

Picture the layer existing. Not a product — a shared, public, correctable account of what the world's entities are called and which is which, with a signature on every decision derived from it.

A health ministry reconciles its facility list against three sources and gets back a merged list, a queue of the hundred cases that genuinely need a human, and a signed record of every merge anyone can re-check years later.

An agent about to move money resolves the payee against a registry, gets `review`, and stops — because refusing is a first-class answer rather than an error state.

A journalist runs a leaked dataset through it and can say *these two records are the same company* with evidence attached, instead of a hunch.

A person asks an organisation for everything it holds on them, and the organisation can actually answer, because it knows which records are theirs.

And underneath all of it, the corrections accumulate. Every adjudication a human makes is a signed fact about the world that makes the next decision cheaper. That is the compounding asset — not the matcher, which is commodity, but the accreting record of what has been decided and by whom.

## The economics, concretely

The cheaper-intelligence argument is not a metaphor. It has a bill attached.

One national facility crosswalk, 138 million candidate pairs after blocking:

| Approach | Cost | Replayable |
|---|---|---|
| Mid-tier model over every pair | $68,107 | No |
| Model over the review queue only | $9,944 | Partly |
| Deterministic engine, offline, on a laptop | $0 | Yes |

Measured at 164 tokens per pair against published pricing. The engine resolved a state-level crosswalk in 21 seconds with no network call.

Running a model over everything turns a laptop job into a line item, and buys an answer that changes between runs. Running it only where the deterministic layer has already said *I cannot decide this* costs a rounding error, and puts the model exactly where its strengths are real.

**The gate is what makes the expensive component affordable.** That is how this work makes intelligence cheaper: not by being smarter, but by refusing to spend intelligence on questions that were never uncertain.

## Why the hardest data first

arche was calibrated on African identity data, and that was a choice about difficulty, not about market.

It is the regime where every comfortable assumption fails at once. Names have no canonical spelling and cross colonial language boundaries — the same person is Mamadou Diallo in Dakar and Muhammad Jallow in Banjul. Identifier schemes are multiple, overlapping and young. Addresses are landmarks and directions rather than street numbers. Coordinates disagree by kilometres. Sources contradict each other and are each partly right.

A system that works there works on the easy cases by construction. The reverse is not true, which is why tools built on clean Western data fail quietly the moment they meet the majority of the world.

The regime is not confined to a continent. Supply chains, informal economies, historical archives, disaster response, any dataset assembled by many hands over many years — all of it is sparse, multilingual and contradictory. Africa is where the calibration was earned. It is not the edge of where it applies.

## The honest ledger

A document like this is usually where a project describes a finished thing. Here is the actual state, because the argument above is worth nothing if the reporting underneath it cannot be trusted.

| State | What |
|---|---|
| **Built** | Detection with statute citation — six packs, every detection carrying the section that classifies it |
| **Built** | Resolution that abstains — a pair sharing an exact national ID can still return `review`, because a high score is not distinctive evidence |
| **Built** | Signed decisions — content-addressed over the evidence and the exact representation that produced them |
| **Built** | A [published benchmark](../concepts/place-benchmark.md) — with its weak-label methodology, five stated limitations, and the case where it demonstrably gets a match wrong |
| **Partial** | The agent surface — masked projections and tool contracts exist; there is no MCP server yet, and saying otherwise would describe something unbuilt |
| **Partial** | Entity types beyond people and places — the artist pack proved a new type is data rather than code; books and food traceability are next |
| **Not yet** | Clustering — the engine returns pairwise edges. A merge that depends on other merges cannot be signed in isolation, so it waits for a benchmark that can measure it |
| **Not yet** | The accumulated adjudications — the compounding asset described above does not exist until people run this on real work |

In the weeks before writing this we found, in our own code, a verification function that accepted forged signatures, a matcher merging clinics 143 kilometres apart, and a redaction path leaking plaintext from spans it claimed to have removed. All three were shipped. All three were found by testing what we had *claimed* rather than what we had written. All three are fixed.

We also discovered that a benchmark we had described as independent validation was nothing of the sort — the two sources shared a common ancestor, which [two lines of arithmetic](../concepts/place-benchmark.md) would have shown us before we published. It is corrected in public, with the method that catches it.

That is the character of the project, and it is the only credential that matters for infrastructure. A layer everyone depends on has to be run by people who go looking for their own errors and say what they find.

## Why now

Two clocks are running. Obligations for high-risk AI systems — data governance, traceability — bind from December 2027, and a compliance substrate has to exist before the scramble rather than during it. Meanwhile every organisation that has just put an agent near its data is discovering it needs a deterministic, citable answer layer for the agent to call, because the model cannot supply one for itself.

They arrive at the same place from opposite directions: a signed, replayable answer to *which entity is this, and may this data move?*

The work is open source and Apache-2.0, the data is public, and the method is designed to be checked rather than trusted. That is not generosity. A representation layer only one company can inspect is not infrastructure — it is a dependency, and nobody should accept one for something this load-bearing.

> Intelligence is getting cheap. Knowing what's real is the thing worth building.

---

*Figures here are measured against public data and reproducible from the repository — the Kano facility crosswalk, the model comparison and the cost estimates all ship as runnable notebooks in [`examples/notebooks/`](https://github.com/unpatterned-labs/arche/tree/main/examples/notebooks). Where a number could not be reproduced it was removed rather than softened. `arche-core` is pre-beta: APIs change between alpha releases, and you should complete your own legal, privacy and security review before using it with real personal data.*
