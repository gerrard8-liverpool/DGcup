from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager


def setup_chinese_font():
    candidate_fonts = [
        "Microsoft YaHei",
        "SimHei",
        "SimSun",
        "Noto Sans CJK SC",
        "Source Han Sans SC",
        "Arial Unicode MS",
    ]

    available_fonts = {f.name for f in font_manager.fontManager.ttflist}

    for font_name in candidate_fonts:
        if font_name in available_fonts:
            plt.rcParams["font.sans-serif"] = [font_name]
            plt.rcParams["axes.unicode_minus"] = False
            return font_name

    plt.rcParams["axes.unicode_minus"] = False
    return None


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


CAPACITIES_MWH = [0, 20, 40, 60, 80, 120, 160, 220]
SCENARIO_DAYS = 15


def clone_scaled_scenarios(scenario_profiles: list[dict], renewable_scale: float) -> list[dict]:
    scaled = []
    for item in scenario_profiles:
        profile = item["profile"].copy()
        profile["wind_power_mw"] *= renewable_scale
        profile["pv_power_mw"] *= renewable_scale
        profile["renewable_power_mw"] = profile["wind_power_mw"] + profile["pv_power_mw"]
        scaled.append(
            {
                "scenario_id": item["scenario_id"],
                "wind_scenario": item["wind_scenario"],
                "pv_scenario": item["pv_scenario"],
                "profile": profile,
            }
        )
    return scaled


def select_knee_capacity(scan_df: pd.DataFrame) -> pd.Series:
    baseline = scan_df.loc[scan_df["storage_capacity_mwh"].idxmin()]

    df = scan_df.copy()
    df["cost_increase_yuan_per_ton"] = (
        df["annual_avg_ton_cost_yuan_per_ton"]
        - baseline["annual_avg_ton_cost_yuan_per_ton"]
    )
    df["production_gain_ton"] = (
        df["annual_total_production_ton"]
        - baseline["annual_total_production_ton"]
    )
    df["curtailment_reduction_mwh"] = (
        baseline["annual_total_curtailment_mwh"]
        - df["annual_total_curtailment_mwh"]
    )
    df["capacity_utilization_gain"] = (
        df["annual_capacity_utilization_rate"]
        - baseline["annual_capacity_utilization_rate"]
    )

    denom = df["cost_increase_yuan_per_ton"] / 100.0

    df["production_gain_per_100yuan"] = np.where(
        denom > 1e-9,
        df["production_gain_ton"] / denom,
        np.nan,
    )
    df["curtailment_reduction_per_100yuan"] = np.where(
        denom > 1e-9,
        df["curtailment_reduction_mwh"] / denom,
        np.nan,
    )
    df["utilization_gain_pp_per_100yuan"] = np.where(
        denom > 1e-9,
        df["capacity_utilization_gain"] * 100.0 / denom,
        np.nan,
    )

    candidates = df[
        (df["storage_capacity_mwh"] > 0)
        & (df["mean_unserved_load_mwh"] <= 1e-8)
        & np.isfinite(df["production_gain_per_100yuan"])
    ].copy()

    if candidates.empty:
        candidates = df[
            (df["storage_capacity_mwh"] > 0)
            & np.isfinite(df["production_gain_per_100yuan"])
        ].copy()

    if candidates.empty:
        best = df.loc[df["annual_avg_ton_cost_yuan_per_ton"].idxmin()].copy()
    else:
        candidates = candidates.sort_values(
            by=[
                "production_gain_per_100yuan",
                "curtailment_reduction_per_100yuan",
                "storage_capacity_mwh",
            ],
            ascending=[False, False, True],
        )
        best = candidates.iloc[0].copy()

    for col in [
        "cost_increase_yuan_per_ton",
        "production_gain_ton",
        "curtailment_reduction_mwh",
        "capacity_utilization_gain",
        "production_gain_per_100yuan",
        "curtailment_reduction_per_100yuan",
        "utilization_gain_pp_per_100yuan",
    ]:
        if col not in best:
            best[col] = df.loc[best.name, col]

    return best


def annual_capacity_scan(
    scenario_profiles: list[dict],
    params: OffgridStorageParams,
    capacities: list[float],
) -> tuple[pd.DataFrame, dict[float, pd.DataFrame]]:
    rows = []
    summary_by_capacity = {}

    for cap in capacities:
        hourly_df, summary_df = run_offgrid_storage_for_scenarios(
            scenario_profiles=scenario_profiles,
            storage_capacity_mwh=float(cap),
            params=params,
        )

        annual_df = summarize_offgrid_annual(
            summary_df,
            scenario_days=SCENARIO_DAYS,
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


def run_one_case(
    case_name: str,
    category: str,
    value: float,
    scenario_profiles: list[dict],
    params: OffgridStorageParams,
    table_dir: Path,
) -> dict:
    print(f"[Sensitivity] {category} = {value} ({case_name})")

    scan_df, summary_by_capacity = annual_capacity_scan(
        scenario_profiles=scenario_profiles,
        params=params,
        capacities=CAPACITIES_MWH,
    )

    best = select_knee_capacity(scan_df)
    best_capacity = float(best["storage_capacity_mwh"])
    best_summary_df = summary_by_capacity[best_capacity]

    _, _, grid_compare_df = run_grid_connected_same_production_comparison(
        scenario_profiles=scenario_profiles,
        offgrid_storage_summary_df=best_summary_df,
        scenario_days=SCENARIO_DAYS,
    )

    offgrid_row = grid_compare_df[grid_compare_df["mode"] == "offgrid_with_storage"].iloc[0]
    grid_row = grid_compare_df[grid_compare_df["mode"] == "grid_connected_same_production"].iloc[0]

    scan_path = table_dir / f"sensitivity_scan_{case_name}.csv"
    scan_df.to_csv(scan_path, index=False, encoding="utf-8-sig")

    return {
        "case_name": case_name,
        "category": category,
        "value": value,
        "recommended_capacity_mwh": best_capacity,
        "annual_production_ton": best["annual_total_production_ton"],
        "capacity_utilization_rate": best["annual_capacity_utilization_rate"],
        "offgrid_storage_ton_cost_yuan_per_ton": offgrid_row["annual_avg_ton_cost_yuan_per_ton"],
        "grid_same_production_ton_cost_yuan_per_ton": grid_row["annual_avg_ton_cost_yuan_per_ton"],
        "grid_cost_advantage_yuan_per_ton": (
            offgrid_row["annual_avg_ton_cost_yuan_per_ton"]
            - grid_row["annual_avg_ton_cost_yuan_per_ton"]
        ),
        "annual_total_curtailment_mwh": best["annual_total_curtailment_mwh"],
        "annual_total_unserved_mwh": best["annual_total_unserved_load_mwh"],
        "production_gain_per_100yuan": best["production_gain_per_100yuan"],
        "curtailment_reduction_per_100yuan": best["curtailment_reduction_per_100yuan"],
        "utilization_gain_pp_per_100yuan": best["utilization_gain_pp_per_100yuan"],
    }


def plot_sensitivity_capacity(summary_df: pd.DataFrame, figure_dir: Path):
    for category in summary_df["category"].unique():
        df = summary_df[summary_df["category"] == category].sort_values("value")

        plt.figure(figsize=(8.4, 5.0))
        plt.plot(df["value"], df["recommended_capacity_mwh"], marker="o", linewidth=2.2)
        plt.xlabel(category)
        plt.ylabel("推荐储能容量 / MWh")
        plt.title(f"敏感性分析：{category} 对推荐容量的影响")
        plt.grid(axis="y", alpha=0.3)
        plt.tight_layout()
        plt.savefig(figure_dir / f"sensitivity_{category}_recommended_capacity.png", dpi=300)
        plt.close()


def plot_sensitivity_grid_advantage(summary_df: pd.DataFrame, figure_dir: Path):
    for category in summary_df["category"].unique():
        df = summary_df[summary_df["category"] == category].sort_values("value")

        plt.figure(figsize=(8.4, 5.0))
        plt.plot(df["value"], df["grid_cost_advantage_yuan_per_ton"], marker="o", linewidth=2.2)
        plt.axhline(0, color="black", linewidth=1.0)
        plt.xlabel(category)
        plt.ylabel("离网储能相对联网同产量成本差 / 元·t$^{-1}$")
        plt.title(f"稳健性检验：{category} 下联网同产量经济性优势")
        plt.grid(axis="y", alpha=0.3)
        plt.tight_layout()
        plt.savefig(figure_dir / f"sensitivity_{category}_grid_cost_advantage.png", dpi=300)
        plt.close()


def main():
    font_name = setup_chinese_font()
    if font_name is None:
        print("Warning: No Chinese font found. Chinese labels may not render correctly.")
    else:
        print(f"Using Chinese font: {font_name}")

    raw_dir = PROJECT_ROOT / "data" / "raw"
    table_dir = PROJECT_ROOT / "outputs" / "tables"
    figure_dir = PROJECT_ROOT / "outputs" / "figures"
    table_dir.mkdir(parents=True, exist_ok=True)
    figure_dir.mkdir(parents=True, exist_ok=True)

    load_df = read_excel_by_prefix(raw_dir, "附件1")
    wind_scenario_df = read_excel_by_prefix(raw_dir, "附件3")
    pv_scenario_df = read_excel_by_prefix(raw_dir, "附件4")

    base_scenarios = build_24_wind_pv_scenario_profiles(
        load_df=load_df,
        wind_df=wind_scenario_df,
        pv_df=pv_scenario_df,
    )

    base_params = OffgridStorageParams()

    cases = []

    for multiplier in [0.6, 0.8, 1.0, 1.2, 1.4]:
        params = replace(
            base_params,
            storage_investment_yuan_per_kwh=base_params.storage_investment_yuan_per_kwh * multiplier,
        )
        cases.append(
            (
                f"storage_cost_{multiplier:.1f}".replace(".", "p"),
                "storage_cost_multiplier",
                multiplier,
                base_scenarios,
                params,
            )
        )

    for c_rate in [0.5, 1.0, 2.0]:
        params = replace(base_params, storage_power_c_rate=c_rate)
        cases.append(
            (
                f"c_rate_{c_rate:.1f}".replace(".", "p"),
                "storage_c_rate",
                c_rate,
                base_scenarios,
                params,
            )
        )

    for efficiency in [0.85, 0.90, 0.95]:
        params = replace(
            base_params,
            charge_efficiency=efficiency,
            discharge_efficiency=efficiency,
        )
        cases.append(
            (
                f"storage_efficiency_{efficiency:.2f}".replace(".", "p"),
                "storage_efficiency",
                efficiency,
                base_scenarios,
                params,
            )
        )

    for scale in [0.90, 1.00, 1.10]:
        scenarios = clone_scaled_scenarios(base_scenarios, renewable_scale=scale)
        cases.append(
            (
                f"renewable_scale_{scale:.2f}".replace(".", "p"),
                "renewable_scale",
                scale,
                scenarios,
                base_params,
            )
        )

    rows = []
    for case_name, category, value, scenarios, params in cases:
        rows.append(
            run_one_case(
                case_name=case_name,
                category=category,
                value=value,
                scenario_profiles=scenarios,
                params=params,
                table_dir=table_dir,
            )
        )

    summary_df = pd.DataFrame(rows)
    summary_df.to_csv(table_dir / "sensitivity_summary.csv", index=False, encoding="utf-8-sig")

    plot_sensitivity_capacity(summary_df, figure_dir)
    plot_sensitivity_grid_advantage(summary_df, figure_dir)

    print("=" * 88)
    print("Sensitivity analysis finished.")
    print("=" * 88)
    print(
        summary_df[
            [
                "category",
                "value",
                "recommended_capacity_mwh",
                "offgrid_storage_ton_cost_yuan_per_ton",
                "grid_same_production_ton_cost_yuan_per_ton",
                "grid_cost_advantage_yuan_per_ton",
                "production_gain_per_100yuan",
                "curtailment_reduction_per_100yuan",
            ]
        ].to_string(index=False)
    )
    print("=" * 88)
    print(f"Summary saved to: {table_dir / 'sensitivity_summary.csv'}")
    print(f"Figures saved to: {figure_dir}")


if __name__ == "__main__":
    main()
