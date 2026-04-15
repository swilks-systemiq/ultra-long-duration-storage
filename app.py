"""
Streamlit UI for the Seasonal Storage TEA model.

Compares seasonal (50h+) storage pathways on a like-for-like LCOS basis,
using methodology consistent with ETC (2025) Power Systems Transformation, Box E.

Run:  streamlit run app.py
"""

from __future__ import annotations
import copy

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from defaults import (
    get_preset,
    flatten_for_display,
    REGIONS,
    YEARS,
    CO2_SOURCES,
    GLOBAL_DEFAULTS,
    DAC_USD_PER_T_BY_YEAR,
)
from model import (
    build_h2_ocgt,
    build_h2_ccgt,
    build_emethane,
    build_ch4_ccs_ccgt,
    build_unabated_gas_removal,
    build_unabated_gas_no_removal,
    build_iron_air,
)


# ---------------------------------------------------------------------------
# Page config + intro
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Seasonal Storage Techno-Economic Model",
    page_icon="⚡",
    layout="wide",
)

st.title("⚡ Seasonal Storage — Techno-Economic Comparison")
st.caption(
    "Pressure-testing the ETC (2025) Power Systems Transformation seasonal-storage "
    "assumptions. Includes a configurable solar → e-methane → CCGT pathway. "
    "All assumptions are overridable; all defaults are sourced."
)

# ---------------------------------------------------------------------------
# Sidebar — global controls and pathway selection
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Global settings")

    region = st.selectbox("Region", REGIONS, index=1, help="ETC China vs Ex-China cost archetype.")
    year = st.selectbox("Year", YEARS, index=1)

    st.markdown("---")
    st.markdown("**Economics**")
    discount_rate = st.slider(
        "Discount rate (%)",
        min_value=4.0, max_value=15.0, value=8.0, step=0.5,
        help="Applied to CAPEX annualisation. ETC uses 7–10% for storage, 8% for H2-OCGT.",
    ) / 100.0
    elec_price = st.slider(
        "Input electricity price ($/MWh)",
        min_value=0, max_value=150, value=40, step=5,
        help=("Price of grid electricity feeding electrolyser/methanation. "
              "ETC Scenario A uses $0, Scenario B uses $70."),
    )

    st.markdown("---")
    st.markdown("**Turbine utilisation**")
    ocgt_util = st.slider(
        "OCGT utilisation (%)",
        min_value=0, max_value=50, value=5, step=1,
        help="Capacity factor for OCGT peakers. ETC default 5% for ultra-long balancing.",
    ) / 100.0
    ccgt_util = st.slider(
        "CCGT utilisation (%)",
        min_value=0, max_value=50, value=10, step=1,
        help="ETC default 10% for CCGT + CCS.",
    ) / 100.0

    st.markdown("---")
    st.markdown("**Electrolyser utilisation**")
    elec_util = st.slider(
        "Electrolyser utilisation (%)",
        min_value=5, max_value=80, value=20, step=5,
        help="ETC Scenario A uses 20%; Scenario B uses 50%.",
    ) / 100.0

    st.markdown("---")
    st.markdown("**Gas storage cycling**")
    storage_cycles = st.slider(
        "H2 / CH4 storage cycles per year",
        min_value=1.0, max_value=24.0, value=12.0, step=0.5,
        help="Shared annual cycle assumption for both H2 and CH4 storage pathways.",
    )

    st.markdown("---")
    st.markdown("**Iron-air battery cycles**")
    iron_air_cycles = st.slider(
        "Iron-air cycles per year",
        min_value=5, max_value=60, value=12, step=1,
        help=("100h-duration iron-air is cycle-constrained: a full cycle is ~200h, "
              "so even at 100% availability max ~45 cycles/yr; 15/yr is realistic "
              "(Liebreich/Form Energy analysis)."),
    )

    st.markdown("---")
    st.markdown("**Gas + CO2 prices**")
    gas_price = st.slider(
        "Natural gas price ($/MMBtu)",
        min_value=2.0, max_value=20.0, value=6.0, step=0.5,
        help="ETC default $6/MMBtu.",
    )
    co2_dac = st.slider(
        "DAC CO2 cost ($/t)",
        min_value=50, max_value=800,
        value=int(DAC_USD_PER_T_BY_YEAR[year]), step=10,
        key=f"co2_dac_{year}",   # resets slider when year selector changes
        help=(
            "Year-dependent default: 2035 = $510/t, 2050 = $300/t. "
            "Override freely; ETC Mind the Gap (2021) uses $100–300/t 2050."
        ),
    )
    co2_biogenic = st.slider(
        "Biogenic CO2 cost ($/t)",
        min_value=0, max_value=200, value=30, step=10,
    )
    co2_point_source = st.slider(
        "Industrial point-source CO2 cost ($/t)",
        min_value=0, max_value=200, value=50, step=10,
    )
    co2_removal = st.slider(
        "Carbon removal cost for offsets ($/t)",
        min_value=0, max_value=600, value=200, step=25,
        help="For 'Unabated OCGT + removals' pathway. ETC modelled $50 and $200.",
    )

    st.markdown("---")
    st.markdown("**Pathways**")
    pathways_to_show = st.multiselect(
        "Select pathways to compare",
        options=[
            "Unabated OCGT (no removals)",
            "Green H2 → OCGT",
            "Green H2 → CCGT",
            "CH4 + CCS → CCGT",
            f"Unabated OCGT + ${co2_removal}/t removal",
            "E-methane (DAC) → CCGT",
            "E-methane (Biogenic) → CCGT",
            "E-methane (Point-source) → CCGT",
            "Iron-air battery",
        ],
        default=[
            "Unabated OCGT (no removals)",
            "Green H2 → OCGT",
            "CH4 + CCS → CCGT",
            f"Unabated OCGT + ${co2_removal}/t removal",
            "E-methane (DAC) → CCGT",
            "E-methane (Biogenic) → CCGT",
            "Iron-air battery",
        ],
    )


# ---------------------------------------------------------------------------
# Build pathway objects from sliders + region/year preset
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def _build_pathways(
    region: str, year: int,
    discount_rate: float, elec_price: float,
    ocgt_util: float, ccgt_util: float, elec_util: float, storage_cycles: float,
    gas_price: float,
    co2_dac: float, co2_biogenic: float, co2_point_source: float, co2_removal: float,
    iron_air_cycles: int = 12,
):
    preset = get_preset(region, year)

    # Apply global overrides
    for stage_key in ["electrolyser", "methanation", "h2_storage", "ch4_storage", "ocgt", "ccgt", "ccs", "iron_air"]:
        preset[stage_key]["discount_rate"] = discount_rate
    preset["electrolyser"]["utilisation"] = elec_util
    preset["methanation"]["utilisation"] = elec_util  # methanation tracks electrolyser
    preset["ocgt"]["utilisation"] = ocgt_util
    preset["ccgt"]["utilisation"] = ccgt_util
    preset["ccs"]["utilisation"] = ccgt_util
    preset["h2_storage"]["cycles_per_year"] = storage_cycles
    preset["ch4_storage"]["cycles_per_year"] = storage_cycles
    preset["iron_air"]["cycles_per_year"] = iron_air_cycles

    # For CH4+CCS pathway, apply CCS parasitic penalty to CCGT efficiency
    ccgt_ccs = copy.deepcopy(preset["ccgt"])
    ccgt_ccs["efficiency"] = preset["ccgt"]["efficiency"] * preset["ccs"]["efficiency"]

    pathways = {}
    pathways["Unabated OCGT (no removals)"] = build_unabated_gas_no_removal(
        preset["ocgt"], gas_price_usd_per_mmbtu=gas_price, discount_rate=discount_rate,
    )
    pathways["Green H2 → OCGT"] = build_h2_ocgt(
        preset["electrolyser"], preset["h2_storage"], preset["ocgt"],
        electricity_price=elec_price, discount_rate=discount_rate,
    )
    pathways["Green H2 → CCGT"] = build_h2_ccgt(
        preset["electrolyser"], preset["h2_storage"], preset["ccgt"],
        electricity_price=elec_price, discount_rate=discount_rate,
    )
    pathways["CH4 + CCS → CCGT"] = build_ch4_ccs_ccgt(
        ccgt_ccs, preset["ccs"], gas_price_usd_per_mmbtu=gas_price, discount_rate=discount_rate,
    )
    pathways[f"Unabated OCGT + ${int(co2_removal)}/t removal"] = build_unabated_gas_removal(
        preset["ocgt"], gas_price_usd_per_mmbtu=gas_price,
        co2_removal_cost=co2_removal, discount_rate=discount_rate,
    )
    pathways["E-methane (DAC) → CCGT"] = build_emethane(
        preset["electrolyser"], preset["methanation"], preset["ch4_storage"], preset["ccgt"],
        co2_cost_per_t=co2_dac, electricity_price=elec_price, co2_source_label="DAC",
        discount_rate=discount_rate,
    )
    pathways["E-methane (Biogenic) → CCGT"] = build_emethane(
        preset["electrolyser"], preset["methanation"], preset["ch4_storage"], preset["ccgt"],
        co2_cost_per_t=co2_biogenic, electricity_price=elec_price, co2_source_label="Biogenic",
        discount_rate=discount_rate,
    )
    pathways["E-methane (Point-source) → CCGT"] = build_emethane(
        preset["electrolyser"], preset["methanation"], preset["ch4_storage"], preset["ccgt"],
        co2_cost_per_t=co2_point_source, electricity_price=elec_price, co2_source_label="Point-source",
        discount_rate=discount_rate,
    )
    pathways["Iron-air battery"] = build_iron_air(
        preset["iron_air"], electricity_price=elec_price, discount_rate=discount_rate,
    )
    return pathways, preset


pathways, preset = _build_pathways(
    region, year, discount_rate, elec_price,
    ocgt_util, ccgt_util, elec_util, storage_cycles,
    gas_price, co2_dac, co2_biogenic, co2_point_source, co2_removal,
    iron_air_cycles,
)

# Filter to selected
selected = {k: v for k, v in pathways.items() if k in pathways_to_show}


# ---------------------------------------------------------------------------
# Main tabs
# ---------------------------------------------------------------------------
tab_compare, tab_sensitivity, tab_heatmap, tab_assumptions = st.tabs(
    ["📊 LCOS comparison", "🎯 Sensitivity (tornado)", "🔥 2D heatmap", "📋 Assumptions"]
)


# ---------------------------------------------------------------------------
# Tab 1 — LCOS comparison bar chart
# ---------------------------------------------------------------------------
with tab_compare:
    st.subheader("Levelised cost of storage, $ per MWh of delivered electricity")
    st.caption(
        f"Region: **{region}**  ·  Year: **{year}**  ·  "
        f"Electricity input: **${elec_price}/MWh**  ·  "
        f"OCGT util: **{ocgt_util:.0%}**  ·  CCGT util: **{ccgt_util:.0%}**  ·  "
        f"Electrolyser util: **{elec_util:.0%}**"
    )

    # Build stacked dataframe
    records = []
    for name, p in selected.items():
        for component, value in p.breakdown().items():
            records.append({"Pathway": name, "Component": component, "Cost ($/MWh)": value})
    df = pd.DataFrame(records)

    if df.empty:
        st.info("Select at least one pathway in the sidebar.")
    else:
        # Group components into higher-level categories for readable stacked bars
        def classify(comp: str) -> str:
            c = comp.lower()
            if "electrolyser" in c:
                return "Electrolyser"
            if "methan" in c:
                return "Methanation"
            if "storage" in c:
                return "Storage"
            if "ocgt" in c or "ccgt" in c:
                if "fuel" in c:
                    return "Fuel (natural gas)"
                return "Turbine"
            if "ccs" in c:
                return "CCS"
            if "electricity" in c:
                return "Electricity input"
            if "co2 feed" in c:
                return "CO2 feedstock"
            if "removal" in c:
                return "Carbon removal offset"
            if "iron-air" in c:
                return "Iron-air storage"
            return "Other"

        df["Category"] = df["Component"].apply(classify)

        # Row ordering for the horizontal bar chart:
        #  1. "Unabated OCGT (no removals)" pinned to the TOP as the fossil counterfactual.
        #  2. All other pathways below it, sorted ASCENDING by LCOS.
        # Plotly's horizontal-bar y-axis places the FIRST category in categoryarray at the
        # bottom, so we build the list in reverse (bottom -> top) and hand it over explicitly.
        totals = df.groupby("Pathway")["Cost ($/MWh)"].sum().sort_values()
        counterfactual = "Unabated OCGT (no removals)"
        decarb_sorted_ascending = [p for p in totals.index if p != counterfactual]
        # Bottom-to-top: most expensive decarb pathway at the bottom, cheapest just below the
        # counterfactual at the top.
        bottom_to_top = list(reversed(decarb_sorted_ascending))
        if counterfactual in totals.index:
            bottom_to_top.append(counterfactual)
        df["Pathway"] = pd.Categorical(df["Pathway"], categories=bottom_to_top, ordered=True)

        color_map = {
            "Electrolyser": "#1f77b4",
            "Methanation": "#17becf",
            "Storage": "#2ca02c",
            "Turbine": "#ff7f0e",
            "Fuel (natural gas)": "#8c564b",
            "CCS": "#e377c2",
            "Electricity input": "#9467bd",
            "CO2 feedstock": "#d62728",
            "Carbon removal offset": "#7f7f7f",
            "Iron-air storage": "#bcbd22",
            "Other": "#cccccc",
        }

        fig = px.bar(
            df, x="Cost ($/MWh)", y="Pathway", color="Category",
            orientation="h", text_auto=".0f",
            color_discrete_map=color_map,
            hover_data={"Component": True, "Cost ($/MWh)": ":.1f"},
            height=max(400, 55 * len(selected)),
        )
        max_total = float(totals.max())
        label_offset = max(14.0, 0.025 * max_total)
        right_padding = max(45.0, 0.05 * max_total)
        fig.update_layout(
            xaxis_title="$ per MWh delivered",
            yaxis_title="",
            legend_title="",
            bargap=0.25,
            margin=dict(r=110),
            yaxis=dict(categoryorder="array", categoryarray=bottom_to_top),
            xaxis=dict(range=[0, max_total + right_padding]),
        )

        # Add total annotations at the bar end
        for name, total in totals.items():
            fig.add_annotation(
                x=total + label_offset, y=name,
                text=f"<b>${total:.0f}</b>",
                showarrow=False,
                font=dict(size=12),
                xanchor="left",
            )

        st.plotly_chart(fig, use_container_width=True)

        # Summary table
        summary = pd.DataFrame(
            {"LCOS ($/MWh delivered)": {name: round(p.lcos(), 0) for name, p in selected.items()}}
        ).sort_values("LCOS ($/MWh delivered)")
        st.dataframe(summary, use_container_width=True)

        with st.expander("Where e-methane wins / loses vs alternatives", expanded=False):
            st.markdown(
                """
                **Why e-methane is *worse* than green H2 → OCGT in the default view:**
                compounded efficiency losses (electrolyser × methanation × CCGT ≈ 35%) combined with
                CO2 feedstock cost and (new) gas-storage CAPEX. If existing natural-gas storage can be
                reused at near-zero marginal cost, and biogenic/point-source CO2 is available at <$30/t,
                e-methane's gap narrows sharply — try **CH4 storage capex → $0.03/kWh** and
                **CO2 (Biogenic) → $0/t** in the Assumptions tab to see this.

                **Why CH4 + CCS usually wins:** CCGTs are cheaper per kW than electrolysers, their
                efficiency (60%) beats OCGT (40%), and natural gas at $6/MMBtu is cheap energy. The
                downside is residual upstream CH4 emissions and imperfect CCS capture — not priced here.

                **The core question in one sentence:** does methanation CAPEX + CO2 cost land below the
                premium you save by avoiding salt-cavern H2 storage and OCGT peakers?
                """
            )


# ---------------------------------------------------------------------------
# Tab 2 — Sensitivity (tornado)
# ---------------------------------------------------------------------------
with tab_sensitivity:
    st.subheader("Sensitivity — ±30% swing on key inputs")
    st.caption("Tornado shows LCOS impact of a ±30% change in each single input, holding everything else at slider values.")

    path_choice = st.selectbox("Pathway to analyse", list(selected.keys()) if selected else list(pathways.keys()))
    swing = st.slider("Swing magnitude (%)", 10, 60, 30, 5) / 100.0

    if path_choice:
        base_lcos = pathways[path_choice].lcos()

        # Define parameter perturbations for this pathway
        def rebuild(overrides: dict):
            preset_override = get_preset(region, year)
            for sk in ["electrolyser", "methanation", "h2_storage", "ch4_storage", "ocgt", "ccgt", "ccs", "iron_air"]:
                preset_override[sk]["discount_rate"] = discount_rate
            preset_override["electrolyser"]["utilisation"] = elec_util
            preset_override["methanation"]["utilisation"] = elec_util
            preset_override["ocgt"]["utilisation"] = ocgt_util
            preset_override["ccgt"]["utilisation"] = ccgt_util
            preset_override["ccs"]["utilisation"] = ccgt_util
            # Apply overrides
            for path, val in overrides.items():
                stage, param = path.split(".")
                preset_override[stage][param] = val
            ccgt_ccs = copy.deepcopy(preset_override["ccgt"])
            ccgt_ccs["efficiency"] = preset_override["ccgt"]["efficiency"] * preset_override["ccs"]["efficiency"]

            args_map = {
                "Unabated OCGT (no removals)": lambda: build_unabated_gas_no_removal(
                    preset_override["ocgt"],
                    gas_price_usd_per_mmbtu=overrides.get("globals.gas_price", gas_price),
                    discount_rate=discount_rate),
                "Green H2 → OCGT": lambda: build_h2_ocgt(
                    preset_override["electrolyser"], preset_override["h2_storage"], preset_override["ocgt"],
                    electricity_price=overrides.get("globals.elec_price", elec_price),
                    discount_rate=discount_rate),
                "Green H2 → CCGT": lambda: build_h2_ccgt(
                    preset_override["electrolyser"], preset_override["h2_storage"], preset_override["ccgt"],
                    electricity_price=overrides.get("globals.elec_price", elec_price),
                    discount_rate=discount_rate),
                "CH4 + CCS → CCGT": lambda: build_ch4_ccs_ccgt(
                    ccgt_ccs, preset_override["ccs"],
                    gas_price_usd_per_mmbtu=overrides.get("globals.gas_price", gas_price),
                    discount_rate=discount_rate),
                f"Unabated OCGT + ${int(co2_removal)}/t removal": lambda: build_unabated_gas_removal(
                    preset_override["ocgt"],
                    gas_price_usd_per_mmbtu=overrides.get("globals.gas_price", gas_price),
                    co2_removal_cost=overrides.get("globals.co2_removal", co2_removal),
                    discount_rate=discount_rate),
                "E-methane (DAC) → CCGT": lambda: build_emethane(
                    preset_override["electrolyser"], preset_override["methanation"],
                    preset_override["ch4_storage"], preset_override["ccgt"],
                    co2_cost_per_t=overrides.get("globals.co2_dac", co2_dac),
                    electricity_price=overrides.get("globals.elec_price", elec_price),
                    co2_source_label="DAC", discount_rate=discount_rate),
                "E-methane (Biogenic) → CCGT": lambda: build_emethane(
                    preset_override["electrolyser"], preset_override["methanation"],
                    preset_override["ch4_storage"], preset_override["ccgt"],
                    co2_cost_per_t=overrides.get("globals.co2_biogenic", co2_biogenic),
                    electricity_price=overrides.get("globals.elec_price", elec_price),
                    co2_source_label="Biogenic", discount_rate=discount_rate),
                "E-methane (Point-source) → CCGT": lambda: build_emethane(
                    preset_override["electrolyser"], preset_override["methanation"],
                    preset_override["ch4_storage"], preset_override["ccgt"],
                    co2_cost_per_t=overrides.get("globals.co2_point_source", co2_point_source),
                    electricity_price=overrides.get("globals.elec_price", elec_price),
                    co2_source_label="Point-source", discount_rate=discount_rate),
                "Iron-air battery": lambda: build_iron_air(
                    preset_override["iron_air"],
                    electricity_price=overrides.get("globals.elec_price", elec_price),
                    discount_rate=discount_rate),
            }
            return args_map[path_choice]()

        # Choose relevant parameters per pathway
        def params_for(path_name: str) -> list:
            common = [
                ("electrolyser.capex_per_kw", preset["electrolyser"]["capex_per_kw"], "Electrolyser CAPEX"),
                ("electrolyser.efficiency", preset["electrolyser"]["efficiency"], "Electrolyser η"),
                ("electrolyser.utilisation", preset["electrolyser"]["utilisation"], "Electrolyser utilisation"),
                ("globals.elec_price", max(elec_price, 0.01), "Input electricity price"),
            ]
            if "H2" in path_name and "OCGT" in path_name:
                return common + [
                    ("ocgt.capex_per_kw", preset["ocgt"]["capex_per_kw"], "OCGT CAPEX"),
                    ("ocgt.utilisation", preset["ocgt"]["utilisation"], "OCGT utilisation"),
                    ("h2_storage.capex_per_kwh", preset["h2_storage"]["capex_per_kwh"], "H2 storage CAPEX"),
                ]
            if "H2" in path_name and "CCGT" in path_name:
                return common + [
                    ("ccgt.capex_per_kw", preset["ccgt"]["capex_per_kw"], "CCGT CAPEX"),
                    ("ccgt.utilisation", preset["ccgt"]["utilisation"], "CCGT utilisation"),
                    ("h2_storage.capex_per_kwh", preset["h2_storage"]["capex_per_kwh"], "H2 storage CAPEX"),
                ]
            if path_name == "Unabated OCGT (no removals)":
                return [
                    ("ocgt.capex_per_kw", preset["ocgt"]["capex_per_kw"], "OCGT CAPEX"),
                    ("ocgt.utilisation", preset["ocgt"]["utilisation"], "OCGT utilisation"),
                    ("ocgt.efficiency", preset["ocgt"]["efficiency"], "OCGT η"),
                    ("globals.gas_price", gas_price, "Natural gas price"),
                ]
            if "CH4 + CCS" in path_name:
                return [
                    ("ccgt.capex_per_kw", preset["ccgt"]["capex_per_kw"], "CCGT CAPEX"),
                    ("ccgt.utilisation", preset["ccgt"]["utilisation"], "CCGT utilisation"),
                    ("ccs.capex_per_kw", preset["ccs"]["capex_per_kw"], "CCS CAPEX"),
                    ("ccs.efficiency", preset["ccs"]["efficiency"], "CCS retention η"),
                    ("globals.gas_price", gas_price, "Natural gas price"),
                ]
            if "Unabated" in path_name:
                return [
                    ("ocgt.capex_per_kw", preset["ocgt"]["capex_per_kw"], "OCGT CAPEX"),
                    ("ocgt.utilisation", preset["ocgt"]["utilisation"], "OCGT utilisation"),
                    ("globals.gas_price", gas_price, "Natural gas price"),
                    ("globals.co2_removal", co2_removal, "Carbon removal $/t"),
                ]
            if "E-methane" in path_name:
                co2_key = ("globals.co2_dac", co2_dac) if "DAC" in path_name else (
                    ("globals.co2_biogenic", co2_biogenic) if "Biogenic" in path_name else
                    ("globals.co2_point_source", co2_point_source)
                )
                return common + [
                    ("methanation.capex_per_kw", preset["methanation"]["capex_per_kw"], "Methanation CAPEX"),
                    ("methanation.efficiency", preset["methanation"]["efficiency"], "Methanation η"),
                    ("ch4_storage.capex_per_kwh", preset["ch4_storage"]["capex_per_kwh"], "CH4 storage CAPEX"),
                    ("ch4_storage.cycles_per_year", preset["ch4_storage"]["cycles_per_year"], "CH4 storage cycles/yr"),
                    ("ccgt.capex_per_kw", preset["ccgt"]["capex_per_kw"], "CCGT CAPEX"),
                    (co2_key[0], co2_key[1], f"CO2 cost ({path_name.split('(')[1].rstrip(') → CCGT')})"),
                ]
            if "Iron-air" in path_name:
                return [
                    ("iron_air.capex_per_kwh", preset["iron_air"]["capex_per_kwh"], "Iron-air CAPEX"),
                    ("iron_air.efficiency", preset["iron_air"]["efficiency"], "Iron-air round-trip η"),
                    ("iron_air.cycles_per_year", preset["iron_air"]["cycles_per_year"], "Cycles per year"),
                    ("globals.elec_price", max(elec_price, 0.01), "Input electricity price"),
                ]
            return []

        rows = []
        for key, base_val, label in params_for(path_choice):
            low = rebuild({key: base_val * (1 - swing)}).lcos()
            high = rebuild({key: base_val * (1 + swing)}).lcos()
            rows.append({"Parameter": label, "Low": low, "High": high, "Range": abs(high - low)})

        if rows:
            tdf = pd.DataFrame(rows).sort_values("Range")
            fig = go.Figure()
            fig.add_trace(go.Bar(
                y=tdf["Parameter"], x=tdf["High"] - base_lcos,
                base=base_lcos, orientation="h", name=f"+{int(swing * 100)}%",
                marker=dict(color="#d62728"),
                hovertemplate="High: $%{x:.0f}<extra></extra>",
            ))
            fig.add_trace(go.Bar(
                y=tdf["Parameter"], x=tdf["Low"] - base_lcos,
                base=base_lcos, orientation="h", name=f"-{int(swing * 100)}%",
                marker=dict(color="#2ca02c"),
                hovertemplate="Low: $%{x:.0f}<extra></extra>",
            ))
            fig.add_vline(x=base_lcos, line_color="black", line_width=1)
            fig.update_layout(
                barmode="overlay",
                title=f"LCOS sensitivity — {path_choice} (base: ${base_lcos:.0f}/MWh)",
                xaxis_title="LCOS ($/MWh)",
                yaxis_title="",
                height=max(400, 50 * len(rows)),
            )
            st.plotly_chart(fig, use_container_width=True)
            st.caption(f"Base case LCOS: **${base_lcos:.0f}/MWh**")
        else:
            st.info("No parameters defined for this pathway.")


# ---------------------------------------------------------------------------
# Tab 3 — 2D heatmap
# ---------------------------------------------------------------------------
with tab_heatmap:
    st.subheader("2D heatmap — LCOS across two variables")
    st.caption(
        "ETC Exhibit 1.39 style. Choose a pathway and two parameters to sweep; "
        "each cell shows LCOS ($/MWh delivered)."
    )

    h_path = st.selectbox(
        "Pathway", list(selected.keys()) if selected else list(pathways.keys()),
        key="heatmap_path",
    )

    col1, col2 = st.columns(2)
    with col1:
        x_axis = st.selectbox(
            "X-axis", ["Input electricity price", "Electrolyser utilisation", "Natural gas price", "CO2 cost"],
            index=0,
        )
    with col2:
        y_axis = st.selectbox(
            "Y-axis", ["Electrolyser utilisation", "Input electricity price", "Turbine utilisation", "CO2 cost"],
            index=0,
        )

    if x_axis == y_axis:
        st.warning("Choose different axes.")
    else:
        def axis_range(name):
            if name == "Input electricity price":
                return np.linspace(0, 120, 13), "$/MWh"
            if name == "Electrolyser utilisation":
                return np.linspace(0.05, 0.8, 16), ""
            if name == "Turbine utilisation":
                return np.linspace(0.01, 0.15, 15), ""
            if name == "Natural gas price":
                return np.linspace(2, 20, 10), "$/MMBtu"
            if name == "CO2 cost":
                return np.linspace(0, 400, 11), "$/t"
            return np.linspace(0, 1, 5), ""

        x_vals, x_unit = axis_range(x_axis)
        y_vals, y_unit = axis_range(y_axis)

        def rebuild_for_heatmap(xv, yv):
            preset_h = get_preset(region, year)
            for sk in ["electrolyser", "methanation", "h2_storage", "ch4_storage", "ocgt", "ccgt", "ccs", "iron_air"]:
                preset_h[sk]["discount_rate"] = discount_rate
            preset_h["electrolyser"]["utilisation"] = elec_util
            preset_h["methanation"]["utilisation"] = elec_util
            preset_h["ocgt"]["utilisation"] = ocgt_util
            preset_h["ccgt"]["utilisation"] = ccgt_util
            preset_h["ccs"]["utilisation"] = ccgt_util

            overrides = {"elec_price": elec_price, "gas_price": gas_price,
                         "co2_dac": co2_dac, "co2_biogenic": co2_biogenic,
                         "co2_point_source": co2_point_source}

            def apply(axis_name, v):
                if axis_name == "Input electricity price":
                    overrides["elec_price"] = v
                elif axis_name == "Electrolyser utilisation":
                    preset_h["electrolyser"]["utilisation"] = v
                    preset_h["methanation"]["utilisation"] = v
                elif axis_name == "Turbine utilisation":
                    preset_h["ocgt"]["utilisation"] = v
                    preset_h["ccgt"]["utilisation"] = v
                elif axis_name == "Natural gas price":
                    overrides["gas_price"] = v
                elif axis_name == "CO2 cost":
                    overrides["co2_dac"] = v
                    overrides["co2_biogenic"] = v
                    overrides["co2_point_source"] = v

            apply(x_axis, xv)
            apply(y_axis, yv)
            ccgt_ccs2 = copy.deepcopy(preset_h["ccgt"])
            ccgt_ccs2["efficiency"] = preset_h["ccgt"]["efficiency"] * preset_h["ccs"]["efficiency"]

            if h_path == "Unabated OCGT (no removals)":
                return build_unabated_gas_no_removal(preset_h["ocgt"],
                                                    gas_price_usd_per_mmbtu=overrides["gas_price"],
                                                    discount_rate=discount_rate)
            if h_path == "Green H2 → OCGT":
                return build_h2_ocgt(preset_h["electrolyser"], preset_h["h2_storage"], preset_h["ocgt"],
                                     electricity_price=overrides["elec_price"], discount_rate=discount_rate)
            if h_path == "Green H2 → CCGT":
                return build_h2_ccgt(preset_h["electrolyser"], preset_h["h2_storage"], preset_h["ccgt"],
                                     electricity_price=overrides["elec_price"], discount_rate=discount_rate)
            if h_path == "CH4 + CCS → CCGT":
                return build_ch4_ccs_ccgt(ccgt_ccs2, preset_h["ccs"],
                                          gas_price_usd_per_mmbtu=overrides["gas_price"],
                                          discount_rate=discount_rate)
            if h_path.startswith("Unabated"):
                return build_unabated_gas_removal(preset_h["ocgt"], gas_price_usd_per_mmbtu=overrides["gas_price"],
                                                  co2_removal_cost=co2_removal, discount_rate=discount_rate)
            if "E-methane" in h_path:
                co2_val = overrides["co2_dac"] if "DAC" in h_path else (
                    overrides["co2_biogenic"] if "Biogenic" in h_path else overrides["co2_point_source"]
                )
                label = "DAC" if "DAC" in h_path else ("Biogenic" if "Biogenic" in h_path else "Point-source")
                return build_emethane(preset_h["electrolyser"], preset_h["methanation"],
                                      preset_h["ch4_storage"], preset_h["ccgt"],
                                      co2_cost_per_t=co2_val,
                                      electricity_price=overrides["elec_price"],
                                      co2_source_label=label, discount_rate=discount_rate)
            if h_path == "Iron-air battery":
                return build_iron_air(preset_h["iron_air"], electricity_price=overrides["elec_price"],
                                      discount_rate=discount_rate)
            return None

        Z = np.zeros((len(y_vals), len(x_vals)))
        for i, yv in enumerate(y_vals):
            for j, xv in enumerate(x_vals):
                p = rebuild_for_heatmap(xv, yv)
                Z[i, j] = p.lcos() if p else np.nan

        fig = go.Figure(data=go.Heatmap(
            z=Z,
            x=[f"{v:.0f}{' %' if y_axis.endswith('utilisation') else ''}" if x_axis.endswith("utilisation")
               else f"{v:.0f}" for v in (x_vals * 100 if x_axis.endswith("utilisation") else x_vals)],
            y=[f"{v:.0f}" for v in (y_vals * 100 if y_axis.endswith("utilisation") else y_vals)],
            colorscale="RdYlGn_r",
            colorbar=dict(title="$/MWh"),
            hovertemplate=f"{x_axis}: %{{x}}<br>{y_axis}: %{{y}}<br>LCOS: $%{{z:.0f}}/MWh<extra></extra>",
            text=[[f"${int(v)}" for v in row] for row in Z],
            texttemplate="%{text}",
            textfont={"size": 10},
        ))
        fig.update_layout(
            title=f"{h_path} — LCOS sweep",
            xaxis_title=f"{x_axis} ({x_unit})" if x_unit else x_axis + (" (%)" if x_axis.endswith("utilisation") else ""),
            yaxis_title=f"{y_axis} ({y_unit})" if y_unit else y_axis + (" (%)" if y_axis.endswith("utilisation") else ""),
            height=600,
        )
        st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# Tab 4 — Assumptions audit trail
# ---------------------------------------------------------------------------
with tab_assumptions:
    st.subheader("Assumption audit trail")
    st.caption(
        "Every default is tagged with a source. ETC = Power Systems Transformation (2025). "
        "'Supplementary' entries come from external literature (clearly flagged)."
    )

    rows = flatten_for_display(preset)
    assum_df = pd.DataFrame(rows, columns=["Stage", "Parameter", "Value", "Source"])
    # Cast Value to string — it contains mixed numeric/string entries (e.g. capex_basis='input')
    assum_df["Value"] = assum_df["Value"].apply(
        lambda v: f"{v:.4g}" if isinstance(v, (int, float)) else str(v)
    )
    st.dataframe(assum_df, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.markdown("**Validation against ETC Exhibit 1.40 (H2 → OCGT, Scenario A: 20% util, $0/MWh)**")

    val_rows = []
    for r in REGIONS:
        for y in YEARS:
            pv = get_preset(r, y)
            pv["electrolyser"]["utilisation"] = 0.20
            pv["ocgt"]["utilisation"] = 0.05
            p = build_h2_ocgt(pv["electrolyser"], pv["h2_storage"], pv["ocgt"], electricity_price=0)
            targets = {
                ("Ex-China", 2035): 610, ("China", 2035): 320,
                ("Ex-China", 2050): 460, ("China", 2050): 270,
            }
            val_rows.append({
                "Region": r, "Year": y,
                "Model LCOS ($/MWh)": round(p.lcos()),
                "ETC target ($/MWh)": targets[(r, y)],
                "Delta (%)": f"{(p.lcos() - targets[(r, y)]) / targets[(r, y)] * 100:+.0f}%",
            })
    st.dataframe(pd.DataFrame(val_rows), use_container_width=True, hide_index=True)
    st.caption("Model is calibrated to within ≈10% of ETC H2→OCGT benchmark in all four region/year cells.")
