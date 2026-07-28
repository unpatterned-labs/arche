# Copyright 2026 unpatterned.org
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Lagos telehealth intake — the egress guard end to end.

An AI agent takes a patient note and wants a US-hosted LLM to summarise it.
This shows what the pack trio + egress guard do that used to be hand-coded:
which law applies, what happens per field, whether the note may cross a border,
and the audit obligations — deterministically, in one path.

It is deliberately HONEST about coverage: the guard's guarantee is fail-closed
*refusal*, not perfect detection. Run:

  uv run python packages/arche-core/examples/telehealth_intake.py
"""

from arche.guard import EgressGuard, GuardDenied
from arche.policy import load_statute
from arche.policy.overlay import apply_overlay, load_overlay
from arche.workflow._primitive import Pipeline

TEXT = ("Patient Chinedu Okafor, NIN 12345678901, HIV positive, "
        "phone 08031234567, Lekki.")


def main() -> None:
    statute = load_statute("NDPA-2023")
    print("SCENARIO: Lagos telehealth intake; an agent wants a US-hosted LLM to")
    print("          summarise the note.\n")
    print("INPUT:", TEXT, "\n")

    # [1] The safe answer for special-category data crossing a border: REFUSE.
    #     Nothing is sent — so the HIV status never leaves, even though free-text
    #     health is not something the detector reliably catches (see [3]).
    guard = EgressGuard(Pipeline(statute="NDPA-2023"), key="clinic-key")
    try:
        guard.guarded(TEXT, provider="us-llm", crosses_border=True)
    except GuardDenied as denied:
        print("[1] Cross-border call to the US LLM, no declared basis  ->  REFUSED")
        print("    reason:", denied.reason)
        print("    cites :", denied.citation)
        print("    => fail-closed: the whole note stays in-region. The HIV status")
        print("       never leaves, whether or not the detector saw it.\n")

    # [2] In-region (or with a declared, permitted basis): emit a projection with
    #     no raw identifiers. What IS detected becomes a hashed ID + citation.
    inregion = EgressGuard(Pipeline(statute="NDPA-2023"), key="clinic-key",
                           transfer_basis="standard_contractual_clauses")
    proj = inregion.guarded(TEXT, provider="in-region-llm")
    print("[2] In-region projection the model may see:")
    print("   ", proj.redacted_text)
    for f in proj.fields:
        print(f"      - {f.category:12} {f.action:9} {f.tier:8} cites {f.citation}")
    print()

    # [3] Honest coverage boundary. The projection above still shows "HIV positive",
    #     "Lekki", and the given name "Chinedu" in the clear, and the 11-digit phone
    #     was mis-typed as a NIN. Detection coverage is the gap; the POLICY is ready:
    action, ref, _ = statute.action_for("PII-6-HEALTH")
    print("[3] Coverage boundary (honest):")
    print("    - free-text health ('HIV positive') NOT detected -> would leak in [2];")
    print(f"      but the policy is ready: PII-6-HEALTH -> {action}, cites {ref}")
    print("    - 'Lekki' and the given name 'Chinedu' under-detected")
    print("    - 11-digit phone mis-typed as NIN (both 11 digits) — a real bug to fix")
    print("    => this is why special-category data crossing a border is REFUSED (1),")
    print("       not trusted to redaction. Fail-closed beats detect-everything.\n")

    # [4] EU AI Act obligations stamped on the run.
    result = Pipeline(statute="NDPA-2023").process(TEXT)
    result = apply_overlay(
        result, load_overlay("EU-AI-ACT"),
        transparency_notice="This assistant uses AI; output is AI-generated.",
    )
    print("[4] EU AI Act obligations for the run:")
    for o in result.metadata["ai_act"]["obligations"]:
        print(f"      - {o['article']:22} satisfied={o['satisfied']}")
    print()

    print("WHAT'S NEW: which law applies, the per-field action + citation (NG/EU/US),")
    print("the fail-closed cross-border refusal, and the AI-Act obligations — one path,")
    print("310KB SDK, deterministic. Before the trio, every line of that was hand-rolled.")


if __name__ == "__main__":
    main()
