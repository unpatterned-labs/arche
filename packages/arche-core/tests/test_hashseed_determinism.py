# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Decision ids must not depend on PYTHONHASHSEED.

Python randomises string hashing per process, so anything that picks from a
set -- a tie between two equally rare phrases -- can pick differently in a
verifier's process than in the one that issued the receipt. Found 20 Nov 2026:
`Our Lady Health Of The Sick Hospital` against `Our Lady's Health of the Sick
Hospital` reported `name_phrase` "sick hospital" under some seeds and "the
sick" under others, with a different decision id each time.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

_SCRIPT = r'''
import json
from arche.resolve import reconcile
ap = {"admin1": "rivers", "admin2": "port harcourt"}
cases = [
    ("health_facility",
     {"id": "a", "name": "Our Lady Health Of The Sick Hospital", "admin_path": ap},
     {"id": "b", "name": "Our Lady's Health of the Sick Hospital", "admin_path": ap}),
    ("place",
     {"id": "a", "name": "Sabon Gari Primary Health Centre", "lat": 12.0, "lon": 8.5},
     {"id": "b", "name": "Sabon Gari Health Centre", "lat": 12.001, "lon": 8.501}),
    ("organisation",
     {"id": "a", "name": "Karfi Agro Cooperative Society Ltd", "address": "12 Zaria Road, Kano"},
     {"id": "b", "name": "Karfi Agro Co-operative Soc.", "address": "12 Zaria Rd, Kano"}),
    ("site",
     {"id": "a", "name": "Kestrel Baking - Bolton", "address": "Moss Lane", "postcode": "BL4 8NB"},
     {"id": "b", "name": "Kestrel Baking Ltd", "address": "Moss Lane", "postcode": "BL4 8NB"}),
]
out = []
for entity, a, b in cases:
    r = reconcile([a], [b], entity=entity, id_field="id")
    out.append([m["decision_id"] for m in r["matches"]])
print(json.dumps(out))
'''


def _ids(seed: str) -> list:
    env = {**os.environ, "PYTHONHASHSEED": seed}
    done = subprocess.run([sys.executable, "-c", _SCRIPT], env=env, capture_output=True,
                          text=True, check=True)
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_decision_ids_are_the_same_under_every_hash_seed():
    runs = {seed: _ids(seed) for seed in ("1", "2", "3", "4")}
    first = runs["1"]
    assert all(ids for ids in first), "every case should produce an edge"
    for seed, ids in runs.items():
        assert ids == first, f"PYTHONHASHSEED={seed} changed a decision id"
