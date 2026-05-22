from __future__ import annotations

import argparse
from pathlib import Path
import sys
import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT / "src"))

from dgcup.data.load_excel import read_excel_by_prefix
from dgcup.data.build_scenarios import build_24_wind_pv_scenario_profiles
from dgcup.optimization.q4_storage_dispatch import (
    OffgridStorageParams,
    run_offgrid_storage_for_scenarios,
    summarize_offgrid_annual,
    run_grid_connected_same_production_comparison,
)


DEFAULT_CAPACITIES = [0, 20, 40, 60, 80]


def parse_capacities(text: str) -> list[float]:
    return [float(x.strip()) for x in text.split(",") if x.strip()]


def copy_scenario_profiles(scenario_profiles: list[dict]) -> list[dict]:
    copied = []
    for item in scenario_profiles:
        copied.append(
            {
                "scenario_id": item["scenario_id"],
                "wind_scenario": item["wind_scenario"],
                "pv_scenario": item["pv_scenario"],
                "profile": item["profile"].copy(),
            }
        )
    return copied


def recompute_renewable(profile: pd.DataFrame) -> pd.DataFrame:
    profile = profile.copy()
    profile["wind_power_mw"] = profile["wind_power_mw"].clip(lower=0.0)
    profile["pv_power_mw"] = profile["pv_power_mw"].clip(lower=0.0)
    profile["base_load_mw"] = profile["base_load_mw"].clip(lower=0.0)
    profile["renewable_power_mw"] = profile["wind_power_mw"] + profile["pv_power_mw"]
    return profile


def apply_deterministic_scale(
    scenario_profiles: list[dict],
    wind_scale: float = 1.0,
    pv_scale: float = 1.0,
    load_scale: float = 1.0,
) -> list[dict]:
    scaled = []
    for item in scenario_profiles:
        profile = item["profile"].copy()
        profile["wind_power_mw"] *= wind_scale
        profile["pv_power_mw"] *= pv_scale
        profile["base_load_mw"] *= load_scale
        profile = recompute_renewable(profile)

        scaled.append(
            {
                "scenario_id": item["scenario_id"],
                "wind_scenario": item["wind_scenario"],
                "pv_scenario": item["pv_scenario"],
                "profile": profile,
            }
        )
    return scaled


def apply_random_perturbation(
    scenario_profiles: list[dict],
    rng: np.random.Generator,
    wind_range: float = 0.0,
    pv_range: float = 0.0,
    load_range: float = 0.0,
) -> list[dict]:
    perturbed = []

    for item in scenario_profiles:
        profile = item["profile"].copy()
        n = len(profile)

        if wind_range > 0:
            profile["wind_power_mw"] *= rng.uniform(1.0 - wind_range, 1.0 + wind_range, size=n)

        if pv_range > 0:
            profile["pv_power_mw"] *= rng.uniform(1.0 - pv_range, 1.0 + pv_range, size=n)

        if load_range > 0:
            profile["base_load_mw"] *= rng.uniform(1.0 - load_range, 1.0 + load_range, size=n)

        profile = recompute_renewable(profile)

        perturbed.append(
            {
                "scenario_id": item["scenario_id"],
                "wind_scenario": item["wind_scenario"],
                "pv_scenario": item["pv_scenario"],
                "profile": profile,
            }
        )

    return perturbed


def annual_capacity_scan(
    scenario_profiles: list[dict],
    params: OffgridStorageParams,
    capacities: list[float],
    scenario_days: float,
) -> tuple[pd.DataFrame, dict[float, pd.DataFrame]]:
    rows = []
    summary_by_capacity: dict[float, pd.DataFrame] = {}

    for cap in capacities:
        _, summary_df = run_offgrid_storage_for_scenarios(
            scenario_profiles=scenario_profiles,
            storage_capacity_mwh=float(cap),
            params=params,
        )

        annual_df = summarize_offgrid_annual(
            summary_df=summary_df,
            scenario_days=scenario_days,
            mode="offgrid_with_storage",
        )

        row = annual_df.iloc[0].to_dict()
        row["storage_capacity_mwh"] = float(cap)
        rows.append(row)
        summary_by_capacity[float(cap)] = summary_df

    scan_df = pd.DataFrame(rows).sort_values("storage_capacity_mwh").reset_index(drop=True)

    baseline = scan_df.loc[scan_df["storage_capacity_mwh"].idxmin()]

    scan_df["cost_increase_yuan_per_ton"] = (
        scan_df["annual_avg_ton_cost_yuan_per_ton"]
        - baseline["annual_avg_ton_cost_yuan_per_ton"]
    )

    scan_df["production_gain_ton"] = (
        scan_df["annual_total_production_ton"]
        - baseline["annual_total_production_ton"]
    )

    scan_df["curtailment_reduction_mwh"] = (
        baseline["annual_total_curtailment_mwh"]
        - scan_df["annual_total_curtailment_mwh"]
    )

    scan_df["capacity_utilization_gain"] = (
        scan_df["annual_capacity_utilization_rate"]
        - baseline["annual_capacity_utilization_rate"]
    )

    denom = scan_df["cost_increase_yuan_per_ton"] / 100.0

    scan_df["production_gain_per_100yuan"] = np.where(
        denom > 1e-9,
        scan_df["production_gain_ton"] / denom,
        np.nan,
    )

    scan_df["curtailment_reduction_per_100yuan"] = np.where(
        denom > 1e-9,
        scan_df["curtailment_reduction_mwh"] / denom,
        np.nan,
    )

    scan_df["utilization_gain_pp_per_100yuan"] = np.where(
        denom > 1e-9,
        scan_df["capacity_utilization_gain"] * 100.0 / denom,
        np.nan,
    )

    return scan_df, summary_by_capacity


def select_knee_capacity(scan_df: pd.DataFrame) -> pd.Series:
    candidates = scan_df[
        (scan_df["storage_capacity_mwh"] > 0)
        & (scan_df["mean_unserved_load_mwh"] <= 1e-8)
        & np.isfinite(scan_df["production_gain_per_100yuan"])
    ].copy()

    if candidates.empty:
        candidates = scan_df[
            (scan_df["storage_capacity_mwh"] > 0)
            & np.isfinite(scan_df["production_gain_per_100yuan"])
        ].copy()

    if candidates.empty:
        return scan_df.loc[scan_df["annual_avg_ton_cost_yuan_per_ton"].idxmin()].copy()

    candidates = candidates.sort_values(
        by=[
            "production_gain_per_100yuan",
            "curtailment_reduction_per_100yuan",
            "storage_capacity_mwh",
        ],
        ascending=[False, False, True],
    )

    return candidates.iloc[0].copy()


def run_one_robust_case(
    case_name: str,
    test_group: str,
    perturbation_desc: str,
    scenario_profiles: list[dict],
    params: OffgridStorageParams,
    capacities: list[float],
    table_dir: Path,
) -> dict:
    scenario_days = 360.0 / len(scenario_profiles)

    print(f"[Robustness] {test_group} | {case_name} | scenarios={len(scenario_profiles)}")

    scan_df, summary_by_capacity = annual_capacity_scan(
        scenario_profiles=scenario_profiles,
        params=params,
        capacities=capacities,
        scenario_days=scenario_days,
    )

    scan_path = table_dir / f"robustness_scan_{case_name}.csv"
    scan_df.to_csv(scan_path, index=False, encoding="utf-8-sig")

    best = select_knee_capacity(scan_df)
    best_capacity = float(best["storage_capacity_mwh"])
    best_summary_df = summary_by_capacity[best_capacity]

    _, _, comparison_df = run_grid_connected_same_production_comparison(
        scenario_profiles=scenario_profiles,
        offgrid_storage_summary_df=best_summary_df,
        scenario_days=scenario_days,
    )

    offgrid_row = comparison_df[comparison_df["mode"] == "offgrid_with_storage"].iloc[0]
    grid_row = comparison_df[comparison_df["mode"] == "grid_connected_same_production"].iloc[0]

    grid_advantage = (
        offgrid_row["annual_avg_ton_cost_yuan_per_ton"]
        - grid_row["annual_avg_ton_cost_yuan_per_ton"]
    )

    return {
        "case_name": case_name,
        "test_group": test_group,
        "perturbation_desc": perturbation_desc,
        "scenario_count": len(scenario_profiles),
        "recommended_capacity_mwh": best_capacity,
        "annual_total_production_ton": best["annual_total_production_ton"],
        "annual_capacity_utilization_rate": best["annual_capacity_utilization_rate"],
        "offgrid_storage_ton_cost_yuan_per_ton": offgrid_row["annual_avg_ton_cost_yuan_per_ton"],
        "grid_same_production_ton_cost_yuan_per_ton": grid_row["annual_avg_ton_cost_yuan_per_ton"],
        "grid_cost_advantage_yuan_per_ton": grid_advantage,
        "grid_advantage_positive": bool(grid_advantage > 0),
        "annual_total_curtailment_mwh": best["annual_total_curtailment_mwh"],
        "annual_total_unserved_mwh": best["annual_total_unserved_load_mwh"],
        "mean_unserved_load_mwh": best["mean_unserved_load_mwh"],
        "zero_unserved": bool(best["mean_unserved_load_mwh"] <= 1e-8),
        "production_gain_per_100yuan": best["production_gain_per_100yuan"],
        "curtailment_reduction_per_100yuan": best["curtailment_reduction_per_100yuan"],
        "utilization_gain_pp_per_100yuan": best["utilization_gain_pp_per_100yuan"],
    }


def build_robustness_overview(case_df: pd.DataFrame) -> pd.DataFrame:
    rows = []

    for group, df in case_df.groupby("test_group", sort=False):
        capacity_values = sorted(df["recommended_capacity_mwh"].unique())

        mode_capacity = (
            df["recommended_capacity_mwh"]
            .mode()
            .iloc[0]
        )

        rows.append(
            {
                "test_group": group,
                "case_count": len(df),
                "mode_recommended_capacity_mwh": mode_capacity,
                "min_recommended_capacity_mwh": df["recommended_capacity_mwh"].min(),
                "max_recommended_capacity_mwh": df["recommended_capacity_mwh"].max(),
                "capacity_values": ",".join(f"{x:.0f}" for x in capacity_values),
                "positive_grid_advantage_rate": df["grid_advantage_positive"].mean(),
                "zero_unserved_rate": df["zero_unserved"].mean(),
                "mean_grid_cost_advantage_yuan_per_ton": df["grid_cost_advantage_yuan_per_ton"].mean(),
                "min_grid_cost_advantage_yuan_per_ton": df["grid_cost_advantage_yuan_per_ton"].min(),
                "max_grid_cost_advantage_yuan_per_ton": df["grid_cost_advantage_yuan_per_ton"].max(),
                "mean_production_gain_per_100yuan": df["production_gain_per_100yuan"].mean(),
                "mean_curtailment_reduction_per_100yuan": df["curtailment_reduction_per_100yuan"].mean(),
            }
        )

    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--random-samples", type=int, default=3)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--capacities", type=str, default="0,20,40,60,80")
    parser.add_argument("--skip-random", action="store_true")
    parser.add_argument("--skip-leave-one-out", action="store_true")
    parser.add_argument("--skip-stress", action="store_true")
    args = parser.parse_args()

    capacities = parse_capacities(args.capacities)
    rng = np.random.default_rng(args.seed)

    raw_dir = PROJECT_ROOT / "data" / "raw"
    table_dir = PROJECT_ROOT / "outputs" / "tables"
    table_dir.mkdir(parents=True, exist_ok=True)

    load_df = read_excel_by_prefix(raw_dir, "附件1")
    wind_scenario_df = read_excel_by_prefix(raw_dir, "附件3")
    pv_scenario_df = read_excel_by_prefix(raw_dir, "附件4")

    base_scenarios = build_24_wind_pv_scenario_profiles(
        load_df=load_df,
        wind_df=wind_scenario_df,
        pv_df=pv_scenario_df,
    )

    params = OffgridStorageParams()

    rows = []

    if not args.skip_random:
        random_groups = [
            ("random_re_5pct", "风光逐小时随机扰动 ±5%", 0.05, 0.05, 0.00),
            ("random_re_10pct", "风光逐小时随机扰动 ±10%", 0.10, 0.10, 0.00),
            ("random_load_5pct", "常规负荷逐小时随机扰动 ±5%", 0.00, 0.00, 0.05),
            ("random_re10_load5", "风光 ±10% 且负荷 ±5% 逐小时随机扰动", 0.10, 0.10, 0.05),
        ]

        for group_name, desc, wind_range, pv_range, load_range in random_groups:
            for sample_idx in range(1, args.random_samples + 1):
                perturbed = apply_random_perturbation(
                    base_scenarios,
                    rng=rng,
                    wind_range=wind_range,
                    pv_range=pv_range,
                    load_range=load_range,
                )

                rows.append(
                    run_one_robust_case(
                        case_name=f"{group_name}_sample_{sample_idx:02d}",
                        test_group=group_name,
                        perturbation_desc=desc,
                        scenario_profiles=perturbed,
                        params=params,
                        capacities=capacities,
                        table_dir=table_dir,
                    )
                )

    if not args.skip_leave_one_out:
        for removed in base_scenarios:
            kept = [
                item
                for item in base_scenarios
                if item["scenario_id"] != removed["scenario_id"]
            ]

            rows.append(
                run_one_robust_case(
                    case_name=f"leave_one_out_remove_{removed['scenario_id']}",
                    test_group="leave_one_out",
                    perturbation_desc=f"删除场景 {removed['scenario_id']} 后重新年化统计",
                    scenario_profiles=kept,
                    params=params,
                    capacities=capacities,
                    table_dir=table_dir,
                )
            )

    if not args.skip_stress:
        stress_cases = [
            ("stress_low_re_15pct", "风光整体降低 15%", 0.85, 0.85, 1.00),
            ("stress_high_load_10pct", "常规负荷整体提高 10%", 1.00, 1.00, 1.10),
            ("stress_double_pressure", "风光整体降低 10% 且常规负荷提高 10%", 0.90, 0.90, 1.10),
            ("stress_high_re_15pct", "风光整体提高 15%", 1.15, 1.15, 1.00),
        ]

        for case_name, desc, wind_scale, pv_scale, load_scale in stress_cases:
            stressed = apply_deterministic_scale(
                base_scenarios,
                wind_scale=wind_scale,
                pv_scale=pv_scale,
                load_scale=load_scale,
            )

            rows.append(
                run_one_robust_case(
                    case_name=case_name,
                    test_group="stress_test",
                    perturbation_desc=desc,
                    scenario_profiles=stressed,
                    params=params,
                    capacities=capacities,
                    table_dir=table_dir,
                )
            )

    case_df = pd.DataFrame(rows)
    overview_df = build_robustness_overview(case_df)

    case_path = table_dir / "robustness_case_summary.csv"
    overview_path = table_dir / "robustness_overview.csv"

    case_df.to_csv(case_path, index=False, encoding="utf-8-sig")
    overview_df.to_csv(overview_path, index=False, encoding="utf-8-sig")

    print("=" * 96)
    print("Robustness tests finished.")
    print("=" * 96)
    print(
        overview_df[
            [
                "test_group",
                "case_count",
                "mode_recommended_capacity_mwh",
                "min_recommended_capacity_mwh",
                "max_recommended_capacity_mwh",
                "positive_grid_advantage_rate",
                "zero_unserved_rate",
                "mean_grid_cost_advantage_yuan_per_ton",
            ]
        ].to_string(index=False)
    )
    print("=" * 96)
    print(f"Case summary saved to: {case_path}")
    print(f"Overview saved to: {overview_path}")


if __name__ == "__main__":
    main()
