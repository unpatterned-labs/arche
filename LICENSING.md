# Licensing

arche uses a dual licensing model designed to maximize open-source adoption while protecting the research datasets that make identity resolution work in emerging markets.

## Code — Apache License 2.0

All source code in `packages/arche-core/` is licensed under the **Apache License 2.0**. You can use, modify, distribute, and build commercial products on top of arche with no restrictions beyond standard Apache 2.0 terms.

This includes:
- The resolution engine (extract, resolve, protect, signal, locate, graph)
- FHIR transforms and DPI adapter interfaces
- Governance/compliance framework
- CLI and MCP server
- All test code

See [LICENSE](LICENSE) for the full text.

## Datasets — CC-BY-NC-SA 4.0

The cultural naming dataset in `datasets/` is licensed under **Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International (CC-BY-NC-SA 4.0)**.

This includes:
- Name equivalence groups (pan-Islamic, West African, East African, Southern African, North African, cross-linguistic)
- Provenance and regional metadata

**You may:**
- Use the dataset for academic research, non-profit work, and personal projects
- Share and adapt the dataset with attribution
- Use the dataset in open-source DPI deployments (government identity systems are non-commercial by nature)

**You may not:**
- Use the dataset in commercial products without a separate license from unpatterned.ai
- Redistribute the dataset without the same CC-BY-NC-SA 4.0 license

**Commercial licensing:** Contact licensing@unpatterned.ai for commercial use of the naming dataset. Pricing is based on deployment scale, not per-record.

See [datasets/DATASET_LICENSE.md](datasets/DATASET_LICENSE.md) for the full text.

## Jurisdiction Compliance Data

Compliance metadata (data protection law details, PII classification rules, retention limits, penalty structures) in jurisdiction packs is **proprietary data** owned by unpatterned.ai. A starter subset is included in the open-source distribution for demonstration and testing. Production compliance data requires a commercial license.

## Why This Structure

| Layer | License | Rationale |
|---|---|---|
| **SDK code** | Apache 2.0 | Maximum adoption. Developers build on it freely. |
| **Naming dataset** | CC-BY-NC-SA 4.0 | Research credibility + community contributions. Commercial use requires license. |
| **Compliance data** | Proprietary | This is curated legal/regulatory research. The thing fintechs pay for. |
| **Trained models** (future) | Restricted | Like Meta's Llama — visible but not freely redistributable for competing products. |
| **Platform (Plehthore)** | Proprietary | The commercial SaaS product. |

This follows the proven open-core model used by Elastic, MongoDB, Databricks, and HashiCorp: open the engine for distribution, protect the data and platform for revenue.

## Attribution

When using arche in academic work, please cite:

```
arche: Open-source identity resolution for Digital Public Infrastructure.
unpatterned.ai, 2026. https://github.com/Plehthore/arche
```

## Contact

- Open-source: https://github.com/Plehthore/arche
- Commercial licensing: licensing@unpatterned.ai
- Lab: https://unpatterned.ai
