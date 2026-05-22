from __future__ import annotations

from dataclasses import dataclass
import numpy as np
import pandas as pd

from scipy.optimize import Bounds, LinearConstraint, milp

from dgcup.core.cost import tou_price_by_hour
from dgcup.core.indicators import calculate_green_indicators


@dataclass(frozen=True)
class ContinuousDispatchParams:
    """Parameters for Q3 continuous hydrogen-ammonia dispatch."""

    plant_capacity_ton_per_day: float = 72.0
    ammonia_output_ton_per_hour: float = 3.0

    max_power_ratio: float = 1.0
    min_running_power_ratio: float = 0.10

    alk_power_mw: float = 20.0
    pem_power_mw: float = 20.0
    ammonia_power_mw: float = 1.5

    wind_lcoe_yuan_per_kwh: float = 0.15
    pv_lcoe_yuan_per_kwh: float = 0.12

    alk_om_yuan_per_kwh: float = 0.10
    pem_om_yuan_per_kwh: float = 0.15
    ammonia_om_yuan_per_kwh: float = 0.002

    export_price_yuan_per_kwh: float = 0.3779

    include_ammonia_capex: bool = True
    ammonia_investment_yuan_per_kg_h2_capacity: float = 60000.0
    ammonia_h2_consumption_kg_h2_per_kg_nh3: float = 0.2
    ammonia_lifetime_years: int = 30
    annual_days: int = 360

    big_m_mw: float = 150.0


def classify_satisfaction(pass_count: int) -> str:
    if pass_count == 3:
        return "全满足"
    if pass_count == 0:
        return "全不满足"
    return "部分满足"


def ammonia_capex_daily_yuan(params: ContinuousDispatchParams) -> float:
    """
    Calculate daily fixed depreciation cost of the ammonia synthesis device.

    In Q3, the installed capacity is still 72 t/day, so fixed depreciation is
    calculated according to installed capacity rather than actual production.
    """
    if not params.include_ammonia_capex:
        return 0.0

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


def _variable_slices(n_hours: int = 24) -> dict[str, slice]:
    return {
        "u": slice(0, n_hours),
        "y": slice(n_hours, 2 * n_hours),
        "z": slice(2 * n_hours, 3 * n_hours),
        "buy": slice(3 * n_hours, 4 * n_hours),
        "sell": slice(4 * n_hours, 5 * n_hours),
    }


def _build_milp(
    profile: pd.DataFrame,
    production_ton: float,
    params: ContinuousDispatchParams,
):
    """
    Build MILP matrices.

    Variables:
    u_t    continuous, normalized hydrogen-ammonia power ratio
    y_t    binary, whether hydrogen-ammonia system is on
    z_t    binary, grid interaction mode, 1 for purchase, 0 for export
    buy_t  continuous, grid purchase power
    sell_t continuous, grid export power
    """
    n_hours = 24
    s = _variable_slices(n_hours)
    n_vars = 5 * n_hours

    total_nh3_power_mw = (
        params.alk_power_mw + params.pem_power_mw + params.ammonia_power_mw
    )

    # Objective coefficients
    c = np.zeros(n_vars)

    om_cost_per_unit_ratio = 1000.0 * (
        params.alk_power_mw * params.alk_om_yuan_per_kwh
        + params.pem_power_mw * params.pem_om_yuan_per_kwh
        + params.ammonia_power_mw * params.ammonia_om_yuan_per_kwh
    )

    for t in range(n_hours):
        hour = int(profile.loc[t, "hour"])
        c[s["u"].start + t] = om_cost_per_unit_ratio
        c[s["buy"].start + t] = 1000.0 * tou_price_by_hour(hour)
        c[s["sell"].start + t] = -1000.0 * params.export_price_yuan_per_kwh

    # Constraints:
    # 1 production equality
    # 2*n_hours min/max running constraints
    # n_hours power-balance constraints
    # 2*n_hours anti-simultaneous buy/export constraints
    n_constraints = 1 + 2 * n_hours + n_hours + 2 * n_hours

    A = np.zeros((n_constraints, n_vars))
    lb = np.full(n_constraints, -np.inf)
    ub = np.full(n_constraints, np.inf)

    row = 0

    # Production target: sum u_t = Q / 3
    A[row, s["u"]] = 1.0
    lb[row] = production_ton / params.ammonia_output_ton_per_hour
    ub[row] = production_ton / params.ammonia_output_ton_per_hour
    row += 1

    for t in range(n_hours):
        u_idx = s["u"].start + t
        y_idx = s["y"].start + t

        # u_t >= min_ratio * y_t  -> u_t - min_ratio*y_t >= 0
        A[row, u_idx] = 1.0
        A[row, y_idx] = -params.min_running_power_ratio
        lb[row] = 0.0
        ub[row] = np.inf
        row += 1

        # u_t <= y_t -> u_t - y_t <= 0
        A[row, u_idx] = 1.0
        A[row, y_idx] = -1.0
        lb[row] = -np.inf
        ub[row] = 0.0
        row += 1

    for t in range(n_hours):
        u_idx = s["u"].start + t
        buy_idx = s["buy"].start + t
        sell_idx = s["sell"].start + t

        base_load = float(profile.loc[t, "base_load_mw"])
        renewable = float(profile.loc[t, "renewable_power_mw"])

        # P_RE + P_buy = P_base + P_NH3_max*u + P_sell
        # -P_NH3_max*u + P_buy - P_sell = P_base - P_RE
        A[row, u_idx] = -total_nh3_power_mw
        A[row, buy_idx] = 1.0
        A[row, sell_idx] = -1.0
        lb[row] = base_load - renewable
        ub[row] = base_load - renewable
        row += 1

    for t in range(n_hours):
        z_idx = s["z"].start + t
        buy_idx = s["buy"].start + t

        # buy_t <= M z_t
        A[row, buy_idx] = 1.0
        A[row, z_idx] = -params.big_m_mw
        lb[row] = -np.inf
        ub[row] = 0.0
        row += 1

        sell_idx = s["sell"].start + t

        # sell_t <= M(1-z_t) -> sell_t + M z_t <= M
        A[row, sell_idx] = 1.0
        A[row, z_idx] = params.big_m_mw
        lb[row] = -np.inf
        ub[row] = params.big_m_mw
        row += 1

    lower_bounds = np.zeros(n_vars)
    upper_bounds = np.zeros(n_vars)

    upper_bounds[s["u"]] = 1.0
    upper_bounds[s["y"]] = 1.0
    upper_bounds[s["z"]] = 1.0
    upper_bounds[s["buy"]] = params.big_m_mw
    upper_bounds[s["sell"]] = params.big_m_mw

    bounds = Bounds(lower_bounds, upper_bounds)

    integrality = np.zeros(n_vars, dtype=int)
    integrality[s["y"]] = 1
    integrality[s["z"]] = 1

    constraints = LinearConstraint(A, lb, ub)

    return c, bounds, constraints, integrality


def solve_continuous_dispatch(
    profile: pd.DataFrame,
    production_ton: float,
    params: ContinuousDispatchParams | None = None,
) -> tuple[pd.DataFrame, dict]:
    """
    Solve Q3 continuous dispatch for one scenario and one production target.
    """
    if params is None:
        params = ContinuousDispatchParams()

    profile = profile.copy().reset_index(drop=True)

    c, bounds, constraints, integrality = _build_milp(
        profile=profile,
        production_ton=production_ton,
        params=params,
    )

    result = milp(
        c=c,
        integrality=integrality,
        bounds=bounds,
        constraints=constraints,
        options={
            "time_limit": 60,
            "mip_rel_gap": 1e-8,
            "disp": False,
        },
    )

    if not result.success:
        raise RuntimeError(
            f"Q3 MILP failed for scenario={profile['scenario_id'].iloc[0]}, "
            f"production={production_ton}. Message: {result.message}"
        )

    n_hours = 24
    s = _variable_slices(n_hours)
    x = result.x

    u = np.clip(x[s["u"]], 0.0, 1.0)
    y = np.rint(np.clip(x[s["y"]], 0.0, 1.0)).astype(int)
    z = np.rint(np.clip(x[s["z"]], 0.0, 1.0)).astype(int)
    buy = np.clip(x[s["buy"]], 0.0, None)
    sell = np.clip(x[s["sell"]], 0.0, None)

    # Clean tiny numerical noise
    u[np.abs(u) < 1e-8] = 0.0
    buy[np.abs(buy) < 1e-8] = 0.0
    sell[np.abs(sell) < 1e-8] = 0.0

    hourly = profile.copy()
    hourly["production_ton"] = production_ton
    hourly["power_ratio"] = u
    hourly["on_status"] = y
    hourly["grid_mode_purchase"] = z

    hourly["alk_power_mw"] = params.alk_power_mw * hourly["power_ratio"]
    hourly["pem_power_mw"] = params.pem_power_mw * hourly["power_ratio"]
    hourly["ammonia_power_mw"] = params.ammonia_power_mw * hourly["power_ratio"]

    hourly["hydrogen_ammonia_load_mw"] = (
        hourly["alk_power_mw"]
        + hourly["pem_power_mw"]
        + hourly["ammonia_power_mw"]
    )

    hourly["total_load_mw"] = (
        hourly["base_load_mw"] + hourly["hydrogen_ammonia_load_mw"]
    )

    hourly["grid_purchase_mw"] = buy
    hourly["grid_export_mw"] = sell

    hourly["renewable_self_used_mw"] = (
        hourly["renewable_power_mw"] - hourly["grid_export_mw"]
    ).clip(lower=0)

    hourly["hourly_ammonia_output_ton"] = (
        hourly["power_ratio"] * params.ammonia_output_ton_per_hour
    )

    hourly["tou_price_yuan_per_kwh"] = hourly["hour"].map(tou_price_by_hour)

    hourly["grid_purchase_cost_yuan"] = (
        hourly["grid_purchase_mw"] * 1000.0 * hourly["tou_price_yuan_per_kwh"]
    )

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

    hourly["grid_export_revenue_yuan"] = (
        hourly["grid_export_mw"] * 1000.0 * params.export_price_yuan_per_kwh
    )

    hourly["hourly_net_cost_yuan"] = (
        hourly["grid_purchase_cost_yuan"]
        + hourly["wind_generation_cost_yuan"]
        + hourly["pv_generation_cost_yuan"]
        + hourly["alk_om_cost_yuan"]
        + hourly["pem_om_cost_yuan"]
        + hourly["ammonia_om_cost_yuan"]
        - hourly["grid_export_revenue_yuan"]
    )

    summary = build_q3_summary(hourly, production_ton, params)

    return hourly, summary


def build_q3_summary(
    hourly: pd.DataFrame,
    production_ton: float,
    params: ContinuousDispatchParams,
) -> dict:
    indicators = calculate_green_indicators(hourly)

    capex_daily = ammonia_capex_daily_yuan(params)

    total_cost = hourly["hourly_net_cost_yuan"].sum() + capex_daily
    ton_cost = total_cost / production_ton

    pass_count = int(indicators["renewable_self_use_pass"]) + int(
        indicators["green_power_pass"]
    ) + int(indicators["renewable_export_pass"])

    running = hourly[hourly["on_status"] == 1]

    if len(running) > 0:
        mean_running_power_ratio = running["power_ratio"].mean()
        min_running_power_ratio = running["power_ratio"].min()
        max_running_power_ratio = running["power_ratio"].max()
    else:
        mean_running_power_ratio = 0.0
        min_running_power_ratio = 0.0
        max_running_power_ratio = 0.0

    scenario_id = hourly["scenario_id"].iloc[0]
    wind_scenario = hourly["wind_scenario"].iloc[0]
    pv_scenario = hourly["pv_scenario"].iloc[0]

    selected_hours = hourly.loc[hourly["on_status"] == 1, "hour"].astype(int).tolist()
    selected_times = hourly.loc[hourly["on_status"] == 1, "time"].astype(str).tolist()

    return {
        "scenario_id": scenario_id,
        "wind_scenario": wind_scenario,
        "pv_scenario": pv_scenario,
        "production_ton": production_ton,
        "total_cost_yuan": total_cost,
        "ton_cost_yuan_per_ton": ton_cost,
        "grid_purchase_cost_yuan": hourly["grid_purchase_cost_yuan"].sum(),
        "wind_generation_cost_yuan": hourly["wind_generation_cost_yuan"].sum(),
        "pv_generation_cost_yuan": hourly["pv_generation_cost_yuan"].sum(),
        "alk_om_cost_yuan": hourly["alk_om_cost_yuan"].sum(),
        "pem_om_cost_yuan": hourly["pem_om_cost_yuan"].sum(),
        "ammonia_om_cost_yuan": hourly["ammonia_om_cost_yuan"].sum(),
        "ammonia_capex_daily_yuan": capex_daily,
        "grid_export_revenue_yuan": hourly["grid_export_revenue_yuan"].sum(),
        "on_hours": int(hourly["on_status"].sum()),
        "selected_hours": ",".join(str(h) for h in selected_hours),
        "selected_times": ";".join(selected_times),
        "avg_power_ratio": hourly["power_ratio"].mean(),
        "mean_running_power_ratio": mean_running_power_ratio,
        "min_running_power_ratio": min_running_power_ratio,
        "max_running_power_ratio": max_running_power_ratio,
        "utilization_rate": hourly["power_ratio"].sum() / 24.0,
        "total_ammonia_output_ton": hourly["hourly_ammonia_output_ton"].sum(),
        "simultaneous_buy_sell_violation": int(
            ((hourly["grid_purchase_mw"] > 1e-6) & (hourly["grid_export_mw"] > 1e-6)).sum()
        ),
        "pass_count": pass_count,
        "satisfaction_type": classify_satisfaction(pass_count),
        **indicators,
    }


def run_production_set_continuous(
    profile: pd.DataFrame,
    productions: list[float] | tuple[float, ...] = (72, 63, 54, 45, 36),
    params: ContinuousDispatchParams | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if params is None:
        params = ContinuousDispatchParams()

    hourly_list = []
    summary_list = []

    for production in productions:
        hourly, summary = solve_continuous_dispatch(
            profile=profile,
            production_ton=float(production),
            params=params,
        )
        hourly_list.append(hourly)
        summary_list.append(summary)

    hourly_df = pd.concat(hourly_list, ignore_index=True)
    summary_df = pd.DataFrame(summary_list)

    return hourly_df, summary_df


def summarize_annual_results_continuous(
    scenario_summary_df: pd.DataFrame,
    scenario_days: int = 15,
) -> pd.DataFrame:
    rows = []

    for production, group in scenario_summary_df.groupby("production_ton"):
        year_total_cost = (group["total_cost_yuan"] * scenario_days).sum()
        year_total_production = (group["production_ton"] * scenario_days).sum()
        annual_avg_ton_cost = year_total_cost / year_total_production

        count_all = int((group["satisfaction_type"] == "全满足").sum())
        count_partial = int((group["satisfaction_type"] == "部分满足").sum())
        count_none = int((group["satisfaction_type"] == "全不满足").sum())

        rows.append(
            {
                "production_ton": production,
                "scenario_count": len(group),
                "annual_days": len(group) * scenario_days,
                "annual_total_cost_yuan": year_total_cost,
                "annual_total_production_ton": year_total_production,
                "annual_avg_ton_cost_yuan_per_ton": annual_avg_ton_cost,
                "all_satisfied_scenarios": count_all,
                "partially_satisfied_scenarios": count_partial,
                "none_satisfied_scenarios": count_none,
                "all_satisfied_days": count_all * scenario_days,
                "partially_satisfied_days": count_partial * scenario_days,
                "none_satisfied_days": count_none * scenario_days,
                "mean_grid_purchase_mwh": group["grid_purchase_mwh"].mean(),
                "mean_grid_export_mwh": group["grid_export_mwh"].mean(),
                "mean_renewable_self_use_ratio": group[
                    "renewable_self_use_ratio"
                ].mean(),
                "mean_green_power_ratio": group["green_power_ratio"].mean(),
                "mean_renewable_export_ratio": group[
                    "renewable_export_ratio"
                ].mean(),
                "mean_on_hours": group["on_hours"].mean(),
                "mean_running_power_ratio": group[
                    "mean_running_power_ratio"
                ].mean(),
                "mean_avg_power_ratio": group["avg_power_ratio"].mean(),
            }
        )

    annual_df = pd.DataFrame(rows).sort_values("production_ton", ascending=False)
    return annual_df


def build_q3_vs_q2_comparison(
    q2_annual_df: pd.DataFrame,
    q3_annual_df: pd.DataFrame,
) -> pd.DataFrame:
    q2 = q2_annual_df.copy()
    q3 = q3_annual_df.copy()

    keep_cols = [
        "production_ton",
        "annual_avg_ton_cost_yuan_per_ton",
        "all_satisfied_days",
        "partially_satisfied_days",
        "none_satisfied_days",
        "mean_grid_purchase_mwh",
        "mean_grid_export_mwh",
        "mean_renewable_self_use_ratio",
        "mean_green_power_ratio",
        "mean_renewable_export_ratio",
    ]

    q2 = q2[keep_cols].rename(
        columns={
            "annual_avg_ton_cost_yuan_per_ton": "q2_annual_avg_ton_cost_yuan_per_ton",
            "all_satisfied_days": "q2_all_satisfied_days",
            "partially_satisfied_days": "q2_partially_satisfied_days",
            "none_satisfied_days": "q2_none_satisfied_days",
            "mean_grid_purchase_mwh": "q2_mean_grid_purchase_mwh",
            "mean_grid_export_mwh": "q2_mean_grid_export_mwh",
            "mean_renewable_self_use_ratio": "q2_mean_renewable_self_use_ratio",
            "mean_green_power_ratio": "q2_mean_green_power_ratio",
            "mean_renewable_export_ratio": "q2_mean_renewable_export_ratio",
        }
    )

    q3 = q3[keep_cols].rename(
        columns={
            "annual_avg_ton_cost_yuan_per_ton": "q3_annual_avg_ton_cost_yuan_per_ton",
            "all_satisfied_days": "q3_all_satisfied_days",
            "partially_satisfied_days": "q3_partially_satisfied_days",
            "none_satisfied_days": "q3_none_satisfied_days",
            "mean_grid_purchase_mwh": "q3_mean_grid_purchase_mwh",
            "mean_grid_export_mwh": "q3_mean_grid_export_mwh",
            "mean_renewable_self_use_ratio": "q3_mean_renewable_self_use_ratio",
            "mean_green_power_ratio": "q3_mean_green_power_ratio",
            "mean_renewable_export_ratio": "q3_mean_renewable_export_ratio",
        }
    )

    merged = q2.merge(q3, on="production_ton", how="inner")

    merged["cost_reduction_yuan_per_ton"] = (
        merged["q2_annual_avg_ton_cost_yuan_per_ton"]
        - merged["q3_annual_avg_ton_cost_yuan_per_ton"]
    )

    merged["cost_reduction_ratio"] = (
        merged["cost_reduction_yuan_per_ton"]
        / merged["q2_annual_avg_ton_cost_yuan_per_ton"]
    )

    merged["grid_purchase_reduction_mwh"] = (
        merged["q2_mean_grid_purchase_mwh"] - merged["q3_mean_grid_purchase_mwh"]
    )

    merged["grid_export_reduction_mwh"] = (
        merged["q2_mean_grid_export_mwh"] - merged["q3_mean_grid_export_mwh"]
    )

    merged["all_satisfied_days_change"] = (
        merged["q3_all_satisfied_days"] - merged["q2_all_satisfied_days"]
    )

    return merged.sort_values("production_ton", ascending=False)
