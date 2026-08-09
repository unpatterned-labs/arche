# A place is not a point

*Space, place, and why the hardest entity to resolve might be the ground under your feet. By Dennis Irorere, Unpatterned Labs, August 2026.*

---

Two rows, two Nigerian registries. One says **"Karfi Health Post"** with coordinates that put it just off the Kano–Zaria road. The other says **"Karfi Primary Health Centre"**, a little over two kilometres away. Same facility, or neighbours?

If you trust the coordinates, they are different places; two kilometres is not GPS jitter. If you trust the names, they nearly agree, except one is a Health Post and the other a Primary Health Centre, and in the Nigerian health system those are different tiers of facility. Every signal you would match on is arguing with the others.

Here is the resolution, and it took local knowledge, not better math: the facility was upgraded. The health post became a PHC, the name changed with the tier, and the two coordinates were captured years apart by different field teams, one standing at the gate and one at the junction where the access road starts. One place, two references, and the disagreement between them is not noise. It is history.

I came to entity resolution from geospatial engineering, so places are where the whole problem started for me, and I have been keeping [reading notes](https://github.com/denironyx/systems-that-decide-what-matters/tree/main/04-spatial-identity) on spatial identity for a while. This post is those notes colliding with the code we ship in [arche](https://github.com/unpatterned-labs/arche): what geographers figured out about place decades before matching software existed, what the address really is, and why the best location matchers in the world quietly agree with the geographers.

## Space is what the GPS sees

The geographer Edward Relph drew the distinction in 1976, in *Place and Placelessness*; Yi-Fu Tuan sharpened it a year later in *Space and Place*, and geographers have been arguing with both ever since (Doreen Massey's relational rejoinder is the famous one). **Space** is amorphous and abstract: coordinates, extents, distance. **Place** is what happens when people claim a piece of space by naming it, using it, and staying long enough for it to accumulate meaning. Relph's point is that a place is not its location alone but the unity of its physical setting, its activities, and its meanings. The idea I underlined hardest: engineers create *localities*, but time is needed to create *place*.

Read that as a data person and it lands with a thud, because our systems store space and pretend it is place. A latitude and longitude is space. "Karfi", the town whose name both facility records carry, is a place: it will keep being Karfi if every GPS unit in Kano is off by a kilometre, and it was Karfi before either coordinate was captured.

This is not romantic hand-waving. It is a claim about which attributes are stable. Coordinates for the same real facility routinely disagree; in [our Nigeria facility crosswalks](../tutorials/place_resolution_at_scale.md), roughly a quarter of accepted matches sit more than two kilometres apart, because someone measured at the gate, someone at the borehole, someone from a desk in Abuja with a gazetteer. The *name* of the place, its *type*, and the named things that *contain* it (Kano State, the LGA, the town) drift far more slowly. Space is precise and unreliable. Place is fuzzy and durable. A matcher has to hold both.

## The address was never about finding your way

The second book on my shelf is Deirdre Mask's *The Address Book*, and its central reversal is the one every identity person should sit with: street addresses were not invented so you could find places. They were invented so the state could find **you**.

House numbering arrives in Europe in the 1700s as an instrument of taxation, conscription, and policing. And here is the detail that connects it straight to our work: Mask reports that in 1700s England, some ninety percent of men shared one of just eight first names. John, William, Henry and their five brothers had collided so completely that a name alone could not identify anyone. States had tried fixing names before, imposing hereditary surnames and keeping parish registers, and the collisions kept coming. House numbering attacked the problem from the other side: pin each person to a numbered place, and an ambiguous name becomes resolvable.

In [Talburt's vocabulary](er-activities.md), that is the moment the address became an *identity attribute*. The address was the state's sharpest join key yet, adopted precisely because the name-frequency problem we still fight today (agreeing on "Ibrahim" in Kano is weak evidence; agreeing on "Gyaranya" is strong) had already broken identification centuries earlier. Frequency-weighted matching and the postal address are two answers to the same collision, three hundred years apart.

Mask ends with a warning that maps cleanly onto Relph. Systems like what3words assign every three-metre square on earth a three-word code, and it works, in the sense that a drone can find you, and several postal services have adopted it. But a grid code is pure space: no community speaks it, no history attaches to it, and even where a post office signs up, the code lives in an app rather than in neighbours' heads. It is also owned: a private company holds the grid, the wordlist, and the licence, which is the exact inverse of the shared, verifiable knowledge that made addresses work. Keep that thought; it comes back when we get to "behind the Total filling station."

## What the best location matchers actually learned

If the geographers are right that place is name plus containment plus meaning, and not coordinates, you would expect the people who match places for a living to have discovered this the hard way. They did, and there is a public record of it.

In 2022, Foursquare put [a point-of-interest matching competition](https://www.kaggle.com/competitions/foursquare-location-matching) on Kaggle: what its description calls over one and a half million place entries, deliberately noised with duplicates and corruptions, score determined by how well you group the records that refer to the same real-world point of interest. It is entity reference resolution for places, at industrial scale, with a leaderboard.

Nobody won on distance. The [top solutions](https://www.kaggle.com/competitions/foursquare-location-matching/writeups/re-waiwai-1st-place-solution) share one shape: generate candidate pairs from geographic proximity *and* text similarity, then decide with learned multi-stage rankers, gradient boosting and fine-tuned transformers among them, fed with comparison features. And the features doing the work are the representation ones: Jaro-Winkler and Levenshtein on names, learned text embeddings, token overlap, category agreement. Distance stays in the feature set, and it matters there, but distance alone cannot decide, because in dense areas everything is close, and two coffee shops thirty metres apart are two entities while one hospital measured twice at 2 km is one.

Read with a geographer's squint, that is the matching community rediscovering Relph: space proposes, place decides. A Kaggle leaderboard cannot prove a philosophy, but it is striking how exactly the winning feature sets recapitulate the theory.

arche's [place pack](https://github.com/unpatterned-labs/arche/tree/main/datasets) is that lesson written down as declared comparators rather than learned weights, because our whole thesis is [shipping representation as inspectable data](representation-engine.md). Five signals, each carrying one piece of the theory:

- **Geo** is haversine distance under an exponential decay, deliberately a supporting signal and never a decision gate. The decay is forgiving because field coordinates are noisy; two points 2 km apart still register a nonzero nudge (about 0.26 under the default decay, a number you can read straight out of the code). And space does get to propose, literally: candidate generation blocks on spatial cells, so nearby pairs are the ones offered for comparison in the first place.
- **Containment** compares the *named hierarchy*: state, LGA, settlement, from a point-in-polygon join against admin boundaries. Agreement at the finest shared level is strong supporting evidence; disagreement at the state level zeroes the signal, and any containment conflict pushes a would-be match to human review instead of an automatic merge. Nothing auto-vetoes; the map gets a voice, not a gavel. This comparator is Relph in code: it matches on the names people gave the land, not the numbers the satellite gave it.
- **Name and type.** The engine ships a type-token splitter: "Karfi Primary Health Centre" splits into the type (*PHC*, via a synonym vocabulary that knows "primary health care centre" and "PHC" mean the same tier) and the distinctive residual (*Karfi*). Our facility crosswalk pipeline compares the residual and the tier separately, which is exactly what the upgrade story needs: same residual, changed type, plausible match, route to review.
- **Token frequency** carries the eight-names lesson: agreement on a token is worth what its rarity says it is worth, measured over the corpus being linked. That is the same move [Robin Linacre's uk_address_matcher](https://github.com/RobinL/uk_address_matcher) makes on UK addresses, where "HIGH" and "STREET" are near-worthless and a rare token decides the match; both systems calibrate rarity from the data in front of them instead of guessing.
- **Address**, for when there is one, weighted knowing that shared city names alone are weak.

None of this is exotic. It is the Foursquare winners' feature set, written down as data instead of learned weights. And an honest status note: the place pack is younger than the person pack, and writing this argument down exposed gaps in the code that have since been closed — the type comparator as its own declared slot, place-calibrated decay, a lexicon-free place-name comparator, and union blocking so a true match whose coordinates disagree by kilometres still reaches the comparators. Being able to find your own gaps by reading the representation is exactly what shipping it as inspectable data is supposed to make possible.

## Places drift, so decisions carry dates

Relph's deepest observation is temporal: time makes place, and time keeps remaking it. States split, LGAs are redrawn, settlements get absorbed, facilities get upgraded, and the filling station that anchors everyone's directions eventually closes while the junction keeps its name for a generation. Karfi Health Post genuinely *was* a different reference than Karfi PHC; the entity moved underneath both.

This is why arche never emits a bare yes. Every decision carries its evidence: which representation version, which comparators, which thresholds, decided *when*. At trust boundaries a decision can be [signed](attest.md), and the signature does not claim "these are eternally the same place." It claims "given this evidence and this representation, this was the decision," which is the only claim a system can honestly make about entities that have histories. The place crosswalk used to return its evidence unsigned; it no longer does. Every crosswalk edge now carries a `decision_id` hashed over its evidence and provenance pins, and `sign_edges` puts a signature on exactly that claim. Attestation is how software admits that place identity is temporal.

The boundaries drift too, and that cuts at us: the containment signal is only as current as the admin polygons it joined against, and GADM, GRID3, and Overture genuinely disagree on some Nigerian LGA lines. So the boundary layer's vintage is one more thing a decision has to pin rather than assume, which is an argument the drift makes for us.

## The sensitive half

Everything above treats places as public. A clinic, a charging point, a junction: resolving them well helps everyone and harms nobody. Make the place a home and the same machinery turns dangerous.

The re-identification literature is blunt about this. Golle and Partridge showed in 2009 that just the pair of your home and work locations, even at coarse granularity, narrows most people to a handful of candidates. De Montjoye and colleagues showed in 2013 that four rough spatio-temporal points uniquely identify 95% of people in a 1.5-million-person mobility dataset. Location is not an attribute *about* you; past a certain precision it simply *is* you. Peter Christen's *Data Matching* (2012) is the standard engineering text for the pipeline this whole post describes; his follow-up with Ranbaduge and Schnell, *Linking Sensitive Data* (2020), exists because linked records are more identifying than any of their parts, and it is the book we reread before touching anything residential.

That is why the same engine that resolves facilities renders [masked by default](../how-to/declare-your-schema.md), why restricted fields never reach clear text, and why the privacy-preserving linkage techniques Christen's group works on are on our list to adopt rather than reinvent. Resolving Karfi's clinics is a geospatial problem. Resolving where the people who visit them sleep is a governed one, and the engine has to know the difference without being told.

## Madina junction, again

In [the representation essay](representation-engine.md) we used the address "behind the Total filling station, Madina junction" as an example of what breaks Western address parsers. I want to end by reading it the other way, because after Relph and Mask it is not a broken address at all.

It is a rich place description. It has a landmark anchor, an implied containment (Madina, Accra), a spatial relation, and a verification community: thousands of people can confirm it, correct it, and navigate by it. It is *more* place-like than "Flat 2, 12 High Street", not less. What it lacks is not information. What it lacks is a system willing to represent it.

Billions of people live at places that are named but not addressed. The machinery above (names weighted by rarity, containment hierarchies, landmark anchors, types split from identities, decisions signed with their dates) is what taking those places seriously looks like in software. The satellite sees space. People make place. We match the second one.

---

## References

- Edward Relph, *Place and Placelessness*, Pion, 1976. The space/place distinction and the role of time in making place.
- Yi-Fu Tuan, *Space and Place: The Perspective of Experience*, University of Minnesota Press, 1977.
- Doreen Massey, "A Global Sense of Place," *Marxism Today*, 1991. The relational rejoinder: places as open and defined by their connections.
- Fred Lukermann, "Geography as a formal intellectual discipline and the way in which it contributes to human knowledge," *Canadian Geographer*, 1964. The components of place Relph builds on.
- Deirdre Mask, *The Address Book: What Street Addresses Reveal About Identity, Race, Wealth, and Power*, St. Martin's Press, 2020.
- Philippe Golle and Kurt Partridge, "On the Anonymity of Home/Work Location Pairs," *Pervasive Computing*, 2009.
- Yves-Alexandre de Montjoye, César A. Hidalgo, Michel Verleysen, Vincent D. Blondel, "Unique in the Crowd: The privacy bounds of human mobility," *Scientific Reports* 3, 1376, 2013.
- Peter Christen, *Data Matching: Concepts and Techniques for Record Linkage, Entity Resolution, and Duplicate Detection*, Springer, 2012.
- Peter Christen, Thilina Ranbaduge, Rainer Schnell, *Linking Sensitive Data: Methods and Techniques for Practical Privacy-Preserving Information Sharing*, Springer, 2020.
- John R. Talburt, *Entity Resolution and Information Quality*, Morgan Kaufmann, 2011. The entities-vs-references discipline, [audited against arche here](er-activities.md).
- [Foursquare — Location Matching](https://www.kaggle.com/competitions/foursquare-location-matching), Kaggle, 2022; [1st place solution writeup](https://www.kaggle.com/competitions/foursquare-location-matching/writeups/re-waiwai-1st-place-solution); [Theo Viel's solution](https://github.com/TheoViel/kaggle_foursquare); [Foursquare's own post-mortem](https://foursquare.com/resources/blog/developer/finding-the-right-poi-match/).
- Robin Linacre, [uk_address_matcher](https://github.com/RobinL/uk_address_matcher). Token-frequency address matching over a national corpus.
- H. B. Newcombe, J. M. Kennedy, S. J. Axford, A. P. James, "Automatic Linkage of Vital Records," *Science* 130(3381), 954-959, 1959. An early foundation of record linkage, and where frequency-based agreement weights first appear.
- The reading notes this post grew from: [systems-that-decide-what-matters, spatial identity](https://github.com/denironyx/systems-that-decide-what-matters/tree/main/04-spatial-identity).

*Related: [the representation engine](representation-engine.md) · [the five ER activities](er-activities.md) · [place resolution at scale (NG + UK)](../tutorials/place_resolution_at_scale.md) · [attest: the signature on the decision](attest.md).*
