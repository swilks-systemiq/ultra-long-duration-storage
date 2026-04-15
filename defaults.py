"""
Default techno-economic assumptions for ultra-long duration storage pathways.

All numeric values are tagged with a source string so that the Streamlit UI can
render a transparent audit trail alongside the charts.

Primary source: ETC (2025) Power Systems Transformation, Exhibits 1.29, 1.38, 1.42
and surrounding text. Supplementary sources are flagged explicitly.
"""

from copy import deepcopy

# ---------------------------------------------------------------------------
# Storage capacity assumptions (for normalising salt-cavern / gas-storage costs)
# ---------------------------------------------------------------------------
# ETC states salt-cavern H2 storage costs are "$25/kgH2 capacity (China) /
# $40/kgH2 capacity (Ex-China)". We convert to $/kWh capacity:
#   1 kgH2 = 33.3 kWh_LHV, so $25/kg = $0.75/kWh; $40/kg = $1.20/kWh
#   throughput cost ~$0.15-0.20/kg -> $0.0045-0.006/kWh
H2_STORAGE_CAPEX_PER_KWH_CHINA = 25.0 / 33.3         # $0.75
H2_STORAGE_CAPEX_PER_KWH_EX_CHINA = 40.0 / 33.3      # $1.20
H2_STORAGE_THROUGHPUT_PER_MWH = 0.18 / 33.3 * 1000   # ~$5.4/MWh throughput

# Seasonal underground methane storage is typically modelled in depleted fields or
# conventional gas storage, which is much cheaper per unit of working-gas capacity
# than H2 salt caverns. A cautious default of ~$0.03/kWh_CH4 corresponds to roughly
# $9m/Bcf of working-gas capacity, within the broad range reported for underground
# gas storage projects in EIA/FERC-linked literature.
CH4_STORAGE_CAPEX_PER_KWH = 0.03
CH4_STORAGE_THROUGHPUT_PER_MWH = 1.0   # modest handling cost
SEASONAL_STORAGE_CYCLES_PER_YEAR = 1.5

# ---------------------------------------------------------------------------
# Electrolyser (ETC Exhibit 1.38)
# ---------------------------------------------------------------------------
ELECTROLYSER = {
    ("China", 2035): {
        "capex_per_kw": 580.0,     # higher than 2050 ($320) to reflect less cost-down
        "fixed_opex_pct": 0.015,
        "efficiency": 0.60,         # LHV, ETC 2035
        "utilisation": 0.20,
        "lifetime_years": 30,
        "discount_rate": 0.08,
        "capex_basis": "input",
        "source": "ETC (2025) Exhibit 1.38; 2035 extrapolated from 2050 trajectory",
    },
    ("China", 2050): {
        "capex_per_kw": 320.0,
        "fixed_opex_pct": 0.015,
        "efficiency": 0.71,         # LHV, ETC 2050
        "utilisation": 0.20,
        "lifetime_years": 30,
        "discount_rate": 0.08,
        "capex_basis": "input",
        "source": "ETC (2025) Exhibit 1.38",
    },
    ("Ex-China", 2035): {
        "capex_per_kw": 1500.0,    # ETC: cost higher today; trending to $870 by 2050
        "fixed_opex_pct": 0.015,
        "efficiency": 0.60,
        "utilisation": 0.20,
        "lifetime_years": 30,
        "discount_rate": 0.08,
        "capex_basis": "input",
        "source": "ETC (2025) Exhibit 1.38 (2050 $870/kW; 2035 extrapolated higher)",
    },
    ("Ex-China", 2050): {
        "capex_per_kw": 870.0,
        "fixed_opex_pct": 0.015,
        "efficiency": 0.71,
        "utilisation": 0.20,
        "lifetime_years": 30,
        "discount_rate": 0.08,
        "capex_basis": "input",
        "source": "ETC (2025) Exhibit 1.38",
    },
}

# ---------------------------------------------------------------------------
# Methanation (Sabatier) — NOT in ETC, sourced from external TEA literature
# Typical commercial CAPEX estimates: €500–1000/kW_CH4_output for 2030s
# Efficiency: 78–83% (LHV of CH4 out / LHV of H2 in + small aux electricity).
# We treat methanation CAPEX in $/kW of CH4 output, and fold CO2 feedstock cost
# into the Pathway's co2_cost_per_t line.
# ---------------------------------------------------------------------------
METHANATION = {
    ("China", 2035): {
        "capex_per_kw": 600.0,
        "fixed_opex_pct": 0.03,
        "efficiency": 0.80,
        "utilisation": 0.20,        # same as electrolyser by default
        "lifetime_years": 25,
        "discount_rate": 0.08,
        "source": "Supplementary: IEA (2020) Outlook for biogas and biomethane; Koytsoumpa et al. (2018)",
    },
    ("China", 2050): {
        "capex_per_kw": 450.0,
        "fixed_opex_pct": 0.03,
        "efficiency": 0.82,
        "utilisation": 0.20,
        "lifetime_years": 25,
        "discount_rate": 0.08,
        "source": "Supplementary: IEA / academic TEA literature, 2050 projection",
    },
    ("Ex-China", 2035): {
        "capex_per_kw": 900.0,
        "fixed_opex_pct": 0.03,
        "efficiency": 0.80,
        "utilisation": 0.20,
        "lifetime_years": 25,
        "discount_rate": 0.08,
        "source": "Supplementary: IEA / academic TEA literature",
    },
    ("Ex-China", 2050): {
        "capex_per_kw": 700.0,
        "fixed_opex_pct": 0.03,
        "efficiency": 0.82,
        "utilisation": 0.20,
        "lifetime_years": 25,
        "discount_rate": 0.08,
        "source": "Supplementary: IEA / academic TEA literature, 2050 projection",
    },
}

# ---------------------------------------------------------------------------
# H2 storage (salt cavern) — ETC Exhibit 1.38
# ---------------------------------------------------------------------------
H2_STORAGE = {
    ("China", 2035): {
        "capex_per_kwh": H2_STORAGE_CAPEX_PER_KWH_CHINA,
        "fixed_opex_pct": 0.015,
        "efficiency": 1.0,            # ETC assumes storage losses negligible
        "cycles_per_year": SEASONAL_STORAGE_CYCLES_PER_YEAR,
        "lifetime_years": 30,
        "discount_rate": 0.08,
        "throughput_cost_per_mwh": H2_STORAGE_THROUGHPUT_PER_MWH,
        "source": "ETC (2025) Exhibit 1.38 for $/kgH2; cycles aligned to seasonal 1.5/yr default",
    },
    ("China", 2050): {
        "capex_per_kwh": H2_STORAGE_CAPEX_PER_KWH_CHINA,
        "fixed_opex_pct": 0.015,
        "efficiency": 1.0,
        "cycles_per_year": SEASONAL_STORAGE_CYCLES_PER_YEAR,
        "lifetime_years": 30,
        "discount_rate": 0.08,
        "throughput_cost_per_mwh": H2_STORAGE_THROUGHPUT_PER_MWH,
        "source": "ETC (2025) Exhibit 1.38 for $/kgH2; cycles aligned to seasonal 1.5/yr default",
    },
    ("Ex-China", 2035): {
        "capex_per_kwh": H2_STORAGE_CAPEX_PER_KWH_EX_CHINA,
        "fixed_opex_pct": 0.015,
        "efficiency": 1.0,
        "cycles_per_year": SEASONAL_STORAGE_CYCLES_PER_YEAR,
        "lifetime_years": 30,
        "discount_rate": 0.08,
        "throughput_cost_per_mwh": H2_STORAGE_THROUGHPUT_PER_MWH,
        "source": "ETC (2025) Exhibit 1.38 for $/kgH2; cycles aligned to seasonal 1.5/yr default",
    },
    ("Ex-China", 2050): {
        "capex_per_kwh": H2_STORAGE_CAPEX_PER_KWH_EX_CHINA,
        "fixed_opex_pct": 0.015,
        "efficiency": 1.0,
        "cycles_per_year": SEASONAL_STORAGE_CYCLES_PER_YEAR,
        "lifetime_years": 30,
        "discount_rate": 0.08,
        "throughput_cost_per_mwh": H2_STORAGE_THROUGHPUT_PER_MWH,
        "source": "ETC (2025) Exhibit 1.38 for $/kgH2; cycles aligned to seasonal 1.5/yr default",
    },
}

# ---------------------------------------------------------------------------
# CH4 storage (natural-gas caverns / depleted fields)
# ---------------------------------------------------------------------------
CH4_STORAGE = {
    ("China", 2035): {
        "capex_per_kwh": CH4_STORAGE_CAPEX_PER_KWH,
        "fixed_opex_pct": 0.01,
        "efficiency": 1.0,
        "cycles_per_year": SEASONAL_STORAGE_CYCLES_PER_YEAR,      # seasonal: summer-to-winter, ~1-2 cycles/yr
        "lifetime_years": 40,
        "discount_rate": 0.07,
        "throughput_cost_per_mwh": CH4_STORAGE_THROUGHPUT_PER_MWH,
        "source": "Supplementary: EIA/FERC-linked underground gas storage costs; cycles aligned to seasonal 1.5/yr default",
    },
    ("China", 2050): {
        "capex_per_kwh": CH4_STORAGE_CAPEX_PER_KWH,
        "fixed_opex_pct": 0.01,
        "efficiency": 1.0,
        "cycles_per_year": SEASONAL_STORAGE_CYCLES_PER_YEAR,
        "lifetime_years": 40,
        "discount_rate": 0.07,
        "throughput_cost_per_mwh": CH4_STORAGE_THROUGHPUT_PER_MWH,
        "source": "Supplementary: EIA/FERC-linked underground gas storage costs; cycles aligned to seasonal 1.5/yr default",
    },
    ("Ex-China", 2035): {
        "capex_per_kwh": CH4_STORAGE_CAPEX_PER_KWH,
        "fixed_opex_pct": 0.01,
        "efficiency": 1.0,
        "cycles_per_year": SEASONAL_STORAGE_CYCLES_PER_YEAR,
        "lifetime_years": 40,
        "discount_rate": 0.07,
        "throughput_cost_per_mwh": CH4_STORAGE_THROUGHPUT_PER_MWH,
        "source": "Supplementary: EIA/FERC-linked underground gas storage costs; cycles aligned to seasonal 1.5/yr default",
    },
    ("Ex-China", 2050): {
        "capex_per_kwh": CH4_STORAGE_CAPEX_PER_KWH,
        "fixed_opex_pct": 0.01,
        "efficiency": 1.0,
        "cycles_per_year": SEASONAL_STORAGE_CYCLES_PER_YEAR,
        "lifetime_years": 40,
        "discount_rate": 0.07,
        "throughput_cost_per_mwh": CH4_STORAGE_THROUGHPUT_PER_MWH,
        "source": "Supplementary: EIA/FERC-linked underground gas storage costs; cycles aligned to seasonal 1.5/yr default",
    },
}

# ---------------------------------------------------------------------------
# OCGT (ETC Exhibit 1.38)
# ---------------------------------------------------------------------------
OCGT = {
    ("China", 2035): {
        "capex_per_kw": 700.0,
        "fixed_opex_per_kw_yr": 4.0,
        "var_opex_per_mwh": 5.0,      # $0.005/kWh
        "efficiency": 0.40,
        "utilisation": 0.05,           # ETC: 5% utilisation for ultra-long
        "lifetime_years": 30,
        "discount_rate": 0.08,
        "source": "ETC (2025) Exhibit 1.38",
    },
    ("China", 2050): {
        "capex_per_kw": 700.0,
        "fixed_opex_per_kw_yr": 4.0,
        "var_opex_per_mwh": 5.0,
        "efficiency": 0.40,
        "utilisation": 0.05,
        "lifetime_years": 30,
        "discount_rate": 0.08,
        "source": "ETC (2025) Exhibit 1.38",
    },
    ("Ex-China", 2035): {
        "capex_per_kw": 760.0,
        "fixed_opex_per_kw_yr": 17.0,
        "var_opex_per_mwh": 3.0,
        "efficiency": 0.40,
        "utilisation": 0.05,
        "lifetime_years": 30,
        "discount_rate": 0.08,
        "source": "ETC (2025) Exhibit 1.38",
    },
    ("Ex-China", 2050): {
        "capex_per_kw": 760.0,
        "fixed_opex_per_kw_yr": 17.0,
        "var_opex_per_mwh": 3.0,
        "efficiency": 0.40,
        "utilisation": 0.05,
        "lifetime_years": 30,
        "discount_rate": 0.08,
        "source": "ETC (2025) Exhibit 1.38",
    },
}

# ---------------------------------------------------------------------------
# CCGT (ETC Exhibit 1.42)
# ---------------------------------------------------------------------------
CCGT = {
    ("China", 2035): {
        "capex_per_kw": 850.0,
        "fixed_opex_per_kw_yr": 5.0,
        "var_opex_per_mwh": 0.07,
        "efficiency": 0.60,
        "utilisation": 0.10,          # ETC: 10% for CCS-on-CCGT
        "lifetime_years": 30,
        "discount_rate": 0.07,
        "source": "ETC (2025) Exhibit 1.42",
    },
    ("China", 2050): {
        "capex_per_kw": 850.0,
        "fixed_opex_per_kw_yr": 5.0,
        "var_opex_per_mwh": 0.07,
        "efficiency": 0.60,
        "utilisation": 0.10,
        "lifetime_years": 30,
        "discount_rate": 0.07,
        "source": "ETC (2025) Exhibit 1.42",
    },
    ("Ex-China", 2035): {
        "capex_per_kw": 932.0,
        "fixed_opex_per_kw_yr": 20.0,
        "var_opex_per_mwh": 0.06,
        "efficiency": 0.60,
        "utilisation": 0.10,
        "lifetime_years": 30,
        "discount_rate": 0.07,
        "source": "ETC (2025) Exhibit 1.42",
    },
    ("Ex-China", 2050): {
        "capex_per_kw": 932.0,
        "fixed_opex_per_kw_yr": 20.0,
        "var_opex_per_mwh": 0.06,
        "efficiency": 0.60,
        "utilisation": 0.10,
        "lifetime_years": 30,
        "discount_rate": 0.07,
        "source": "ETC (2025) Exhibit 1.42",
    },
}

# ---------------------------------------------------------------------------
# CCS on CCGT — BNEF / ETC figures
# Modelled as an *additional* stage layered on CCGT. efficiency=0.9 reflects the
# parasitic load on the CCGT (~7pp penalty on 60% eff ≈ retention of 0.88-0.93).
# ---------------------------------------------------------------------------
CCS = {
    ("China", 2035): {
        "capex_per_kw": 600.0,
        "fixed_opex_per_kw_yr": 15.0,
        "var_opex_per_mwh": 10.0,     # includes CO2 T&S
        "efficiency": 0.88,            # retention after parasitic load
        "utilisation": 0.10,
        "lifetime_years": 25,
        "discount_rate": 0.07,
        "source": "ETC (2025) text + BNEF (2025) LCOE Data Viewer",
    },
    ("China", 2050): {
        "capex_per_kw": 500.0,
        "fixed_opex_per_kw_yr": 12.0,
        "var_opex_per_mwh": 8.0,
        "efficiency": 0.90,
        "utilisation": 0.10,
        "lifetime_years": 25,
        "discount_rate": 0.07,
        "source": "ETC (2025) text + BNEF (2025)",
    },
    ("Ex-China", 2035): {
        "capex_per_kw": 800.0,
        "fixed_opex_per_kw_yr": 25.0,
        "var_opex_per_mwh": 15.0,
        "efficiency": 0.88,
        "utilisation": 0.10,
        "lifetime_years": 25,
        "discount_rate": 0.07,
        "source": "ETC (2025) + BNEF (2025)",
    },
    ("Ex-China", 2050): {
        "capex_per_kw": 650.0,
        "fixed_opex_per_kw_yr": 22.0,
        "var_opex_per_mwh": 12.0,
        "efficiency": 0.90,
        "utilisation": 0.10,
        "lifetime_years": 25,
        "discount_rate": 0.07,
        "source": "ETC (2025) + BNEF (2025)",
    },
}

# ---------------------------------------------------------------------------
# Iron-air battery (supplementary) — calibrated against Form Energy disclosures
#
# Key reality check: iron-air is cycle-constrained, NOT CAPEX-constrained. A
# 100h duration battery physically takes ~100h to charge + ~100h to discharge,
# so a full cycle is ~200h. Even at 100% availability that caps cycles at ~45/yr;
# realistic availability (~50%) gives ~15 cycles/yr. With ~45% round-trip
# efficiency (Form Energy's published range is 38-50%) the economics are tough.
#
# CAPEX: Form Energy's Maine project is reported at ~$1bn for 30 GWh =
# ~$33/kWh installed. Their target for 2030+ is lower ($20-25/kWh) but remains
# unproven at scale.
#
# References:
# - Form Energy PR + ME GEO RFP disclosure (~$33/kWh, 30 GWh, Maine 2025)
# - M. Liebreich "Cleaning Up" episode 144 on iron-air economics
# - Jaramillo (Form Energy CEO) public statements on cycle rate and η
# ---------------------------------------------------------------------------
IRON_AIR = {
    ("China", 2035): {
        "capex_per_kwh": 30.0,
        "fixed_opex_pct": 0.015,
        "efficiency": 0.45,
        "cycles_per_year": 15,       # 100h duration + ~50% availability; cycle-limited
        "lifetime_years": 20,
        "discount_rate": 0.08,
        "source": "Supplementary: Form Energy disclosures (~$33/kWh); Liebreich (Cleaning Up ep.144) on cycle constraint",
    },
    ("China", 2050): {
        "capex_per_kwh": 22.0,
        "fixed_opex_pct": 0.015,
        "efficiency": 0.50,
        "cycles_per_year": 15,        # cycle constraint is physics, not cost
        "lifetime_years": 20,
        "discount_rate": 0.08,
        "source": "Supplementary: Form Energy 2030+ targets ($20-25/kWh); cycle limit unchanged",
    },
    ("Ex-China", 2035): {
        "capex_per_kwh": 33.0,        # Form Energy Maine project implied cost
        "fixed_opex_pct": 0.015,
        "efficiency": 0.45,
        "cycles_per_year": 15,
        "lifetime_years": 20,
        "discount_rate": 0.08,
        "source": "Supplementary: Form Energy Maine project (~$1bn / 30 GWh = $33/kWh)",
    },
    ("Ex-China", 2050): {
        "capex_per_kwh": 25.0,
        "fixed_opex_pct": 0.015,
        "efficiency": 0.50,
        "cycles_per_year": 15,
        "lifetime_years": 20,
        "discount_rate": 0.08,
        "source": "Supplementary: Form Energy 2030+ cost target; cycles still physics-limited",
    },
}

# ---------------------------------------------------------------------------
# Global / economy-wide assumptions
# ---------------------------------------------------------------------------
GLOBAL_DEFAULTS = {
    "gas_price_usd_per_mmbtu": 6.0,                 # ETC Section 1.5.1 / Exhibit 1.29 note
    "electricity_input_price_usd_per_mwh": 40.0,    # ETC scenario B for illustration
    "co2_dac_usd_per_t": 200.0,                     # ETC Mind the Gap 2050 optimistic
    "co2_biogenic_usd_per_t": 30.0,                 # Biogenic CO2 (ethanol/biogas upgrading)
    "co2_point_source_usd_per_t": 50.0,             # Industrial point-source captured CO2
    "co2_removal_usd_per_t": 200.0,                 # DACCS for offsetting residual emissions
    "turbine_utilisation_override": 0.05,           # user-adjustable via slider
    "discount_rate_override": 0.08,                 # user-adjustable via slider
}

REGIONS = ["China", "Ex-China"]
YEARS = [2035, 2050]

CO2_SOURCES = {
    "DAC": "co2_dac_usd_per_t",
    "Biogenic": "co2_biogenic_usd_per_t",
    "Industrial point-source": "co2_point_source_usd_per_t",
}


def get_preset(region: str, year: int) -> dict:
    """Return a deep-copy dict of all tech parameters for the chosen region/year."""
    key = (region, year)
    return {
        "electrolyser": deepcopy(ELECTROLYSER[key]),
        "methanation": deepcopy(METHANATION[key]),
        "h2_storage": deepcopy(H2_STORAGE[key]),
        "ch4_storage": deepcopy(CH4_STORAGE[key]),
        "ocgt": deepcopy(OCGT[key]),
        "ccgt": deepcopy(CCGT[key]),
        "ccs": deepcopy(CCS[key]),
        "iron_air": deepcopy(IRON_AIR[key]),
        "globals": deepcopy(GLOBAL_DEFAULTS),
    }


def flatten_for_display(preset: dict) -> list:
    """Return a list of (stage, param, value, source) rows for the assumption panel."""
    rows = []
    for stage_name, params in preset.items():
        if stage_name == "globals":
            for k, v in params.items():
                rows.append((stage_name, k, v, "Global"))
            continue
        src = params.get("source", "")
        for k, v in params.items():
            if k == "source":
                continue
            rows.append((stage_name, k, v, src))
    return rows
