from pathlib import Path
import sys
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT / "src"))

from dgcup.data.load_excel import read_excel_by_prefix
from dgcup.data.build_scenarios import build_24_wind_pv_scenario_profiles
from dgcup.optimization.q3_continuous_dispatch import (
    ContinuousDispatchParams,
    run_production_set_continuous,
    summarize_annual_results_continuous,
    build_q3_vs_q2_comparison,
)
from dgcup.visualization.q3_plots import (
    plot_q3_representative_dispatch_curve,
    plot_q3_scenario_cost_boxplot,
    plot_q3_satisfaction_stacked_bar,
    plot_q3_annual_avg_cost,
    plot_q3_vs_q2_cost_reduction,
    plot_q3_vs_q2_grid_interaction,
)


PRODUCTIONS = (72, 63, 54, 45, 36)


def main():
    raw_dir = PROJECT_ROOT / "data" / "raw"
    table_dir = PROJECT_ROOT / "outputs" / "tables"
    figure_dir = PROJECT_ROOT / "outputs" / "figures"

    table_dir.mkdir(parents=True, exist_ok=True)
    figure_dir.mkdir(parents=True, exist_ok=True)

    params = ContinuousDispatchParams()

    load_df = read_excel_by_prefix(raw_dir, "附件1")
    wind_scenario_df = read_excel_by_prefix(raw_dir, "附件3")
    pv_scenario_df = read_excel_by_prefix(raw_dir, "附件4")

    scenario_profiles = build_24_wind_pv_scenario_profiles(
        load_df=load_df,
        wind_df=wind_scenario_df,
        pv_df=pv_scenario_df,
    )

    all_hourly_list = []
    all_summary_list = []

    total_tasks = len(scenario_profiles) * len(PRODUCTIONS)
    finished_tasks = 0

    print("=" * 88)
    print("Q3 continuous hydrogen-ammonia dispatch started.")
    print("=" * 88)

    for scenario in scenario_profiles:
        hourly_df, summary_df = run_production_set_continuous(
            profile=scenario["profile"],
            productions=PRODUCTIONS,
            params=params,
        )

        finished_tasks += len(PRODUCTIONS)
        print(
            f"Finished scenario {scenario['scenario_id']} "
            f"({finished_tasks}/{total_tasks} MILPs)"
        )

        all_hourly_list.append(hourly_df)
        all_summary_list.append(summary_df)

    all_hourly_df = pd.concat(all_hourly_list, ignore_index=True)
    all_summary_df = pd.concat(all_summary_list, ignore_index=True)

    all_hourly_df.to_csv(
        table_dir / "q3_all_scenarios_hourly_dispatch.csv",
        index=False,
        encoding="utf-8-sig",
    )

    all_summary_df.to_csv(
        table_dir / "q3_all_scenarios_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )

    annual_summary_df = summarize_annual_results_continuous(
        scenario_summary_df=all_summary_df,
        scenario_days=15,
    )

    annual_summary_df.to_csv(
        table_dir / "q3_annual_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )

    comparison_df = None
    q2_annual_path = table_dir / "q2_annual_summary.csv"

    if q2_annual_path.exists():
        q2_annual_df = pd.read_csv(q2_annual_path)
        comparison_df = build_q3_vs_q2_comparison(
            q2_annual_df=q2_annual_df,
            q3_annual_df=annual_summary_df,
        )
        comparison_df.to_csv(
            table_dir / "q3_vs_q2_comparison.csv",
            index=False,
            encoding="utf-8-sig",
        )
    else:
        print("Warning: q2_annual_summary.csv not found. Q3 vs Q2 comparison skipped.")

    # Figures
    plot_q3_representative_dispatch_curve(all_hourly_df, figure_dir, production_ton=54.0)
    plot_q3_scenario_cost_boxplot(all_summary_df, figure_dir)
    plot_q3_satisfaction_stacked_bar(annual_summary_df, figure_dir)
    plot_q3_annual_avg_cost(annual_summary_df, figure_dir)

    if comparison_df is not None:
        plot_q3_vs_q2_cost_reduction(comparison_df, figure_dir)
        plot_q3_vs_q2_grid_interaction(comparison_df, figure_dir)

    best_annual = annual_summary_df.loc[
        annual_summary_df["annual_avg_ton_cost_yuan_per_ton"].idxmin()
    ]

    print("=" * 88)
    print("Q3 continuous hydrogen-ammonia dispatch finished.")
    print("=" * 88)
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
        "mean_grid_purchase_mwh",
        "mean_grid_export_mwh",
        "mean_on_hours",
        "mean_running_power_ratio",
    ]

    print(
        annual_summary_df[annual_cols]
        .sort_values("production_ton", ascending=False)
        .to_string(index=False)
    )

    if comparison_df is not None:
        print("-" * 88)
        print("[Q3 vs Q2] Annual-equivalent comparison")
        compare_cols = [
            "production_ton",
            "q2_annual_avg_ton_cost_yuan_per_ton",
            "q3_annual_avg_ton_cost_yuan_per_ton",
            "cost_reduction_yuan_per_ton",
            "cost_reduction_ratio",
            "q2_all_satisfied_days",
            "q3_all_satisfied_days",
            "grid_purchase_reduction_mwh",
            "grid_export_reduction_mwh",
        ]

        print(
            comparison_df[compare_cols]
            .sort_values("production_ton", ascending=False)
            .to_string(index=False)
        )

    print("=" * 88)
    print(f"Tables saved to: {table_dir}")
    print(f"Figures saved to: {figure_dir}")
    print("=" * 88)


if __name__ == "__main__":
    main()
