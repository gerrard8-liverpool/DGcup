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
    run_offgrid_no_storage_for_scenarios,
    scan_storage_capacity,
    run_offgrid_storage_for_scenarios,
    summarize_offgrid_annual,
    run_grid_connected_same_production_comparison,
)
from dgcup.visualization.q4_plots import (
    plot_q4_no_storage_production_bar,
    plot_q4_no_storage_curtailment_unserved,
    plot_q4_storage_capacity_scan,
    plot_q4_storage_dispatch_curve,
    plot_q4_storage_production_bar,
    plot_q4_wind_pv_utilization_improvement,
    plot_q4_grid_vs_offgrid_cost_comparison,
    plot_q4_storage_annual_tradeoff,
    plot_q4_storage_benefit_per_cost,
)


def _positive_norm(series: pd.Series) -> pd.Series:
    max_val = series.max()
    if max_val <= 1e-12:
        return pd.Series(0.0, index=series.index)
    return series / max_val


def build_annual_capacity_scan(
    scenario_profiles: list[dict],
    capacities: list[float],
    params: OffgridStorageParams,
    scenario_days: int = 15,
) -> tuple[pd.DataFrame, dict[float, pd.DataFrame], dict[float, pd.DataFrame]]:
    annual_rows = []
    hourly_by_capacity = {}
    summary_by_capacity = {}

    for cap in capacities:
        print(f"Annual capacity scan: {cap:.0f} MWh")

        hourly_df, summary_df = run_offgrid_storage_for_scenarios(
            scenario_profiles=scenario_profiles,
            storage_capacity_mwh=float(cap),
            params=params,
        )

        annual_df = summarize_offgrid_annual(
            summary_df,
            scenario_days=scenario_days,
            mode="offgrid_with_storage",
        )

        row = annual_df.iloc[0].to_dict()
        row["storage_capacity_mwh"] = float(cap)
        annual_rows.append(row)

        hourly_by_capacity[float(cap)] = hourly_df
        summary_by_capacity[float(cap)] = summary_df

    annual_scan_df = (
        pd.DataFrame(annual_rows)
        .sort_values("storage_capacity_mwh")
        .reset_index(drop=True)
    )

    baseline = annual_scan_df.loc[annual_scan_df["storage_capacity_mwh"].idxmin()]

    annual_scan_df["cost_increase_yuan_per_ton"] = (
        annual_scan_df["annual_avg_ton_cost_yuan_per_ton"]
        - baseline["annual_avg_ton_cost_yuan_per_ton"]
    )

    annual_scan_df["production_gain_ton"] = (
        annual_scan_df["annual_total_production_ton"]
        - baseline["annual_total_production_ton"]
    )

    annual_scan_df["capacity_utilization_gain"] = (
        annual_scan_df["annual_capacity_utilization_rate"]
        - baseline["annual_capacity_utilization_rate"]
    )

    annual_scan_df["curtailment_reduction_mwh"] = (
        baseline["annual_total_curtailment_mwh"]
        - annual_scan_df["annual_total_curtailment_mwh"]
    )

    annual_scan_df["unserved_reduction_mwh"] = (
        baseline["annual_total_unserved_load_mwh"]
        - annual_scan_df["annual_total_unserved_load_mwh"]
    )

    annual_scan_df["renewable_utilization_gain"] = (
        annual_scan_df["annual_renewable_utilization_ratio"]
        - baseline["annual_renewable_utilization_ratio"]
    )

    denominator = annual_scan_df["cost_increase_yuan_per_ton"] / 100.0

    annual_scan_df["production_gain_per_100yuan"] = np.where(
        denominator > 1e-9,
        annual_scan_df["production_gain_ton"] / denominator,
        np.nan,
    )

    annual_scan_df["curtailment_reduction_per_100yuan"] = np.where(
        denominator > 1e-9,
        annual_scan_df["curtailment_reduction_mwh"] / denominator,
        np.nan,
    )

    annual_scan_df["utilization_gain_pp_per_100yuan"] = np.where(
        denominator > 1e-9,
        annual_scan_df["capacity_utilization_gain"] * 100.0 / denominator,
        np.nan,
    )

    annual_scan_df["renewable_utilization_gain_pp_per_100yuan"] = np.where(
        denominator > 1e-9,
        annual_scan_df["renewable_utilization_gain"] * 100.0 / denominator,
        np.nan,
    )

    annual_scan_df["marginal_production_gain_ton"] = annual_scan_df[
        "annual_total_production_ton"
    ].diff()

    annual_scan_df["marginal_curtailment_reduction_mwh"] = (
        -annual_scan_df["annual_total_curtailment_mwh"].diff()
    )

    annual_scan_df["marginal_cost_increase_yuan_per_ton"] = annual_scan_df[
        "annual_avg_ton_cost_yuan_per_ton"
    ].diff()

    annual_scan_df["marginal_production_gain_per_100yuan"] = np.where(
        annual_scan_df["marginal_cost_increase_yuan_per_ton"] > 1e-9,
        annual_scan_df["marginal_production_gain_ton"]
        / (annual_scan_df["marginal_cost_increase_yuan_per_ton"] / 100.0),
        np.nan,
    )

    annual_scan_df["marginal_curtailment_reduction_per_100yuan"] = np.where(
        annual_scan_df["marginal_cost_increase_yuan_per_ton"] > 1e-9,
        annual_scan_df["marginal_curtailment_reduction_mwh"]
        / (annual_scan_df["marginal_cost_increase_yuan_per_ton"] / 100.0),
        np.nan,
    )

    # No subjective weighted score is used as the main decision criterion.
    # Recommendation rule:
    # 1. Candidate capacities must eliminate average unserved load.
    # 2. Among feasible candidates, select the maximum production gain per 100 yuan/t cost increase.
    # 3. If tied, prefer larger curtailment reduction per 100 yuan/t.
    # 4. If still tied, prefer smaller storage capacity.
    candidate_df = annual_scan_df[
        (annual_scan_df["storage_capacity_mwh"] > 0)
        & (annual_scan_df["mean_unserved_load_mwh"] <= 1e-8)
        & np.isfinite(annual_scan_df["production_gain_per_100yuan"])
    ].copy()

    if candidate_df.empty:
        candidate_df = annual_scan_df[
            (annual_scan_df["storage_capacity_mwh"] > 0)
            & np.isfinite(annual_scan_df["production_gain_per_100yuan"])
        ].copy()

    if candidate_df.empty:
        recommended_idx = annual_scan_df["annual_avg_ton_cost_yuan_per_ton"].idxmin()
    else:
        candidate_df = candidate_df.sort_values(
            by=[
                "production_gain_per_100yuan",
                "curtailment_reduction_per_100yuan",
                "storage_capacity_mwh",
            ],
            ascending=[False, False, True],
        )
        recommended_idx = candidate_df.index[0]

    annual_scan_df["is_recommended_by_composite"] = False
    annual_scan_df["is_recommended_by_unit_benefit"] = False
    annual_scan_df.loc[recommended_idx, "is_recommended_by_unit_benefit"] = True
    annual_scan_df.loc[recommended_idx, "is_recommended_by_composite"] = True
    annual_scan_df["recommendation_rule"] = (
        "max production gain per 100 yuan/t among zero-unserved candidates; "
        "curtailment reduction used as tie-breaker"
    )

    return annual_scan_df, hourly_by_capacity, summary_by_capacity

def main():
    raw_dir = PROJECT_ROOT / "data" / "raw"
    table_dir = PROJECT_ROOT / "outputs" / "tables"
    figure_dir = PROJECT_ROOT / "outputs" / "figures"

    table_dir.mkdir(parents=True, exist_ok=True)
    figure_dir.mkdir(parents=True, exist_ok=True)

    params = OffgridStorageParams()

    load_df = read_excel_by_prefix(raw_dir, "附件1")
    wind_scenario_df = read_excel_by_prefix(raw_dir, "附件3")
    pv_scenario_df = read_excel_by_prefix(raw_dir, "附件4")

    scenario_profiles = build_24_wind_pv_scenario_profiles(
        load_df=load_df,
        wind_df=wind_scenario_df,
        pv_df=pv_scenario_df,
    )

    print("=" * 88)
    print("Q4 off-grid and storage analysis started.")
    print("=" * 88)

    no_storage_hourly_df, no_storage_summary_df = run_offgrid_no_storage_for_scenarios(
        scenario_profiles=scenario_profiles,
        params=params,
    )

    no_storage_hourly_df.to_csv(
        table_dir / "q4_offgrid_no_storage_hourly_dispatch.csv",
        index=False,
        encoding="utf-8-sig",
    )

    no_storage_summary_df.to_csv(
        table_dir / "q4_offgrid_no_storage_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )

    no_storage_annual_df = summarize_offgrid_annual(
        no_storage_summary_df,
        scenario_days=15,
        mode="offgrid_no_storage",
    )

    no_storage_annual_df.to_csv(
        table_dir / "q4_offgrid_no_storage_annual_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )

    max_curtail_row = no_storage_summary_df.loc[
        no_storage_summary_df["curtailment_mwh"].idxmax()
    ]
    max_curtail_scenario_id = max_curtail_row["scenario_id"]

    max_curtail_profile = next(
        item["profile"]
        for item in scenario_profiles
        if item["scenario_id"] == max_curtail_scenario_id
    )

    print(
        f"Max curtailment scenario: {max_curtail_scenario_id} | "
        f"Curtailment: {max_curtail_row['curtailment_mwh']:.2f} MWh"
    )

    scan_hourly_df, scan_summary_df, saturation_storage = scan_storage_capacity(
        profile=max_curtail_profile,
        params=params,
        step_mwh=20.0,
    )

    scan_hourly_df.to_csv(
        table_dir / "q4_storage_capacity_scan_hourly.csv",
        index=False,
        encoding="utf-8-sig",
    )

    scan_summary_df.to_csv(
        table_dir / "q4_storage_capacity_scan_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )

    saturation_capacity = float(saturation_storage["storage_capacity_mwh"])

    print(
        f"Saturation reference capacity: {saturation_capacity:.0f} MWh | "
        f"Daily production: {saturation_storage['total_ammonia_output_ton']:.2f} t"
    )

    capacities = sorted(scan_summary_df["storage_capacity_mwh"].unique().astype(float).tolist())

    annual_capacity_scan_df, hourly_by_capacity, summary_by_capacity = build_annual_capacity_scan(
        scenario_profiles=scenario_profiles,
        capacities=capacities,
        params=params,
        scenario_days=15,
    )

    annual_capacity_scan_df.to_csv(
        table_dir / "q4_storage_capacity_annual_scan.csv",
        index=False,
        encoding="utf-8-sig",
    )

    recommended_row = annual_capacity_scan_df[
        annual_capacity_scan_df["is_recommended_by_composite"]
    ].iloc[0]

    recommended_storage_capacity = float(recommended_row["storage_capacity_mwh"])

    print(
        f"Technical-economic recommended capacity: {recommended_storage_capacity:.0f} MWh | "
        f"Annual ton cost: {recommended_row['annual_avg_ton_cost_yuan_per_ton']:.2f} yuan/tNH3 | "
        f"Annual production: {recommended_row['annual_total_production_ton']:.2f} t | "
        f"Production gain per 100 yuan/t: {recommended_row['production_gain_per_100yuan']:.2f} t | "
        f"Curtailment reduction per 100 yuan/t: {recommended_row['curtailment_reduction_per_100yuan']:.2f} MWh"
    )

    storage_hourly_df = hourly_by_capacity[recommended_storage_capacity]
    storage_summary_df = summary_by_capacity[recommended_storage_capacity]

    storage_hourly_df.to_csv(
        table_dir / "q4_storage_hourly_dispatch.csv",
        index=False,
        encoding="utf-8-sig",
    )

    storage_summary_df.to_csv(
        table_dir / "q4_storage_scenario_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )

    storage_annual_df = summarize_offgrid_annual(
        storage_summary_df,
        scenario_days=15,
        mode="offgrid_with_storage",
    )

    storage_annual_df.to_csv(
        table_dir / "q4_storage_annual_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )

    (
        grid_same_hourly_df,
        grid_same_summary_df,
        grid_vs_offgrid_annual_df,
    ) = run_grid_connected_same_production_comparison(
        scenario_profiles=scenario_profiles,
        offgrid_storage_summary_df=storage_summary_df,
        scenario_days=15,
    )

    grid_same_hourly_df.to_csv(
        table_dir / "q4_grid_same_production_hourly_dispatch.csv",
        index=False,
        encoding="utf-8-sig",
    )

    grid_same_summary_df.to_csv(
        table_dir / "q4_grid_same_production_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )

    grid_vs_offgrid_annual_df.to_csv(
        table_dir / "q4_grid_vs_offgrid_annual_comparison.csv",
        index=False,
        encoding="utf-8-sig",
    )

    plot_q4_no_storage_production_bar(no_storage_summary_df, figure_dir)
    plot_q4_no_storage_curtailment_unserved(no_storage_summary_df, figure_dir)
    plot_q4_storage_capacity_scan(scan_summary_df, figure_dir)
    plot_q4_storage_annual_tradeoff(annual_capacity_scan_df, figure_dir)
    plot_q4_storage_benefit_per_cost(annual_capacity_scan_df, figure_dir)

    plot_q4_storage_dispatch_curve(
        storage_hourly_df,
        figure_dir,
        scenario_id=max_curtail_scenario_id,
    )

    plot_q4_storage_production_bar(
        no_storage_summary_df,
        storage_summary_df,
        figure_dir,
    )

    plot_q4_wind_pv_utilization_improvement(
        no_storage_summary_df,
        storage_summary_df,
        figure_dir,
    )

    plot_q4_grid_vs_offgrid_cost_comparison(
        grid_vs_offgrid_annual_df,
        figure_dir,
    )

    print("=" * 88)
    print("Q4 off-grid and storage analysis finished.")
    print("=" * 88)

    print("[Q4(1)] Off-grid without storage annual-equivalent summary")
    print(
        no_storage_annual_df[
            [
                "annual_total_production_ton",
                "annual_capacity_utilization_rate",
                "annual_avg_ton_cost_yuan_per_ton",
                "mean_curtailment_mwh",
                "mean_unserved_load_mwh",
                "mean_renewable_utilization_ratio",
                "mean_energy_self_sufficiency_ratio",
            ]
        ].to_string(index=False)
    )

    print("-" * 88)
    print("[Q4(2)] Off-grid with technical-economic recommended storage")
    print(
        storage_annual_df[
            [
                "annual_total_production_ton",
                "annual_capacity_utilization_rate",
                "annual_avg_ton_cost_yuan_per_ton",
                "mean_curtailment_mwh",
                "mean_unserved_load_mwh",
                "mean_renewable_utilization_ratio",
                "mean_energy_self_sufficiency_ratio",
            ]
        ].to_string(index=False)
    )

    print("-" * 88)
    print("[Q4 Storage Capacity Annual Scan]")
    display_cols = [
        "storage_capacity_mwh",
        "annual_total_production_ton",
        "annual_capacity_utilization_rate",
        "annual_avg_ton_cost_yuan_per_ton",
        "annual_total_curtailment_mwh",
        "production_gain_per_100yuan",
        "curtailment_reduction_per_100yuan",
        "utilization_gain_pp_per_100yuan",
        "is_recommended_by_unit_benefit",
    ]
    print(
        annual_capacity_scan_df[display_cols]
        .to_string(index=False)
    )

    print("-" * 88)
    print("[Q4(3)] Grid-connected vs off-grid same-production comparison")
    print(
        grid_vs_offgrid_annual_df[
            [
                "mode",
                "annual_total_production_ton",
                "annual_avg_ton_cost_yuan_per_ton",
                "annual_capacity_utilization_rate",
            ]
        ].to_string(index=False)
    )

    print("=" * 88)
    print(f"Tables saved to: {table_dir}")
    print(f"Figures saved to: {figure_dir}")
    print("=" * 88)


if __name__ == "__main__":
    main()
