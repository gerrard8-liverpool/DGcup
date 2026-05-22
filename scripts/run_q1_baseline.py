from pathlib import Path
import sys
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT / "src"))

from dgcup.data.load_excel import read_excel_by_prefix
from dgcup.core.power_balance import build_q1_power_balance
from dgcup.core.indicators import calculate_green_indicators
from dgcup.core.cost import calculate_q1_cost
from dgcup.visualization.plots import (
    plot_q1_power_balance,
    plot_q1_grid_interaction,
    plot_q1_indicators,
    plot_q1_cost_breakdown,
)


def main():
    raw_dir = PROJECT_ROOT / "data" / "raw"
    table_dir = PROJECT_ROOT / "outputs" / "tables"
    figure_dir = PROJECT_ROOT / "outputs" / "figures"

    table_dir.mkdir(parents=True, exist_ok=True)
    figure_dir.mkdir(parents=True, exist_ok=True)

    load_df = read_excel_by_prefix(raw_dir, "附件1")
    renewable_df = read_excel_by_prefix(raw_dir, "附件2")

    hourly = build_q1_power_balance(load_df, renewable_df)

    indicators = calculate_green_indicators(hourly)
    cost_summary = calculate_q1_cost(hourly)

    summary = {**indicators, **cost_summary}

    hourly.to_csv(table_dir / "q1_hourly_results.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([summary]).to_csv(
        table_dir / "q1_summary.csv", index=False, encoding="utf-8-sig"
    )

    plot_q1_power_balance(hourly, figure_dir)
    plot_q1_grid_interaction(hourly, figure_dir)
    plot_q1_indicators(summary, figure_dir)
    plot_q1_cost_breakdown(cost_summary, figure_dir)

    print("=" * 80)
    print("Q1 baseline calculation finished.")
    print("=" * 80)
    print(f"Total load: {summary['total_load_mwh']:.4f} MWh")
    print(f"Renewable generation: {summary['renewable_generation_mwh']:.4f} MWh")
    print(f"Grid purchase: {summary['grid_purchase_mwh']:.4f} MWh")
    print(f"Grid export: {summary['grid_export_mwh']:.4f} MWh")
    print("-" * 80)
    print(
        f"Renewable self-use ratio: {summary['renewable_self_use_ratio']:.4%} "
        f"Pass: {summary['renewable_self_use_pass']}"
    )
    print(
        f"Green power ratio: {summary['green_power_ratio']:.4%} "
        f"Pass: {summary['green_power_pass']}"
    )
    print(
        f"Renewable export ratio: {summary['renewable_export_ratio']:.4%} "
        f"Pass: {summary['renewable_export_pass']}"
    )
    print("-" * 80)
    print(f"Total cost: {summary['total_cost_yuan']:.2f} yuan")
    print(
        f"Ton-ammonia cost: "
        f"{summary['ton_ammonia_cost_yuan_per_ton']:.2f} yuan/tNH3"
    )
    print("=" * 80)
    print(f"Hourly table saved to: {table_dir / 'q1_hourly_results.csv'}")
    print(f"Summary table saved to: {table_dir / 'q1_summary.csv'}")
    print(f"Figures saved to: {figure_dir}")


if __name__ == "__main__":
    main()
