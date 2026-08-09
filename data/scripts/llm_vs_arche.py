"""Head-to-head: a frontier LLM vs arche's gate, on real Nigerian facility data.

The honest version of "can't a frontier model just do this?". It runs both over
the same pairs and reports where they disagree, so the question is settled by
evidence rather than by argument.

Usage
-----
    # key comes from your environment or .env
    export ANTHROPIC_API_KEY=...        # or OPENAI_API_KEY
    python data/scripts/llm_vs_arche.py --provider anthropic --model claude-sonnet-4-5

    # no key, no network — see the pairs and arche's verdicts only
    python data/scripts/llm_vs_arche.py --dry-run

The pairs below are not cherry-picked to make arche look good. They are the
real output of `crosswalk(HFR_Kano_residue, GRID3_Kano, entity="place")` — the
top of the match list and the top of the review list. The review cases are the
interesting ones: they are where a fluent, confident answer is available and
wrong.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# (facility A, facility B, arche's verdict, arche's score, why it matters)
PAIRS = [
    # --- arche said MATCH: word order, transliteration, type suffix ---
    ("Al Noury Specialist Hospital", "Al Noury Hospital Specialist",
     "match", 1.000, "word order"),
    ("Yan Amar Health Post", "Yan'Amar Health Post",
     "match", 0.961, "apostrophe / transliteration"),
    ("Kura Surgery and Maternity", "Kura Surgery and Maternity Clinic",
     "match", 0.937, "type suffix only"),
    ("Ggss Maimunatu Health Clinic", "Maimunatu Ggss Health Clinic",
     "match", 1.000, "word order"),

    # --- arche said REVIEW: same place name, materially different facility ---
    ("Dadin Kowa Health Post", "Dadin Kowa Nursing and Maternity Home",
     "review", 0.693, "same settlement, different facility TYPE"),
    ("Gurduba Model Primary Health Center", "Gurduba Health Post",
     "review", 0.687, "different facility LEVEL"),
    ("Mariya Sunusi Maternity Hospital", "Mariya Sanusi General Hospital",
     "review", 0.689, "transliteration match BUT maternity vs general"),
    ("Infectious Disease Hospital", "Kano Infectious Diseases Hospital",
     "review", 0.694, "unqualified name — which one?"),
    ("Gwammaja Maternity and Child Primary Health Center",
     "Gwammaja Primary Health Center",
     "review", 0.693, "specialisation dropped"),
    ("Rurum Tsohon Gari Primary Health Center", "Rurum Primary Health Clinic",
     "review", 0.686, "'Tsohon Gari' = old town — a distinct settlement"),
]

PROMPT = """You are reconciling two Nigerian health facility registries.

Facility A: {a}
Facility B: {b}

Are these the same real-world facility? A wrong merge sends vaccines to the
wrong place and corrupts a national Master Facility List.

Answer with a single JSON object, nothing else:
{{"verdict": "same" | "different" | "unsure", "confidence": 0.0-1.0, "why": "<one short sentence>"}}"""


def load_dotenv() -> None:
    """Minimal .env reader so the script works the way the repo is set up."""
    for path in (".env", os.path.join(os.path.dirname(__file__), "..", "..", ".env")):
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip("'\""))
            return


def ask_llm(provider: str, model: str, a: str, b: str) -> dict:
    prompt = PROMPT.format(a=a, b=b)
    if provider == "anthropic":
        import anthropic

        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=model, max_tokens=200, temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text
    elif provider == "openai":
        from openai import OpenAI

        client = OpenAI()
        resp = client.chat.completions.create(
            model=model, temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.choices[0].message.content
    else:
        raise SystemExit(f"unknown provider: {provider}")

    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1].lstrip("json").strip()
    return json.loads(raw)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="anthropic", choices=["anthropic", "openai"])
    ap.add_argument("--model", default="claude-sonnet-4-5")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the pairs and arche's verdicts; call no model")
    args = ap.parse_args()

    load_dotenv()

    print(f"{'A':52} {'B':52} {'arche':8} {'LLM':10} {'conf':>5}")
    print("-" * 132)

    overconfident = []
    agreed = 0
    asked = 0

    for a, b, verdict, score, why in PAIRS:
        if args.dry_run:
            print(f"{a[:50]:52} {b[:50]:52} {verdict:8} {'—':10} {'—':>5}   ({why})")
            continue

        try:
            out = ask_llm(args.provider, args.model, a, b)
        except Exception as exc:  # noqa: BLE001 — this is a demo harness
            print(f"{a[:50]:52} {b[:50]:52} {verdict:8} ERROR      —   {exc}")
            continue

        asked += 1
        llm = out.get("verdict", "?")
        conf = out.get("confidence", 0.0)
        print(f"{a[:50]:52} {b[:50]:52} {verdict:8} {llm:10} {conf:>5.2f}   {out.get('why','')[:60]}")

        # The failure that matters: arche abstained, the model was sure.
        if verdict == "review" and llm == "same" and conf >= 0.7:
            overconfident.append((a, b, conf, out.get("why", "")))
        if (verdict == "match" and llm == "same") or (verdict == "review" and llm == "unsure"):
            agreed += 1

    if args.dry_run:
        print("\nDry run: no model was called. Re-run with a key to fill the LLM column.")
        return 0

    print("\n" + "=" * 60)
    print(f"pairs asked                        : {asked}")
    print(f"model agreed with arche's posture  : {agreed}")
    print(f"arche abstained, model was certain : {len(overconfident)}")
    for a, b, conf, why in overconfident:
        print(f"    [{conf:.2f}] {a}  ==  {b}")
        print(f"           model: {why}")
    print()
    print("Each line above is a merge arche refused and the model would have made.")
    print("In a Master Facility List, a wrong merge is not a lower score — it is")
    print("two clinics becoming one, and one of them losing its vaccine allocation.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
