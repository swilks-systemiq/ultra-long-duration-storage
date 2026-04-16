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

# ---------------------------------------------------------------------------
# Password gate — set APP_PASSWORD in .streamlit/secrets.toml or env var
# ---------------------------------------------------------------------------
import hmac, os

def _check_password() -> bool:
    """Return True if the user has entered the correct password."""
    password = st.secrets.get("APP_PASSWORD") or os.environ.get("APP_PASSWORD", "")
    if not password:
        return True  # no password configured — skip gate

    if st.session_state.get("authenticated"):
        return True

    with st.form("login"):
        st.text_input("Password", type="password", key="pw_input")
        submitted = st.form_submit_button("Enter")
    if submitted and hmac.compare_digest(st.session_state.pw_input, password):
        st.session_state.authenticated = True
        st.rerun()
    elif submitted:
        st.error("Incorrect password.")
    return False

if not _check_password():
    st.stop()

st.title("⚡ Seasonal Storage — Techno-Economic Comparison")
st.caption(
    "Pressure-testing the ETC (2025) Power Systems Transformation seasonal-storage "
    "assumptions. Includes a configurable solar → E-CH4 → CCGT pathway. "
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
        min_value=1, max_value=24, value=12, step=1,
        help="Shared annual cycle assumption for both H2 and CH4 storage pathways.",
    )

    st.markdown("---")
    st.markdown("**Turbine for e-fuel pathways**")
    h2_turbine = st.radio(
        "Green H2 turbine",
        options=["OCGT", "CCGT"], index=0, horizontal=True,
        help=("OCGT: lower CAPEX, 40% eff, 5% util. CCGT: higher CAPEX, 60% eff, 10% util. "
              "ETC Ex-China 2050 H2-OCGT Scenario A lands around $460/MWh."),
    )
    em_turbine = st.radio(
        "E-CH4 turbine",
        options=["OCGT", "CCGT"], index=0, horizontal=True,
        help=("Note: E-CH4 → OCGT is NOT in ETC. Lower turbine η means more CH4 — and "
              "more CO2 feedstock — per MWhe delivered. Expect a large cost jump vs CCGT."),
    )

    st.markdown("---")
    st.markdown("**Iron-air battery cycles**")
    iron_air_cycles = st.slider(
        "Iron-air cycles per year",
        min_value=1, max_value=24, value=6, step=1,
        help=("For a 100h system, utilisation is approximately cycles × 100 / 8,760. "
              "So 6 cycles/yr is about 7% utilisation, 12 cycles/yr about 14%, and "
              "24 cycles/yr about 27%."),
    )

    st.markdown("---")
    st.markdown("**Gas + CO2 prices**")
    gas_price = st.slider(
        "Natural gas price ($/MMBtu)",
        min_value=2.0, max_value=20.0, value=6.0, step=0.5,
        help=("ETC default $6/MMBtu. Rough benchmarks: shock pricing of €40–60/MWh is about "
              "$13.8–20.7/MMBtu. More normal ranges are roughly EU: $8.6–12.1/MMBtu and "
              "US: $2–4/MMBtu."),
    )
    co2_dac = st.slider(
        "DAC CO2 cost ($/t)",
        min_value=50, max_value=800,
        value=int(DAC_USD_PER_T_BY_YEAR[year]), step=10,
        key=f"co2_dac_{year}",   # resets slider when year selector changes
        help=(
            "Year-dependent default: 2035 = $478/t, 2050 = $234/t. "
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
    # Pathway labels dynamically reflect the turbine selection above
    green_h2_label = f"Green H2 → {h2_turbine}"
    em_dac_label = f"E-CH4 (DAC) → {em_turbine}"
    em_bio_label = f"E-CH4 (Biogenic) → {em_turbine}"
    em_ps_label = f"E-CH4 (Point-source) → {em_turbine}"
    unabated_removal_label = f"Unabated OCGT + ${co2_removal}/t removal"

    pathways_to_show = st.multiselect(
        "Select pathways to compare",
        options=[
            "Existing Unabated OCGT (no removals)",
            "Unabated OCGT (no removals)",
            green_h2_label,
            "CH4 + CCS → CCGT",
            unabated_removal_label,
            em_dac_label,
            em_bio_label,
            em_ps_label,
            "Iron-air battery",
        ],
        default=[
            "Existing Unabated OCGT (no removals)",
            "Unabated OCGT (no removals)",
            green_h2_label,
            "CH4 + CCS → CCGT",
            unabated_removal_label,
            em_dac_label,
            em_bio_label,
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
    iron_air_cycles: int = 6,
    h2_turbine: str = "OCGT",
    em_turbine: str = "OCGT",
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

    # Select the turbine preset dict for each family based on the user's choice
    h2_turbine_dict = preset["ocgt"] if h2_turbine == "OCGT" else preset["ccgt"]
    em_turbine_dict = preset["ocgt"] if em_turbine == "OCGT" else preset["ccgt"]

    pathways = {}
    # "Existing" OCGT — no turbine CAPEX (already built/paid for), OPEX + fuel + storage only
    existing_ocgt = copy.deepcopy(preset["ocgt"])
    existing_ocgt["capex_per_kw"] = 0
    pathways["Existing Unabated OCGT (no removals)"] = build_unabated_gas_no_removal(
        existing_ocgt, gas_price_usd_per_mmbtu=gas_price, discount_rate=discount_rate,
        ch4_storage=preset["ch4_storage"],
    )
    pathways["Unabated OCGT (no removals)"] = build_unabated_gas_no_removal(
        preset["ocgt"], gas_price_usd_per_mmbtu=gas_price, discount_rate=discount_rate,
        ch4_storage=preset["ch4_storage"],
    )
    # Green H2 pathway — turbine is user-selected (default OCGT)
    if h2_turbine == "OCGT":
        pathways[f"Green H2 → {h2_turbine}"] = build_h2_ocgt(
            preset["electrolyser"], preset["h2_storage"], h2_turbine_dict,
            electricity_price=elec_price, discount_rate=discount_rate,
        )
    else:
        pathways[f"Green H2 → {h2_turbine}"] = build_h2_ccgt(
            preset["electrolyser"], preset["h2_storage"], h2_turbine_dict,
            electricity_price=elec_price, discount_rate=discount_rate,
        )
    pathways["CH4 + CCS → CCGT"] = build_ch4_ccs_ccgt(
        ccgt_ccs, preset["ccs"], gas_price_usd_per_mmbtu=gas_price, discount_rate=discount_rate,
    )
    pathways[f"Unabated OCGT + ${int(co2_removal)}/t removal"] = build_unabated_gas_removal(
        preset["ocgt"], gas_price_usd_per_mmbtu=gas_price,
        co2_removal_cost=co2_removal, discount_rate=discount_rate,
        ch4_storage=preset["ch4_storage"],
    )
    # E-CH4 pathways — turbine is user-selected (default OCGT). Note: E-CH4 → OCGT
    # is NOT in ETC; switching from CCGT to OCGT drops pathway efficiency from ~35% to ~23%,
    # which scales CO2 feedstock and electricity input needs up by ~1.5x.
    pathways[f"E-CH4 (DAC) → {em_turbine}"] = build_emethane(
        preset["electrolyser"], preset["methanation"], preset["ch4_storage"], em_turbine_dict,
        co2_cost_per_t=co2_dac, electricity_price=elec_price, co2_source_label="DAC",
        turbine_type=em_turbine, discount_rate=discount_rate,
    )
    pathways[f"E-CH4 (Biogenic) → {em_turbine}"] = build_emethane(
        preset["electrolyser"], preset["methanation"], preset["ch4_storage"], em_turbine_dict,
        co2_cost_per_t=co2_biogenic, electricity_price=elec_price, co2_source_label="Biogenic",
        turbine_type=em_turbine, discount_rate=discount_rate,
    )
    pathways[f"E-CH4 (Point-source) → {em_turbine}"] = build_emethane(
        preset["electrolyser"], preset["methanation"], preset["ch4_storage"], em_turbine_dict,
        co2_cost_per_t=co2_point_source, electricity_price=elec_price, co2_source_label="Point-source",
        turbine_type=em_turbine, discount_rate=discount_rate,
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
    h2_turbine=h2_turbine, em_turbine=em_turbine,
)

# Filter to selected
selected = {k: v for k, v in pathways.items() if k in pathways_to_show}


# ---------------------------------------------------------------------------
# Main tabs
# ---------------------------------------------------------------------------
tab_compare, tab_flows, tab_sensitivity, tab_heatmap, tab_method, tab_assumptions = st.tabs(
    ["📊 LCOS comparison", "🔀 Pathway diagrams", "🎯 Sensitivity (tornado)", "🔥 2D heatmap", "🧮 LCOS method", "📋 Assumptions"]
)


# ---------------------------------------------------------------------------
# Tab 1 — LCOS method and input definitions
# ---------------------------------------------------------------------------
with tab_method:
    st.subheader("How LCOS is calculated")
    st.markdown(
        """
        <style>
        .katex-display {
            text-align: left !important;
            margin: 0.25rem 0 1rem 0 !important;
        }
        .katex-display > .katex {
            text-align: left !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("The model reports **levelised cost of storage (LCOS)** in **$ per MWh of delivered electricity**:")
    st.latex(r"LCOS = \frac{\sum_t \frac{CAPEX_t + OPEX_t + input\ costs_t}{(1+r)^t}}{\sum_t \frac{Electricity\ delivered_t}{(1+r)^t}}")
    st.markdown(
        "In plain English: we add up all discounted costs over the asset life and divide by all "
        "discounted electricity delivered to the grid."
    )

    st.markdown("For a multi-step pathway, the model cascades efficiency through each stage:")
    st.latex(r"\eta_{pathway} = \prod_i \eta_i")
    st.markdown("So the upstream electricity or fuel needed per MWh delivered is:")
    st.latex(r"Input\ needed = \frac{1}{\eta_{pathway}}")

    st.markdown(
        """
        **What goes into the LCOS number**

        - `CAPEX`: annualised plant or storage investment, converted into `$ / MWh delivered`
        - `Fixed OPEX`: annual operating costs that scale with capacity
        - `Variable OPEX`: running costs that scale with output
        - `Electricity input`: grid power fed into electrolysers or batteries
        - `Fuel`: natural-gas input for fossil pathways
        - `CO2 feedstock`: CO2 purchased for E-CH4 synthesis
        - `Carbon removal offset`: offset cost for the unabated OCGT + removals pathway
        """
    )

    st.markdown(
        """
        **Input definitions**

        - `Discount rate`: financing assumption used to annualise CAPEX
        - `Input electricity price`: cost of electricity going into electrolysers or iron-air charging
        - `OCGT / CCGT utilisation`: annual capacity factor of the turbine block
        - `Electrolyser utilisation`: annual capacity factor for H2 production
        - `H2 / CH4 storage cycles per year`: how often the underground storage asset turns over each year
        - `Iron-air cycles per year`: how often the battery fully cycles each year
        - `Natural gas price`: fuel input price for fossil methane pathways
        - `DAC / biogenic / point-source CO2 cost`: feedstock price for E-CH4 pathways
        - `Carbon removal cost for offsets`: cost used only for the unabated OCGT + removals case
        """
    )

    st.markdown(
        """
        **How to interpret the result**

        - Lower LCOS means cheaper delivered electricity from that pathway under the chosen assumptions.
        - A pathway with lower efficiency can still win if it uses cheaper storage, turbines, or feedstocks.
        - Storage cycle assumptions matter a lot because they spread storage CAPEX over more or fewer MWh delivered.
        """
    )


# ---------------------------------------------------------------------------
# Tab 2 — LCOS comparison bar chart
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
        # CAPEX vs OPEX classification — drives segment border style (solid vs dashed).
        df["CostType"] = df["Component"].apply(
            lambda c: "CAPEX" if "CAPEX" in c else "OPEX"
        )

        # Row ordering for the horizontal bar chart:
        #  1. "Unabated OCGT (no removals)" pinned to the TOP as the fossil counterfactual.
        #  2. All other pathways below it, sorted ASCENDING by LCOS.
        # Plotly's horizontal-bar y-axis places the FIRST category in categoryarray at the
        # bottom, so we build the list in reverse (bottom -> top) and hand it over explicitly.
        totals = df.groupby("Pathway")["Cost ($/MWh)"].sum().sort_values()
        counterfactuals = [
            "Unabated OCGT (no removals)",
            "Existing Unabated OCGT (no removals)",
        ]
        decarb_sorted_ascending = [p for p in totals.index if p not in counterfactuals]
        # Bottom-to-top: most expensive decarb pathway at the bottom, cheapest just below the
        # counterfactuals at the top.
        bottom_to_top = list(reversed(decarb_sorted_ascending))
        for cf in counterfactuals:
            if cf in totals.index:
                bottom_to_top.append(cf)
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

        # Build bars manually so we can apply per-segment borders.
        # Plotly bar marker.line supports width+color but NOT dash, so OPEX dashed
        # borders are drawn as shape overlays after the bars are stacked.
        category_order = list(color_map.keys())
        present_cats = [c for c in category_order if c in df["Category"].unique()]
        BORDER_COLOR = "black"
        BORDER_WIDTH = 1.2

        fig = go.Figure()
        trace_order = []  # list of (cat, ct, series) in stacking order per pathway
        for cat in present_cats:
            for ct in ["CAPEX", "OPEX"]:
                subset = df[(df["Category"] == cat) & (df["CostType"] == ct)]
                if subset.empty:
                    continue
                grouped = (
                    subset.groupby("Pathway", observed=True)["Cost ($/MWh)"].sum()
                    .reindex(bottom_to_top, fill_value=0.0)
                )
                trace_order.append((cat, ct, grouped))
                # Solid border for CAPEX from marker.line; OPEX has no marker border
                # (the dashed border is drawn separately as a rect shape overlay).
                line_kwargs = (
                    dict(color=BORDER_COLOR, width=BORDER_WIDTH)
                    if ct == "CAPEX" else dict(width=0)
                )

                def _hover_for(pw, _sub=subset):
                    rows = _sub[_sub["Pathway"] == pw]
                    return "<br>".join(
                        f"  {r['Component']}: ${r['Cost ($/MWh)']:.1f}"
                        for _, r in rows.iterrows()
                    )
                hover = [_hover_for(pw) for pw in grouped.index]

                fig.add_trace(go.Bar(
                    y=list(grouped.index),
                    x=list(grouped.values),
                    orientation="h",
                    name=f"{cat} ({ct})",
                    legendgroup=cat,
                    showlegend=False,
                    marker=dict(color=color_map[cat], line=line_kwargs),
                    text=[f"{v:.0f}" if v > 0 else "" for v in grouped.values],
                    textposition="auto",
                    customdata=[[h] for h in hover],
                    hovertemplate=(
                        f"<b>{cat} — {ct}</b><br>"
                        "%{y}<br>"
                        "Subtotal: $%{x:.1f}/MWh"
                        "<br>%{customdata[0]}<extra></extra>"
                    ),
                ))

        # Overlay dashed borders on every OPEX segment.
        # Category axis uses integer indices (0..N-1) for shape y-refs; with bargap=0.25,
        # each bar occupies 0.75 of its category slot so half-height ≈ 0.375.
        bar_half_height = 0.375
        for i, pathway in enumerate(bottom_to_top):
            cumulative = 0.0
            for cat, ct, grouped in trace_order:
                width = float(grouped.get(pathway, 0.0))
                if width <= 0:
                    cumulative += width
                    continue
                if ct == "OPEX":
                    fig.add_shape(
                        type="rect", xref="x", yref="y",
                        x0=cumulative, x1=cumulative + width,
                        y0=i - bar_half_height, y1=i + bar_half_height,
                        line=dict(color=BORDER_COLOR, width=BORDER_WIDTH, dash="3px,2px"),
                        fillcolor="rgba(0,0,0,0)",
                        layer="above",
                    )
                cumulative += width

        # Category colour legend — one swatch per present category
        for cat in present_cats:
            fig.add_trace(go.Bar(
                y=[None], x=[None],
                name=cat,
                marker=dict(color=color_map[cat], line=dict(width=0)),
                showlegend=True, legendgroup=cat,
            ))

        # Border-style legend — scatter line traces so the dash pattern renders
        fig.add_trace(go.Scatter(
            x=[None], y=[None], mode="lines",
            line=dict(color=BORDER_COLOR, width=2, dash="solid"),
            name="CAPEX (solid border)",
            legendgroup="__border", showlegend=True,
        ))
        fig.add_trace(go.Scatter(
            x=[None], y=[None], mode="lines",
            line=dict(color=BORDER_COLOR, width=2, dash="3px,2px"),
            name="OPEX (dashed border)",
            legendgroup="__border", showlegend=True,
        ))

        max_total = float(totals.max())
        label_offset = max(14.0, 0.025 * max_total)
        right_padding = max(45.0, 0.05 * max_total)
        fig.update_layout(
            barmode="stack",
            xaxis_title="$ per MWh delivered",
            yaxis_title="",
            legend_title="",
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="left",
                x=0,
                traceorder="normal",
                entrywidth=145,
                entrywidthmode="pixels",
            ),
            bargap=0.25,
            margin=dict(r=110),
            yaxis=dict(categoryorder="array", categoryarray=bottom_to_top),
            xaxis=dict(range=[0, max_total + right_padding]),
            height=max(400, 55 * len(selected)),
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

        # Dynamic efficiency chain for the explanatory blurb
        _em_t_eff = preset["ocgt"]["efficiency"] if em_turbine == "OCGT" else preset["ccgt"]["efficiency"]
        _em_pathway_eff = (
            preset["electrolyser"]["efficiency"] * preset["methanation"]["efficiency"] * _em_t_eff
        )

        with st.expander("Where E-CH4 wins / loses vs alternatives", expanded=False):
            st.markdown(
                f"""
                **Your current turbine selection:** Green H2 → **{h2_turbine}**, E-CH4 → **{em_turbine}**.
                E-CH4 round-trip efficiency under this setup is
                **electrolyser × methanation × {em_turbine} ≈ {_em_pathway_eff:.0%}**.

                **Why E-CH4 is usually worse than green H2 → {h2_turbine}:** compounded efficiency
                losses combined with CO2 feedstock cost and (new) gas-storage CAPEX. If existing
                natural-gas storage can be reused at near-zero marginal cost, and biogenic/point-source
                CO2 is available at <$30/t, E-CH4's gap narrows sharply if you set **CH4 storage CAPEX
                to $0.03/kWh** and **CO2 (Biogenic) to $0/t**.

                **Why CH4 + CCS usually wins:** CCGTs are cheaper per kW than electrolysers, their
                efficiency (60%) beats OCGT (40%), and natural gas at $6/MMBtu is cheap energy. The
                downside is residual upstream CH4 emissions and imperfect CCS capture — not priced here.

                **The core question in one sentence:** does methanation CAPEX + CO2 cost land below the
                premium you save by avoiding salt-cavern H2 storage and purpose-built peakers?
                """
            )

        with st.expander("⚠️ Known limitations / missing assumptions", expanded=False):
            st.markdown(
                f"""
                The model is deliberately simple. If these matter for your decision, override the
                relevant defaults or treat the result as indicative only.

                - **E-CH4 → OCGT is not in ETC.** We model it by pairing the existing ETC OCGT
                  CAPEX/η/utilisation preset with a methanation stage. No source calibration exists
                  for this specific combination — treat the result as a first-order estimate.
                - **Turbine utilisation is pathway-independent.** The sidebar's OCGT and CCGT
                  utilisation sliders apply to every pathway that uses that turbine. In reality,
                  CH4+CCS and E-CH4+CCGT might dispatch differently from an H2 peaker even
                  under the same system conditions.
                - **Methanation utilisation is pinned to the electrolyser utilisation slider**
                  (same value). If you want methanation to run more flexibly (e.g., around a
                  buffer stock of H2), you need to detach them — not exposed in this UI.
                - **CO2 costs are per-tonne only.** Compression, transport and delivery to the
                  methanation reactor are assumed bundled into the $/tCO2 price. For piped DAC
                  output the assumption is defensible; for distant biogenic/point-source CO2
                  it may understate.
                - **No H2/CH4 blending modelled.** Real turbines can burn 30:70 mixtures;
                  we treat pathways as single-fuel.
                - **No CCS on combustion for e-fuels.** A user asking about
                  "E-CH4 + post-combustion CCS = net-negative power with DAC feedstock"
                  would need to extend the model.
                - **Emissions not priced** outside the unabated-gas + removal pathway. We don't
                  apply a carbon price to the unabated-OCGT counterfactual.
                - **H2 / CH4 storage losses** (boil-off, leakage, self-discharge) are set to
                  zero per ETC's simplification. Multi-month seasonal cycles could lose 1–5%
                  of stored energy depending on containment.
                """
            )


# ---------------------------------------------------------------------------
# Tab 3 — Pathway diagrams (simplified flow charts)
# ---------------------------------------------------------------------------
with tab_flows:
    st.subheader("Pathway flow diagrams")
    st.caption(
        "Simplified schematics of how each pathway converts inputs to delivered "
        "electricity. Node border colour = functional category; values reflect "
        "current sidebar settings."
    )

    st.markdown(
        """
        **Categories:**
        &nbsp;<span style="color:#1f77b4;font-weight:600">■ Feedstock</span> (electricity, gas, CO2)
        &nbsp;·&nbsp; <span style="color:#ff7f0e;font-weight:600">■ Conversion</span> (electrolyser, methanation, CCS)
        &nbsp;·&nbsp; <span style="color:#2ca02c;font-weight:600">■ Storage</span> (cavern, tank, battery)
        &nbsp;·&nbsp; <span style="color:#d62728;font-weight:600">■ Turbine</span> (OCGT / CCGT)
        &nbsp;·&nbsp; <span style="color:#9467bd;font-weight:600">■ Offset</span> (CO2 removal credit)
        &nbsp;·&nbsp; <span style="color:#7f7f7f;font-weight:600">■ Output</span> (delivered / vented)
        """,
        unsafe_allow_html=True,
    )

    CAT_STYLE = {
        "feedstock":  'fillcolor="#d6e9f8", color="#1f77b4"',
        "conversion": 'fillcolor="#fde4c8", color="#ff7f0e"',
        "storage":    'fillcolor="#d4ecd4", color="#2ca02c"',
        "turbine":    'fillcolor="#f5cccc", color="#d62728"',
        "offset":     'fillcolor="#e6d6ef", color="#9467bd"',
        "output":     'fillcolor="#e8e8e8", color="#7f7f7f"',
    }

    def _dot(nodes, edges):
        """
        Build a DOT string.
          nodes: list of (node_id, label, category)
          edges: list of (from_id, to_id, edge_label_or_empty)
        """
        lines = [
            "digraph G {",
            "  rankdir=LR;",
            '  bgcolor="transparent";',
            '  node [shape=box, style="rounded,filled", fontname="Arial", penwidth=2];',
            '  edge [fontname="Arial", fontsize=10, color="#555555"];',
            "  graph [nodesep=0.35, ranksep=0.55];",
        ]
        for nid, label, cat in nodes:
            lines.append(f'  {nid} [label="{label}", {CAT_STYLE[cat]}];')
        for f, t, lbl in edges:
            lines.append(
                f'  {f} -> {t} [label="{lbl}"];' if lbl else f'  {f} -> {t};'
            )
        lines.append("}")
        return "\n".join(lines)

    # Derived values for labels
    _h2_t_eff = preset["ocgt"]["efficiency"] if h2_turbine == "OCGT" else preset["ccgt"]["efficiency"]
    _em_t_eff = preset["ocgt"]["efficiency"] if em_turbine == "OCGT" else preset["ccgt"]["efficiency"]
    _ccs_net_eff = preset["ccgt"]["efficiency"] * preset["ccs"]["efficiency"]

    diagrams: dict[str, str] = {}

    diagrams["Existing Unabated OCGT (no removals)"] = _dot(
        nodes=[
            ("gas",       f"Natural gas\\n${gas_price:.1f}/MMBtu", "feedstock"),
            ("ch4_store", f"CH4 storage\\n{storage_cycles:.0f} cycles/yr", "storage"),
            ("ocgt",      f"Existing OCGT\\n(no CAPEX)\\nη={preset['ocgt']['efficiency']:.0%}\\n(CO2 vented, not priced)", "turbine"),
            ("out",       "Electricity\\ndelivered", "output"),
        ],
        edges=[("gas", "ch4_store", ""), ("ch4_store", "ocgt", "CH4"), ("ocgt", "out", "")],
    )

    diagrams["Unabated OCGT (no removals)"] = _dot(
        nodes=[
            ("gas",       f"Natural gas\\n${gas_price:.1f}/MMBtu", "feedstock"),
            ("ch4_store", f"CH4 storage\\n{storage_cycles:.0f} cycles/yr", "storage"),
            ("ocgt",      f"OCGT\\nη={preset['ocgt']['efficiency']:.0%}\\n(CO2 vented, not priced)", "turbine"),
            ("out",       "Electricity\\ndelivered", "output"),
        ],
        edges=[("gas", "ch4_store", ""), ("ch4_store", "ocgt", "CH4"), ("ocgt", "out", "")],
    )

    diagrams[f"Unabated OCGT + ${int(co2_removal)}/t removal"] = _dot(
        nodes=[
            ("gas",       f"Natural gas\\n${gas_price:.1f}/MMBtu", "feedstock"),
            ("ch4_store", f"CH4 storage\\n{storage_cycles:.0f} cycles/yr", "storage"),
            ("ocgt",      f"OCGT\\nη={preset['ocgt']['efficiency']:.0%}", "turbine"),
            ("out",       "Electricity\\ndelivered", "output"),
            ("co2",       "CO2 emissions", "output"),
            ("offset",    f"Carbon removal\\n${int(co2_removal)}/t", "offset"),
        ],
        edges=[
            ("gas", "ch4_store", ""), ("ch4_store", "ocgt", "CH4"),
            ("ocgt", "out", ""), ("ocgt", "co2", ""), ("co2", "offset", "offset"),
        ],
    )

    diagrams[f"Green H2 → {h2_turbine}"] = _dot(
        nodes=[
            ("elec_in",      f"Electricity input\\n${elec_price}/MWh", "feedstock"),
            ("electrolyser", f"Electrolyser\\nη={preset['electrolyser']['efficiency']:.0%}\\nutil {elec_util:.0%}", "conversion"),
            ("h2_store",     f"H2 salt-cavern\\nstorage\\n{storage_cycles:.0f} cycles/yr", "storage"),
            ("turbine",      f"{h2_turbine}\\nη={_h2_t_eff:.0%}", "turbine"),
            ("out",          "Electricity\\ndelivered", "output"),
        ],
        edges=[
            ("elec_in", "electrolyser", ""),
            ("electrolyser", "h2_store", "H2"),
            ("h2_store", "turbine", ""),
            ("turbine", "out", ""),
        ],
    )

    diagrams["CH4 + CCS → CCGT"] = _dot(
        nodes=[
            ("gas",  f"Natural gas\\n${gas_price:.1f}/MMBtu", "feedstock"),
            ("ccgt", f"CCGT\\nη={preset['ccgt']['efficiency']:.0%}", "turbine"),
            ("ccs",  f"CCS capture\\n{preset['ccs']['efficiency']:.0%} retention\\nnet η={_ccs_net_eff:.0%}", "conversion"),
            ("out",  "Electricity\\ndelivered", "output"),
            ("co2",  "CO2 captured\\n& stored", "output"),
        ],
        edges=[
            ("gas", "ccgt", ""),
            ("ccgt", "ccs", "flue"),
            ("ccs", "co2", ""),
            ("ccgt", "out", ""),
        ],
    )

    for src_label, co2_val in [
        ("DAC", co2_dac), ("Biogenic", co2_biogenic), ("Point-source", co2_point_source),
    ]:
        diagrams[f"E-CH4 ({src_label}) → {em_turbine}"] = _dot(
            nodes=[
                ("elec_in",      f"GElectricity input\\n${elec_price}/MWh", "feedstock"),
                ("co2_in",       f"CO2 ({src_label})\\n${int(co2_val)}/t", "feedstock"),
                ("electrolyser", f"Electrolyser\\nη={preset['electrolyser']['efficiency']:.0%}", "conversion"),
                ("methanation",  f"Methanation\\nη={preset['methanation']['efficiency']:.0%}", "conversion"),
                ("ch4_store",    f"CH4 storage\\n{storage_cycles:.0f} cycles/yr", "storage"),
                ("turbine",      f"{em_turbine}\\nη={_em_t_eff:.0%}", "turbine"),
                ("out",          "Electricity\\ndelivered", "output"),
            ],
            edges=[
                ("elec_in", "electrolyser", ""),
                ("electrolyser", "methanation", "H2"),
                ("co2_in", "methanation", ""),
                ("methanation", "ch4_store", "CH4"),
                ("ch4_store", "turbine", ""),
                ("turbine", "out", ""),
            ],
        )

    diagrams["Iron-air battery"] = _dot(
        nodes=[
            ("elec_in", f"Electricity input\\n${elec_price}/MWh", "feedstock"),
            ("battery", f"Iron-air battery\\nη_rt={preset['iron_air']['efficiency']:.0%}\\n{iron_air_cycles} cycles/yr", "storage"),
            ("out",     "Electricity\\ndelivered", "output"),
        ],
        edges=[("elec_in", "battery", ""), ("battery", "out", "")],
    )

    # Render — only the currently selected pathways, in the same order as sidebar
    shown_any = False
    for name in pathways_to_show:
        if name in diagrams:
            with st.expander(name, expanded=True):
                st.graphviz_chart(diagrams[name], use_container_width=True)
                shown_any = True
    if not shown_any:
        st.info("Select at least one pathway in the sidebar to see its diagram.")


# ---------------------------------------------------------------------------
# Tab 4 — Sensitivity (tornado)
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

            # Dynamic turbine selection matches the sidebar choice.
            h2_t_dict = preset_override["ocgt"] if h2_turbine == "OCGT" else preset_override["ccgt"]
            em_t_dict = preset_override["ocgt"] if em_turbine == "OCGT" else preset_override["ccgt"]

            h2_builder = build_h2_ocgt if h2_turbine == "OCGT" else build_h2_ccgt

            # Existing OCGT — zero CAPEX
            existing_ocgt_ovr = copy.deepcopy(preset_override["ocgt"])
            existing_ocgt_ovr["capex_per_kw"] = 0

            args_map = {
                "Existing Unabated OCGT (no removals)": lambda: build_unabated_gas_no_removal(
                    existing_ocgt_ovr,
                    gas_price_usd_per_mmbtu=overrides.get("globals.gas_price", gas_price),
                    discount_rate=discount_rate,
                    ch4_storage=preset_override["ch4_storage"]),
                "Unabated OCGT (no removals)": lambda: build_unabated_gas_no_removal(
                    preset_override["ocgt"],
                    gas_price_usd_per_mmbtu=overrides.get("globals.gas_price", gas_price),
                    discount_rate=discount_rate,
                    ch4_storage=preset_override["ch4_storage"]),
                f"Green H2 → {h2_turbine}": lambda: h2_builder(
                    preset_override["electrolyser"], preset_override["h2_storage"], h2_t_dict,
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
                    discount_rate=discount_rate,
                    ch4_storage=preset_override["ch4_storage"]),
                f"E-CH4 (DAC) → {em_turbine}": lambda: build_emethane(
                    preset_override["electrolyser"], preset_override["methanation"],
                    preset_override["ch4_storage"], em_t_dict,
                    co2_cost_per_t=overrides.get("globals.co2_dac", co2_dac),
                    electricity_price=overrides.get("globals.elec_price", elec_price),
                    co2_source_label="DAC", turbine_type=em_turbine, discount_rate=discount_rate),
                f"E-CH4 (Biogenic) → {em_turbine}": lambda: build_emethane(
                    preset_override["electrolyser"], preset_override["methanation"],
                    preset_override["ch4_storage"], em_t_dict,
                    co2_cost_per_t=overrides.get("globals.co2_biogenic", co2_biogenic),
                    electricity_price=overrides.get("globals.elec_price", elec_price),
                    co2_source_label="Biogenic", turbine_type=em_turbine, discount_rate=discount_rate),
                f"E-CH4 (Point-source) → {em_turbine}": lambda: build_emethane(
                    preset_override["electrolyser"], preset_override["methanation"],
                    preset_override["ch4_storage"], em_t_dict,
                    co2_cost_per_t=overrides.get("globals.co2_point_source", co2_point_source),
                    electricity_price=overrides.get("globals.elec_price", elec_price),
                    co2_source_label="Point-source", turbine_type=em_turbine, discount_rate=discount_rate),
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
            if path_name.startswith("Green H2"):
                # Which turbine is actually in play for this H2 pathway
                tkey = "ocgt" if path_name.endswith("→ OCGT") else "ccgt"
                tlabel = "OCGT" if tkey == "ocgt" else "CCGT"
                return common + [
                    (f"{tkey}.capex_per_kw", preset[tkey]["capex_per_kw"], f"{tlabel} CAPEX"),
                    (f"{tkey}.utilisation", preset[tkey]["utilisation"], f"{tlabel} utilisation"),
                    ("h2_storage.capex_per_kwh", preset["h2_storage"]["capex_per_kwh"], "H2 storage CAPEX"),
                ]
            if path_name == "Existing Unabated OCGT (no removals)":
                return [
                    ("ocgt.utilisation", preset["ocgt"]["utilisation"], "OCGT utilisation"),
                    ("ocgt.efficiency", preset["ocgt"]["efficiency"], "OCGT η"),
                    ("ch4_storage.capex_per_kwh", preset["ch4_storage"]["capex_per_kwh"], "CH4 storage CAPEX"),
                    ("ch4_storage.cycles_per_year", preset["ch4_storage"]["cycles_per_year"], "CH4 storage cycles/yr"),
                    ("globals.gas_price", gas_price, "Natural gas price"),
                ]
            if path_name == "Unabated OCGT (no removals)":
                return [
                    ("ocgt.capex_per_kw", preset["ocgt"]["capex_per_kw"], "OCGT CAPEX"),
                    ("ocgt.utilisation", preset["ocgt"]["utilisation"], "OCGT utilisation"),
                    ("ocgt.efficiency", preset["ocgt"]["efficiency"], "OCGT η"),
                    ("ch4_storage.capex_per_kwh", preset["ch4_storage"]["capex_per_kwh"], "CH4 storage CAPEX"),
                    ("ch4_storage.cycles_per_year", preset["ch4_storage"]["cycles_per_year"], "CH4 storage cycles/yr"),
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
                    ("ch4_storage.capex_per_kwh", preset["ch4_storage"]["capex_per_kwh"], "CH4 storage CAPEX"),
                    ("ch4_storage.cycles_per_year", preset["ch4_storage"]["cycles_per_year"], "CH4 storage cycles/yr"),
                    ("globals.gas_price", gas_price, "Natural gas price"),
                    ("globals.co2_removal", co2_removal, "Carbon removal $/t"),
                ]
            if "E-CH4" in path_name:
                co2_key = ("globals.co2_dac", co2_dac) if "DAC" in path_name else (
                    ("globals.co2_biogenic", co2_biogenic) if "Biogenic" in path_name else
                    ("globals.co2_point_source", co2_point_source)
                )
                tkey = "ocgt" if path_name.endswith("→ OCGT") else "ccgt"
                tlabel = "OCGT" if tkey == "ocgt" else "CCGT"
                co2_src = path_name.split("(")[1].split(")")[0]
                return common + [
                    ("methanation.capex_per_kw", preset["methanation"]["capex_per_kw"], "Methanation CAPEX"),
                    ("methanation.efficiency", preset["methanation"]["efficiency"], "Methanation η"),
                    ("ch4_storage.capex_per_kwh", preset["ch4_storage"]["capex_per_kwh"], "CH4 storage CAPEX"),
                    ("ch4_storage.cycles_per_year", preset["ch4_storage"]["cycles_per_year"], "CH4 storage cycles/yr"),
                    (f"{tkey}.capex_per_kw", preset[tkey]["capex_per_kw"], f"{tlabel} CAPEX"),
                    (co2_key[0], co2_key[1], f"CO2 cost ({co2_src})"),
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

            if h_path == "Existing Unabated OCGT (no removals)":
                existing_ocgt_h = copy.deepcopy(preset_h["ocgt"])
                existing_ocgt_h["capex_per_kw"] = 0
                return build_unabated_gas_no_removal(existing_ocgt_h,
                                                    gas_price_usd_per_mmbtu=overrides["gas_price"],
                                                    discount_rate=discount_rate,
                                                    ch4_storage=preset_h["ch4_storage"])
            if h_path == "Unabated OCGT (no removals)":
                return build_unabated_gas_no_removal(preset_h["ocgt"],
                                                    gas_price_usd_per_mmbtu=overrides["gas_price"],
                                                    discount_rate=discount_rate,
                                                    ch4_storage=preset_h["ch4_storage"])
            if h_path.startswith("Green H2"):
                t_is_ocgt = h_path.endswith("→ OCGT")
                t_dict = preset_h["ocgt"] if t_is_ocgt else preset_h["ccgt"]
                builder = build_h2_ocgt if t_is_ocgt else build_h2_ccgt
                return builder(preset_h["electrolyser"], preset_h["h2_storage"], t_dict,
                               electricity_price=overrides["elec_price"], discount_rate=discount_rate)
            if h_path == "CH4 + CCS → CCGT":
                return build_ch4_ccs_ccgt(ccgt_ccs2, preset_h["ccs"],
                                          gas_price_usd_per_mmbtu=overrides["gas_price"],
                                          discount_rate=discount_rate)
            if h_path.startswith("Unabated") and "removal" in h_path:
                return build_unabated_gas_removal(preset_h["ocgt"], gas_price_usd_per_mmbtu=overrides["gas_price"],
                                                  co2_removal_cost=co2_removal, discount_rate=discount_rate,
                                                  ch4_storage=preset_h["ch4_storage"])
            if "E-CH4" in h_path:
                co2_val = overrides["co2_dac"] if "DAC" in h_path else (
                    overrides["co2_biogenic"] if "Biogenic" in h_path else overrides["co2_point_source"]
                )
                label = "DAC" if "DAC" in h_path else ("Biogenic" if "Biogenic" in h_path else "Point-source")
                t_is_ocgt = h_path.endswith("→ OCGT")
                t_dict = preset_h["ocgt"] if t_is_ocgt else preset_h["ccgt"]
                t_label = "OCGT" if t_is_ocgt else "CCGT"
                return build_emethane(preset_h["electrolyser"], preset_h["methanation"],
                                      preset_h["ch4_storage"], t_dict,
                                      co2_cost_per_t=co2_val,
                                      electricity_price=overrides["elec_price"],
                                      co2_source_label=label, turbine_type=t_label,
                                      discount_rate=discount_rate)
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
# Tab 6 — Assumptions audit trail
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
