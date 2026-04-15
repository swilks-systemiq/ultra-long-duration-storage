"""
LCOS engine for ultra-long duration (50h+) storage pathways.

Methodology mirrors ETC (2025) Power Systems Transformation, Section 1.5.1 / Box E:
    LCOS = sum_t (CAPEX + OPEX + charge_cost) / (1+r)^t  /  sum_t (Energy_out) / (1+r)^t

For a pathway that chains multiple stages (e.g. electrolyser -> methanation -> storage -> turbine),
we cascade efficiencies and express every stage's annualised cost on a per-MWhe-delivered basis.

All functions are pure: they take a dict-like input and return numbers or dicts.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable

# ---------------------------------------------------------------------------
# Physical / unit constants
# ---------------------------------------------------------------------------
HOURS_PER_YEAR = 8760
MJ_PER_MWH = 3600.0
# Lower heating value of methane (CH4): ~50.0 MJ/kg => ~13.9 kWh/kg
# Molar masses: CH4 = 16 g/mol, CO2 = 44 g/mol
# 1 MWh (LHV) of CH4 combustion needs 1 / 13.9 kg CH4 = 0.0719 kmol CH4
# => produces 0.0719 kmol CO2 = 0.0719 * 44 = 3.17 kg CO2 per MWh_CH4_LHV
# Equivalently, methanation needs ~0.198 tCO2 per MWh_CH4_LHV produced
T_CO2_PER_MWH_CH4 = 0.198

# Hydrogen LHV ~33.3 kWh/kg (per ETC footnote 127)
KWH_PER_KG_H2 = 33.3


# ---------------------------------------------------------------------------
# Finance helpers
# ---------------------------------------------------------------------------
def crf(discount_rate: float, lifetime_years: int) -> float:
    """Capital recovery factor."""
    if discount_rate <= 0:
        return 1.0 / lifetime_years
    r = discount_rate
    n = lifetime_years
    return r * (1 + r) ** n / ((1 + r) ** n - 1)


# ---------------------------------------------------------------------------
# Stage = one conversion/storage block with CAPEX, OPEX, efficiency, utilisation
# ---------------------------------------------------------------------------
@dataclass
class Stage:
    """
    A single pathway stage (electrolyser, methanation, storage, turbine, CCS, ...).

    Convention for inputs/outputs:
    - capex_per_kw_out: $ per kW of *output-rated* capacity of the stage (i.e. the kW of the
      downstream product, e.g. for an electrolyser we define CAPEX per kW of H2 output).
      For storage, use capex_per_kwh_cap (energy capacity, not power).
    - utilisation: 0..1 fraction of full-load hours per year this stage actually runs.
      For storage, use cycles_per_year instead (energy delivered = cap x cycles).
    - efficiency: fraction of input energy retained in the output product.
    - var_opex_per_mwh_out: variable OPEX per MWh of stage output.
    - fuel_cost_per_mwh_out: optional fuel cost per MWh of output (fossil turbines).
    """
    name: str
    capex_per_kw_out: float = 0.0          # $/kW (for power-rated stages)
    capex_per_kwh_cap: float = 0.0         # $/kWh (for storage stages)
    fixed_opex_per_kw_yr: float = 0.0      # $/kW/yr
    fixed_opex_pct_capex: float = 0.0      # fraction of CAPEX per year, alternative to $/kW/yr
    var_opex_per_mwh_out: float = 0.0      # $/MWh_out
    fuel_cost_per_mwh_out: float = 0.0     # $/MWh_out (fossil or purchased input)
    efficiency: float = 1.0                # 0..1, output/input (energy basis)
    utilisation: float = 1.0               # 0..1 for power stages
    cycles_per_year: float = 0.0           # for storage stages; if >0 overrides utilisation
    lifetime_years: int = 25
    discount_rate: float = 0.08
    # Extra $/MWh cost lines that should be shown separately in the breakdown
    extra_cost_per_mwh_out: Dict[str, float] = field(default_factory=dict)
    # Storage throughput cost ($/MWh cycled) - for salt cavern / tank turnover costs
    throughput_cost_per_mwh: float = 0.0
    # Duration (hours) for storage stages: energy cap = power x duration
    storage_duration_h: float = 0.0
    # Is this a storage stage? Affects annualised-cost normalisation
    is_storage: bool = False
    # Basis of capex_per_kw_out: "output" (default, e.g. $/kW_CH4 or $/kW_elec_out)
    # or "input" (e.g. electrolyser $/kW_elec_in). For "input" basis, the MWh_out per
    # kW per year is scaled by the stage efficiency.
    capex_basis: str = "output"

    def annualised_capex_per_kw(self) -> float:
        return self.capex_per_kw_out * crf(self.discount_rate, self.lifetime_years)

    def annualised_capex_per_kwh(self) -> float:
        return self.capex_per_kwh_cap * crf(self.discount_rate, self.lifetime_years)

    def fixed_opex_per_kw(self) -> float:
        pct_based = self.capex_per_kw_out * self.fixed_opex_pct_capex
        return self.fixed_opex_per_kw_yr + pct_based

    def fixed_opex_per_kwh_cap(self) -> float:
        return self.capex_per_kwh_cap * self.fixed_opex_pct_capex

    def cost_per_mwh_out(self) -> Dict[str, float]:
        """
        Return a dict of $/MWh_out cost components for this stage (excluding the cascading
        pathway multiplier — that's applied by the Pathway wrapper).
        """
        components: Dict[str, float] = {}
        if self.is_storage:
            # Storage: energy cap x cycles defines annual throughput
            if self.cycles_per_year > 0:
                # $/MWh delivered = annualised_capex_per_kwh / cycles_per_year
                components[f"{self.name} CAPEX"] = (
                    self.annualised_capex_per_kwh() * 1000 / max(self.cycles_per_year, 1e-9)
                )
                components[f"{self.name} fixed OPEX"] = (
                    self.fixed_opex_per_kwh_cap() * 1000 / max(self.cycles_per_year, 1e-9)
                )
            components[f"{self.name} throughput"] = self.throughput_cost_per_mwh
        else:
            # Power stage: annualised $/kW divided by MWh delivered per kW per year
            # If capex_basis == "output", 1 kW ≡ 1 kW of stage output.
            # If capex_basis == "input",  1 kW ≡ 1 kW of stage *input* (so 1 kW of output
            # requires 1/η kW of input capacity, and MWh_out/kW/yr scales by η).
            basis_factor = self.efficiency if self.capex_basis == "input" else 1.0
            denom_mwh_per_kw_yr = (
                max(self.utilisation, 1e-6) * HOURS_PER_YEAR / 1000.0 * basis_factor
            )
            components[f"{self.name} CAPEX"] = self.annualised_capex_per_kw() / denom_mwh_per_kw_yr
            components[f"{self.name} fixed OPEX"] = self.fixed_opex_per_kw() / denom_mwh_per_kw_yr
            if self.var_opex_per_mwh_out:
                components[f"{self.name} variable OPEX"] = self.var_opex_per_mwh_out
            if self.fuel_cost_per_mwh_out:
                components[f"{self.name} fuel"] = self.fuel_cost_per_mwh_out
        for k, v in self.extra_cost_per_mwh_out.items():
            components[f"{self.name} {k}"] = v
        return components


# ---------------------------------------------------------------------------
# Pathway = ordered chain of stages, producing 1 MWh of delivered electricity
# ---------------------------------------------------------------------------
@dataclass
class Pathway:
    """
    An ordered chain of stages.

    The *last* stage is assumed to produce delivered electricity (MWhe).
    Earlier stages produce the intermediate energy carrier consumed by the next stage.

    Efficiency cascade (from the output backwards):
        MWh out = 1
        MWh of stage_i intermediate = 1 / (prod of downstream stages' efficiencies)

    Each stage's per-MWh-out cost is scaled by (1 / downstream_efficiency_product) to
    express everything on a per-MWhe-delivered basis.

    An optional `upstream_electricity_mwh_per_mwhe` is the MWhe of *grid* electricity needed
    per MWhe delivered (for e-fuel pathways only). The Pathway also tracks an optional
    CO2 feedstock requirement for synthetic methane.
    """
    name: str
    stages: List[Stage]
    electricity_input_price: float = 0.0           # $/MWh of grid electricity feeding stage 1
    stage_1_is_electrolyser: bool = False          # treat stage 1 input as electricity (MWhe)
    co2_cost_per_t: float = 0.0                    # $/tCO2 feedstock (for methanation only)
    co2_t_per_mwh_ch4: float = T_CO2_PER_MWH_CH4   # stoich CO2 need
    needs_co2: bool = False                        # toggles CO2 cost line
    carbon_removal_cost_per_t: float = 0.0         # $/tCO2 for offsetting residual emissions
    co2_emitted_t_per_mwhe: float = 0.0            # emissions needing offset (unabated gas)
    notes: str = ""

    def efficiency_product(self) -> float:
        e = 1.0
        for s in self.stages:
            e *= max(s.efficiency, 1e-6)
        return e

    def breakdown(self) -> Dict[str, float]:
        """
        Return {component_label: $/MWhe_delivered} for all cost lines in this pathway.
        """
        out: Dict[str, float] = {}
        # For each stage, scale its per-MWh-out costs by the "downstream efficiency"
        # i.e. to produce 1 MWhe delivered, we need 1/(prod of downstream eff) MWh_out of stage i
        stages = self.stages
        n = len(stages)
        for i, stage in enumerate(stages):
            downstream_eff = 1.0
            for j in range(i + 1, n):
                downstream_eff *= max(stages[j].efficiency, 1e-6)
            # MWh_out of this stage per MWhe delivered
            scale = 1.0 / max(downstream_eff, 1e-6)
            stage_costs = stage.cost_per_mwh_out()
            for label, val in stage_costs.items():
                out[label] = out.get(label, 0.0) + val * scale

        # Upstream electricity input (for e-fuel pathways)
        if self.stage_1_is_electrolyser and self.electricity_input_price:
            # MWhe of input electricity needed per MWhe delivered = 1 / total_eff
            mwh_elec_in = 1.0 / self.efficiency_product()
            out["Electricity input"] = self.electricity_input_price * mwh_elec_in

        # CO2 feedstock cost for e-methane pathways
        if self.needs_co2 and self.co2_cost_per_t:
            # tCO2 per MWh_CH4 * MWh_CH4 per MWhe delivered
            # MWh_CH4 per MWhe = 1 / (eff of stages after methanation, inclusive of turbine)
            # We find the methanation stage by convention (named "Methanation") and take
            # the product of efficiencies *after* it. If not found, use turbine eff only.
            post_methanation_eff = 1.0
            found = False
            for s in self.stages:
                if found:
                    post_methanation_eff *= max(s.efficiency, 1e-6)
                if s.name.lower().startswith("methan"):
                    found = True
            if not found:
                # fallback: assume the last stage is the turbine
                post_methanation_eff = max(self.stages[-1].efficiency, 1e-6)
            mwh_ch4_per_mwhe = 1.0 / max(post_methanation_eff, 1e-6)
            t_co2 = self.co2_t_per_mwh_ch4 * mwh_ch4_per_mwhe
            out["CO2 feedstock"] = self.co2_cost_per_t * t_co2

        # Carbon removal offset cost (for unabated gas pathway)
        if self.carbon_removal_cost_per_t and self.co2_emitted_t_per_mwhe:
            out["Carbon removal offset"] = (
                self.carbon_removal_cost_per_t * self.co2_emitted_t_per_mwhe
            )

        return out

    def lcos(self) -> float:
        return sum(self.breakdown().values())


# ---------------------------------------------------------------------------
# Convenience: build a Pathway from simpler dict inputs (used by app.py)
# ---------------------------------------------------------------------------
def build_h2_ocgt(electrolyser, storage, ocgt, electricity_price, discount_rate=None):
    """Green H2 -> salt cavern -> OCGT."""
    stages = [
        _stage_from_dict("Electrolyser", electrolyser, discount_rate),
        _stage_from_dict("H2 storage", storage, discount_rate, is_storage=True),
        _stage_from_dict("OCGT", ocgt, discount_rate),
    ]
    return Pathway(
        name="Green H2 → OCGT",
        stages=stages,
        electricity_input_price=electricity_price,
        stage_1_is_electrolyser=True,
    )


def build_h2_ccgt(electrolyser, storage, ccgt, electricity_price, discount_rate=None):
    stages = [
        _stage_from_dict("Electrolyser", electrolyser, discount_rate),
        _stage_from_dict("H2 storage", storage, discount_rate, is_storage=True),
        _stage_from_dict("CCGT", ccgt, discount_rate),
    ]
    return Pathway(
        name="Green H2 → CCGT",
        stages=stages,
        electricity_input_price=electricity_price,
        stage_1_is_electrolyser=True,
    )


def build_emethane(
    electrolyser, methanation, storage, ccgt,
    co2_cost_per_t, electricity_price, co2_source_label, discount_rate=None,
):
    """Solar -> electrolyser -> methanation -> gas storage -> CCGT."""
    stages = [
        _stage_from_dict("Electrolyser", electrolyser, discount_rate),
        _stage_from_dict("Methanation", methanation, discount_rate),
        _stage_from_dict("CH4 storage", storage, discount_rate, is_storage=True),
        _stage_from_dict("CCGT", ccgt, discount_rate),
    ]
    return Pathway(
        name=f"E-methane ({co2_source_label}) → CCGT",
        stages=stages,
        electricity_input_price=electricity_price,
        stage_1_is_electrolyser=True,
        co2_cost_per_t=co2_cost_per_t,
        needs_co2=True,
    )


def build_ch4_ccs_ccgt(ccgt, ccs, gas_price_usd_per_mmbtu, discount_rate=None):
    """Methane + CCS on CCGT. Fossil fuel input priced at gas_price."""
    # $6/MMBtu * (1 MMBtu / 0.2931 MWh_LHV) ≈ $20.47/MWh_fuel
    # fuel_cost_per_mwh_out = gas_price / MMBtu_per_MWh / turbine_eff
    MMBTU_PER_MWH = 3.412  # standard conversion (1 MWh_th = 3.412 MMBtu)
    fuel_cost_per_mwh_elec = gas_price_usd_per_mmbtu * MMBTU_PER_MWH / max(ccgt["efficiency"], 1e-6)
    ccgt_stage = _stage_from_dict("CCGT", ccgt, discount_rate)
    ccgt_stage.fuel_cost_per_mwh_out = fuel_cost_per_mwh_elec
    # CCS efficiency penalty is captured by lowering ccgt efficiency in the caller (see defaults)
    ccs_stage = _stage_from_dict("CCS", ccs, discount_rate)
    # CCS stage efficiency is the parasitic retention (e.g. 0.9 if 10% parasitic load)
    stages = [ccgt_stage, ccs_stage]
    return Pathway(name="CH4 + CCS → CCGT", stages=stages)


def build_unabated_gas_removal(ocgt, gas_price_usd_per_mmbtu, co2_removal_cost, discount_rate=None):
    MMBTU_PER_MWH = 3.412
    fuel_cost_per_mwh_elec = gas_price_usd_per_mmbtu * MMBTU_PER_MWH / max(ocgt["efficiency"], 1e-6)
    turbine = _stage_from_dict("OCGT", ocgt, discount_rate)
    turbine.fuel_cost_per_mwh_out = fuel_cost_per_mwh_elec
    # Emissions: natural gas ~0.2 tCO2/MWh_LHV; divided by turbine eff
    emissions_t_per_mwhe = 0.2 / max(ocgt["efficiency"], 1e-6)
    return Pathway(
        name=f"Unabated gas + removals (${co2_removal_cost}/tCO2)",
        stages=[turbine],
        carbon_removal_cost_per_t=co2_removal_cost,
        co2_emitted_t_per_mwhe=emissions_t_per_mwhe,
    )


def build_iron_air(battery, electricity_price, discount_rate=None):
    """
    Iron-air battery: a single electrochemical storage stage.

    Here we model the battery as a combined 'power+energy' stage. We express CAPEX per kWh
    of energy capacity (the dominant cost driver) and use cycles_per_year for LCOS
    normalisation. Efficiency ~50% accounts for round-trip losses; electricity input
    price is scaled by 1/eff.
    """
    stage = _stage_from_dict("Iron-air", battery, discount_rate, is_storage=True)
    return Pathway(
        name="Iron-air battery",
        stages=[stage],
        electricity_input_price=electricity_price,
        stage_1_is_electrolyser=True,  # treat as electricity-in
    )


def _stage_from_dict(name: str, d: Dict, discount_rate: Optional[float] = None, is_storage: bool = False) -> Stage:
    s = Stage(
        name=name,
        capex_per_kw_out=d.get("capex_per_kw", 0.0),
        capex_per_kwh_cap=d.get("capex_per_kwh", 0.0),
        fixed_opex_per_kw_yr=d.get("fixed_opex_per_kw_yr", 0.0),
        fixed_opex_pct_capex=d.get("fixed_opex_pct", 0.0),
        var_opex_per_mwh_out=d.get("var_opex_per_mwh", 0.0),
        efficiency=d.get("efficiency", 1.0),
        utilisation=d.get("utilisation", 1.0),
        cycles_per_year=d.get("cycles_per_year", 0.0),
        lifetime_years=d.get("lifetime_years", 25),
        discount_rate=discount_rate if discount_rate is not None else d.get("discount_rate", 0.08),
        throughput_cost_per_mwh=d.get("throughput_cost_per_mwh", 0.0),
        is_storage=is_storage,
        capex_basis=d.get("capex_basis", "output"),
    )
    return s


# ---------------------------------------------------------------------------
# Sensitivity helpers
# ---------------------------------------------------------------------------
def sensitivity_sweep(
    base_builder: Callable[[], Pathway],
    param_setter: Callable[[float], Pathway],
    base_value: float,
    swing_pct: float = 0.3,
):
    """Return (low_lcos, base_lcos, high_lcos) for a ±swing_pct sensitivity."""
    low_p = base_value * (1 - swing_pct)
    high_p = base_value * (1 + swing_pct)
    base_lcos = base_builder().lcos()
    low_lcos = param_setter(low_p).lcos()
    high_lcos = param_setter(high_p).lcos()
    return low_lcos, base_lcos, high_lcos
