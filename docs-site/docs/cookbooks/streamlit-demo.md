# Cookbook — Streamlit stakeholder demo

You're presenting `arche-core` to a stakeholder — a procurement officer at a Lagos health-tech buyer, a programme manager at an African NLP funder, a regulator's deputy who wants to see what *"statute-grounded PII detection"* means in practice. They have ten minutes. They are not going to read the README. They are going to look at a screen.

**Before arche-core:** you screenshot terminal output and hope it lands. The screenshots show JSON dumps. The stakeholder politely asks how this is different from Presidio.

**With arche-core:** a fifty-line Streamlit app turns the same `Pipeline.process()` call into something that lands in seconds. Paste text, pick a jurisdiction, see detections with their statute citations, see the redacted output, copy a signed JWS receipt.

```python
# app.py
import streamlit as st
from arche import Pipeline
from arche.sign import SignWorkflow, generate_keypair

st.set_page_config(page_title="arche-core demo", layout="wide")
st.title("African PII detection — with the law it operates under built in")

JURISDICTIONS = {
    "Nigeria — NDPA-2023": "NG",
    "South Africa — POPIA": "ZA",
    "Kenya — Kenya DPA": "KE",
    "Ghana — Ghana DPA": "GH",
}

col_left, col_right = st.columns([1, 1])

with col_left:
    label = st.selectbox("Jurisdiction", list(JURISDICTIONS.keys()))
    jurisdiction = JURISDICTIONS[label]
    sample = st.text_area(
        "Paste text to scan (synthetic only — never real PII)",
        height=240,
        value=(
            "Customer Adesola Okonkwo registered with NIN 12345678901 "
            "and BVN 22156789012. Contact phone 0803 555 7890. "
            "Company: RC 245678."
        ),
    )
    run = st.button("Detect + apply policy", type="primary")

if run and sample.strip():
    pipeline = Pipeline(jurisdiction=jurisdiction, tokenize_salt="demo_2026")
    result = pipeline.process(sample)

    with col_right:
        st.subheader("Detections")
        st.dataframe(
            [
                {
                    "Category": d.category,
                    "Tier": d.sensitivity_tier.value,
                    "Citation": d.regulatory_citation,
                    "Text": d.text,
                }
                for d in result.detections
            ],
            hide_index=True,
            use_container_width=True,
        )

        st.subheader("Redacted text (safe to share)")
        st.code(result.redacted_text, language="text")

        st.subheader("Policy outcomes — the rule that fired")
        st.dataframe(
            [
                {
                    "Category": o.category,
                    "Action": o.action,
                    "Statute reference": o.statute_reference,
                }
                for o in result.policy_outcomes
            ],
            hide_index=True,
            use_container_width=True,
        )

        # Optional: signed receipt the stakeholder can copy + verify
        if st.checkbox("Generate signed JWS receipt"):
            demo_key = generate_keypair()
            signed = SignWorkflow(jurisdiction=jurisdiction).sign(
                sample, demo_key, purpose="stakeholder_demo"
            )
            st.subheader("Signed JWS envelope")
            st.code(signed, language="text")
            st.caption(
                f"Issuer did:key: {demo_key.did_key[:40]}... "
                "Verify offline with arche.sign.VerifyExtractWorkflow."
            )

st.divider()
st.caption(
    "Demo runs locally. No data leaves your machine. "
    "Source: github.com/unpatterned-labs/arche. License: Apache 2.0. "
    "Status: pre-beta (development) — not for production use."
)
```

Run it:

```bash
pip install arche-core streamlit
streamlit run app.py
```

The browser opens at `http://localhost:8501`. Paste any of the four preloaded samples (NG / ZA / KE / GH). Click *Detect + apply policy*. The detections show up with sensitivity tier and the actual statute section the policy mapping cites — not as a JSON blob but as a table the stakeholder can read.

## What the stakeholder takes away

When the stakeholder watches the demo and sees `NDPA-2023 s.30, NIMC Act s.27` rendered next to the NIN they pasted, they internalise *"oh, this is the legal layer wrapped around the detection layer."* That sentence is the pitch. It lands in a second when they see it; it takes a paragraph when you describe it.

When they switch the jurisdiction dropdown from Nigeria to South Africa and watch the citations change to POPIA, they internalise *"one tool, four jurisdictions."* That's another second.

When they tick *Generate signed JWS receipt* and see the envelope, they internalise *"and the audit trail is cryptographic."* Third second.

You're now three seconds in and they've understood the moat. Use the remaining nine minutes and fifty-seven seconds to ask what they're trying to build.

## Deployment options

| Where | When |
|---|---|
| Local laptop | Internal demos, evaluation, sales calls |
| Streamlit Community Cloud | Public live demo (e.g. demo.unpatterned.org) — free tier is fine for stakeholder demos |
| Docker container behind your reverse proxy | When the stakeholder wants to evaluate on their own data inside their perimeter |

The Streamlit Community Cloud deployment of this script (with four preloaded samples) is exactly what's at [demo.unpatterned.org](https://demo.unpatterned.org). Source: [`demo/app.py`](https://github.com/unpatterned-labs/arche/blob/main/demo/app.py).

## See also

- [Cookbook — Nigerian fintech KYC](fintech-kyc.md) — the production version of what this demo shows
- [Quick Start example 1](../getting-started/quickstart.md#1-the-pipeline-primitive-ndpa-2023-enforcement-in-one-call) — same Pipeline call as the demo
- [Why arche & when to use it](../tutorials/arche_vs_alternatives.md) — the conversion page after the demo lands