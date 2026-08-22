#!/usr/bin/env python
# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""A demo of what an agent gets from arche-mcp, without needing an agent.

    uv run python packages/arche-mcp/demo.py

Calls the same handler functions the MCP tools call, in the order an agent
would, and prints what comes back. No MCP client, no model, no API key — so it
runs in front of a room without anything to go wrong.

It walks one document through the flow twice, Nigerian and British, because the
difference between those two runs is the argument. The same call returns a
redaction with a statute section for one and an honest "I could not look" for
the other, and a tool that could not tell those apart would be worse than
useless. Then it resolves two records the engine refuses to merge, and says why.
"""

from __future__ import annotations

import warnings

warnings.filterwarnings("ignore")

from arche_mcp import handlers  # noqa: E402

NG = ("Referral: Dr Adaeze Okonkwo, NIN 12345678901, at Karfi Health Post, "
      "Kano. Tel 08031234567, adaeze@example.ng. RC 1234567.")
GB = ("Referral: Dr Jane Smith, NI number QQ123456C, at St Thomas' Hospital, "
      "London SW1A 1AA. Tel 07700 900123.")

RULE = "=" * 72


def head(n: int, title: str) -> None:
    print(f"\n{RULE}\n{n}. {title}\n{RULE}")


def walk(label: str, text: str) -> None:
    print(f"\n--- {label} " + "-" * (68 - len(label)))
    print(f"  {text[:100]}...")

    inferred = handlers.infer_jurisdiction(text)
    signals = ", ".join(e["signal"] for e in inferred["evidence"]) or "none"
    print(f"\n  infer_jurisdiction  -> {inferred['country'] or 'ABSTAIN'} "
          f"(confidence {inferred['confidence']}, from: {signals})")
    print(f"                         statute {inferred['statute_id'] or 'NONE'}, "
          f"policy_available={inferred['policy_available']}")
    if not inferred["policy_available"]:
        print(f"                         {inferred['policy_reason'][:64]}...")

    plan = handlers.plan_protection(jurisdiction=inferred["country"])
    print(f"\n  plan_protection     -> {plan['verdict']}")
    print(f"                         {len(plan['uncovered'])} categories with no "
          f"detector at all")
    if plan["degraded_categories"]:
        print(f"                         {len(plan['degraded_categories'])} with a "
              f"detector built elsewhere: {', '.join(plan['degraded_categories'])}")

    scan = handlers.guarded_scan(text, key="demo-key",
                                 jurisdiction=inferred["country"])
    print("\n  guarded_scan        -> ", end="")
    if scan["denied"]:
        print(f"DENIED: {scan['reason'][:60]}...")
        return
    print(f"{len(scan['fields'])} fields removed")
    print(f"                         {scan['redacted_text'][:96]}")
    for field in scan["fields"][:3]:
        print(f"                           {field['category']:<16} "
              f"{field['action']:<9} {field['citation'] or '(no statute names it)'}")


def main() -> None:
    head(1, "What can this installation do?")
    caps = handlers.capabilities()
    print(f"  arche-core       {caps['arche_core_version']}")
    print(f"  statutes         {', '.join(caps['statutes_available'])}")
    print(f"  can infer        {', '.join(caps['jurisdictions_inferable'])}")
    print(f"  entity packs     {', '.join(caps['entity_packs'])}")
    print(f"  optional extras  {caps['extras']}")
    print("\n  Nothing here is a guess. An agent that skips this call finds out")
    print("  a detector is missing by getting an empty result and believing it.")

    head(2, "The same call, two countries")
    walk("Nigeria", NG)
    walk("Britain", GB)
    print("\n  The British run is the interesting one. Same tool, same code, and")
    print("  it says so: three of the detectors that ran were built for African")
    print("  data. A clean result there does not mean the document was clean.")

    head(3, "Which fields does a pack actually read?")
    described = handlers.describe_pack("person")
    for field in described["fields"][:4]:
        print(f"  {field['field']:<14} weight {field['weight']:<5} "
              f"{'+'.join(field['kinds'])}")
    print("\n  Anything else is IGNORED, not rejected. Give a record an")
    print("  'occupation' and nothing errors and nothing changes.")

    head(4, "Two records the engine refuses to merge")
    a = [{"id": "a1", "name": "General Hospital"}]
    b = [{"id": "b1", "name": "General Hospital"}]
    edge = handlers.compare_records(a, b, entity="place")["matches"][0]
    print("  'General Hospital'  vs  'General Hospital'")
    print(f"\n  score            {edge['score']:.3f}   <- byte-identical strings")
    print(f"  decision         {edge['decision']}")
    print(f"  distinctive_max  {edge['distinctive_max']:.3f}   <- floor is 0.750")
    print("\n  Every comparator agreed perfectly and it still will not merge them,")
    print("  because 'General' and 'Hospital' are ordinary words and agreeing on")
    print("  ordinary words is not evidence. That is the whole argument.")

    head(5, "And one it does merge")
    a = [{"id": "a1", "name": "Adaeze Okonkwo", "birth_date": "1990-03-02"}]
    b = [{"id": "b1", "name": "Adaeze Okonkwo", "birth_date": "2/3/1990"}]
    edge = handlers.compare_records(a, b, entity="person")["matches"][0]
    print("  'Adaeze Okonkwo' 1990-03-02  vs  'Adaeze Okonkwo' 2/3/1990")
    print(f"\n  score            {edge['score']:.3f}")
    print(f"  decision         {edge['decision']}")
    print(f"  evidence         {edge['evidence']}")
    print("\n  Different date formats, one date. A rare name carries it.")

    print(f"\n{RULE}")
    print("Every number above came from the same functions the MCP tools call.")
    print("Wire it to a client with the config in packages/arche-mcp/README.md.")
    print(RULE)


if __name__ == "__main__":
    main()
