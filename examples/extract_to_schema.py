# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Four declarations, four texts: what fills, from where, and what stays open.

Run with:

    uv run --no-sync python examples/extract_to_schema.py [basic|auto]

``basic`` (default) is the base install: validators, the name lexicon, the
address parser, no model. ``auto`` adds GLiNER 2.5 when ``arche-core[detect2]``
is installed and asks it for each declaration's own field names. Every field
prints its source, so the difference between the two is visible per field
rather than argued about.
"""

from __future__ import annotations

import sys
import warnings

import arche

warnings.simplefilter("ignore")
BACKEND = sys.argv[1] if len(sys.argv) > 1 else "basic"

SUPPLIER = {
    "entity": "organisation",
    "fields": {
        "supplier_name": {"role": "identifies", "kind": ["name", "tftoken"],
                          "description": "registered or trading name of the supplier company"},
        "rc_number": {"role": "identifies", "kind": "id", "id_family": "rc",
                      "description": "CAC company registration number, RC followed by digits"},
        "contact_email": {"role": "describes", "kind": "email"},
        "contact_phone": {"role": "describes", "kind": "phone", "restricted": True},
        "bank_account": {"role": "ignore"},
    },
}

CASES = [
    ("person, a KYC note", "examples/declarations/person.decl.yaml",
     "KYC note: Adesola Okonkwo, born 14/02/1990, NIN 12345678901, phone 0803 555 7890, "
     "adesola@example.com, lives at 12 Zaria Road, Kano."),
    ("place, a facility survey", "examples/declarations/place.decl.yaml",
     "Facility: Karfi Primary Health Centre, Kumbotso LGA, Kano State. Address: Karfi village "
     "road, opposite the central mosque. GPS 11.8975, 8.5210."),
    ("artist, a royalty line", "examples/declarations/artist.decl.yaml",
     "Royalty statement line 14: WIZKID (Ayodeji Balogun), MBID 5bd8bfe3-1bde-4fdd-b6a3-"
     "53f0a52f6f6b, ISNI 0000 0004 5906 4224, streams 1,204,113."),
    ("organisation, an onboarding email", SUPPLIER,
     "Dear team, please onboard Kijani Tea Exporters Ltd (RC 1234567). Our finance contact is "
     "Amina Wanjiru, amina@kijani.co.ke, +254 722 123456. Bank: Zenith 0123456789. Regards, Tunde."),
]

for label, decl, text in CASES:
    schema = arche.schema(decl)
    result = arche.extract(text, schema=schema, backend=BACKEND)
    print(f"== {label}  [{BACKEND}: model={result.model}]")
    for name in schema.labels():
        evidence = result.fields.get(name)
        if evidence is None:
            print(f"   {name:14} -- unresolved")
        else:
            print(f"   {name:14} {evidence.value!r:44} {evidence.source:9} {evidence.detail}")
    print()
