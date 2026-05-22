from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
import sys
import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT / "src"))
sys.path.append(str(PROJECT_ROOT))

from dgcup.data.load_excel import read_excel_by_prefix
from dgcup.data.build_scenarios import build_24_wind_pv_scenario_profiles
from dgcup.optimization.q4_storage_dispatch import OffgridStorageParams

from scripts.run_q4_knee_analysis import (
    parse_capacities,
    annual_capacity_scan,
    build_knee_summary,
    get_final_capacity,
)


def setup_chinese_font() -> None:
    candidates = [
        "Microsoft YaHei",
        "SimHei",
        "SimSun",
        "Noto Sans CJK SC",
        "Source Han Sans SC",
        "Arial Unicode MS",
    ]
    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in candidates:
        if name in available:
            plt.rcParams["font.sans-serif"] = [name]
            break
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["figure.dpi"] = 120
    plt.rcParams["savefig.dpi"] = 300


def build_weight_cases(base: OffgridStorageParams) -> list[dict]:
    """
    Q4 MILP objective weight sensitivity cases.

    The objective is a weighted linear approximation of dispatch priority:
    1) penalize unserved load;
    2) reward ammonia production;
    3) penalize curtailment.

    These cases test whether the final storage capacity recommendation is
    caused by one specific objective weight setting.
    """
    return [
        {
            "case_name": "base",
            "unserved_penalty_multiplier": 1.0,
            "production_reward_multiplier": 1.0,
            "curtailment_penalty_multiplier": 1.0,
            "params": base,
        },
        {
            "case_name": "unserved_penalty_0p5",
            "unserved_penalty_multiplier": 0.5,
            "production_reward_multiplier": 1.0,
            "curtailment_penalty_multiplier": 1.0,
            "params": replace(
                base,
                unserved_penalty_yuan_per_mwh=base.unserved_penalty_yuan_per_mwh * 0.5,
            ),
        },
        {
            "case_name": "unserved_penalty_2p0",
            "unserved_penalty_multiplier": 2.0,
            "production_reward_multiplier": 1.0,
            "curtailment_penalty_multiplier": 1.0,
            "params": replace(
                base,
                unserved_penalty_yuan_per_mwh=base.unserved_penalty_yuan_per_mwh * 2.0,
            ),
        },
        {
            "case_name": "production_reward_0p8",
            "unserved_penalty_multiplier": 1.0,
            "production_reward_multiplier": 0.8,
            "curtailment_penalty_multiplier": 1.0,
            "params": replace(
                base,
                production_reward_yuan_per_unit_ratio=base.production_reward_yuan_per_unit_ratio * 0.8,
            ),
        },
        {
            "case_name": "production_reward_1p2",
            "unserved_penalty_multiplier": 1.0,
            "production_reward_multiplier": 1.2,
            "curtailment_penalty_multiplier": 1.0,
            "params": replace(
                base,
                production_reward_yuan_per_unit_ratio=base.production_reward_yuan_per_unit_ratio * 1.2,
            ),
        },
        {
            "case_name": "curtailment_penalty_0p5",
            "unserved_penalty_multiplier": 1.0,
            "production_reward_multiplier": 1.0,
            "curtailment_penalty_multiplier": 0.5,
            "params": replace(
                base,
                curtailment_penalty_yuan_per_mwh=base.curtailment_penalty_yuan_per_mwh * 0.5,
            ),
        },
        {
            "case_name": "curtailment_penalty_2p0",
            "unserved_penalty_multiplier": 1.0,
            "production_reward_multiplier": 1.0,
            "curtailment_penalty_multiplier": 2.0,
            "params": replace(
                base,
                curtailment_penalty_yuan_per_mwh=base.curtailment_penalty_yuan_per_mwh * 2.0,
            ),
        },
    ]


def summarize_one_case(
    case_name: str,
    params: OffgridStorageParams,
    scenario_profiles: list[dict],
    capacities: list[float],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    scan_df = annual_capacity_scan(
        scenario_profiles=scenario_profiles,
        params=params,
        capacities=capacities,
    )

    knee_summary, tier_summary = build_knee_summary(scan_df)
    rec_cap, lower, upper = get_final_capacity(knee_summary)

    rec_row = scan_df.loc[
        scan_df["storage_capacity_mwh"].sub(rec_cap).abs().idxmin()
    ]

    saturation_row = tier_summary[
        tier_summary["tier"] == "technical_saturation"
    ]

    saturation_cap = (
        float(saturation_row["capacity_mwh"].iloc[0])
        if not saturation_row.empty
        else np.nan
    )

    row = {
        "case_name": case_name,
        "recommended_capacity_mwh": rec_cap,
        "recommended_interval_lower_mwh": lower,
        "recommended_interval_upper_mwh": upper,
        "technical_saturation_capacity_mwh": saturation_cap,
        "recommended_annual_ton_cost_yuan_per_ton": float(
            rec_row["annual_avg_ton_cost_yuan_per_ton"]
        ),
        "recommended_annual_production_ton": float(
            rec_row["annual_total_production_ton"]
        ),
        "recommended_capacity_utilization_rate": float(
            rec_row["annual_capacity_utilization_rate"]
        ),
        "recommended_total_curtailment_mwh": float(
            rec_row["annual_total_curtailment_mwh"]
        ),
        "recommended_production_gain_ton": float(
            rec_row["production_gain_ton"]
        ),
        "recommended_curtailment_reduction_mwh": float(
            rec_row["curtailment_reduction_mwh"]
        ),
    }

    scan_df["case_name"] = case_name
    knee_summary["case_name"] = case_name
    tier_summary["case_name"] = case_name

    return scan_df, knee_summary, tier_summary, row


def plot_recommended_capacity(summary_df: pd.DataFrame, figure_dir: Path) -> None:
    setup_chinese_font()

    df = summary_df.copy().reset_index(drop=True)

    fig, ax = plt.subplots(figsize=(12.5, 6.8))

    x = np.arange(len(df))
    bars = ax.bar(
        x,
        df["recommended_capacity_mwh"],
        width=0.72,
        alpha=0.86,
        label="权重扰动下工程推荐容量",
    )

    ax.axhspan(
        110,
        115,
        alpha=0.16,
        label="基准拐点共识区间 110–115 MWh",
    )
    ax.axhline(
        115,
        linestyle="--",
        linewidth=2.2,
        label="基准工程推荐容量 115 MWh",
    )

    for i, val in enumerate(df["recommended_capacity_mwh"]):
        ax.text(
            i,
            val + 1.6,
            f"{val:.0f}",
            ha="center",
            va="bottom",
            fontsize=10,
        )

    ax.set_xticks(x)
    ax.set_xticklabels(df["case_name"], rotation=35, ha="right")
    ax.set_ylabel("储能容量 / MWh")
    ax.set_title("问题四：目标权重敏感性下的储能工程推荐容量")
    ax.set_ylim(0, max(130, df["recommended_capacity_mwh"].max() + 20))
    ax.grid(axis="y", alpha=0.25)
    ax.legend(loc="best", framealpha=0.95)

    note = (
        "说明：各权重扰动情形均使用与主 Q4 拐点分析一致的推荐规则，"
        "即取年制氨量提升与弃电削减拐点共识区间的上界作为工程推荐容量。"
    )

    ax.text(
        0.5,
        -0.32,
        note,
        transform=ax.transAxes,
        ha="center",
        va="top",
        fontsize=10.5,
        bbox=dict(
            boxstyle="round,pad=0.35",
            facecolor="white",
            edgecolor="#B0B0B0",
            alpha=0.95,
        ),
    )

    plt.tight_layout()
    plt.savefig(
        figure_dir / "q4_weight_sensitivity_recommended_capacity.png",
        bbox_inches="tight",
    )
    plt.close(fig)


def plot_cost_production_optional(summary_df: pd.DataFrame, figure_dir: Path) -> None:
    setup_chinese_font()

    df = summary_df.copy().reset_index(drop=True)
    x = np.arange(len(df))

    fig, ax1 = plt.subplots(figsize=(12.5, 6.8))
    ax2 = ax1.twinx()

    ax1.plot(
        x,
        df["recommended_annual_ton_cost_yuan_per_ton"],
        marker="o",
        linewidth=2.2,
        label="推荐容量下吨氨成本",
    )
    ax2.plot(
        x,
        df["recommended_annual_production_ton"],
        marker="s",
        linestyle="--",
        linewidth=2.2,
        label="推荐容量下年制氨量",
    )

    ax1.set_xticks(x)
    ax1.set_xticklabels(df["case_name"], rotation=35, ha="right")
    ax1.set_ylabel("吨氨成本 / 元·t$^{-1}$")
    ax2.set_ylabel("年制氨量 / t")
    ax1.set_title("问题四：目标权重扰动下推荐方案的成本与产量")
    ax1.grid(alpha=0.25)

    cost_min = df["recommended_annual_ton_cost_yuan_per_ton"].min()
    cost_max = df["recommended_annual_ton_cost_yuan_per_ton"].max()
    prod_min = df["recommended_annual_production_ton"].min()
    prod_max = df["recommended_annual_production_ton"].max()

    if abs(cost_max - cost_min) < 1e-8:
        ax1.set_ylim(cost_min - 20, cost_max + 20)
    if abs(prod_max - prod_min) < 1e-8:
        ax2.set_ylim(prod_min - 20, prod_max + 20)

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="best", framealpha=0.95)

    plt.tight_layout()
    plt.savefig(
        figure_dir / "q4_weight_sensitivity_cost_production.png",
        bbox_inches="tight",
    )
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--step", type=float, default=5.0)
    parser.add_argument("--max-capacity", type=float, default=220.0)
    args = parser.parse_args()

    raw_dir = PROJECT_ROOT / "data" / "raw"
    table_dir = PROJECT_ROOT / "outputs" / "tables"
    figure_dir = PROJECT_ROOT / "outputs" / "figures"

    table_dir.mkdir(parents=True, exist_ok=True)
    figure_dir.mkdir(parents=True, exist_ok=True)

    load_df = read_excel_by_prefix(raw_dir, "附件1")
    wind_df = read_excel_by_prefix(raw_dir, "附件3")
    pv_df = read_excel_by_prefix(raw_dir, "附件4")

    scenario_profiles = build_24_wind_pv_scenario_profiles(
        load_df=load_df,
        wind_df=wind_df,
        pv_df=pv_df,
    )

    capacities = parse_capacities(args.max_capacity, args.step)

    base_params = OffgridStorageParams()
    cases = build_weight_cases(base_params)

    summary_rows = []
    all_scan = []
    all_knee = []
    all_tier = []

    print("=" * 96)
    print("Q4 objective-weight sensitivity analysis started.")
    print("=" * 96)

    for case in cases:
        print(f"[Q4 objective-weight sensitivity] case = {case['case_name']}")

        scan_df, knee_df, tier_df, summary_row = summarize_one_case(
            case_name=case["case_name"],
            params=case["params"],
            scenario_profiles=scenario_profiles,
            capacities=capacities,
        )

        summary_row["unserved_penalty_multiplier"] = case["unserved_penalty_multiplier"]
        summary_row["production_reward_multiplier"] = case["production_reward_multiplier"]
        summary_row["curtailment_penalty_multiplier"] = case["curtailment_penalty_multiplier"]

        summary_rows.append(summary_row)
        all_scan.append(scan_df)
        all_knee.append(knee_df)
        all_tier.append(tier_df)

    summary_df = pd.DataFrame(summary_rows)

    base_rec = float(
        summary_df.loc[
            summary_df["case_name"] == "base",
            "recommended_capacity_mwh",
        ].iloc[0]
    )

    summary_df["capacity_deviation_from_base_mwh"] = (
        summary_df["recommended_capacity_mwh"] - base_rec
    )

    summary_df["same_as_base_recommendation"] = (
        summary_df["capacity_deviation_from_base_mwh"].abs() <= 1e-9
    )

    summary_df["within_baseline_consensus_interval"] = summary_df[
        "recommended_capacity_mwh"
    ].between(110.0, 115.0, inclusive="both")

    scan_all_df = pd.concat(all_scan, ignore_index=True)
    knee_all_df = pd.concat(all_knee, ignore_index=True)
    tier_all_df = pd.concat(all_tier, ignore_index=True)

    summary_path = table_dir / "q4_weight_sensitivity_summary.csv"
    knee_path = table_dir / "q4_weight_sensitivity_knee_detail.csv"
    tier_path = table_dir / "q4_weight_sensitivity_tier_detail.csv"
    scan_path = table_dir / "q4_weight_sensitivity_capacity_scan.csv"

    summary_df.to_csv(summary_path, index=False, encoding="utf-8-sig")
    knee_all_df.to_csv(knee_path, index=False, encoding="utf-8-sig")
    tier_all_df.to_csv(tier_path, index=False, encoding="utf-8-sig")
    scan_all_df.to_csv(scan_path, index=False, encoding="utf-8-sig")

    plot_recommended_capacity(summary_df, figure_dir)
    plot_cost_production_optional(summary_df, figure_dir)

    print("=" * 96)
    print("Q4 objective-weight sensitivity analysis finished.")
    print("=" * 96)
    print(
        summary_df[
            [
                "case_name",
                "recommended_interval_lower_mwh",
                "recommended_interval_upper_mwh",
                "recommended_capacity_mwh",
                "technical_saturation_capacity_mwh",
                "capacity_deviation_from_base_mwh",
                "same_as_base_recommendation",
                "recommended_annual_ton_cost_yuan_per_ton",
                "recommended_annual_production_ton",
            ]
        ].to_string(index=False)
    )
    print("=" * 96)
    print(f"Summary saved to: {summary_path}")
    print(f"Knee detail saved to: {knee_path}")
    print(f"Tier detail saved to: {tier_path}")
    print(f"Full scan saved to: {scan_path}")
    print(f"Figures saved to: {figure_dir}")
    print("=" * 96)


if __name__ == "__main__":
    main()
