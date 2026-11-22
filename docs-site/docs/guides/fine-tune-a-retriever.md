# Fine-tune a retriever

At the end of this page you can train an encoder on your own labelled pairs, measure it against the character baseline, decide whether it earned its place, and put it behind a reference so every decision names the exact weights that proposed its candidates. It is written for someone who has not fine-tuned a model before.

A retriever has one job: for a record, put the right counterpart somewhere in the first few candidates. It does not decide. The engine decides, from the candidates the retriever hands it. A retriever that ranks the right record tenth is doing its job; one that leaves it out of the first fifty is not.

```sh
pip install "arche-core[detect2]"     # torch and transformers
```

## Before you train anything

Five rules. Each one is here because breaking it produced a number that looked like progress and was not.

1. **Labels come from somewhere outside your matcher.** A registry that asserts two records are one entity, a publisher's link table, a person's review. Pairs your own matcher proposed and accepted teach the model to agree with the matcher.
2. **Split by entity, before anything else.** Every name of one entity goes to the same side. Use a hash of the entity id, not a random draw you can re-run until it looks good. When you can, hold out whole regions instead.
3. **Measure the baseline first.** arche's `CharNgramIndex` (character 3-gram TF-IDF) is fast, needs no model, and is hard to beat. If it already finds more than about 92% of true pairs in its top 10 on your development split, there is no room for a model to show a gain: stop here.
4. **Write the rule down before you look at the test split.** What gain counts, at which `k`, with which interval, and what latency and model size are acceptable. Save it in a file, with the date. A rule chosen after the results is a description, not a test.
5. **Train on the domain you will search.** Names in one domain follow conventions another domain does not share. See [what this looked like on real data](#what-this-looked-like-on-real-data).

## A worked example

Thirty-two invented health facilities, each with two names from two sources: the facility-type phrase differs ("Health Post" in one, "Dispensary" in the other), and every third name is split in one source and not the other. These are the two ways real registries disagree.

```python
import hashlib

from arche.retrieval import CharNgramIndex, EncoderIndex, TextEncoder
from arche.retrieval._train import TrainConfig, fine_tune

# 1. Labelled pairs: two names for one facility, from a source that asserts the link.
places = ["Abaji", "Bakori", "Dutsen", "Ezinne", "Gwarzo", "Ikire", "Jalingo", "Kafin",
          "Lafiagi", "Mada", "Nkalagu", "Obudu", "Pankshin", "Rijau", "Sabon", "Takum",
          "Ugep", "Wamba", "Yauri", "Zuru", "Amasiri", "Biliri", "Danja", "Egbe",
          "Funtua", "Garki", "Idanre", "Jos", "Kontagora", "Lokoja", "Makurdi", "Nsukka"]
kinds = [("Health Post", "Dispensary"), ("Primary Health Centre", "PHC"),
         ("Health Clinic", "Primary Health Center"), ("Basic Health Centre", "BHC")]
pairs = []
for i, p in enumerate(places):
    a, b = kinds[i % len(kinds)]
    joined = p[:3] + " " + p[3:] if i % 3 == 0 else p   # some names split in one source
    pairs.append((f"{p} {a}", f"{joined} {b}", p))       # (text, other text, entity)

# 2. Split by entity, before anything else, with a hash nobody can tune.
def split(entity):
    return "test" if int(hashlib.sha256(entity.encode()).hexdigest(), 16) % 3 == 0 else "dev"

train = [(a, b) for a, b, e in pairs if split(e) == "dev"]
test = [(a, b) for a, b, e in pairs if split(e) == "test"]
gallery = [b for _, b, _ in pairs]          # search every target, train and test alike
print(len(train), "training pairs,", len(test), "test queries")

# 3. Measure the baseline first.
def recall_at_1(index):
    hits = 0
    for a, b in test:
        found = index.search(a, k=1)          # [(row, score)], best first
        hits += bool(found) and gallery[found[0][0]] == b
    return hits / len(test)

print("TF-IDF recall@1:", round(recall_at_1(CharNgramIndex(gallery)), 3))

# 4. Train, on training pairs only.
out = fine_tune("intfloat/multilingual-e5-small", train, "models/toy",
                config=TrainConfig(epochs=3, batch_size=8, lr=5e-5, prefix="query: "),
                device="cpu")

# 5. Evaluate the trained encoder the same way, and read its pins.
encoder = TextEncoder(str(out), prefix="query: ")
print("fine-tuned recall@1:", round(recall_at_1(EncoderIndex(gallery, encoder)), 3))
print(sorted(encoder.pins()))
```

```text
18 training pairs, 14 test queries
TF-IDF recall@1: 0.857
epoch 1/3  loss 1.05816
epoch 2/3  loss 0.3492
epoch 3/3  loss 0.18115
fine-tuned recall@1: 1.0
['encoder', 'max_length', 'pooling', 'prefix', 'weights']
```

It ran in a little over two minutes on a laptop CPU, once the base model (about 470 MB) was downloaded.

**What the numbers mean, and what they do not.** Fourteen test queries is a toy: one query is seven points. This shows the workflow, not that fine-tuning helps. On real data you want hundreds of test queries, three training seeds, and an interval on the gain (below).

**What the loss means.** `fine_tune` trains contrastively: for each name, the model is asked to pick its true partner out of every partner in the batch. The loss falls as it gets better at that. A loss that stops falling early means the pairs are too easy or the learning rate too low; one that falls to almost zero on a few hundred pairs means it is memorising them.

**What `fine_tune` saved.** `models/toy` holds the weights, the tokenizer, and `arche_training.json`: the base model and its weights digest, a digest of the training pairs, every setting, the seed, and the loss per epoch. Keep it with the model. It is how anyone, you included, can tell later what this model was trained on.

## Using it in arche

A trained encoder goes behind a reference like any other retriever. The reference's pins carry the encoder's weights digest into every decision id, so a candidate proposed by this model can always be traced to it, and a decision moves if the model does.

```python
from arche.references import link
from arche.retrieval import EncoderIndex, IndexedReference, TextEncoder

encoder = TextEncoder("models/toy", prefix="query: ")
registry = [{"id": "r1", "name": "Gwarzo Dispensary"},
            {"id": "r2", "name": "Gwarzo General Hospital"},
            {"id": "r3", "name": "Kafin PHC"}]
ref = IndexedReference(registry, name="toy-registry",
                       retriever=lambda texts: EncoderIndex(texts, encoder))

print([r["id"] for r in ref.candidates({"name": "Gwarzo Health Post"}, limit=2)])
out = link([{"id": "q1", "name": "Gwarzo Health Post"}], ref, entity="place")
retriever = out["pins"]["candidate_provider"]["reference"]["retriever"]
print(retriever["retriever"], retriever["weights"][:19] + "...")
```

```text
['r2', 'r1']
encoder sha256:1234569db753...
```

Look at the first line. The toy model put the general hospital above the dispensary: eighteen pairs taught it that the place name matters, and nothing about which facility types are the same kind of thing. Both are in the first two candidates, which is the retriever's job; telling them apart is the engine's. It is also why you evaluate at `k=10` rather than `k=1`.

## From the toy to your data

**Pairs.** Use every pair whose two names differ. Identical names teach nothing; a few are harmless. Aliases one source records for itself (a previous name, a trading name) are pairs too.

**Hard negatives.** Pass `hard_negatives=`, one list per pair, of names that look like the anchor and are a different entity: the anchor's nearest neighbours under `CharNgramIndex`, from the same district, minus its own partner. These are what a general-purpose model gets wrong. Drop any whose name is the same as the anchor's: in real registries that is almost always a duplicate record of the same entity, and training on it teaches the model that an identical name means a different thing.

**Settings.** The defaults (`TrainConfig()`: two epochs, batch 64, learning rate 2e-5) are a sound start for tens of thousands of pairs. Larger batches give each step more negatives for free. Train three seeds and report their mean; if they disagree by more than a point, the result is noise.

**A GPU.** The facility experiment below trained three seeds on 24,882 pairs and evaluated them in under eight minutes on a laptop GPU; on a CPU, expect hours. Search at inference time is cheap on either.

**Evaluation.** Recall at 10 against the TF-IDF baseline on the test entities, searching the whole gallery. Put an interval on the gain with a paired bootstrap over test entities (resample entities, recompute both arms, take the 2.5th and 97.5th percentiles of the difference). Then check for leakage: no test entity in training, and count how many test name pairs appear verbatim among the training pairs. Then read the queries the model lost, one by one; they say more than the average.

## What this looked like on real data

Two experiments, run with the same base model and the same rules. The rule, the data digests and the code digests were written down before each test split was read; the scripts and results are in `data/scripts/` and `data/er_bench/`.

| Trained on | Tested on | TF-IDF recall@10 | Fine-tuned | Gain, 95% interval |
|---|---|---:|---:|---:|
| Wikidata names of places and organisations in Nigeria | 86 reviewed GRID3/HFR facility pairs | 0.942 | 0.857 | −8.5 points [−17.1, −0.4] |
| GRID3/HFR crosswalk of 34 other states | the same 86 pairs | 0.942 | 1.000 | +5.8 [+1.2, +11.6] |
| GRID3/HFR crosswalk of 34 other states | 1,569 crosswalk pairs in three held-out states | 0.969 | 0.990 | +2.0 [+1.2, +2.9] |

The first model was good at Wikidata: on Wikidata's own test split it gained 13.6 points. On facilities it lost queries the baseline found, on names split or joined differently in the two registries and on names whose type word differed ("Health Post" in one, "Dispensary" in the other). The second model learned those conventions from facility names. Rule 5 is this table.

Sources: GRID3 NGA Health Facilities v2.0, CIESIN, Columbia University (2024), CC BY 4.0, https://doi.org/10.7916/kv1n-0743; Nigeria Health Facility Registry via the Humanitarian Data Exchange, CC BY; Wikidata, CC0.

## When it goes wrong

- **Searching one query takes hundreds of milliseconds on a CPU.** torch uses every logical CPU by default, and on machines with many threads that is slower, not faster. arche caps it around its own model calls; set `arche.configure(torch_threads=4)` to choose the cap yourself.
- **A warning about an "incorrect regex pattern" when loading a saved model.** It is raised for this tokenizer family and does not change the tokens; compare `tokenizer("…")` before and after saving if you want to be sure.
- **A gain that looks too good.** Suspect your own measurement first: a test entity that leaked into training, a gallery that does not contain the targets, a comparison of ids where you meant to compare names. Fix the probe, rerun, and say what changed.
