---
template: home.html
hide:
  - footer
---

<section class="hero">
<div class="hero-copy">
<p class="kicker">Open-source Python library</p>
<h1>Are these the same thing?</h1>
<p class="lede">Two records, spelled differently, sharing an id. arche says whether they are one thing, shows the evidence, says <em>review</em> when it should, and keeps a receipt you can replay next year.</p>
<p class="actions"><a class="btn" href="get-started/five-minutes/">Get started</a><a class="btn secondary" href="how-it-works/">Read how it works</a></p>
<p class="position">Splink computes the probability. <strong>arche keeps the receipt.</strong></p>
</div>
<div class="term"><div class="term-bar"><i></i><i></i><i></i><span>terminal</span></div>
<pre><span class="dim">$</span> pip install arche-core
<span class="dim">$</span> arche compare --text --json - \
    "Adesola Okonkwo, NIN 12345678901, adesola@example.com" \
    "Adesola E. Okonkwo, NIN 12345678901, 124 Maple Street"

<span class="dim">{</span>
<span class="dim">  "identity":</span> "same_entity",
<span class="dim">  "action":</span> "merge",
<span class="dim">  "basis":</span> "corroborated",
<span class="dim">  "explanation":</span> "national ID match; name similarity 80%",
<span class="dim">  "factors":</span> {"name": 0.8, "national_id": 1.0, "name_tf": 0.7233},
<span class="ok">  "decision_id": "dec:sha256:8912e7da95835995ea26b78045221e…"</span>
<span class="dim">}</span></pre>
</div>
</section>

<section class="cards">
<div class="card">
<h3>It refuses to guess</h3>
<p><code>review</code> is a real answer. Two identical strings that are ordinary words are held apart, and the page says why. No jurisdiction it can infer, no statute that covers the country, no distinctive agreement: each comes back as its own answer, never as a verdict dressed up.</p>
</div>
<div class="card">
<h3>Every decision has an id</h3>
<p><code>decision_id</code> is a content hash over the evidence and the pinned versions. Same inputs, same id, byte for byte. Look it up, explain it, replay it, sign it, hand it to someone who does not trust you.</p>
</div>
<div class="card">
<h3>The law is attached</h3>
<p><code>detect_pii</code> returns every span with the statute section it falls under. <code>deidentify</code> returns the copy the statute permits. A redaction under the wrong law looks finished and is not, so arche refuses when the evidence for the jurisdiction is thin.</p>
</div>
</section>

<section class="for-section">
<p class="section-title">Built for</p>
<div class="for">
<div><h3>Supplier onboarding</h3><p>A vendor form, a bank statement and a registry extract that spell one company three ways. Resolve them to one record with the evidence, and keep the receipt for the audit.</p></div>
<div><h3>Delivery addresses</h3><p><em>The blue gate behind Elim Pharmacy, 124 Elim Streat.</em> A verified endpoint when the evidence is strong, one short question when it is close, an honest refusal when it is weak.</p></div>
<div><h3>Public registers</h3><p>Schools, clinics and companies across two lists that disagree on spelling, coordinates and ids. Batch resolution with Splink underneath when the batch is large enough to train it.</p></div>
<div><h3>Data handed to a model</h3><p>What is in this text, under which law, and what may leave the machine. A fail-closed guard in front of any provider, and an MCP server so an agent asks before it sends.</p></div>
</div>
</section>

<section class="example">
<div class="example-head">
<h2>The same, from Python</h2>
<span>Three fragments of text mention someone. They share a national id and a name, once with a middle initial, disagree on an email, and none of the addresses match. Same person?</span>
</div>

```python
import arche

text1 = "Adesola Okonkwo, NIN 12345678901, address: 123 Maple Street, adesola@example.com"
text2 = "Adesola Okonkwo, NIN 12345678901, adesola@gmail.com, address: 124 Maple Street"
text3 = "Adesola E. Okonkwo, NIN 12345678901, adesola@gmail.com, address: 231 Elim Street"

ledger = arche.attach("duckdb:///:memory:")            # a file path keeps it
person = dict(entity="person", jurisdiction="NG", backend="basic", store=ledger)

r12 = arche.compare(text1, text2, **person)
r13 = arche.compare(text1, text3, **person)
r23 = arche.compare(text2, text3, **person)
print(r12.identity, r12.action, "|", r23.identity, r23.action)

(entity,) = ledger.entities()                          # three texts, one person
print(entity.shared, entity.conflicts)
print(ledger.replay(r12.decision_id).reproduced)       # the same decision, again

safe = arche.deidentify(text1, jurisdiction="NG", backend="basic")
print(safe.text)                                       # the statute chose each rendering
```

```text
same_entity merge | same_entity merge
{'national_id': '12345678901'} {'email': ['adesola@example.com', 'adesola@gmail.com'], 'full_name': ['Adesola Okonkwo', 'Adesola E. Okonkwo']}
True
NAME_f71c6342 NAME_925a28e1, NIN [NIN], address: [ADDRESS], EMAIL_3f6caee6
```

<p class="example-note"><code>identity</code> is what arche believes: the same person, because a shared national id is distinctive. <code>action</code> is what it recommends: <code>merge</code>, because the name corroborates the id; on a national id alone it would say <code>hold</code>. The email the records disagree on is not averaged away, it sits in <code>conflicts</code> for whoever acts on the entity. The ledger noticed that three pairwise answers describe one person, kept the receipts, and can make any of them again. The last line is the copy the statute permits, from the same detectors.</p>
</section>

<section class="docs-section">
<div class="docs-head">
<h2>Documentation</h2>
<span>Every example on these pages is run against the installed package before it is published.</span>
</div>
<div class="map">
<div>
<a class="map-kicker" href="get-started/">Get started</a>
<a href="get-started/install/">Install</a>
<a href="get-started/five-minutes/">Five minutes</a>
<a href="get-started/python/">From Python</a>
<a href="get-started/docker/">Docker and deploy</a>
</div>
<div>
<a class="map-kicker" href="guides/">Guides</a>
<a href="guides/find-and-mask/">Find and mask</a>
<a href="guides/keep-and-replay/">Keep and replay a decision</a>
<a href="guides/documents-to-decision/">Resolve documents</a>
<a href="guides/mcp-server/">Let an agent call arche</a>
<a href="guides/serve-over-http/">Serve over HTTP</a>
</div>
<div>
<a class="map-kicker" href="how-it-works/">How it works</a>
<a href="how-it-works/the-decision/">The decision</a>
<a href="how-it-works/evidence/">Evidence, gates and distinctiveness</a>
<a href="how-it-works/backends/">Backends: arche, Splink, auto</a>
<a href="how-it-works/jurisdictions/">Jurisdictions and statutes</a>
<a href="how-it-works/attestation/">Attested answers</a>
</div>
<div>
<a class="map-kicker" href="reference/">Reference</a>
<a href="reference/python-api/">Python API</a>
<a href="reference/cli/">Command line</a>
<a href="reference/http-api/">HTTP API</a>
<a href="reference/mcp-tools/">MCP tools</a>
<a href="reference/benchmarks/">Benchmarks</a>
<a class="map-kicker map-kicker--second" href="writing/">Writing</a>
<a href="writing/what-a-name-list-is-worth/">What a name list is worth</a>
<a href="writing/similar-is-not-the-same/">Similar is not the same</a>
</div>
</div>
</section>

<p class="meta">Splink is the better matcher and arche uses it: on Febrl 4, on Splink's own 50k historical set and on a Nigerian school register, Splink wins, and <code>backend="auto"</code> hands it the scoring above a thousand records. arche is what sits around the score: the evidence, the gate, the id, the receipt. The <a href="reference/benchmarks/">benchmarks</a> include the runs where arche loses. arche is pre-1.0; do not make production decisions about personal data with it without your own privacy, security, legal and accuracy review.</p>
