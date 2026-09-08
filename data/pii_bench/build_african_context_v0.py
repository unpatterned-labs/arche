#!/usr/bin/env python
# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""Build `african_context_v0.jsonl`: a constructed PII-detection set with exact spans.

    python data/pii_bench/build_african_context_v0.py

Why constructed
---------------
The open PII sets with span labels are either licence-gated (ai4privacy's
300k is academic-only, no derivatives; i2b2/n2c2 needs a data-use agreement)
or carry no African identifiers at all. This set is built from templates the
way those sets were, with one difference: every identifier passes arche's own
validator at build time, every span is computed by construction rather than
searched for, and every row carries **negatives** -- an order number, an ISBN,
a time, an amount -- so a false positive has somewhere to land and be counted.

What it is not: adjudicated text from the wild. Recall on this set says the
detectors read what they were built to read; it does not say what they do on
a clinic's actual referral notes, which is the set that still has to be made
by hand (plan B4, second half). Numbers from this file are labelled
*constructed* wherever they are published.

Names are drawn from two pools and each span records which: names the shipped
lexicon holds (``lexicon``) and names it does not (``heldout``), checked at
build time with :func:`arche.detect._names.lexicon.is_known_african_name`, so
the lexicon's coverage of its own gap is visible in the results rather than
assumed. Seeded; the file is reproducible byte for byte.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[1]
sys.path.insert(0, str(_REPO / "packages" / "arche-core" / "src"))

from arche.detect._names.lexicon import is_known_african_name  # noqa: E402
from arche.detect.gh.ids import _validate_ghana_card  # noqa: E402
from arche.detect.ke.ids import _validate_kra_pin  # noqa: E402
from arche.detect.za.ids import _validate_sa_id  # noqa: E402

OUT = _HERE / "african_context_v0.jsonl"
SEED = 2026
ROWS_PER_JURISDICTION = 60

FIRST = ["Adesola", "Chiamaka", "Nnamdi", "Oluwaseun", "Ibrahim", "Fatima", "Amina",
         "Wanjiru", "Kamau", "Achieng", "Thandiwe", "Sipho", "Naledi", "Kwabena", "Efua",
         "Kofi", "Abena", "Tobenna", "Zainab", "Emeka", "Halima", "Chidi", "Nomvula",
         "Kwame", "Akosua", "Yusuf", "Ngozi", "Otieno", "Lerato", "Yaw"]
LAST = ["Okonkwo", "Abdullahi", "Musa", "Adeyemi", "Nwosu", "Okafor", "Bello", "Mwangi",
        "Odhiambo", "Kariuki", "Dlamini", "Nkosi", "Mokoena", "Mensah", "Boateng", "Asante",
        "Owusu", "Eze", "Ibekwe", "Kamara", "Quill", "Oyelaran", "Vermeulen", "Khumalo"]
STREETS = {
    "NG": ["12 Zaria Road", "4 Ember Street", "Plot 7 Awolowo Way", "23 Aminu Kano Crescent",
           "No. 9 Ikot Ekpene Road"],
    "KE": ["Kimathi Street", "Plot 14 Ngong Road", "Moi Avenue", "Kenyatta Avenue"],
    "ZA": ["17 Jan Smuts Avenue", "8 Bree Street", "45 Long Street", "3 Vilakazi Street"],
    "GH": ["14 Oxford Street, Osu", "Liberation Road", "Ring Road Central", "Spintex Road"],
}
ANCHORS = ["opposite the central mosque", "behind Shoprite", "beside the filling station",
           "after the second gate", "near St Mary's church"]
CITIES = {"NG": ["Kano", "Lagos", "Enugu", "Ibadan"], "KE": ["Nairobi", "Kisumu", "Mombasa"],
          "ZA": ["Johannesburg", "Durban", "Cape Town"], "GH": ["Accra", "Kumasi", "Tamale"]}
# Valid national lengths: NG 11 digits (0803 + 7), KE 10 (0722 + 6), ZA 10
# (082 + 7), GH 10 (024 + 7). The first draft gave Kenya 0722 + 7 and Nigeria
# a 12-digit 09012 form, and the benchmark duly reported them missed -- the
# validators caught a data bug before it became a detector claim.
PHONES = {
    "NG": ["0803 {a} {b}", "0806{a}{b}", "+234 803 {a} {b}", "0703-{a}-{b}", "0901 {a} {b}"],
    "KE": ["0722 {a}{c}", "+254 722 {a} {c}", "0712 {a} {c}", "+254712{a}{c}"],
    "ZA": ["082 {a} {b}", "+27 82 {a} {b}", "071 {a}{b}", "+27 71 {a} {b}"],
    "GH": ["024 {a} {b}", "+233 24 {a} {b}", "054{a}{b}", "+233 54 {a} {b}"],
}
DOMAINS = ["gmail.com", "yahoo.com", "example.ng", "kijani.co.ke", "outlook.com", "mtn.gh"]


def luhn_check(body: str) -> str:
    total = 0
    for i, ch in enumerate(reversed(body)):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return str((10 - total % 10) % 10)


class Gen:
    def __init__(self, rng: random.Random):
        self.r = rng

    def digits(self, n: int) -> str:
        return "".join(self.r.choice("0123456789") for _ in range(n))

    def name(self) -> tuple[str, str]:
        first, last = self.r.choice(FIRST), self.r.choice(LAST)
        full = f"{first} {last}"
        known = is_known_african_name(first) and is_known_african_name(last)
        return full, ("lexicon" if known else "heldout")

    def nin(self) -> str:
        return self.digits(11)

    def bvn(self) -> str:
        return "22" + self.digits(9)

    def sa_id(self) -> str:
        while True:
            yy, mm, dd = self.r.randint(60, 99), self.r.randint(1, 12), self.r.randint(1, 28)
            body = f"{yy:02d}{mm:02d}{dd:02d}{self.r.randint(0, 9999):04d}0{self.r.choice('89')}"
            cand = body + luhn_check(body)
            if _validate_sa_id(cand)[0]:
                return cand

    def ghana_card(self) -> str:
        while True:
            cand = f"GHA-{self.digits(9)}-{self.r.randint(0, 9)}"
            if _validate_ghana_card(cand)[0]:
                return cand

    def kra_pin(self) -> str:
        while True:
            cand = f"{self.r.choice('AP')}{self.digits(9)}{self.r.choice('ABCDEFGHJKLMNPQRSTUVWXYZ')}"
            if _validate_kra_pin(cand)[0]:
                return cand

    def za_passport(self) -> str:
        return f"{self.r.choice('AM')}{self.digits(8)}"

    def phone(self, j: str) -> str:
        return self.r.choice(PHONES[j]).format(a=self.digits(3), b=self.digits(4),
                                               c=self.digits(3))

    def email(self, full_name: str) -> str:
        first, last = full_name.lower().split()
        return f"{first}.{last}{self.r.randint(1, 99)}@{self.r.choice(DOMAINS)}"

    def address(self, j: str) -> str:
        street = self.r.choice(STREETS[j])
        city = self.r.choice(CITIES[j])
        if j == "NG" and self.r.random() < 0.5:
            return f"{street}, {self.r.choice(ANCHORS)}, {city}"
        return f"{street}, {city}"

    def dob(self) -> str:
        y, m, d = self.r.randint(1955, 2005), self.r.randint(1, 12), self.r.randint(1, 28)
        return self.r.choice([f"{d:02d}/{m:02d}/{y}", f"{y}-{m:02d}-{d:02d}", f"{d} March {y}"])

    def card(self) -> str:
        body = self.r.choice("45") + self.digits(14)
        n = body + luhn_check(body)
        return " ".join(n[i:i + 4] for i in range(0, 16, 4))

    def ip(self) -> str:
        return f"{self.r.randint(11, 223)}.{self.r.randint(0, 255)}.{self.r.randint(0, 255)}.{self.r.randint(1, 254)}"

    def password(self) -> str:
        return "".join(self.r.choice("abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789!$#") for _ in range(10))

    def account(self) -> str:
        return self.digits(10)

    # ---- negatives: shapes that look like identifiers and are not -----------
    def order_no(self) -> str:
        return self.r.choice(["ORD-", "INV-", "PO "]) + self.digits(self.r.choice([7, 8, 10]))

    def isbn(self) -> str:
        while True:
            body = "978" + self.digits(9)
            total = sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(body))
            isbn = body + str((10 - total % 10) % 10)
            return f"ISBN {isbn}"

    def amount(self, j: str) -> str:
        sym = {"NG": "NGN", "KE": "KES", "ZA": "ZAR", "GH": "GHS"}[j]
        return f"{sym} {self.r.randint(1, 900)},{self.digits(3)}.00"

    def time(self) -> str:
        return f"{self.r.randint(8, 18)}:{self.r.choice(['00', '15', '30', '45'])}"

    def plain_date(self) -> str:
        return f"{self.r.randint(1, 28):02d}/{self.r.randint(1, 12):02d}/2026"


class Row:
    """Assemble a text from parts, recording spans by construction."""

    def __init__(self, jurisdiction: str):
        self.j = jurisdiction
        self.parts: list[str] = []
        self.spans: list[dict] = []
        self.negatives: list[dict] = []
        self.pos = 0

    def say(self, s: str) -> Row:
        self.parts.append(s)
        self.pos += len(s)
        return self

    def pii(self, value: str, category: str, **meta) -> Row:
        self.spans.append({"start": self.pos, "end": self.pos + len(value),
                           "category": category, **meta})
        return self.say(value)

    def neg(self, value: str, kind: str) -> Row:
        self.negatives.append({"start": self.pos, "end": self.pos + len(value), "kind": kind})
        return self.say(value)

    def build(self, row_id: str) -> dict:
        text = "".join(self.parts)
        for s in self.spans + self.negatives:
            assert text[s["start"]:s["end"]], (row_id, s)
        return {"id": row_id, "jurisdiction": self.j, "text": text,
                "spans": self.spans, "negatives": self.negatives}


def national_id(g: Gen, j: str) -> tuple[str, str, str]:
    """(cue text, value, category) for the jurisdiction's primary identifier."""
    if j == "NG":
        return ("NIN ", g.nin(), "PII-2-NIN") if g.r.random() < 0.7 else ("BVN ", g.bvn(), "PII-2-BVN")
    if j == "KE":
        return ("KRA PIN ", g.kra_pin(), "PII-2-KRA_PIN") if g.r.random() < 0.5 \
            else ("Huduma Namba ", g.digits(9), "PII-2-HUDUMA")
    if j == "ZA":
        return ("ID number ", g.sa_id(), "PII-2-NATIONAL_ID") if g.r.random() < 0.75 \
            else ("passport ", g.za_passport(), "PII-2-PASSPORT")
    return ("Ghana Card ", g.ghana_card(), "PII-2-GHANA_CARD")


def make_row(g: Gen, j: str, template: int, row_id: str) -> dict:
    r = Row(j)
    name, pool = g.name()
    cue, idv, idcat = national_id(g, j)
    t = template % 8
    if t == 0:    # KYC note
        (r.say("KYC note: ").pii(name, "PII-1-NAME", pool=pool).say(", born ")
          .pii(g.dob(), "PII-1-DOB").say(f", {cue}").pii(idv, idcat).say(", phone ")
          .pii(g.phone(j), "PII-3-PHONE").say(", ").pii(g.email(name), "PII-3-EMAIL")
          .say(", lives at ").pii(g.address(j), "PII-4-ADDRESS").say(". Account opened ")
          .neg(g.plain_date(), "date").say(" at ").neg(g.time(), "time").say("."))
    elif t == 1:  # clinic referral
        (r.say("Referral: patient ").pii(name, "PII-1-NAME", pool=pool).say(" (").say(cue)
          .pii(idv, idcat).say(") seen ").neg(g.plain_date(), "date").say(". Next of kin on ")
          .pii(g.phone(j), "PII-3-PHONE").say(". Ward fee ").neg(g.amount(j), "amount")
          .say(", receipt ").neg(g.order_no(), "order_no").say("."))
    elif t == 2:  # HR onboarding
        (r.say("New starter ").pii(name, "PII-1-NAME", pool=pool).say(", ")
          .pii(g.email(name), "PII-3-EMAIL").say(", salary account ")
          .pii(g.account(), "PII-5-BANK_ACCOUNT").say(", laptop asset ")
          .neg(g.order_no(), "order_no").say(", VPN from ").pii(g.ip(), "PII-8-IP_ADDRESS")
          .say(". Temporary password ").pii(g.password(), "PII-8-PASSWORD").say("."))
    elif t == 3:  # bank complaint
        (r.say("Complaint from ").pii(name, "PII-1-NAME", pool=pool).say(": card ")
          .pii(g.card(), "PII-5-CARD").say(" charged ").neg(g.amount(j), "amount")
          .say(" twice on ").neg(g.plain_date(), "date").say(". Callback ")
          .pii(g.phone(j), "PII-3-PHONE").say(", reference ").neg(g.order_no(), "order_no")
          .say("."))
    elif t == 4:  # school register
        (r.say("Register: ").pii(name, "PII-1-NAME", pool=pool).say(", born ")
          .pii(g.dob(), "PII-1-DOB").say(", guardian ").pii(g.phone(j), "PII-3-PHONE")
          .say(", ").pii(g.address(j), "PII-4-ADDRESS").say(". Textbook ").neg(g.isbn(), "isbn")
          .say(" issued."))
    elif t == 5:  # delivery note
        (r.say("Deliver ").neg(g.order_no(), "order_no").say(" to ")
          .pii(name, "PII-1-NAME", pool=pool).say(", ").pii(g.address(j), "PII-4-ADDRESS")
          .say(". Call ").pii(g.phone(j), "PII-3-PHONE").say(" on arrival; window ")
          .neg(g.time(), "time").say("-").neg(g.time(), "time").say("."))
    elif t == 6:  # chat message
        (r.say("pls send ur ").say(cue.strip().lower()).say(" ").pii(idv, idcat)
          .say(" and ").pii(g.email(name), "PII-3-EMAIL").say(" so i can register u, mine is ")
          .pii(g.phone(j), "PII-3-PHONE").say(" - ").pii(name.split()[0], "PII-1-NAME", pool=pool)
          .say(""))
    else:         # invoice (mostly negatives)
        (r.say("Invoice ").neg(g.order_no(), "order_no").say(" dated ").neg(g.plain_date(), "date")
          .say(": ").neg(g.amount(j), "amount").say(" payable by ").neg(g.plain_date(), "date")
          .say(". Contact ").pii(name, "PII-1-NAME", pool=pool).say(", ")
          .pii(g.email(name), "PII-3-EMAIL").say(". Ref ").neg(g.digits(10), "ten_digits")
          .say("."))
    return r.build(row_id)


def main() -> int:
    g = Gen(random.Random(SEED))
    rows = []
    for j in ("NG", "KE", "ZA", "GH"):
        for i in range(ROWS_PER_JURISDICTION):
            rows.append(make_row(g, j, i, f"{j.lower()}-{i:03d}"))
    with OUT.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    spans = sum(len(r["spans"]) for r in rows)
    negs = sum(len(r["negatives"]) for r in rows)
    pools = {}
    for r in rows:
        for s in r["spans"]:
            if s["category"] == "PII-1-NAME":
                pools[s["pool"]] = pools.get(s["pool"], 0) + 1
    print(f"wrote {OUT.relative_to(_REPO)}: {len(rows)} rows, {spans} spans, {negs} negatives, "
          f"names {pools}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
