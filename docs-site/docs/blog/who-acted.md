# Who acted?

*Agents are being built as if they are people. They are closer to driving licences. That mistake has a direction, and the direction is not the one the decentralisation story predicts.*

---

An agent books a flight for Amara. Wrong date. The airline's log says the booking came from an authenticated session belonging to Amara.

Now answer a simple question: **who acted?**

There are four candidates and the log recorded one of them.

**Amara**, who asked for a flight and did not check the date. **The agent instance**, which held the credential and made the call. **The model**, which produced the reasoning, and which was silently updated on Tuesday. **The operator**, who runs the agent, sets its guardrails and can see every action it has ever taken.

Every one of those is a defensible answer. The system stored the least useful one, because it was the only one the schema had a field for.

This is not an AI safety problem. It is an identity problem, and it is the oldest one there is, arriving in a costume nobody recognises.

## A day, and eight actions

Push the scene forward a couple of years and it stops being one booking.

Before I am awake, something has read my inbox and replied to a scheduling request, because it knows my calendar and the reply was obvious. It books a taxi and, on the way in, reorders the usual groceries. At my desk it files an expense claim, because it can read the receipt and knows the policy. Mid-morning it answers a customer question in my name, correctly, because it has read the last four hundred answers I gave. In the afternoon it renews a subscription, cancels a booking that clashed and rebooks it, and shares a project document with a new supplier so the meeting can happen.

Eight actions. Every one is something I would have done, most of them better than I would have done it, and I approved none of them individually, because approving them individually is the thing I was trying to stop doing.

Now run the opening question down the list.

| The agent did | Can it be undone | Who is answerable |
|---|---|---|
| **Reordered groceries** | yes, return them | me, and nobody minds |
| **Booked a taxi** | yes, for a fee | me |
| **Sent a scheduling reply** | no, but the harm is bounded | me |
| **Renewed a subscription** | yes, next month | me |
| **Filed an expense claim** | yes, and it is now a record | me, and if it was wrong it may be fraud |
| **Answered a customer in my name** | no, they have already relied on it | **my employer** |
| **Cancelled and rebooked** | partly, at a cost someone bears | unclear |
| **Shared a document with a supplier** | **never** | **unclear** |

The bottom of that table is where the trouble lives, and it is not where the safety conversation usually points.

## Five kinds of action, and only one has no undo

Sorting them properly matters, because a single approval model for all of them is either uselessly strict or quietly reckless.

**Reversible and cheap.** Groceries, a subscription, a calendar hold. Getting these wrong costs an afternoon. An agent should just do them, and the ceremony of asking is worse than the occasional mistake.

**Irreversible but bounded.** A sent email. You cannot unsend it, and the damage stops at embarrassment. Most agent writing treats this as the hard case. It is not.

**Financial.** A booking, a payment, a renewal. Reversible with friction, and the friction is the point: money has a whole apparatus of chargebacks and disputes built precisely because everyone accepted long ago that reversal must be possible.

**Binding on someone else.** The customer answer. I did not commit myself, I committed **my employer**, and a third party has already acted on it. There is no undo because someone else has already moved. Whatever authority the agent used, it was not mine to lend.

**Disclosure.** Sharing the document. This is the category with no reversal of any kind. A payment can be refunded, an email apologised for, a contract unwound. **You cannot un-tell someone something.** The document is on their laptop, in their mail archive, in their backups, and no amount of accountability infrastructure retrieves it.

Which produces a rule that I think is more useful than most of what gets written about agent guardrails:

> **Sort agent actions by reversibility, not by how consequential they feel.** A large reversible payment is safer to automate than a small irreversible disclosure, and the second one looks harmless right up until it is not.

This is the same distinction this engine already draws between believing two records match and *merging* them. A belief costs nothing to revise. A merge is usually permanent. Agents take that distinction, which was a database concern, and push it into everything a person does in a day.

## An agent is a driving licence, not a person

The [three tiers of identity data](../concepts/person-identity.md) are Andre Durand's, from 2002, and they sort a person's attributes by **who assigned them**.

Tier 1 is yours and durable. Your name, your birthplace, your biometrics. Tier 2 is lent to you by a relationship: a driving licence, a staff number, a bank account. Tier 3 is assigned to you by someone you have no relationship with, for their purposes.

Durand's rule for Tier 2 is the one to keep:

> Once the relationship that defines the identity is terminated, the attributes associated with it are no longer useful.

A driving licence is a state saying *this person may drive, until this date, subject to these conditions.* It is scoped, dated, revocable and about a capability rather than a self.

**An agent acting for you is exactly that shape.** It may do certain things, on your behalf, until you say stop. It is a delegated capability with an expiry.

And we are building them as Tier 1. They get their own accounts. Their own API keys. Their own persistent memory of you. Their own identity in the systems they touch, increasingly indistinguishable from a human user's. We are issuing passports where we should be issuing licences, and the difference is that a passport says who you are while a licence says what you may do.

That is a category error, and category errors in identity systems do not stay theoretical. They become the audit log you cannot reconstruct three years later.

## The substance you did not get to keep

Here is the part that inverts a story I find genuinely appealing.

A database has no [substance](../concepts/person-identity.md). It holds attributes and nothing that binds them. Your hospital record, your bank record and your employer's record are three bundles with no version of you that owns the join. That absence is why entity resolution exists at all: somebody has to reconstruct the connection by inference, because nobody stored it.

An agent looks like the fix. Finally something that holds all your context at once, remembers your preferences, knows your calendar and your accounts and your health appointments, and acts coherently across every system you touch. **Digital substance, at last.**

Except read that sentence again and ask where the substance lives.

Not with you. The coherence is real and it is **held by the agent**, which runs on infrastructure you do not control, under an operator who can change the model on Tuesday, revoke the memory, or read all of it. You have not acquired substance. You have rented it, and the landlord can see inside.

That is worse than the fragmentation it fixes. Fragmented identity is at least *distributed*: your bank cannot see your medical history because there is no join. An agent with your credentials is the join, and it is one company.

## The contrarian bit: agents will re-centralise identity

The standard telling has agents and self-sovereign identity arriving together. You hold your own verifiable credentials, your agent presents them selectively, you disclose one claim without revealing the rest. Individual empowerment, at last, with the platforms disintermediated.

I think the structural pressure runs the other way, and hard.

An agent has to act. To act it needs credentials. There are exactly two arrangements:

**The agent holds your credentials.** It can act without interrupting you, which is the entire value proposition. And now the agent's operator holds the keys to your bank, your email, your health portal and your government services. That is not a platform login. A platform login sees the logins. **This sees every action you take anywhere.** It is the most concentrated administrative identity relationship ever built, and you agreed to it because the alternative was answering prompts all day.

**You approve each action.** The credentials stay with you and the agent is a suggestion engine. This is the safe design, and it is the one that loses, because it reintroduces exactly the friction the agent was bought to remove.

The convenience gradient points one way. It always has. Every previous attempt at user-held identity lost to *sign in with a big company*, for the same reason: the safe version asks more of the user, and users are busy.

So the honest prediction: **the agent is the strongest force for administrative identity since the platform login**, and the SSI framing may end up describing the losing branch. I would like to be wrong. I do not think the argument is weak.

## Your digital twin is Tier 3 that can spend money

One more turn, and it is the one that bothers me most.

What is an agent's model of you? It is inferred. Assembled by correlating your behaviour across sources, kept because it makes predictions, held by a party acting in its own commercial interest.

That is Durand's **Tier 3**, precisely. The abstracted identity. The behavioural segment, the lookalike audience, the profile assigned to you by someone you never contracted with.

Marketing built that artifact to sell you things. An agent builds the same artifact to **act as** you.

The technique is not new and the stakes are not comparable. [Customer 360 and entity resolution are the same operation](../concepts/person-identity.md), differing in who asked, who benefits, and what an error costs. A wrong merge in an ad graph shows you the wrong advert, which is nearly free. **A wrong merge in an agent's model of you books the wrong flight, pays the wrong invoice, or tells a doctor about an allergy you do not have.**

We are about to find out what happens when profiles calibrated for a domain where being wrong is cheap start taking actions where it is not.

## What should exist instead

None of this argues against agents. It argues that we are issuing the wrong artifact.

An agent does not need an identity. It needs a **verifiable delegation**: a credential that says *this agent may do these things, for this person, until this date, and here is how to check.* Scoped, expiring, revocable, and independently verifiable by the party being asked to honour it.

That is the issuer, holder, verifier triangle, with the human as issuer and the agent as holder. The machinery already exists. Verifiable credentials, selective disclosure, holder binding with a fresh nonce so a captured presentation cannot be replayed. This engine ships that machinery today for co-reference decisions, and the shape transfers directly.

What follows if you take it seriously:

**Log the principal, not the session.** Four candidates acted in the opening scene. A useful record names the human who delegated, the agent instance, the model version and the operator. One field cannot hold four answers.

**Scope the delegation to the reversibility class.** The grocery row and the disclosure row in that table should never have been covered by the same authorisation. One deserves a standing permission with a spending cap; the other deserves a decision a person makes once, in the moment, knowing it cannot be taken back.

**Delegations expire, because Tier 2 attributes always did.** An agent authorisation with no end date is a driving licence with no expiry, and we stopped issuing those for good reasons.

**Believing is not acting.** This engine already separates deciding two records match from *merging* them, because a merge is usually irreversible. Agents make that distinction load-bearing everywhere. An agent that believes two records co-refer and one that acts on the belief are doing different things with different costs, and the second needs a higher bar.

**Abstention has to survive delegation.** An agent asked *are these the same person* can guess or it can call something that is allowed to say no. Giving an agent the ability to [abstain with evidence](../concepts/sameness-and-similarity.md) is most of what makes it safe to automate. An agent that must always answer will assert things nobody authorised.

## Where this touches what we build

Honestly, and with the gap named.

The position is that you do not compete with the agent, you become what it calls when the answer has to be defensible. The agent brings reasoning, memory and context, and will keep getting better at all three. What it cannot supply by being smarter is reproducibility, a stated loss function, or an accountability chain, because [none of those are on the capability curve](../concepts/sameness-and-similarity.md).

A signed decision with a reproducible identifier is exactly the artifact you want when someone asks, three years later, on what basis an agent acted. Not *the model said so*, but *given this evidence and these parameters, this is what the rule output, and here is who ran it.*

The gap: **there is no MCP server.** The design is real and the code does not exist, and an earlier version of our own documentation claimed otherwise, which is a small instance of the exact failure this post is about. Today an agent reaches this engine through the same Python API a person uses.

## What would make me wrong

Written down so it can be checked rather than quietly dropped.

**Users accept the friction.** If people genuinely tolerate approving actions, the safe branch wins and the re-centralisation argument dissolves. Every prior identity cycle says they will not. This one might differ, because the stakes are visible in a way that cookie consent never was.

**Delegation standards arrive before the agents do.** If scoped, expiring, verifiable agent authorisation becomes the default before agents hold raw credentials at scale, the concentration never happens. This is a race, and standards are usually slower.

**Regulation reaches it in time.** The demand for adjudication rises with automation, and agents are the sharpest version of that. But GDPR Article 22 applies more narrowly than people assume, and a great many agent workflows will be structured as assistive rather than decisive precisely to stay outside it.

**Nobody ever asks who acted.** The bleakest possibility and not the least likely. If the wrong flight is a shrug and the wrong invoice gets refunded, the audit chain is a cost with no buyer, and everything above is correct and irrelevant.

## Acknowledgements

The three-tier model is [Andre Durand's](https://www.pingidentity.com/), from 2002, and it has aged remarkably well for something written before the smartphone. The attributes, traits and preferences distinction and the framing of identity systems as things that acquire, correlate, reason over and govern information about subjects come from Phil Windley's [*Learning Digital Identity*](https://www.oreilly.com/library/view/learning-digital-identity/9781098117689/) (O'Reilly, 2023).

[Kim Cameron's Laws of Identity](https://www.identityblog.com/stories/2005/05/13/TheLawsOfIdentity.pdf) (2005) argued that a universal identifier is a design error, twenty years before anyone proposed giving one to a piece of software.

The bundle-versus-substance framing, and the observation that we have no digital substance connecting the attributes we present online, follows notes by Dennis Irorere on [the nature of identity](https://github.com/denironyx/systems-that-decide-what-matters/blob/main/01-foundations/01-the-nature-of-identity-and-digital-identity.md).

## Notes

1. "Agent" here means software that takes actions on a person's behalf using that person's credentials, not a chatbot that answers questions. The distinction is the whole argument: answering is cheap to get wrong and acting is not.
2. The four-principals problem is not hypothetical. It is the ordinary case, and the reason it reads as novel is that no widely deployed schema has fields for it.
3. Disclosure being irreversible is not a claim about encryption or access control. It is a claim about people: once someone knows something, the knowing is not revocable, whatever happens to the file. Every other category on that list has a mechanism for undoing. This one has none.
4. This is a position piece rather than a measurement. Nothing in it is benchmarked, and the prediction about re-centralisation is falsifiable in the ways listed above rather than demonstrated.

## Related

- [Person identity](../concepts/person-identity.md) for the tiers, the substance problem, and where Customer 360 sits
- [Sameness and similarity](../concepts/sameness-and-similarity.md) for why abstention is a first-class answer
- [Re-verify a decision](../how-to/re-verify-a-decision.md) for what a checkable decision actually looks like
