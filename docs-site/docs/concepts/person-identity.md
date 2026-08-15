# Person identity: the attributes, and who assigned them

*What a person's record is made of, why most of it was given to them by an institution, and why the technique that builds a patient record is the same one that builds an advertising profile.*

---

Someone says "Amara from accounts". You know who they mean.

Now put that in a system. There is no field called *from accounts*. There is a payroll row, a badge number, an email address, a bank account, a phone that used to belong to someone else, and a name that appears eleven times in the staff directory. The knowledge that made the sentence work is not in any of them.

That gap is the subject of this page. **A person is not a record. A record is a claim someone made about a person, using the fields their system happened to have.**

## Two old answers, and why the argument still matters

There is a very old disagreement underneath every identity system, and it is worth naming because modern systems keep picking a side without noticing.

**David Hume's bundle theory** says a person just *is* a bundle of attributes, each with independent value. There is no extra thing holding them together. Take away the attributes and nothing remains.

**Descartes' substance theory** says the attributes are borne by something that persists. That substance is why you are the same person you were at seven, despite changing your hair, your beliefs, your address and your legal name.

Both matter here. **A database is a committed bundle theorist.** It has rows of attributes and no substance. Which is precisely the problem:

> We have no digital substance to connect the various attributes we present online.

Your hospital record, your bank record and your employer's record are three bundles with nothing joining them, and no version of you that owns the join. Every system that wants a complete picture has to reconstruct the substance by *inference*, from attributes. That reconstruction is entity resolution, and it is what this whole engine does. Worth being clear-eyed about it: **arche is a machine for guessing at a substance that the data does not contain.**

## Attributes, traits, and preferences

Not everything on a record does the same job.

| | What it is | Changes | Examples |
|---|---|---|---|
| **Traits** | inherent, or nearly so | slowly or never | birthplace, date of birth, biometrics |
| **Attributes** | acquired | often | address, employer, bank balance, allergies |
| **Preferences** | defaults and desires | at will | seat choice, favourite brand, contact method |

A matcher that treats these alike will do something silly. Two people sharing a **preference** is nearly meaningless, two sharing a **trait** is worth a great deal, and an **attribute** sits between and decays. An address from 2015 is weak evidence in 2026 and strong evidence about 2015.

## Three words the field uses, and what they actually mean

Identity literature has its own vocabulary, and it is worth pinning down because it sorts identity on a *different axis* from the one that follows.

**Foundational identity** is general-purpose. Civil registration, a national ID, a birth record. It was not created for any particular transaction, and its job is to establish that you exist and are who you say. Roughly a billion people do not have one.

**Functional identity** was created for one job. A driving licence proves you may drive. A health card enrols you in a scheme. A tax number lets a state collect. Each is excellent at its own purpose and was never meant to travel, which does not stop everyone using them as general-purpose proof anyway.

**Federated identity** is the plumbing between silos: an identity issued in one domain, accepted in another. Signing in with Google. eIDAS across EU member states. It does not create identity so much as move recognition around.

Now the part people conflate. **Those three describe what an identity is *for*. The tiers below describe who assigned it and how long it lasts.** Different axes, and you need both.

Push on it and something uncomfortable falls out. A national ID is *foundational* by purpose, and by the second axis it is still something a state issued and a state can revoke. Statelessness is exactly that revocation. So even foundational identity, the thing meant to be bedrock, is lent rather than owned. **The only attributes genuinely yours are traits, and biometrics belong to that set in the worst way: irrevocable, and therefore unfixable once copied.**

## Who assigned it, and for how long

The most useful cut is not what an attribute *is* but **who gave it to you**. Andre Durand's three tiers, from 2002, still describe the landscape better than most current writing.

<div class="arche-tiers">
<div class="tier t1">
  <div class="tier-head">
    <span class="tier-n">Tier 1</span>
    <span class="tier-name">Yours</span>
    <span class="tier-life">durable, and you did not choose any of it</span>
  </div>
  <div class="tier-items">
    <span>Name at birth</span><span>Date of birth</span><span>Place of birth</span><span>Biometrics</span>
  </div>
  <p class="tier-foot">Notice how short this list is, and that biometrics are on it precisely because they cannot be reissued when they leak.</p>
</div>
<div class="tier t2">
  <div class="tier-head">
    <span class="tier-n">Tier 2</span>
    <span class="tier-name">Lent to you</span>
    <span class="tier-life">exists while a relationship exists, and expires with it</span>
  </div>
  <div class="tier-items">
    <span>Driving licence</span><span>Passport</span><span>Staff number</span><span>Work phone</span><span>School roll</span><span>Bank account</span><span>Home address</span><span>National ID</span>
  </div>
  <p class="tier-foot">Most of your record. Every item here was issued by somebody who can also withdraw it.</p>
</div>
<div class="tier t3">
  <div class="tier-head">
    <span class="tier-n">Tier 3</span>
    <span class="tier-name">Assigned to you</span>
    <span class="tier-life">by parties you never contracted with, for their purposes</span>
  </div>
  <div class="tier-items">
    <span>Cookie · device ID</span><span>Watch history</span><span>Abandoned baskets</span><span>Behavioural segment</span><span>Lookalike audience</span><span>Inferred household</span>
  </div>
  <p class="tier-foot">The richest record of who you are, and the one you have least claim to.</p>
</div>
</div>

Read the middle band again, because it is most of your record and it is **borrowed**. Durand's line is the one to keep:

> Once the relationship that defines the identity is terminated, the attributes associated with it are no longer useful.

Which is why matching on a work email is fine today and misleading in three years, and why an old address is not a wrong address but a *correct address about a former time*. Most identity data has a validity period, and almost no schema records one.

The bottom band is the uncomfortable one. Durand's own description of those relationships is that they are "usually forced on us."

## Customer 360 is entity resolution with a different customer

This is the connection worth making explicitly, because the two literatures barely acknowledge each other.

A hospital wanting one patient record and an ad platform wanting one customer view are performing **the same technical operation**. Take fragmented records from systems that never agreed on identifiers. Decide which refer to the same person. Merge. The vocabulary differs (Customer 360, Marketing 360, identity graph, golden record, master data management) and the algorithms are the same algorithms.

What differs is not the technique. It is three things the technique cannot see:

**Who asked.** A patient wants their notes joined. Nobody asks to be joined into a lookalike audience.

**Who benefits.** In a health record, the person whose data it is. In an identity graph, the party buying the segment.

**What a mistake costs.** A false merge in a hospital puts a stranger's allergy in your file. A false merge in an ad graph shows you the wrong advert, which is nearly free, which is exactly why ad-tech tolerates match rates that would be malpractice in a clinic.

That last one explains a lot of the field. **Precision standards follow the cost of being wrong**, and a great deal of published entity-resolution practice was calibrated in a domain where being wrong is cheap.

So arche has to be honest about this: **the join that gives a ministry a clean facility list is the same join that builds a behavioural profile.** The engine cannot tell them apart. Only the policy around it can, which is why the [gate is described as a values statement rather than a cleverness](sameness-and-similarity.md), and why *unlinkability* sits in [the list of things we do not yet defend](arche-in-practice.md).

## What your streaming account knows

Take the tiers seriously for a moment and look at where the density actually is.

Your foundational identity says you exist, when you were born and where. Four or five facts, and a state holds the register.

Your streaming account knows what you watched, what you finished, what you abandoned eight minutes in, what you re-watched at two in the morning, what you started while someone else was in the room and stopped. A supermarket loyalty card knows when your household changed size, roughly when someone stopped eating meat, and plausibly when someone became pregnant, weeks before most of the family. A browser cookie knows what you looked at and did not buy.

None of that is a **trait**. It is preferences and habits, which are the softest, most revealing and most commercially valuable material in the whole record. And every bit of it sits in **Tier 3**: assembled by a party you never contracted with, held on their infrastructure, used for their purposes.

So the position is genuinely odd. **The thinnest record about you is the one designed to identify you. The richest is the one you have least claim to.** And the rich one is increasingly what decides things: what you are shown, what you are charged, what you are offered credit for.

## The thing current identity systems are actually for

This deserves saying plainly because it explains most of the frustration.

Identity systems are, overwhelmingly, **recognition systems built so organisations can know users**. They are not proof systems built so people can demonstrate things. Every design choice follows from that. The organisation accumulates, the person does not. The organisation holds the register, the person holds a card that points at it. When you move between organisations nothing travels with you, so each one starts again, builds its own partial picture, and treats it as authoritative.

The asymmetry is the product rather than a side effect. Your bank knows a great deal about you and you know almost nothing about your bank's model of you. You cannot read it, correct it, or take it with you.

[Tim Berners-Lee](https://www.theregister.com/2022/01/20/tim_bernerslee/) has been making a version of this argument for years, and calls the pattern **silos**: too much power and too much personal data sitting with a handful of platforms, with your own photographs, posts and history stuck inside networks you cannot extract them from. His framing of the remedy is unusually blunt for a technical argument:

> You should have complete control of your data. It's not oil. It's not a commodity.

And that it should not be sellable, because it is a right rather than an asset.

That diagnosis is what [Solid](https://solidproject.org/) exists to answer: personal data in pods you control access to, with applications visiting the data instead of the data being copied into applications. It is the storage half of the substance problem, and it is why the criticism in this project's own planning is about timing rather than architecture.

## Who controls the join

Three arrangements, and almost everything you use is the first.

**Administrative.** The organisation owns the rules, the attributes and the sharing. Your bank decides what your bank identity is. This is the dominant model and the reason your data is scattered across parties who each hold a partial, authoritative-feeling copy.

**User-centred.** You choose among approved providers. Signing in with Google or Apple. Better than nothing, and it relocates the administrative power rather than removing it: the provider still sees every login.

**Self-sovereign.** Parties authenticate each other cryptographically, and the person holds their own credentials and discloses selectively. The **issuer, holder, verifier** triangle: a university issues a degree credential, you hold it, an employer verifies it without contacting the university.

Self-sovereign identity is the answer to the substance problem. If you hold credentials that are cryptographically bound to you, *you* are the thing connecting the attributes. Digital substance, restored.

arche already implements a slice of this, and it is worth being precise about which slice. Decisions can be issued as verifiable credentials with selective disclosure and holder binding, so a subject can prove one claim without revealing the rest. What arche does **not** have is the storage half: a place the person keeps their records and grants scoped access. That is what [Solid pods](https://solidproject.org/) are for, and the honest assessment is that they are architecturally right and commercially premature. Solid has been imminent since 2018. A cooperative in Sefwi Wiawso will not self-host, so somebody hosts for them and the sovereignty becomes nominal, which is worse than not claiming it.

The design position that follows: build a storage seam a pod could satisfy, implement it against something boring, and plug Solid in when the ecosystem is real.

## What this means for matching a person

Four rules fall out of the tiers, and each is implemented rather than aspirational.

**A Tier 2 identifier is strong and dated.** A national ID or phone number clears the distinctiveness gate. It should also carry a validity period, and today it does not. That is a named gap.

**Names are Tier 1 and weak anyway.** A name is genuinely yours and shared with thousands of people. This is the whole reason a frequency table exists: agreeing on a name is worth exactly what its rarity says.

**A relationship attribute is not an identity attribute.** Two people at one address are a household, not a person. Address amplifies a decision and must never manufacture one.

**Do not merge Tier 3 into Tier 1.** An inferred segment is a claim someone made about a person for their own purposes. Treating it as evidence of identity launders a guess into a fact, and it is the specific mechanism by which advertising-grade inference ends up in a record that decides whether someone gets a loan.

## What we do not claim

**arche does not give anyone digital substance.** It infers a join from attributes and signs the inference. That is useful and it is not sovereignty. A person still cannot hold their own arche decision and present it.

**There is no subject-facing surface.** A signed decision is only accountability infrastructure if the person it is about can see and contest it. Today the artifact serves regulators and counterparties. Both NDPA and GDPR grant rectification rights, and the appeal path is undesigned. This is simultaneously the largest gap and the most on-mission thing available to build.

**A linking engine has no opinion on when linking is wrong.** The `protect` layer masks values; it does not resist linkage. A project whose stated mission is open entity intelligence *for* the majority world should have a written position on uses it does not endorse, and does not yet have one.

## Acknowledgements

The framing of this page follows notes by Dennis Irorere on [the nature of identity](https://github.com/denironyx/systems-that-decide-what-matters/blob/main/01-foundations/01-the-nature-of-identity-and-digital-identity.md) and [what digital identity is](https://github.com/denironyx/systems-that-decide-what-matters/blob/main/01-foundations/02-what-is-digital-identity.md), including the bundle-versus-substance reading and the observation that we lack a digital substance to connect the attributes we present online.

The three-tier model is **Andre Durand's**, from 2002, and it has aged better than most identity writing of the period. The attributes, traits and preferences split comes from the same tradition of identity-systems literature, notably Phil Windley's [*Learning Digital Identity*](https://www.oreilly.com/library/view/learning-digital-identity/9781098117689/) (O'Reilly, 2023), which is the best current single source on this material and where the functional definition of an identity system quoted at the top of these notes originates.

The bundle and substance positions are Hume's and Descartes' respectively, and the argument that a database is committed to the former is not original either.

[Kim Cameron's Laws of Identity](https://www.identityblog.com/stories/2005/05/13/TheLawsOfIdentity.pdf) (2005) remain the clearest statement of why a universal identifier is a bad idea, which is the reason arche produces keyed, purpose-scoped pseudonyms instead of one durable identifier per person.

[Solid](https://solidproject.org/) is Tim Berners-Lee's project, and the criticism of its timing here is about ecosystem maturity rather than about the architecture, which we think is right.

## Notes

1. Durand's tiers are used here as a description of how identity data actually arrives, not as a normative claim that Tier 3 should not exist. The argument is that a system should know which tier a field came from, because the tiers have different evidential weight and different consent stories.
2. "Customer 360 is the same operation" is a claim about technique, not a claim that the two are morally equivalent. The differences are in who asked, who benefits, and what an error costs, and those differences are real.
3. Validity periods are the most consequential missing feature on this page. A co-reference decision is true *as of* its evidence, and neither the decision nor the credential currently records the period the underlying attributes were valid for.

## Related

- [Sameness and similarity](sameness-and-similarity.md) for why a matcher cannot observe identity and has to decide it
- [Place identity](place-identity.md) and [Product identity](product-identity.md) for the same attribute analysis on other entity types
- [Attest](attest.md) for the credential machinery, including selective disclosure and holder binding
- [The five ER activities](er-activities.md) for why arche deliberately has no identity registry
