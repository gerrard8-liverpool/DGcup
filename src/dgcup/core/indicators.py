import pandas as pd


def calculate_green_indicators(hourly: pd.DataFrame) -> dict:
    """
    Calculate green power direct-connection indicators.

    After the competition clarification, the first indicator is calculated
    using the physically consistent renewable self-use ratio:

        renewable_self_use_ratio
        = renewable local consumption / renewable generation
        = (renewable generation - grid export) / renewable generation

    This is equivalent to:

        (total load - grid purchase) / renewable generation

    under grid-connected operation without storage.
    """
    total_load_mwh = hourly["total_load_mw"].sum()
    renewable_generation_mwh = hourly["renewable_power_mw"].sum()
    grid_purchase_mwh = hourly["grid_purchase_mw"].sum()
    grid_export_mwh = hourly["grid_export_mw"].sum()

    renewable_self_used_mwh = renewable_generation_mwh - grid_export_mwh

    renewable_self_use_ratio = renewable_self_used_mwh / renewable_generation_mwh
    green_power_ratio = renewable_self_used_mwh / total_load_mwh
    renewable_export_ratio = grid_export_mwh / renewable_generation_mwh

    eps = 1e-9

    return {
        "total_load_mwh": total_load_mwh,
        "renewable_generation_mwh": renewable_generation_mwh,
        "grid_purchase_mwh": grid_purchase_mwh,
        "grid_export_mwh": grid_export_mwh,
        "renewable_self_used_mwh": renewable_self_used_mwh,
        "renewable_self_use_ratio": renewable_self_use_ratio,
        "green_power_ratio": green_power_ratio,
        "renewable_export_ratio": renewable_export_ratio,
        "renewable_self_use_pass": renewable_self_use_ratio >= 0.60 - eps,
        "green_power_pass": green_power_ratio >= 0.30 - eps,
        "renewable_export_pass": renewable_export_ratio <= 0.20 + eps,
    }
