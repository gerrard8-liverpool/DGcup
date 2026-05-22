from __future__ import annotations

from typing import Any
import pandas as pd


def _build_base_profile(
    load_df: pd.DataFrame,
    time_col_idx: int = 0,
    load_pu_col_idx: int = 1,
    base_load_peak_mw: float = 6.0,
) -> pd.DataFrame:
    """Build base-load profile from attachment 1."""
    profile = pd.DataFrame()
    profile["hour"] = range(24)
    profile["time"] = load_df.iloc[:24, time_col_idx].astype(str).values
    profile["base_load_mw"] = (
        load_df.iloc[:24, load_pu_col_idx].astype(float).values * base_load_peak_mw
    )
    return profile


def build_typical_scenario_profile(
    load_df: pd.DataFrame,
    renewable_df: pd.DataFrame,
    base_load_peak_mw: float = 6.0,
    wind_capacity_mw: float = 40.0,
    pv_capacity_mw: float = 64.0,
) -> pd.DataFrame:
    """
    Build the typical-day scenario profile using attachment 1 and attachment 2.

    Returned columns:
    - scenario_id
    - wind_scenario
    - pv_scenario
    - hour
    - time
    - base_load_mw
    - wind_power_mw
    - pv_power_mw
    - renewable_power_mw
    """
    profile = _build_base_profile(
        load_df=load_df,
        base_load_peak_mw=base_load_peak_mw,
    )

    profile["scenario_id"] = "typical"
    profile["wind_scenario"] = "typical"
    profile["pv_scenario"] = "typical"

    profile["wind_power_mw"] = (
        renewable_df.iloc[:24, 1].astype(float).values * wind_capacity_mw
    )
    profile["pv_power_mw"] = (
        renewable_df.iloc[:24, 2].astype(float).values * pv_capacity_mw
    )
    profile["renewable_power_mw"] = (
        profile["wind_power_mw"] + profile["pv_power_mw"]
    )

    ordered_cols = [
        "scenario_id",
        "wind_scenario",
        "pv_scenario",
        "hour",
        "time",
        "base_load_mw",
        "wind_power_mw",
        "pv_power_mw",
        "renewable_power_mw",
    ]
    return profile[ordered_cols]


def build_24_wind_pv_scenario_profiles(
    load_df: pd.DataFrame,
    wind_df: pd.DataFrame,
    pv_df: pd.DataFrame,
    base_load_peak_mw: float = 6.0,
    wind_capacity_mw: float = 40.0,
    pv_capacity_mw: float = 64.0,
) -> list[dict[str, Any]]:
    """
    Build 24 wind-PV combined scenario profiles using attachment 3 and attachment 4.

    Attachment 3:
    - column 0: time
    - columns 1-6: wind scenarios

    Attachment 4:
    - column 0: time
    - columns 1-4: PV scenarios
    """
    scenarios: list[dict[str, Any]] = []

    base_profile = _build_base_profile(
        load_df=load_df,
        base_load_peak_mw=base_load_peak_mw,
    )

    wind_cols = list(wind_df.columns[1:])
    pv_cols = list(pv_df.columns[1:])

    for wind_idx, wind_col in enumerate(wind_cols, start=1):
        for pv_idx, pv_col in enumerate(pv_cols, start=1):
            profile = base_profile.copy()

            scenario_id = f"W{wind_idx}_PV{pv_idx}"
            wind_name = str(wind_col)
            pv_name = str(pv_col)

            profile["scenario_id"] = scenario_id
            profile["wind_scenario"] = wind_name
            profile["pv_scenario"] = pv_name

            profile["wind_power_mw"] = (
                wind_df.iloc[:24, wind_idx].astype(float).values * wind_capacity_mw
            )
            profile["pv_power_mw"] = (
                pv_df.iloc[:24, pv_idx].astype(float).values * pv_capacity_mw
            )
            profile["renewable_power_mw"] = (
                profile["wind_power_mw"] + profile["pv_power_mw"]
            )

            ordered_cols = [
                "scenario_id",
                "wind_scenario",
                "pv_scenario",
                "hour",
                "time",
                "base_load_mw",
                "wind_power_mw",
                "pv_power_mw",
                "renewable_power_mw",
            ]

            scenarios.append(
                {
                    "scenario_id": scenario_id,
                    "wind_scenario": wind_name,
                    "pv_scenario": pv_name,
                    "profile": profile[ordered_cols],
                }
            )

    return scenarios
