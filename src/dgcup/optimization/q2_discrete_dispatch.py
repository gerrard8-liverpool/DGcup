from __future__ import annotations

from dataclasses import dataclass
import numpy as np
import pandas as pd

from dgcup.core.cost import tou_price_by_hour
from dgcup.core.indicators import calculate_green_indicators


@dataclass(frozen=True)
class DiscreteDispatchParams:
    """Parameters for Q2 discrete full-on/full-off ammonia dispatch."""

    plant_capacity_ton_per_day: float = 72.0
    ammonia_output_ton_per_hour: float = 3.0

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


def ammonia_capex_daily_yuan(params: DiscreteDispatchParams) -> float:
    """
    Calculate daily fixed depreciation cost of the ammonia synthesis device.

    In Q2, the park has already expanded to 72 t/day capacity.
    Therefore fixed depreciation is calculated using installed capacity,
    not actual daily production.
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


def classify_satisfaction(pass_count: int) -> str:
    if pass_count == 3:
        return "全满足"
    if pass_count == 0:
        return "全不满足"
    return "部分满足"


def calculate_hourly_dispatch(
    profile: pd.DataFrame,
    on_status: np.ndarray | list[int],
    params: DiscreteDispatchParams,
) -> pd.DataFrame:
    """
    Calculate hourly power balance and hourly cost for a given on/off schedule.

    on_status:
    - 1: hydrogen-ammonia system is fully on
    - 0: hydrogen-ammonia system is off
    """
    hourly = profile.copy().reset_index(drop=True)
    on_status = np.asarray(on_status, dtype=int)

    if len(on_status) != len(hourly):
        raise ValueError("Length of on_status must match hourly profile length.")

    hourly["on_status"] = on_status

    hourly["alk_power_mw"] = params.alk_power_mw * hourly["on_status"]
    hourly["pem_power_mw"] = params.pem_power_mw * hourly["on_status"]
    hourly["ammonia_power_mw"] = params.ammonia_power_mw * hourly["on_status"]

    hourly["hydrogen_ammonia_load_mw"] = (
        hourly["alk_power_mw"]
        + hourly["pem_power_mw"]
        + hourly["ammonia_power_mw"]
    )

    hourly["total_load_mw"] = (
        hourly["base_load_mw"] + hourly["hydrogen_ammonia_load_mw"]
    )

    hourly["grid_purchase_mw"] = (
        hourly["total_load_mw"] - hourly["renewable_power_mw"]
    ).clip(lower=0)

    hourly["grid_export_mw"] = (
        hourly["renewable_power_mw"] - hourly["total_load_mw"]
    ).clip(lower=0)

    hourly["renewable_self_used_mw"] = hourly[
        ["total_load_mw", "renewable_power_mw"]
    ].min(axis=1)

    hourly["tou_price_yuan_per_kwh"] = hourly["hour"].map(tou_price_by_hour)

    hourly["grid_purchase_cost_yuan"] = (
        hourly["grid_purchase_mw"] * 1000 * hourly["tou_price_yuan_per_kwh"]
    )

    hourly["wind_generation_cost_yuan"] = (
        hourly["wind_power_mw"] * 1000 * params.wind_lcoe_yuan_per_kwh
    )

    hourly["pv_generation_cost_yuan"] = (
        hourly["pv_power_mw"] * 1000 * params.pv_lcoe_yuan_per_kwh
    )

    hourly["alk_om_cost_yuan"] = (
        hourly["alk_power_mw"] * 1000 * params.alk_om_yuan_per_kwh
    )

    hourly["pem_om_cost_yuan"] = (
        hourly["pem_power_mw"] * 1000 * params.pem_om_yuan_per_kwh
    )

    hourly["ammonia_om_cost_yuan"] = (
        hourly["ammonia_power_mw"] * 1000 * params.ammonia_om_yuan_per_kwh
    )

    hourly["grid_export_revenue_yuan"] = (
        hourly["grid_export_mw"] * 1000 * params.export_price_yuan_per_kwh
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

    return hourly


def _build_summary(
    hourly: pd.DataFrame,
    production_ton: float,
    params: DiscreteDispatchParams,
) -> dict:
    indicators = calculate_green_indicators(hourly)

    capex_daily = ammonia_capex_daily_yuan(params)

    grid_purchase_cost = hourly["grid_purchase_cost_yuan"].sum()
    wind_generation_cost = hourly["wind_generation_cost_yuan"].sum()
    pv_generation_cost = hourly["pv_generation_cost_yuan"].sum()
    alk_om_cost = hourly["alk_om_cost_yuan"].sum()
    pem_om_cost = hourly["pem_om_cost_yuan"].sum()
    ammonia_om_cost = hourly["ammonia_om_cost_yuan"].sum()
    grid_export_revenue = hourly["grid_export_revenue_yuan"].sum()

    total_cost = hourly["hourly_net_cost_yuan"].sum() + capex_daily
    ton_cost = total_cost / production_ton

    pass_count = int(indicators["renewable_self_use_pass"]) + int(
        indicators["green_power_pass"]
    ) + int(indicators["renewable_export_pass"])

    selected_hours = hourly.loc[hourly["on_status"] == 1, "hour"].astype(int).tolist()
    selected_times = hourly.loc[hourly["on_status"] == 1, "time"].astype(str).tolist()

    scenario_id = hourly["scenario_id"].iloc[0]
    wind_scenario = hourly["wind_scenario"].iloc[0]
    pv_scenario = hourly["pv_scenario"].iloc[0]

    renewable_local_consumption_ratio = (
        indicators["renewable_generation_mwh"] - indicators["grid_export_mwh"]
    ) / indicators["renewable_generation_mwh"]

    return {
        "scenario_id": scenario_id,
        "wind_scenario": wind_scenario,
        "pv_scenario": pv_scenario,
        "production_ton": production_ton,
        "on_hours": int(hourly["on_status"].sum()),
        "selected_hours": ",".join(str(h) for h in selected_hours),
        "selected_times": ";".join(selected_times),
        "utilization_rate": hourly["on_status"].sum() / 24.0,
        "total_cost_yuan": total_cost,
        "ton_cost_yuan_per_ton": ton_cost,
        "grid_purchase_cost_yuan": grid_purchase_cost,
        "wind_generation_cost_yuan": wind_generation_cost,
        "pv_generation_cost_yuan": pv_generation_cost,
        "alk_om_cost_yuan": alk_om_cost,
        "pem_om_cost_yuan": pem_om_cost,
        "ammonia_om_cost_yuan": ammonia_om_cost,
        "ammonia_capex_daily_yuan": capex_daily,
        "grid_export_revenue_yuan": grid_export_revenue,
        "renewable_local_consumption_ratio": renewable_local_consumption_ratio,
        "pass_count": pass_count,
        "satisfaction_type": classify_satisfaction(pass_count),
        **indicators,
    }


def optimize_discrete_dispatch(
    profile: pd.DataFrame,
    production_ton: float,
    params: DiscreteDispatchParams | None = None,
) -> tuple[pd.DataFrame, dict]:
    """
    Optimize Q2 discrete dispatch using exact incremental-cost ranking.

    Because there is no storage state, ramping constraint, or minimum on/off time
    in Q2, the objective is separable by hour. For a fixed production target,
    selecting the hours with the smallest incremental costs gives the global optimum.
    """
    if params is None:
        params = DiscreteDispatchParams()

    on_hours_float = production_ton / params.ammonia_output_ton_per_hour
    on_hours = int(round(on_hours_float))

    if abs(on_hours_float - on_hours) > 1e-8:
        raise ValueError(
            f"Production {production_ton} t/day cannot be represented by "
            f"{params.ammonia_output_ton_per_hour} t/h full-load production."
        )

    if not 0 <= on_hours <= 24:
        raise ValueError("on_hours must be between 0 and 24.")

    zero_status = np.zeros(24, dtype=int)
    hourly_zero = calculate_hourly_dispatch(profile, zero_status, params)

    delta_rows = []

    for hour in range(24):
        one_hour_status = np.zeros(24, dtype=int)
        one_hour_status[hour] = 1

        hourly_one = calculate_hourly_dispatch(profile, one_hour_status, params)

        delta_cost = (
            hourly_one.loc[hour, "hourly_net_cost_yuan"]
            - hourly_zero.loc[hour, "hourly_net_cost_yuan"]
        )

        delta_rows.append(
            {
                "hour": hour,
                "time": profile.loc[hour, "time"],
                "delta_cost_yuan": delta_cost,
            }
        )

    delta_df = pd.DataFrame(delta_rows).sort_values(
        ["delta_cost_yuan", "hour"], ascending=[True, True]
    )

    selected_hours = delta_df.head(on_hours)["hour"].astype(int).tolist()

    on_status = np.zeros(24, dtype=int)
    on_status[selected_hours] = 1

    hourly = calculate_hourly_dispatch(profile, on_status, params)

    hourly = hourly.merge(
        delta_df[["hour", "delta_cost_yuan"]],
        on="hour",
        how="left",
    )

    hourly["production_ton"] = production_ton
    hourly["hourly_ammonia_output_ton"] = (
        hourly["on_status"] * params.ammonia_output_ton_per_hour
    )

    summary = _build_summary(hourly, production_ton, params)

    return hourly, summary


def run_production_set(
    profile: pd.DataFrame,
    productions: list[float] | tuple[float, ...] = (72, 63, 54, 45, 36),
    params: DiscreteDispatchParams | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run Q2 optimization for multiple daily production targets."""
    if params is None:
        params = DiscreteDispatchParams()

    hourly_list = []
    summary_list = []

    for production in productions:
        hourly, summary = optimize_discrete_dispatch(
            profile=profile,
            production_ton=float(production),
            params=params,
        )
        hourly_list.append(hourly)
        summary_list.append(summary)

    hourly_df = pd.concat(hourly_list, ignore_index=True)
    summary_df = pd.DataFrame(summary_list)

    return hourly_df, summary_df


def summarize_annual_results(
    scenario_summary_df: pd.DataFrame,
    scenario_days: int = 15,
) -> pd.DataFrame:
    """
    Build annual-equivalent summary for Q2.

    Each of the 24 wind-PV scenarios represents scenario_days days.
    """
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
            }
        )

    annual_df = pd.DataFrame(rows).sort_values("production_ton", ascending=False)
    return annual_df
