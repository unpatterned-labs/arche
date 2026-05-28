## arche

arche is the open-source engine that resolves who someone is across messy, multilingual, regulated data, and proves it.


# arche — The Identity Intelligence Engine

> *"Solve the hardest version of the problem. Everything easier becomes a free feature."*

**arche** is an open-source identity intelligence engine. Extract, match, and link entity identities across any document, system, or format. Names, addresses, national IDs, businesses, financial identifiers — detected, resolved, and linked into unified identity graphs.

---

## 1. The atomic problem

Identity is fragmented and nobody owns the layer that fixes it.

The same person is "Mohammed," "Muhammad," "Mamadou," "ميسي." The same business is "Acme Ltd," "ACME LIMITED," "Acme Nig. Ltd." The same patient sits in three clinic systems under three spellings. Every system that touches people or organizations has an identity-resolution problem hiding inside it, and almost everyone hand-rolls a brittle version: regex, fuzzy match, a spreadsheet of name variants, a junior engineer's weekend.

That is the unglamorous plumbing. It is real, it is everywhere, and it is unowned. That is the opportunity.

## 2. Why now

Three forces are converging:

1. **AI agents hallucinate identity.** An LLM will assert "Leo" is Lionel Messi or a retired midfielder with equal confidence. Agents touching real-world entities need a deterministic, validated layer underneath that says "these two are the same, here is why, here is the proof." That primitive does not exist yet.
2. **Data-protection law grew teeth, globally.** NDPA, POPIA, Kenya DPA, GDPR. You can no longer just *detect* PII. You must *act* on it under a specific statute and *prove* you did. Detection is a commodity; statute-grounded action plus an audit trail is not.


## 3. What arche is

The thing that does not exist anywhere else is the **triad**:

```
   cultural-naming intelligence   +   deterministic ID validation   +   statute-grounded policy
   (Mohammed = Mamadou = ميسي)        (NIN/BVN/Ghana Card checksums)     (act + cite the law, audit it)
```
