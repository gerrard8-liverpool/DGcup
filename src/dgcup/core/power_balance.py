import pandas as pd


def build_q1_power_balance(
    load_df: pd.DataFrame,
    renewable_df: pd.DataFrame,
    base_load_peak_mw: float = 6.0,
    wind_capacity_mw: float = 40.0,
    pv_capacity_mw: float = 64.0,
    alk_power_mw: float = 10.0,
    pem_power_mw: float = 10.0,
    ammonia_power_mw: float = 0.75,
) -> pd.DataFrame:
    """Build hourly power balance for Q1 typical-day full-load operation."""

    result = pd.DataFrame()
    result["time"] = load_df.iloc[:, 0].astype(str)

    result["base_load_mw"] = load_df.iloc[:, 1].astype(float) * base_load_peak_mw

    result["alk_power_mw"] = alk_power_mw
    result["pem_power_mw"] = pem_power_mw
    result["ammonia_power_mw"] = ammonia_power_mw
    result["hydrogen_ammonia_load_mw"] = alk_power_mw + pem_power_mw + ammonia_power_mw

    result["total_load_mw"] = (
        result["base_load_mw"] + result["hydrogen_ammonia_load_mw"]
    )

    result["wind_power_mw"] = renewable_df.iloc[:, 1].astype(float) * wind_capacity_mw
    result["pv_power_mw"] = renewable_df.iloc[:, 2].astype(float) * pv_capacity_mw
    result["renewable_power_mw"] = result["wind_power_mw"] + result["pv_power_mw"]

    result["grid_purchase_mw"] = (
        result["total_load_mw"] - result["renewable_power_mw"]
    ).clip(lower=0)

    result["grid_export_mw"] = (
        result["renewable_power_mw"] - result["total_load_mw"]
    ).clip(lower=0)

    result["renewable_self_used_mw"] = result[
        ["total_load_mw", "renewable_power_mw"]
    ].min(axis=1)

    return result
