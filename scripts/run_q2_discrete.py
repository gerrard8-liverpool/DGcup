from pathlib import Path
import sys
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT / "src"))

from dgcup.data.load_excel import read_excel_by_prefix
from dgcup.data.build_scenarios import (
    build_typical_scenario_profile,
    build_24_wind_pv_scenario_profiles,
)
from dgcup.optimization.q2_discrete_dispatch import (
    DiscreteDispatchParams,
    run_production_set,
    summarize_annual_results,
)
from dgcup.visualization.q2_plots import (
    plot_q2_typical_schedule_gantt,
    plot_q2_typical_cost_vs_production,
    plot_q2_typical_green_indicators,
    plot_q2_scenario_cost_boxplot,
    plot_q2_satisfaction_stacked_bar,
    plot_q2_annual_avg_cost,
)


PRODUCTIONS = (72, 63, 54, 45, 36)


def main():
    raw_dir = PROJECT_ROOT / "data" / "raw"
    table_dir = PROJECT_ROOT / "outputs" / "tables"
    figure_dir = PROJECT_ROOT / "outputs" / "figures"

    table_dir.mkdir(parents=True, exist_ok=True)
    figure_dir.mkdir(parents=True, exist_ok=True)

    params = DiscreteDispatchParams()

    load_df = read_excel_by_prefix(raw_dir, "附件1")
    typical_renewable_df = read_excel_by_prefix(raw_dir, "附件2")
    wind_scenario_df = read_excel_by_prefix(raw_dir, "附件3")
    pv_scenario_df = read_excel_by_prefix(raw_dir, "附件4")

    # ============================================================
    # Q2(1): typical wind-PV scenario
    # ============================================================
    typical_profile = build_typical_scenario_profile(
        load_df=load_df,
        renewable_df=typical_renewable_df,
    )

    typical_hourly_df, typical_summary_df = run_production_set(
        profile=typical_profile,
        productions=PRODUCTIONS,
        params=params,
    )

    typical_hourly_df.to_csv(
        table_dir / "q2_typical_hourly_dispatch.csv",
        index=False,
        encoding="utf-8-sig",
    )

    typical_summary_df.to_csv(
        table_dir / "q2_typical_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )

    # ============================================================
    # Q2(2): 24 wind-PV combined scenarios
    # ============================================================
    scenario_profiles = build_24_wind_pv_scenario_profiles(
        load_df=load_df,
        wind_df=wind_scenario_df,
        pv_df=pv_scenario_df,
    )

    all_hourly_list = []
    all_summary_list = []

    for scenario in scenario_profiles:
        hourly_df, summary_df = run_production_set(
            profile=scenario["profile"],
            productions=PRODUCTIONS,
            params=params,
        )
        all_hourly_list.append(hourly_df)
        all_summary_list.append(summary_df)

    all_hourly_df = pd.concat(all_hourly_list, ignore_index=True)
    all_summary_df = pd.concat(all_summary_list, ignore_index=True)

    all_hourly_df.to_csv(
        table_dir / "q2_all_scenarios_hourly_dispatch.csv",
        index=False,
        encoding="utf-8-sig",
    )

    all_summary_df.to_csv(
        table_dir / "q2_all_scenarios_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )

    annual_summary_df = summarize_annual_results(
        scenario_summary_df=all_summary_df,
        scenario_days=15,
    )

    annual_summary_df.to_csv(
        table_dir / "q2_annual_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )

    # ============================================================
    # Figures
    # ============================================================
    plot_q2_typical_schedule_gantt(typical_hourly_df, figure_dir)
    plot_q2_typical_cost_vs_production(typical_summary_df, figure_dir)
    plot_q2_typical_green_indicators(typical_summary_df, figure_dir)
    plot_q2_scenario_cost_boxplot(all_summary_df, figure_dir)
    plot_q2_satisfaction_stacked_bar(annual_summary_df, figure_dir)
    plot_q2_annual_avg_cost(annual_summary_df, figure_dir)

    # ============================================================
    # Console summary
    # ============================================================
    best_typical = typical_summary_df.loc[
        typical_summary_df["ton_cost_yuan_per_ton"].idxmin()
    ]

    best_annual = annual_summary_df.loc[
        annual_summary_df["annual_avg_ton_cost_yuan_per_ton"].idxmin()
    ]

    print("=" * 88)
    print("Q2 discrete ammonia-production dispatch finished.")
    print("=" * 88)
    print("[Q2(1)] Typical wind-PV scenario")
    print(
        f"Best daily production: {best_typical['production_ton']:.0f} t/day | "
        f"Ton cost: {best_typical['ton_cost_yuan_per_ton']:.2f} yuan/tNH3 | "
        f"Satisfaction: {best_typical['satisfaction_type']}"
    )
    print("-" * 88)

    display_cols = [
        "production_ton",
        "on_hours",
        "ton_cost_yuan_per_ton",
        "grid_purchase_mwh",
        "grid_export_mwh",
        "renewable_self_use_ratio",
        "green_power_ratio",
        "renewable_export_ratio",
        "satisfaction_type",
    ]

    print(
        typical_summary_df[display_cols]
        .sort_values("production_ton", ascending=False)
        .to_string(index=False)
    )

    print("-" * 88)
    print("[Q2(2)] 24 wind-PV scenarios annual-equivalent result")
    print(
        f"Best annual-equivalent production: {best_annual['production_ton']:.0f} t/day | "
        f"Annual average ton cost: "
        f"{best_annual['annual_avg_ton_cost_yuan_per_ton']:.2f} yuan/tNH3"
    )

    annual_cols = [
        "production_ton",
        "annual_avg_ton_cost_yuan_per_ton",
        "all_satisfied_days",
        "partially_satisfied_days",
        "none_satisfied_days",
    ]

    print(
        annual_summary_df[annual_cols]
        .sort_values("production_ton", ascending=False)
        .to_string(index=False)
    )

    print("=" * 88)
    print(f"Tables saved to: {table_dir}")
    print(f"Figures saved to: {figure_dir}")
    print("=" * 88)


if __name__ == "__main__":
    main()
