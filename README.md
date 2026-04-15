# Seasonal Storage — Techno-Economic Model

Interactive Streamlit model to compare seasonal (50h+) storage pathways on a
like-for-like LCOS basis, using methodology consistent with
**ETC (2025) *Power Systems Transformation*** (Box E, Exhibits 1.32–1.42).

Built specifically to pressure-test the ETC conclusions on seasonal storage in
advance of a discussion about **solar → e-methane → CCGT** as a novel seasonal pathway.

## Pathways compared

| Pathway | Notes |
|---------|-------|
| **Unabated OCGT (no removals)** | **Counterfactual — fossil status quo, no decarbonisation** |
| Green H2 → OCGT | ETC reference |
| Green H2 → CCGT | ETC sensitivity |
| CH4 + CCS → CCGT | ETC reference |
| Unabated OCGT + carbon-removal offset | ETC sensitivity |
| **Solar → e-methane (DAC CO2) → CCGT** | Novel, not covered in ETC report |
| **Solar → e-methane (Biogenic CO2) → CCGT** | Novel variant |
| **Solar → e-methane (Point-source CO2) → CCGT** | Novel variant |
| Iron-air battery (e.g., Form Energy) | Emerging seasonal-storage tech |

Every numeric assumption is overridable from the sidebar; every default carries a source tag in the **Assumptions** tab.

## Run

```
pip install -r requirements.txt
streamlit run app.py
```

The app opens in the browser. Use the sidebar to set region (China / Ex-China), year (2035 / 2050), and any slider. Tabs:

1. **LCOS comparison** — stacked bar chart of delivered-electricity cost per pathway.
2. **Sensitivity (tornado)** — ±30% swings on key inputs for a chosen pathway.
3. **2D heatmap** — sweep any two of {electrolyser utilisation, electricity input price, turbine utilisation, gas price, CO2 cost}.
4. **Assumptions** — full audit trail with sources, plus ETC validation panel.

## Methodology

For each pathway, stages are chained and efficiency cascades through the chain:

```
η_pathway = Π_stages η_stage          (e.g. electrolyser × methanation × CCGT ≈ 0.71 × 0.82 × 0.60 = 0.35)
MWh_grid_in per MWhe out = 1 / η_pathway       (for e-fuel pathways)
```

Each stage's annualised cost is expressed as `$/MWh_out` and scaled by `1 / (downstream η product)`
so all cost lines ultimately appear on a `$/MWh_delivered` basis. Capital recovery factor:

```
CRF = r(1+r)^n / ((1+r)^n − 1)
```

Electrolyser CAPEX is treated as per **kW electrical input** (standard convention).
Turbine CAPEX is per **kW electrical output**. This is handled by a `capex_basis` flag on each stage.

**CO2 feedstock for e-methane**: stoichiometric 0.198 tCO2 per MWh_CH4 (LHV), scaled up through the CCGT efficiency.

## Validation

The model reproduces ETC Exhibit 1.40 (Scenario A: 20% electrolyser utilisation, $0/MWh electricity) within ≈10% across all four region/year combinations:

| Region | Year | Model ($/MWh) | ETC ($/MWh) | Δ |
|---|---|---|---|---|
| Ex-China | 2035 | ~606 | 610 | −1% |
| China | 2035 | ~329 | 320 | +3% |
| Ex-China | 2050 | ~417 | 460 | −9% |
| China | 2050 | ~253 | 270 | −6% |

Other pathways at Ex-China 2050 defaults sit inside ETC ranges:
- CH4 + CCS → CCGT (10% util): ~$264/MWh vs ETC $200–270
- Unabated OCGT + $50/t removal (5% util): ~$272/MWh vs ETC $215–300
- Unabated OCGT + $200/t removal: ~$347/MWh vs ETC $270–380

## Default assumptions — what comes from ETC vs supplementary

| Parameter | Source |
|---|---|
| Electrolyser CAPEX, η, utilisation, OPEX | ETC Exhibit 1.38 |
| H2 salt-cavern storage CAPEX, throughput, cycles | ETC Exhibit 1.38 |
| OCGT CAPEX, OPEX, efficiency | ETC Exhibit 1.38 |
| CCGT CAPEX, OPEX, efficiency | ETC Exhibit 1.42 |
| CCS CAPEX, parasitic efficiency penalty | ETC + BNEF (2025) LCOE Data Viewer |
| Natural gas price ($6/MMBtu) | ETC Section 1.5.1 |
| DAC CO2 cost (2035: $510/t, 2050: $300/t) | Year-dependent; informed by current project-level quotes (2035) and ETC *Mind the Gap* (2021) trajectory toward 2050 |
| **Methanation CAPEX & efficiency** | Supplementary — IEA (2020); academic TEA literature |
| **CH4 (gas) storage CAPEX & cycles** | Supplementary — EIA/FERC-linked underground gas-storage cost data |
| **Iron-air CAPEX, efficiency** | Supplementary — Form Energy public targets; BNEF (2024) Long-Duration Energy Storage Survey |
| Storage cycle count (12/yr default for H2 and CH4) | User-adjustable default for ultra-long-duration balancing case |

The Assumptions tab in the UI lists every value with its source tag.

## Key sanity checks built into the default view

- Solar → e-methane (DAC, $200/t CO2, new gas storage) lands *above* H2 → OCGT Scenario A → the headline ETC conclusion still holds at default inputs.
- But if existing gas-storage infrastructure can be reused (drop CH4 storage CAPEX to ~$0.03/kWh) **and** biogenic CO2 is available at ≤$30/t, e-methane closes most of the gap to CH4+CCS.
- Iron-air battery is **cycle-constrained, not CAPEX-constrained**. With 100h duration, a full cycle takes ~200h; at realistic 50% availability that caps cycles at ~15/yr. At Form Energy's Maine project implied CAPEX (~$33/kWh) and ~45% RTE, this lands at $300–350/MWh delivered — not the $47/MWh that more aggressive cycle assumptions would produce. The sidebar exposes a "cycles per year" slider and the heatmap can sweep it, because this is the central Liebreich/Jaramillo debate point.

## Files

- `model.py` — Pure-python LCOS engine. `Stage` dataclass, `Pathway` class, `build_*()` helpers.
- `defaults.py` — Assumption library with source tags, `get_preset(region, year)` accessor.
- `app.py` — Streamlit UI: sidebar + four tabs.
- `requirements.txt` — Dependencies.

No network calls, no external data — everything is reproducible offline from slider values.
