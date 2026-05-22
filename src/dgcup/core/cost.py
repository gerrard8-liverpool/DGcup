import pandas as pd


def tou_price_by_hour(hour: int) -> float:
    """Return time-of-use electricity price, unit: yuan/kWh."""
    if 10 <= hour < 15 or 18 <= hour < 21:
        return 0.8024
    if 7 <= hour < 10 or 15 <= hour < 18 or 21 <= hour < 23:
        return 0.6074
    return 0.3424


def calculate_q1_cost(
    hourly: pd.DataFrame,
    ammonia_output_ton: float = 36.0,
    wind_lcoe_yuan_per_kwh: float = 0.15,
    pv_lcoe_yuan_per_kwh: float = 0.12,
    alk_om_yuan_per_kwh: float = 0.10,
    pem_om_yuan_per_kwh: float = 0.15,
    ammonia_om_yuan_per_kwh: float = 0.002,
    export_price_yuan_per_kwh: float = 0.3779,
    include_ammonia_capex: bool = True,
    ammonia_investment_yuan_per_kg_h2_capacity: float = 60000.0,
    ammonia_h2_consumption_kg_h2_per_kg_nh3: float = 0.2,
    ammonia_lifetime_years: int = 30,
    annual_days: int = 360,
) -> dict:
    """
    Calculate Q1 daily cost and ton-ammonia cost.

    Cost components:
    1. grid purchase cost;
    2. wind generation cost;
    3. PV generation cost;
    4. ALK electrolyzer O&M;
    5. PEM electrolyzer O&M;
    6. ammonia synthesis O&M;
    7. ammonia synthesis annualized investment cost;
    8. grid export revenue.

    Notes:
    - Wind/PV degree costs are treated as generation costs.
    - Ammonia synthesis investment cost is annualized by straight-line depreciation.
    - annual_days=360 is consistent with the 24 scenarios * 15 days annual-equivalent setting.
    """
    hourly = hourly.copy()
    hourly["hour"] = range(len(hourly))
    hourly["tou_price_yuan_per_kwh"] = hourly["hour"].map(tou_price_by_hour)

    grid_purchase_cost = (
        hourly["grid_purchase_mw"] * 1000 * hourly["tou_price_yuan_per_kwh"]
    ).sum()

    wind_generation_cost = (
        hourly["wind_power_mw"] * 1000 * wind_lcoe_yuan_per_kwh
    ).sum()

    pv_generation_cost = (
        hourly["pv_power_mw"] * 1000 * pv_lcoe_yuan_per_kwh
    ).sum()

    alk_om_cost = (
        hourly["alk_power_mw"] * 1000 * alk_om_yuan_per_kwh
    ).sum()

    pem_om_cost = (
        hourly["pem_power_mw"] * 1000 * pem_om_yuan_per_kwh
    ).sum()

    ammonia_om_cost = (
        hourly["ammonia_power_mw"] * 1000 * ammonia_om_yuan_per_kwh
    ).sum()

    grid_export_revenue = (
        hourly["grid_export_mw"] * 1000 * export_price_yuan_per_kwh
    ).sum()

    ammonia_output_kg_per_day = ammonia_output_ton * 1000
    h2_demand_kg_per_day = (
        ammonia_output_kg_per_day * ammonia_h2_consumption_kg_h2_per_kg_nh3
    )
    h2_capacity_kg_per_hour = h2_demand_kg_per_day / 24

    ammonia_investment_yuan = (
        ammonia_investment_yuan_per_kg_h2_capacity * h2_capacity_kg_per_hour
    )

    if include_ammonia_capex:
        ammonia_capex_daily_yuan = (
            ammonia_investment_yuan / ammonia_lifetime_years / annual_days
        )
    else:
        ammonia_capex_daily_yuan = 0.0

    total_cost = (
        grid_purchase_cost
        + wind_generation_cost
        + pv_generation_cost
        + alk_om_cost
        + pem_om_cost
        + ammonia_om_cost
        + ammonia_capex_daily_yuan
        - grid_export_revenue
    )

    ton_ammonia_cost = total_cost / ammonia_output_ton

    return {
        "grid_purchase_cost_yuan": grid_purchase_cost,
        "wind_generation_cost_yuan": wind_generation_cost,
        "pv_generation_cost_yuan": pv_generation_cost,
        "alk_om_cost_yuan": alk_om_cost,
        "pem_om_cost_yuan": pem_om_cost,
        "ammonia_om_cost_yuan": ammonia_om_cost,
        "ammonia_capex_daily_yuan": ammonia_capex_daily_yuan,
        "ammonia_investment_yuan": ammonia_investment_yuan,
        "grid_export_revenue_yuan": grid_export_revenue,
        "total_cost_yuan": total_cost,
        "ton_ammonia_cost_yuan_per_ton": ton_ammonia_cost,
    }
