from __future__ import annotations

from dataclasses import dataclass
import math
import numpy as np
import pandas as pd

from scipy.optimize import Bounds, LinearConstraint, milp

from dgcup.optimization.q3_continuous_dispatch import (
    ContinuousDispatchParams,
    solve_continuous_dispatch,
)


@dataclass(frozen=True)
class OffgridStorageParams:
    """Parameters for Q4 off-grid storage dispatch."""

    plant_capacity_ton_per_day: float = 72.0
    ammonia_output_ton_per_hour: float = 3.0

    min_running_power_ratio: float = 0.10

    alk_power_mw: float = 20.0
    pem_power_mw: float = 20.0
    ammonia_power_mw: float = 1.5

    wind_lcoe_yuan_per_kwh: float = 0.15
    pv_lcoe_yuan_per_kwh: float = 0.12

    alk_om_yuan_per_kwh: float = 0.10
    pem_om_yuan_per_kwh: float = 0.15
    ammonia_om_yuan_per_kwh: float = 0.002

    ammonia_investment_yuan_per_kg_h2_capacity: float = 60000.0
    ammonia_h2_consumption_kg_h2_per_kg_nh3: float = 0.2
    ammonia_lifetime_years: int = 30
    annual_days: int = 360

    storage_investment_yuan_per_kwh: float = 1000.0
    storage_om_yuan_per_kwh: float = 0.01
    storage_lifetime_years: int = 15

    # Storage power-to-energy ratio.
    # 1.0 means 1C: a storage unit can be fully charged/discharged in one hour.
    # This is an explicit modelling assumption and can be tested in sensitivity analysis.
    storage_power_c_rate: float = 1.0

    charge_efficiency: float = 0.90
    discharge_efficiency: float = 0.90
    self_discharge_rate: float = 0.002

    # Optimization weights for off-grid operation.
    # First minimize unserved load, then maximize ammonia production.
    unserved_penalty_yuan_per_mwh: float = 1.0e7
    production_reward_yuan_per_unit_ratio: float = 1.0e5
    curtailment_penalty_yuan_per_mwh: float = 1.0


def total_nh3_power_mw(params: OffgridStorageParams) -> float:
    return params.alk_power_mw + params.pem_power_mw + params.ammonia_power_mw


def ammonia_capex_daily_yuan(params: OffgridStorageParams) -> float:
    ammonia_output_kg_per_day = params.plant_capacity_ton_per_day * 1000.0
    h2_demand_kg_per_day = (
        ammonia_output_kg_per_day * params.ammonia_h2_consumption_kg_h2_per_kg_nh3
    )
    h2_capacity_kg_per_hour = h2_demand_kg_per_day / 24.0

    investment_yuan = (
        params.ammonia_investment_yuan_per_kg_h2_capacity
        * h2_capacity_kg_per_hour
    )

    return investment_yuan / params.ammonia_lifetime_years / params.annual_days


def storage_capex_daily_yuan(
    storage_capacity_mwh: float,
    params: OffgridStorageParams,
) -> float:
    storage_capacity_kwh = storage_capacity_mwh * 1000.0
    investment_yuan = storage_capacity_kwh * params.storage_investment_yuan_per_kwh

    return investment_yuan / params.storage_lifetime_years / params.annual_days


def _green_indicators_offgrid(hourly: pd.DataFrame) -> dict:
    total_load_mwh = hourly["total_load_mw"].sum()
    renewable_generation_mwh = hourly["renewable_power_mw"].sum()
    curtailment_mwh = hourly["curtailment_mw"].sum()
    grid_export_mwh = 0.0
    grid_purchase_mwh = 0.0

    renewable_self_used_mwh = renewable_generation_mwh - grid_export_mwh - curtailment_mwh

    if renewable_generation_mwh > 0:
        renewable_self_use_ratio = renewable_self_used_mwh / renewable_generation_mwh
        renewable_export_ratio = grid_export_mwh / renewable_generation_mwh
    else:
        renewable_self_use_ratio = 0.0
        renewable_export_ratio = 0.0

    if total_load_mwh > 0:
        green_power_ratio = renewable_self_used_mwh / total_load_mwh
    else:
        green_power_ratio = 0.0

    pass_count = int(renewable_self_use_ratio >= 0.60) + int(
        green_power_ratio >= 0.30
    ) + int(renewable_export_ratio <= 0.20)

    if pass_count == 3:
        satisfaction_type = "全满足"
    elif pass_count == 0:
        satisfaction_type = "全不满足"
    else:
        satisfaction_type = "部分满足"

    return {
        "total_load_mwh": total_load_mwh,
        "renewable_generation_mwh": renewable_generation_mwh,
        "grid_purchase_mwh": grid_purchase_mwh,
        "grid_export_mwh": grid_export_mwh,
        "curtailment_mwh": curtailment_mwh,
        "renewable_self_used_mwh": renewable_self_used_mwh,
        "renewable_self_use_ratio": renewable_self_use_ratio,
        "green_power_ratio": green_power_ratio,
        "renewable_export_ratio": renewable_export_ratio,
        "renewable_self_use_pass": renewable_self_use_ratio >= 0.60,
        "green_power_pass": green_power_ratio >= 0.30,
        "renewable_export_pass": renewable_export_ratio <= 0.20,
        "pass_count": pass_count,
        "satisfaction_type": satisfaction_type,
    }


def _calculate_hourly_costs(
    hourly: pd.DataFrame,
    params: OffgridStorageParams,
    storage_capacity_mwh: float = 0.0,
) -> pd.DataFrame:
    hourly = hourly.copy()

    hourly["wind_generation_cost_yuan"] = (
        hourly["wind_power_mw"] * 1000.0 * params.wind_lcoe_yuan_per_kwh
    )
    hourly["pv_generation_cost_yuan"] = (
        hourly["pv_power_mw"] * 1000.0 * params.pv_lcoe_yuan_per_kwh
    )
    hourly["alk_om_cost_yuan"] = (
        hourly["alk_power_mw"] * 1000.0 * params.alk_om_yuan_per_kwh
    )
    hourly["pem_om_cost_yuan"] = (
        hourly["pem_power_mw"] * 1000.0 * params.pem_om_yuan_per_kwh
    )
    hourly["ammonia_om_cost_yuan"] = (
        hourly["ammonia_power_mw"] * 1000.0 * params.ammonia_om_yuan_per_kwh
    )

    if "storage_charge_mw" not in hourly.columns:
        hourly["storage_charge_mw"] = 0.0
    if "storage_discharge_mw" not in hourly.columns:
        hourly["storage_discharge_mw"] = 0.0

    hourly["storage_om_cost_yuan"] = (
        (hourly["storage_charge_mw"] + hourly["storage_discharge_mw"])
        * 1000.0
        * params.storage_om_yuan_per_kwh
    )

    hourly["hourly_net_cost_yuan"] = (
        hourly["wind_generation_cost_yuan"]
        + hourly["pv_generation_cost_yuan"]
        + hourly["alk_om_cost_yuan"]
        + hourly["pem_om_cost_yuan"]
        + hourly["ammonia_om_cost_yuan"]
        + hourly["storage_om_cost_yuan"]
    )

    return hourly


def _build_offgrid_summary(
    hourly: pd.DataFrame,
    params: OffgridStorageParams,
    storage_capacity_mwh: float,
    mode: str,
) -> dict:
    hourly = _calculate_hourly_costs(hourly, params, storage_capacity_mwh)

    indicators = _green_indicators_offgrid(hourly)

    ammonia_capex = ammonia_capex_daily_yuan(params)
    storage_capex = storage_capex_daily_yuan(storage_capacity_mwh, params)

    total_cost = hourly["hourly_net_cost_yuan"].sum() + ammonia_capex + storage_capex
    total_ammonia_output = hourly["hourly_ammonia_output_ton"].sum()

    ton_cost = total_cost / total_ammonia_output if total_ammonia_output > 1e-8 else np.inf

    total_load_mwh = hourly["total_load_mw"].sum()
    unserved_mwh = hourly["unserved_load_mw"].sum()

    energy_self_sufficiency_ratio = (
        (total_load_mwh - unserved_mwh) / total_load_mwh
        if total_load_mwh > 1e-8
        else 0.0
    )

    renewable_generation_mwh = hourly["renewable_power_mw"].sum()
    curtailment_mwh = hourly["curtailment_mw"].sum()

    renewable_utilization_ratio = (
        (renewable_generation_mwh - curtailment_mwh) / renewable_generation_mwh
        if renewable_generation_mwh > 1e-8
        else 0.0
    )

    scenario_id = hourly["scenario_id"].iloc[0]
    wind_scenario = hourly["wind_scenario"].iloc[0]
    pv_scenario = hourly["pv_scenario"].iloc[0]

    return {
        "mode": mode,
        "scenario_id": scenario_id,
        "wind_scenario": wind_scenario,
        "pv_scenario": pv_scenario,
        "storage_capacity_mwh": storage_capacity_mwh,
        "total_cost_yuan": total_cost,
        "ton_cost_yuan_per_ton": ton_cost,
        "total_ammonia_output_ton": total_ammonia_output,
        "capacity_utilization_rate": total_ammonia_output / params.plant_capacity_ton_per_day,
        "on_hours": int(hourly["on_status"].sum()),
        "avg_power_ratio": hourly["power_ratio"].mean(),
        "mean_running_power_ratio": (
            hourly.loc[hourly["on_status"] == 1, "power_ratio"].mean()
            if int(hourly["on_status"].sum()) > 0
            else 0.0
        ),
        "base_load_mwh": hourly["base_load_mw"].sum(),
        "hydrogen_ammonia_load_mwh": hourly["hydrogen_ammonia_load_mw"].sum(),
        "unserved_load_mwh": unserved_mwh,
        "energy_self_sufficiency_ratio": energy_self_sufficiency_ratio,
        "renewable_utilization_ratio": renewable_utilization_ratio,
        "ammonia_capex_daily_yuan": ammonia_capex,
        "storage_capex_daily_yuan": storage_capex,
        "wind_generation_cost_yuan": hourly["wind_generation_cost_yuan"].sum(),
        "pv_generation_cost_yuan": hourly["pv_generation_cost_yuan"].sum(),
        "alk_om_cost_yuan": hourly["alk_om_cost_yuan"].sum(),
        "pem_om_cost_yuan": hourly["pem_om_cost_yuan"].sum(),
        "ammonia_om_cost_yuan": hourly["ammonia_om_cost_yuan"].sum(),
        "storage_om_cost_yuan": hourly["storage_om_cost_yuan"].sum(),
        "storage_charge_mwh": hourly["storage_charge_mw"].sum(),
        "storage_discharge_mwh": hourly["storage_discharge_mw"].sum(),
        "soc_max_mwh": hourly["soc_mwh"].max() if "soc_mwh" in hourly.columns else 0.0,
        "soc_min_mwh": hourly["soc_mwh"].min() if "soc_mwh" in hourly.columns else 0.0,
        **indicators,
    }


def run_offgrid_no_storage(
    profile: pd.DataFrame,
    params: OffgridStorageParams | None = None,
) -> tuple[pd.DataFrame, dict]:
    """
    Q4(1): Off-grid operation without storage.

    Rule:
    1. Renewable generation first serves base load.
    2. Remaining renewable power is used for ammonia production if it can meet
       the 10% minimum stable load.
    3. Remaining surplus is curtailed.
    4. If renewable power is below base load, unserved load is recorded.
    """
    if params is None:
        params = OffgridStorageParams()

    profile = profile.copy().reset_index(drop=True)
    pmax = total_nh3_power_mw(params)
    pmin = params.min_running_power_ratio * pmax

    rows = []

    for _, row in profile.iterrows():
        base_load = float(row["base_load_mw"])
        renewable = float(row["renewable_power_mw"])
        surplus = renewable - base_load

        if surplus < 0:
            power_ratio = 0.0
            unserved = -surplus
            curtailment = 0.0
        elif surplus < pmin:
            power_ratio = 0.0
            unserved = 0.0
            curtailment = surplus
        elif surplus < pmax:
            power_ratio = surplus / pmax
            unserved = 0.0
            curtailment = 0.0
        else:
            power_ratio = 1.0
            unserved = 0.0
            curtailment = surplus - pmax

        new_row = row.to_dict()
        new_row["power_ratio"] = power_ratio
        new_row["on_status"] = int(power_ratio > 1e-8)
        new_row["alk_power_mw"] = params.alk_power_mw * power_ratio
        new_row["pem_power_mw"] = params.pem_power_mw * power_ratio
        new_row["ammonia_power_mw"] = params.ammonia_power_mw * power_ratio
        new_row["hydrogen_ammonia_load_mw"] = pmax * power_ratio
        new_row["total_load_mw"] = base_load + pmax * power_ratio
        new_row["curtailment_mw"] = curtailment
        new_row["unserved_load_mw"] = unserved
        new_row["storage_charge_mw"] = 0.0
        new_row["storage_discharge_mw"] = 0.0
        new_row["soc_mwh"] = 0.0
        new_row["hourly_ammonia_output_ton"] = (
            params.ammonia_output_ton_per_hour * power_ratio
        )
        rows.append(new_row)

    hourly = pd.DataFrame(rows)
    hourly = _calculate_hourly_costs(hourly, params, storage_capacity_mwh=0.0)
    summary = _build_offgrid_summary(
        hourly=hourly,
        params=params,
        storage_capacity_mwh=0.0,
        mode="offgrid_no_storage",
    )

    return hourly, summary


def _storage_variable_slices(n_hours: int = 24) -> dict[str, slice]:
    start = 0
    slices: dict[str, slice] = {}

    for name, length in [
        ("u", n_hours),
        ("y", n_hours),
        ("ch", n_hours),
        ("dis", n_hours),
        ("soc", n_hours + 1),
        ("curt", n_hours),
        ("unserved", n_hours),
        ("b", n_hours),
    ]:
        slices[name] = slice(start, start + length)
        start += length

    return slices


def solve_offgrid_storage_dispatch(
    profile: pd.DataFrame,
    storage_capacity_mwh: float,
    params: OffgridStorageParams | None = None,
) -> tuple[pd.DataFrame, dict]:
    """
    Q4(2): Off-grid dispatch with fixed storage capacity.

    Objective hierarchy implemented by weighted linear objective:
    1. Minimize unserved load.
    2. Maximize ammonia production.
    3. Reduce curtailment and operating cost.
    """
    if params is None:
        params = OffgridStorageParams()

    profile = profile.copy().reset_index(drop=True)

    n_hours = 24
    pmax = total_nh3_power_mw(params)
    storage_power_limit_mw = storage_capacity_mwh * params.storage_power_c_rate
    s = _storage_variable_slices(n_hours)
    n_vars = s["b"].stop

    c = np.zeros(n_vars)

    om_cost_per_unit_ratio = 1000.0 * (
        params.alk_power_mw * params.alk_om_yuan_per_kwh
        + params.pem_power_mw * params.pem_om_yuan_per_kwh
        + params.ammonia_power_mw * params.ammonia_om_yuan_per_kwh
    )

    storage_om_cost_per_mw = 1000.0 * params.storage_om_yuan_per_kwh

    c[s["u"]] = om_cost_per_unit_ratio - params.production_reward_yuan_per_unit_ratio
    c[s["ch"]] = storage_om_cost_per_mw
    c[s["dis"]] = storage_om_cost_per_mw
    c[s["curt"]] = params.curtailment_penalty_yuan_per_mwh
    c[s["unserved"]] = params.unserved_penalty_yuan_per_mwh

    constraints_rows = []
    lbs = []
    ubs = []

    def add_constraint(coeffs: dict[int, float], lb: float, ub: float):
        row = np.zeros(n_vars)
        for idx, val in coeffs.items():
            row[idx] = val
        constraints_rows.append(row)
        lbs.append(lb)
        ubs.append(ub)

    # u/y min and max constraints
    for t in range(n_hours):
        u_idx = s["u"].start + t
        y_idx = s["y"].start + t

        add_constraint(
            {u_idx: 1.0, y_idx: -params.min_running_power_ratio},
            0.0,
            np.inf,
        )
        add_constraint(
            {u_idx: 1.0, y_idx: -1.0},
            -np.inf,
            0.0,
        )

    # Power balance
    for t in range(n_hours):
        u_idx = s["u"].start + t
        ch_idx = s["ch"].start + t
        dis_idx = s["dis"].start + t
        curt_idx = s["curt"].start + t
        unserved_idx = s["unserved"].start + t

        base_load = float(profile.loc[t, "base_load_mw"])
        renewable = float(profile.loc[t, "renewable_power_mw"])

        # P_RE + P_dis + P_unserved
        # =
        # P_base + P_NH3_max*u + P_ch + P_curt
        #
        # -P_NH3_max*u - P_ch + P_dis - P_curt + P_unserved
        # =
        # P_base - P_RE
        add_constraint(
            {
                u_idx: -pmax,
                ch_idx: -1.0,
                dis_idx: 1.0,
                curt_idx: -1.0,
                unserved_idx: 1.0,
            },
            base_load - renewable,
            base_load - renewable,
        )

    # SOC dynamics
    for t in range(n_hours):
        soc_t = s["soc"].start + t
        soc_next = s["soc"].start + t + 1
        ch_idx = s["ch"].start + t
        dis_idx = s["dis"].start + t

        # SOC_{t+1} = (1-sigma)SOC_t + eta_ch*ch - dis/eta_dis
        add_constraint(
            {
                soc_next: 1.0,
                soc_t: -(1.0 - params.self_discharge_rate),
                ch_idx: -params.charge_efficiency,
                dis_idx: 1.0 / params.discharge_efficiency,
            },
            0.0,
            0.0,
        )

    # Cyclic SOC
    add_constraint(
        {
            s["soc"].start + n_hours: 1.0,
            s["soc"].start: -1.0,
        },
        0.0,
        0.0,
    )

    # Prevent simultaneous charge and discharge
    for t in range(n_hours):
        ch_idx = s["ch"].start + t
        dis_idx = s["dis"].start + t
        b_idx = s["b"].start + t

        # ch <= E*b
        add_constraint(
            {
                ch_idx: 1.0,
                b_idx: -storage_capacity_mwh,
            },
            -np.inf,
            0.0,
        )

        # dis <= E*(1-b) -> dis + E*b <= E
        add_constraint(
            {
                dis_idx: 1.0,
                b_idx: storage_capacity_mwh,
            },
            -np.inf,
            storage_capacity_mwh,
        )

    A = np.vstack(constraints_rows)
    lb = np.array(lbs)
    ub = np.array(ubs)

    lower_bounds = np.zeros(n_vars)
    upper_bounds = np.zeros(n_vars)

    upper_bounds[s["u"]] = 1.0
    upper_bounds[s["y"]] = 1.0
    upper_bounds[s["ch"]] = storage_power_limit_mw
    upper_bounds[s["dis"]] = storage_power_limit_mw
    upper_bounds[s["soc"]] = storage_capacity_mwh
    upper_bounds[s["curt"]] = 300.0
    upper_bounds[s["unserved"]] = 300.0
    upper_bounds[s["b"]] = 1.0

    integrality = np.zeros(n_vars, dtype=int)
    integrality[s["y"]] = 1
    integrality[s["b"]] = 1

    result = milp(
        c=c,
        integrality=integrality,
        bounds=Bounds(lower_bounds, upper_bounds),
        constraints=LinearConstraint(A, lb, ub),
        options={
            "time_limit": 90,
            "mip_rel_gap": 1e-8,
            "disp": False,
        },
    )

    if not result.success:
        raise RuntimeError(
            f"Q4 storage MILP failed for scenario={profile['scenario_id'].iloc[0]}, "
            f"capacity={storage_capacity_mwh} MWh. Message: {result.message}"
        )

    x = result.x

    u = np.clip(x[s["u"]], 0.0, 1.0)
    y = np.rint(np.clip(x[s["y"]], 0.0, 1.0)).astype(int)
    ch = np.clip(x[s["ch"]], 0.0, None)
    dis = np.clip(x[s["dis"]], 0.0, None)
    soc = np.clip(x[s["soc"]][1:], 0.0, None)
    curt = np.clip(x[s["curt"]], 0.0, None)
    unserved = np.clip(x[s["unserved"]], 0.0, None)

    for arr in [u, ch, dis, soc, curt, unserved]:
        arr[np.abs(arr) < 1e-8] = 0.0

    hourly = profile.copy()
    hourly["storage_capacity_mwh"] = storage_capacity_mwh
    hourly["power_ratio"] = u
    hourly["on_status"] = y
    hourly["alk_power_mw"] = params.alk_power_mw * hourly["power_ratio"]
    hourly["pem_power_mw"] = params.pem_power_mw * hourly["power_ratio"]
    hourly["ammonia_power_mw"] = params.ammonia_power_mw * hourly["power_ratio"]
    hourly["hydrogen_ammonia_load_mw"] = pmax * hourly["power_ratio"]
    hourly["total_load_mw"] = (
        hourly["base_load_mw"] + hourly["hydrogen_ammonia_load_mw"]
    )
    hourly["storage_charge_mw"] = ch
    hourly["storage_discharge_mw"] = dis
    hourly["soc_mwh"] = soc
    hourly["curtailment_mw"] = curt
    hourly["unserved_load_mw"] = unserved
    hourly["hourly_ammonia_output_ton"] = (
        hourly["power_ratio"] * params.ammonia_output_ton_per_hour
    )

    hourly = _calculate_hourly_costs(hourly, params, storage_capacity_mwh)
    summary = _build_offgrid_summary(
        hourly=hourly,
        params=params,
        storage_capacity_mwh=storage_capacity_mwh,
        mode="offgrid_with_storage",
    )

    return hourly, summary


def run_offgrid_no_storage_for_scenarios(
    scenario_profiles: list[dict],
    params: OffgridStorageParams | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if params is None:
        params = OffgridStorageParams()

    hourly_list = []
    summary_list = []

    for scenario in scenario_profiles:
        hourly, summary = run_offgrid_no_storage(
            profile=scenario["profile"],
            params=params,
        )
        hourly_list.append(hourly)
        summary_list.append(summary)

    return pd.concat(hourly_list, ignore_index=True), pd.DataFrame(summary_list)


def scan_storage_capacity(
    profile: pd.DataFrame,
    params: OffgridStorageParams | None = None,
    step_mwh: float = 20.0,
    max_capacity_mwh: float | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    if params is None:
        params = OffgridStorageParams()

    no_storage_hourly, no_storage_summary = run_offgrid_no_storage(profile, params)

    if max_capacity_mwh is None:
        max_curtailment = no_storage_summary["curtailment_mwh"]
        max_capacity_mwh = max(20.0, math.ceil(1.2 * max_curtailment / step_mwh) * step_mwh)

    capacities = np.arange(0.0, max_capacity_mwh + 0.5 * step_mwh, step_mwh)

    hourly_list = []
    summary_list = []

    for cap in capacities:
        hourly, summary = solve_offgrid_storage_dispatch(
            profile=profile,
            storage_capacity_mwh=float(cap),
            params=params,
        )
        hourly_list.append(hourly)
        summary_list.append(summary)

    scan_hourly_df = pd.concat(hourly_list, ignore_index=True)
    scan_summary_df = pd.DataFrame(summary_list)

    valid = scan_summary_df[
        np.isfinite(scan_summary_df["ton_cost_yuan_per_ton"])
        & (scan_summary_df["total_ammonia_output_ton"] > 1e-8)
    ].copy()

    # Q4 storage sizing rule:
    # The pure minimum-cost solution may choose 0 MWh because storage investment is expensive.
    # However, Q4 explicitly asks for storage configuration. Therefore, we use a
    # technical-economic sizing rule: choose the minimum storage capacity that reaches
    # 99% of the maximum achievable daily ammonia production in the maximum-curtailment
    # scenario. This captures the saturation point before marginal benefits become small.
    max_production = valid["total_ammonia_output_ton"].max()
    production_threshold = 0.99 * max_production

    candidates = valid[valid["total_ammonia_output_ton"] >= production_threshold].copy()

    if candidates.empty:
        best_idx = valid["total_ammonia_output_ton"].idxmax()
    else:
        best_idx = candidates["storage_capacity_mwh"].idxmin()

    scan_summary_df["is_recommended_storage"] = False
    scan_summary_df.loc[best_idx, "is_recommended_storage"] = True
    scan_summary_df["recommendation_rule"] = (
        "minimum capacity reaching 99% of maximum daily ammonia production"
    )

    best_summary = scan_summary_df.loc[best_idx].to_dict()

    return scan_hourly_df, scan_summary_df, best_summary


def run_offgrid_storage_for_scenarios(
    scenario_profiles: list[dict],
    storage_capacity_mwh: float,
    params: OffgridStorageParams | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if params is None:
        params = OffgridStorageParams()

    hourly_list = []
    summary_list = []

    for scenario in scenario_profiles:
        hourly, summary = solve_offgrid_storage_dispatch(
            profile=scenario["profile"],
            storage_capacity_mwh=storage_capacity_mwh,
            params=params,
        )
        hourly_list.append(hourly)
        summary_list.append(summary)

    return pd.concat(hourly_list, ignore_index=True), pd.DataFrame(summary_list)


def summarize_offgrid_annual(
    summary_df: pd.DataFrame,
    scenario_days: int = 15,
    mode: str = "offgrid",
) -> pd.DataFrame:
    annual_total_cost = (summary_df["total_cost_yuan"] * scenario_days).sum()
    annual_total_production = (
        summary_df["total_ammonia_output_ton"] * scenario_days
    ).sum()

    annual_ton_cost = (
        annual_total_cost / annual_total_production
        if annual_total_production > 1e-8
        else np.inf
    )

    annual_capacity_utilization = annual_total_production / (72.0 * 360.0)

    annual_total_curtailment_mwh = (
        summary_df["curtailment_mwh"] * scenario_days
    ).sum()

    annual_total_unserved_load_mwh = (
        summary_df["unserved_load_mwh"] * scenario_days
    ).sum()

    annual_total_renewable_generation_mwh = (
        summary_df["renewable_generation_mwh"] * scenario_days
    ).sum()

    annual_total_load_mwh = (
        summary_df["total_load_mwh"] * scenario_days
    ).sum()

    annual_renewable_utilization_ratio = (
        (annual_total_renewable_generation_mwh - annual_total_curtailment_mwh)
        / annual_total_renewable_generation_mwh
        if annual_total_renewable_generation_mwh > 1e-8
        else 0.0
    )

    annual_energy_self_sufficiency_ratio = (
        (annual_total_load_mwh - annual_total_unserved_load_mwh)
        / annual_total_load_mwh
        if annual_total_load_mwh > 1e-8
        else 0.0
    )

    row = {
        "mode": mode,
        "scenario_count": len(summary_df),
        "annual_days": len(summary_df) * scenario_days,
        "annual_total_cost_yuan": annual_total_cost,
        "annual_total_production_ton": annual_total_production,
        "annual_avg_ton_cost_yuan_per_ton": annual_ton_cost,
        "annual_capacity_utilization_rate": annual_capacity_utilization,
        "annual_total_curtailment_mwh": annual_total_curtailment_mwh,
        "annual_total_unserved_load_mwh": annual_total_unserved_load_mwh,
        "annual_total_renewable_generation_mwh": annual_total_renewable_generation_mwh,
        "annual_total_load_mwh": annual_total_load_mwh,
        "annual_renewable_utilization_ratio": annual_renewable_utilization_ratio,
        "annual_energy_self_sufficiency_ratio": annual_energy_self_sufficiency_ratio,
        "mean_daily_production_ton": summary_df["total_ammonia_output_ton"].mean(),
        "mean_ton_cost_yuan_per_ton": summary_df["ton_cost_yuan_per_ton"].replace(np.inf, np.nan).mean(),
        "mean_curtailment_mwh": summary_df["curtailment_mwh"].mean(),
        "mean_unserved_load_mwh": summary_df["unserved_load_mwh"].mean(),
        "mean_renewable_utilization_ratio": summary_df["renewable_utilization_ratio"].mean(),
        "mean_energy_self_sufficiency_ratio": summary_df["energy_self_sufficiency_ratio"].mean(),
        "mean_storage_charge_mwh": summary_df["storage_charge_mwh"].mean(),
        "mean_storage_discharge_mwh": summary_df["storage_discharge_mwh"].mean(),
        "all_satisfied_days": int((summary_df["satisfaction_type"] == "全满足").sum()) * scenario_days,
        "partially_satisfied_days": int((summary_df["satisfaction_type"] == "部分满足").sum()) * scenario_days,
        "none_satisfied_days": int((summary_df["satisfaction_type"] == "全不满足").sum()) * scenario_days,
    }

    return pd.DataFrame([row])

def run_grid_connected_same_production_comparison(
    scenario_profiles: list[dict],
    offgrid_storage_summary_df: pd.DataFrame,
    scenario_days: int = 15,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Q4(3): Compare off-grid storage mode with grid-connected mode under the
    same scenario-level ammonia production demand.
    """
    q3_params = ContinuousDispatchParams()

    grid_hourly_list = []
    grid_summary_list = []

    summary_map = {
        row.scenario_id: row.total_ammonia_output_ton
        for row in offgrid_storage_summary_df.itertuples()
    }

    for scenario in scenario_profiles:
        scenario_id = scenario["scenario_id"]
        target_production = float(summary_map[scenario_id])

        if target_production < 1e-8:
            continue

        hourly, summary = solve_continuous_dispatch(
            profile=scenario["profile"],
            production_ton=target_production,
            params=q3_params,
        )
        summary["mode"] = "grid_connected_same_production"
        summary["target_production_ton"] = target_production

        grid_hourly_list.append(hourly)
        grid_summary_list.append(summary)

    grid_hourly_df = pd.concat(grid_hourly_list, ignore_index=True)
    grid_summary_df = pd.DataFrame(grid_summary_list)

    offgrid_annual = summarize_offgrid_annual(
        offgrid_storage_summary_df,
        scenario_days=scenario_days,
        mode="offgrid_with_storage",
    )
    grid_annual = summarize_grid_same_production_annual(
        grid_summary_df,
        scenario_days=scenario_days,
        mode="grid_connected_same_production",
    )

    comparison = pd.concat([offgrid_annual, grid_annual], ignore_index=True)

    return grid_hourly_df, grid_summary_df, comparison


def summarize_grid_same_production_annual(
    summary_df: pd.DataFrame,
    scenario_days: int = 15,
    mode: str = "grid_connected_same_production",
) -> pd.DataFrame:
    annual_total_cost = (summary_df["total_cost_yuan"] * scenario_days).sum()
    annual_total_production = (summary_df["production_ton"] * scenario_days).sum()

    annual_ton_cost = annual_total_cost / annual_total_production

    row = {
        "mode": mode,
        "scenario_count": len(summary_df),
        "annual_days": len(summary_df) * scenario_days,
        "annual_total_cost_yuan": annual_total_cost,
        "annual_total_production_ton": annual_total_production,
        "annual_avg_ton_cost_yuan_per_ton": annual_ton_cost,
        "annual_capacity_utilization_rate": annual_total_production / (72.0 * 360.0),
        "mean_daily_production_ton": summary_df["production_ton"].mean(),
        "mean_ton_cost_yuan_per_ton": summary_df["ton_cost_yuan_per_ton"].mean(),
        "mean_curtailment_mwh": 0.0,
        "mean_unserved_load_mwh": 0.0,
        "mean_renewable_utilization_ratio": np.nan,
        "mean_energy_self_sufficiency_ratio": np.nan,
        "mean_storage_charge_mwh": 0.0,
        "mean_storage_discharge_mwh": 0.0,
        "all_satisfied_days": int((summary_df["satisfaction_type"] == "全满足").sum()) * scenario_days,
        "partially_satisfied_days": int((summary_df["satisfaction_type"] == "部分满足").sum()) * scenario_days,
        "none_satisfied_days": int((summary_df["satisfaction_type"] == "全不满足").sum()) * scenario_days,
    }

    return pd.DataFrame([row])
