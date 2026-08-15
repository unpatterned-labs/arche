# You do not need an account to buy bread

*Most relationships should end. The web cannot express that, which is why you have four hundred accounts. What decentralised identity fixes, and the parts of it where this project has no business at all.*

---

You walk into a shop. You pick up bread. You pay. You leave.

Nobody asked your name. No profile was created. The shop does not now hold a record of you that persists after you are out of the door, and if you never return, nothing anywhere needs cleaning up. The relationship lasted ninety seconds and that was the correct length for it.

Now imagine the same shop insisted you create an account first. Email, password, verification link, cookie banner, and a marketing preference you will get wrong. To buy bread.

That is the web. Not as a design decision anyone defended, but as an accident we have lived inside so long it stopped looking like one.

## A day, and eleven relationships

Yesterday, without thinking about it once, I entered into or renewed about eleven relationships.

WhatsApp before getting up, because that is where my family is. YouTube Music on the way in, which is Google, which is also my email, my calendar and the login I use for a dozen other things. Three work systems, each with its own account. A delivery app at lunch, where I typed my address again, because the address I have typed into four other delivery apps is not available to this one. Amazon in the evening for something dull. Netflix after that, which has been learning what I watch for years and is genuinely good at it now.

Every one of those is a different kind of relationship, and the interesting thing is that **none of them is the kind I would have chosen if choosing were on offer.**

Look at what each one actually is:

| I use it for | What I get | What they keep | If I leave |
|---|---|---|---|
| **WhatsApp** | my family, reachable | who I talk to, and how often | my family is still there, so I do not |
| **YouTube Music** | playlists I built over years | the playlists | I rebuild them by hand, one at a time |
| **Netflix** | recommendations that took a decade to get good | every minute I have ever watched | I start again from nothing |
| **A delivery app** | lunch | my address, my card, a profile I did not want | nothing, and I retype my address elsewhere |
| **Amazon** | one click | purchases, addresses, cards, returns | the friction comes back |
| **My bank** | money that moves in seconds | the account | the money leaves in an afternoon |

Read the last column downward. That is the whole essay in one table.

## Four kinds of lock-in, and only one of them is fair

They are not stuck for the same reason, and the differences matter because the fixes are different.

**Data lock-in.** Netflix is good because it has watched me watch things for ten years. That history is the product. If I move to Prime, I do not just lose a subscription, I lose the decade, and I start with a service that knows nothing about me and is therefore worse at the one thing I want from it. **The switching cost is not the price. It is the amnesia.**

**Network lock-in.** WhatsApp holds nothing especially valuable about me. It holds everyone I know. This is the honest kind: it is not a trick, it is what a communication network *is*, and no data portability standard fixes it. Only interoperability does, which is a different and harder argument.

**Convenience lock-in.** Amazon has my cards and addresses and knows my sizes. Leaving costs me an afternoon of re-entry. Mild, and the most fixable of the four.

**Identity lock-in, which is the one that compounds.** I sign in to a dozen services with Google. Those services do not have my password, they have a Google assertion. Which means **Google can end all of them at once**, and if I ever lose that account I do not lose one relationship, I lose the keys to the rest.

That last one deserves more alarm than it gets. Signing in with a big company solved a real problem, and password fatigue was genuinely miserable. In exchange it produced a single revocable dependency underneath a whole digital life. It is the model Phil Windley calls **user-centred**: better than an account everywhere, and still not yours, because the provider sits in the middle of every login and sees each one.

## The thing I actually want, and cannot have

Here is the small, specific, apparently reasonable thing.

I would like to take my viewing history from Netflix to Prime Video. Not the films. The *history*. The record of what I watched, finished, abandoned and re-watched, which I generated, minute by minute, by watching.

I cannot. There is no export worth the name and no import at all, and the reason is not technical. A watch history is a few megabytes of rows.

Now compare with money, which is where this gets embarrassing.

## Your money moves. Your identity does not.

I can pay a stranger in another country in about two seconds. I can move my salary between banks and be done by the afternoon. Card networks, [UPI](https://www.npci.org.in/what-we-do/upi/product-overview) in India, PIX in Brazil, M-Pesa across East Africa: value crosses institutional boundaries constantly, at enormous scale, between parties who are fierce competitors and have never met.

That interoperability did not emerge. It was **built**, deliberately, with shared standards, a settlement layer, and in the strongest cases a central bank or regulator that simply required it. UPI and PIX went from nothing to national defaults in a few years because a public rail existed and participation was mandatory.

Identity got none of that. There is no clearing house for a relationship, no settlement layer for a preference, no regulator requiring that my watch history be portable the way my salary is.

And the reason is worth stating plainly, because it is not an oversight:

> **Money is fungible and your data is not.** A bank's advantage does not come from holding *your particular pounds*, so letting them move costs it a deposit and nothing else. Netflix's advantage comes precisely from holding *your particular history*. Portability is resisted because the data is the moat.

Which tells you that this will not be fixed by asking nicely. Every previous case where data moved at scale, from phone number portability to open banking, happened because somebody made it compulsory.

## The accident

[Kim Cameron](https://www.identityblog.com/stories/2005/05/13/TheLawsOfIdentity.pdf) diagnosed it in 2005, in a sentence worth reading slowly:

> The Internet was built without a way to know who and what you are connecting to.

There is no identity layer. TCP/IP moves packets. HTTP moves documents. Neither has any notion of a person, so when the web needed one, every site built its own. The result, as Phil Windley puts it in [*Learning Digital Identity*](https://www.oreilly.com/library/view/learning-digital-identity/9781098117689/), is a **patchwork of identity one-offs**: a username and password for every relationship, on every site, forever.

That patchwork has a name. It is **administrative identity**, and it means the organisation owns the relationship. It decides what you are, keeps the register, sets the rules, and can end the relationship without your involvement. You do not hold an identity so much as appear in theirs.

Windley's word for what this produces is the one that stuck with me: **anemic relationships**. Thin, one-directional, and asymmetric. The shop knows you. You do not know the shop. Multiply by four hundred accounts.

## Ephemerality is a feature we deleted

Here is the thing the grocery store gets right and the web cannot express.

Go back to the table. Not one of those eleven relationships needed to be permanent, and most of them became permanent because the architecture had no other setting.

**In the physical world, the default relationship is ephemeral, and persistence is opt-in.** You can shop anonymously. You can also hand over a loyalty card, and that is a choice you made, in the moment, for a benefit you understood.

Online the default is inverted. Persistence is mandatory and ephemerality is impossible. You cannot buy the digital equivalent of bread without leaving a record, because the only mechanism available for *doing a thing* is *becoming a subject in someone's system*.

And notice what this costs on both sides. You accumulate accounts and breaches. The organisation accumulates a liability it did not want: a database of people who bought bread once in 2019, which it must now secure, govern, and eventually explain to a regulator.

**Almost nobody wanted the persistent relationship. The architecture had no way to say no.**

## What the alternative actually looks like

The fix is not "log in with a different company". That relocates the administrative authority rather than removing it.

The fix is to make **claims** presentable without an account. A credential you hold, issued by someone a verifier already trusts, disclosed selectively, and checkable without the verifier contacting the issuer at all.

The shape is the **issuer, holder, verifier** triangle. A state issues you a proof of age. You hold it. A shop verifies it. The state never learns you bought anything, and the shop never learns your name, your address or your date of birth. It learns one bit: over eighteen, yes.

Then the interaction ends. Nothing to store, nothing to breach, nothing to delete on request.

And for the relationships I *do* want to keep, the same machinery gives me the thing the table said I could not have. If my viewing history lives in a store I control, and Netflix reads it under a scope I granted rather than copying it into a warehouse I cannot see, then moving to Prime is granting a different application the same scope. The decade comes with me. **The recommendations get to compete on how well they use my history, instead of on who managed to capture it first.**

That is a better market, not just a nicer arrangement for me. Data lock-in lets a service coast on accumulated history. Portability makes it earn the relationship every month.

The move underneath is worth naming, because it inverts the usual model. **The relationship becomes the primitive, not the identity.** Relationships have lifespans, and a well-built system lets both parties choose one: ninety seconds for bread, years for a bank, and revocable at either end. Persistence becomes something you opt into rather than the price of entry.

That is also the answer to the [data-silo problem Tim Berners-Lee keeps pointing at](https://www.theregister.com/2022/01/20/tim_bernerslee/). If applications visit data you hold, in a pod you control, instead of copying it into a database they hold, then the silo never forms. Credentials are the presentation half. Pods are the storage half. Both are necessary and neither is sufficient alone.

## Why this gets more urgent, not less, with agents

An [agent acting on your behalf](who-acted.md) needs credentials to act. If the only available model is administrative, the agent's operator ends up holding the keys to your bank, your inbox, your health portal and your government services. That is the most concentrated identity relationship ever assembled, and the convenience gradient runs straight toward it.

Scoped, expiring, verifiable credentials are the only version of that story that does not end in one company holding everything. **Decentralised identity stops being a philosophical preference at the point where software starts acting for you**, and starts being the difference between delegation and surrender.

## Where arche fits, and where it does not

This is the part worth being straight about, because the honest answer includes a fair amount of "not us".

### Not us, and it should not be

**Credential exchange, wallets, authentication.** Proving you hold a key, presenting a credential, checking a signature against an issuer. That is DIDComm, verifiable credential formats, wallet software. It is a different discipline and we have no advantage in it.

**The ephemeral interaction itself.** A shop learning one bit about you and nothing else is exactly the case where a resolution engine must stay out of the room. There is nothing to resolve, and building anything that wanted to would be working against the point.

And the sharper version, which I would rather write down than have someone else observe:

> **arche is a linking engine, and linking is precisely what ephemerality is designed to defeat.** In a world where interactions leave nothing behind, there is less for us to do with people, and that is a success rather than a lost market.

A project whose mission is open entity intelligence for the majority world does not get to quietly prefer the architecture that generates more records to reconcile.

### Still us, and structurally

Four places where the work does not go away, and one of them is the hard part of every national identity programme.

**Issuance is a resolution problem wearing a cryptography costume.** Before a state can issue you a credential it has to decide *which record in the register is you*. Every national ID rollout discovers that deduplicating the register is the expensive half and the cryptography is the easy half. A credential system built on a register full of duplicates issues duplicate credentials with perfect signatures.

**Legacy does not evaporate.** A health system with forty years of paper still has to reconcile it. Decentralised identity improves the *next* record; it does nothing for the previous forty million, and those are the ones deciding whether someone gets treated today.

**A DID is not a referent.** A credential says it was issued by a party. That party is a cryptographic identifier, and deciding it denotes *the cooperative in Sefwi Wiawso you actually mean* is co-reference, not verification. This is a real hole in the standards: [UNTP](../concepts/entities.md) assumes party identifiers already agree, and its identity anchor only covers the case where an authoritative register exists. For a cooperative in a district with no register, none does.

**Most entities cannot hold a wallet.** A clinic does not have a phone. A cooperative does not present credentials. A plot of land, a shipment, a facility, a company registration: their records are held *about* them, by others, in systems that never agreed. Decentralised identity is a **person-shaped solution**, and the reconciliation problem for everything that is not a person is untouched by it.

### What follows for us

If decentralised identity works, the person lane should shrink, and we should be glad. The centre of gravity moves to the entities that cannot hold credentials: organisations, places, products, documents. Which is, as it happens, [where the work has actually been going](../concepts/entities.md).

The seam worth building is narrow and concrete: a **storage interface a pod could satisfy**, so records can live somewhere the subject controls and be fetched under scope rather than copied. Implement it against something boring, keep the interface honest, and plug Solid in if and when the ecosystem is real. Solid has been imminent since 2018, and a cooperative in Sefwi Wiawso will not self-host, so somebody hosts for them and the sovereignty becomes nominal. That is a timing criticism, not an architectural one.

And one thing we already have that belongs in this world: a decision can be issued as a credential with selective disclosure and holder binding, so a subject can prove one claim without revealing the rest, and a verifier can reject a replayed presentation. The machinery is there. What is missing is the half where the **subject** holds it, which is the same gap as the missing appeal path.

## What would make this wrong

**Nobody wants ephemerality enough to change anything.** The friction argument cuts here too. If people will accept an account for everything, and they have for twenty years, the pressure never builds.

**Verifier adoption never arrives.** Credentials are worthless until the shop can check one. Issuers move first, verifiers move last, and the gap is where most of these efforts have died.

**Portability arrives and nothing changes.** The EU already grants a right to data portability, and it has produced a lot of zip files and very little movement. A right to receive your data is not the same as a rail that carries it somewhere useful, and if portability keeps meaning "here is a JSON export, good luck", then the lock-in survives the regulation intact.

**Ephemerality and accountability pull apart.** The strongest objection, and the one I have not resolved. A decision nobody can trace is also a decision nobody can appeal. There is a real tension between an interaction that leaves nothing behind and a person's right to contest what was decided about them, and anyone selling decentralised identity as pure gain is not looking at it squarely.

## Acknowledgements

The grocery-store framing, the reading of the web as a **patchwork of identity one-offs**, and the term **anemic relationships** for what administrative identity produces are Phil Windley's, from [*Learning Digital Identity*](https://www.oreilly.com/library/view/learning-digital-identity/9781098117689/) (O'Reilly, 2023). He also founded the Internet Identity Workshop, which is where a great deal of this thinking was worked out in public over two decades.

[Kim Cameron's Laws of Identity](https://www.identityblog.com/stories/2005/05/13/TheLawsOfIdentity.pdf) (2005) named the missing identity layer and argued against universal identifiers, twenty years before it became fashionable.

[Tim Berners-Lee](https://www.theregister.com/2022/01/20/tim_bernerslee/) on silos, and [Solid](https://solidproject.org/) as the storage half of the answer.

## Notes

1. "Ephemeral" here means the relationship ends, not that the transaction is untraceable. A shop still has a receipt and a payment record. The claim is narrower: it should not also need a durable profile of the buyer.
2. The four "still us" cases are not a defence of the market. Three of them are consequences of decentralised identity being incomplete, and the fourth is a consequence of it being person-shaped. If both were fixed, the honest position would be that this part of the work was transitional.
3. The payments comparison is a comparison of *interoperability*, not of technology. Card authorisation takes seconds and settlement takes days, which does not weaken the point: the boundary between institutions is crossed routinely and by design, which is exactly what identity data cannot do.
4. This is a position piece. Nothing in it is measured, and the prediction about where arche's centre of gravity should move is a strategic judgement rather than a finding.

## Related

- [Who acted?](who-acted.md) for why delegation, not identity, is what an agent needs
- [Person identity](../concepts/person-identity.md) for the tiers, the substance problem, and the asymmetry these systems were built to produce
- [Entities](../concepts/entities.md) for the things that cannot hold a wallet
