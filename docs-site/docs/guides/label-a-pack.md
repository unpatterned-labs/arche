# Label a pack

A review pack asks a person whether two records are the same. A **label pack** asks for something smaller: which part of a text is which. Use it to make gold data for a parser (house number, road, town in an address) or for any field you want to measure a model against. Studio shows the text, the labels and your guide, and nothing a model produced: gold is only gold if the person did not see a guess.

## Make a pack from a CSV

A label pack is a directory with two files.

`items.csv` holds one row per item. It needs an id column and the column a person labels. Any other columns are carried into the export untouched.

```text
id,country,address
a1,ng,"14 AJALA ROAD, TEMANU"
a2,ke,"Along Kanyiri road, Ashgrove"
```

`pack.json` names the columns and the labels:

```json
{
  "schema": "arche.label_pack.v1",
  "title": "Addresses",
  "id_field": "id",
  "text_field": "address",
  "labels": [
    {"key": "house_number", "name": "House number", "hotkey": "n"},
    {"key": "road",         "name": "Road",         "hotkey": "r"},
    {"key": "city",         "name": "City",         "hotkey": "c"}
  ],
  "guide": "GUIDE.md",
  "group_field": "country",
  "export": "labels.csv"
}
```

Each label needs a key (lower case, letters, digits and `_`) and a hotkey of one character. `x`, `j` and `k` are taken. `guide` is an optional Markdown file in the pack, shown beside each item. `export` is where Export writes, inside the pack, and defaults to `labels.csv`. `group_field` (optional) names a column to filter by, such as a country, so a pack can be labelled in batches. A pack that does not validate is left out of the list rather than half-shown.

## Open it

Put the directory under `label_packs/` in Studio's home (`./data/label_packs` in a checkout that has `data/`, `~/.arche/studio/label_packs` otherwise), or point Studio at the directory that holds it:

```sh
arche studio --labels path/to/packs     # or ARCHE_LABEL_PACKS=path/to/packs
```

Then open the **Label** tab at `http://127.0.0.1:8765`, choose the pack and type your name in *Labelling as*. A label without a name is refused, because it cannot be audited.

## Label

Studio splits the text into **chunks**: at commas and semicolons, and after a leading number (`10 Harbour Street` becomes `10` and `Harbour Street`; `No 5` becomes `No` and `5`). The split is punctuation and nothing else, so every chunk starts unlabelled. The chunk with the black outline is the one you are on.

| Key | Does |
|---|---|
| a label's hotkey | label the current chunk and move to the next unlabelled one |
| `Space` / `→` | leave the chunk and move on; `←` moves back |
| `Backspace` | undo |
| `Delete` | remove the current chunk's label |
| `Enter` | save and go to the next item |
| `j` / `k` | next / previous item, without saving |
| `x` | not an item to label (saved as skipped, with your name) |

Click the space between two words to split a chunk there, or the space between two chunks to join them. Drag across words to make them one chunk. Click a label's tag to remove it. **Free select** switches to marking any stretch of characters, for the odd text that chunks cannot hold; an item saved that way reopens in free select.

Either way the label is the same thing, a start, an end and a label, so the export does not depend on how it was marked.

Each save is appended to `_studio/labels/<pack>.jsonl` in Studio's home, with who, when and a digest of the pack. The latest save of an item is its label, and the earlier ones are its history. The pack itself is never written to, except by Export. *Saved just now* lists your last few saves, to catch a slip.

## Export

**Export** writes one row per item: the item's own columns, one column per label (the labelled text, in reading order), `skip` and `labelled_by`. Rows nobody has labelled yet have empty label columns and no `labelled_by`, so a script reading the export can tell an unlabelled row from a row whose answer is empty.
