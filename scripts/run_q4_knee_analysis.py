from __future__ import annotations

import argparse
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

from dgcup.data.load_excel import read_excel_by_prefix
from dgcup.data.build_scenarios import build_24_wind_pv_scenario_profiles
from dgcup.optimization.q4_storage_dispatch import (
    OffgridStorageParams,
    run_offgrid_storage_for_scenarios,
    summarize_offgrid_annual,
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


def parse_capacities(max_capacity: float, step: float) -> list[float]:
    values = np.arange(0.0, max_capacity + 0.5 * step, step)
    return [float(x) for x in values]


def annual_capacity_scan(
    scenario_profiles: list[dict],
    params: OffgridStorageParams,
    capacities: list[float],
) -> pd.DataFrame:
    scenario_days = 360.0 / len(scenario_profiles)
    rows = []

    for cap in capacities:
        print(f"[Q4 knee scan] capacity = {cap:.2f} MWh")

        _, summary_df = run_offgrid_storage_for_scenarios(
            scenario_profiles=scenario_profiles,
            storage_capacity_mwh=cap,
            params=params,
        )

        annual = summarize_offgrid_annual(
            summary_df=summary_df,
            scenario_days=scenario_days,
            mode="offgrid_storage_capacity_scan",
        )

        row = annual.iloc[0].to_dict()
        row["storage_capacity_mwh"] = cap
        rows.append(row)

    df = pd.DataFrame(rows).sort_values("storage_capacity_mwh").reset_index(drop=True)

    base = df.iloc[0]

    df["cost_increase_yuan_per_ton"] = (
        df["annual_avg_ton_cost_yuan_per_ton"]
        - base["annual_avg_ton_cost_yuan_per_ton"]
    )

    df["production_gain_ton"] = (
        df["annual_total_production_ton"]
        - base["annual_total_production_ton"]
    )

    df["curtailment_reduction_mwh"] = (
        base["annual_total_curtailment_mwh"]
        - df["annual_total_curtailment_mwh"]
    )

    df["capacity_utilization_gain_pct"] = (
        df["annual_capacity_utilization_rate"]
        - base["annual_capacity_utilization_rate"]
    ) * 100.0

    df["delta_capacity_mwh"] = df["storage_capacity_mwh"].diff()
    df["delta_cost_yuan_per_ton"] = df["annual_avg_ton_cost_yuan_per_ton"].diff()
    df["delta_production_ton"] = df["annual_total_production_ton"].diff()
    df["delta_curtailment_reduction_mwh"] = df["curtailment_reduction_mwh"].diff()

    denom = df["delta_cost_yuan_per_ton"] / 100.0

    df["marginal_production_gain_per_100yuan"] = np.where(
        denom > 1e-9,
        df["delta_production_ton"] / denom,
        np.nan,
    )

    df["marginal_curtailment_reduction_per_100yuan"] = np.where(
        denom > 1e-9,
        df["delta_curtailment_reduction_mwh"] / denom,
        np.nan,
    )

    return df


def normalize(arr: np.ndarray) -> np.ndarray:
    arr = np.asarray(arr, dtype=float)
    vmin = np.nanmin(arr)
    vmax = np.nanmax(arr)
    if not np.isfinite(vmin) or not np.isfinite(vmax) or abs(vmax - vmin) < 1e-12:
        return np.zeros_like(arr)
    return (arr - vmin) / (vmax - vmin)


def knee_by_chord_distance(df: pd.DataFrame, benefit_col: str) -> dict:
    valid = df[
        (df["storage_capacity_mwh"] > 0)
        & np.isfinite(df[benefit_col])
    ].copy()

    if len(valid) < 3:
        return {
            "method": "chord_distance",
            "knee_capacity_mwh": np.nan,
            "score": np.nan,
        }

    x = normalize(valid["storage_capacity_mwh"].to_numpy())
    y = normalize(valid[benefit_col].to_numpy())

    # For an increasing concave benefit curve, the elbow is the point farthest
    # above the straight line connecting the endpoints.
    score = y - x
    idx = int(np.nanargmax(score))
    row = valid.iloc[idx]

    return {
        "method": "chord_distance",
        "knee_capacity_mwh": float(row["storage_capacity_mwh"]),
        "score": float(score[idx]),
    }


def knee_by_normalized_net_benefit(df: pd.DataFrame, benefit_col: str) -> dict:
    valid = df[
        (df["storage_capacity_mwh"] > 0)
        & (df["cost_increase_yuan_per_ton"] > 1e-9)
        & np.isfinite(df[benefit_col])
    ].copy()

    if len(valid) < 3:
        return {
            "method": "normalized_net_benefit",
            "knee_capacity_mwh": np.nan,
            "score": np.nan,
        }

    benefit_norm = normalize(valid[benefit_col].to_numpy())
    cost_norm = normalize(valid["cost_increase_yuan_per_ton"].to_numpy())

    # This score is not a manually weighted sum between production and curtailment.
    # It tests one benefit dimension at a time and balances normalized benefit
    # against normalized cost increase.
    score = benefit_norm - cost_norm
    idx = int(np.nanargmax(score))
    row = valid.iloc[idx]

    return {
        "method": "normalized_net_benefit",
        "knee_capacity_mwh": float(row["storage_capacity_mwh"]),
        "score": float(score[idx]),
    }


def knee_by_piecewise_bic(df: pd.DataFrame, benefit_col: str) -> dict:
    valid = df[
        (df["storage_capacity_mwh"] >= 0)
        & np.isfinite(df[benefit_col])
    ].copy()

    x = valid["storage_capacity_mwh"].to_numpy(dtype=float)
    y = valid[benefit_col].to_numpy(dtype=float)

    if len(valid) < 6 or np.nanmax(y) - np.nanmin(y) < 1e-12:
        return {
            "method": "piecewise_bic",
            "knee_capacity_mwh": np.nan,
            "bic": np.nan,
            "slope_before": np.nan,
            "slope_after": np.nan,
            "slope_ratio": np.nan,
        }

    candidates = x[2:-2]
    best = None

    for tau in candidates:
        X = np.column_stack(
            [
                np.ones_like(x),
                np.minimum(x, tau),
                np.maximum(0.0, x - tau),
            ]
        )

        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        y_hat = X @ beta
        sse = float(np.sum((y - y_hat) ** 2))
        sse = max(sse, 1e-12)

        n = len(y)
        k = 3
        bic = n * np.log(sse / n) + k * np.log(n)

        slope_before = float(beta[1])
        slope_after = float(beta[2])
        slope_ratio = (
            slope_after / slope_before
            if abs(slope_before) > 1e-12
            else np.nan
        )

        item = {
            "method": "piecewise_bic",
            "knee_capacity_mwh": float(tau),
            "bic": float(bic),
            "slope_before": slope_before,
            "slope_after": slope_after,
            "slope_ratio": float(slope_ratio),
        }

        if best is None or item["bic"] < best["bic"]:
            best = item

    return best


def build_knee_summary(scan_df: pd.DataFrame) -> pd.DataFrame:
    benefit_specs = [
        ("production_gain_ton", "年制氨量提升"),
        ("curtailment_reduction_mwh", "弃电削减量"),
        ("capacity_utilization_gain_pct", "产能利用率提升"),
    ]

    rows = []

    for col, label in benefit_specs:
        for func in [
            knee_by_chord_distance,
            knee_by_normalized_net_benefit,
            knee_by_piecewise_bic,
        ]:
            result = func(scan_df, col)
            result["benefit_indicator"] = col
            result["benefit_name"] = label
            rows.append(result)

    summary = pd.DataFrame(rows)

    # Final recommendation: use the production and curtailment knees detected
    # by normalized net benefit. This avoids assigning subjective weights between
    # production and curtailment.
    key = summary[
        (summary["method"] == "normalized_net_benefit")
        & (summary["benefit_indicator"].isin(["production_gain_ton", "curtailment_reduction_mwh"]))
        & np.isfinite(summary["knee_capacity_mwh"])
    ]

    if len(key) > 0:
        lower = float(key["knee_capacity_mwh"].min())
        upper = float(key["knee_capacity_mwh"].max())
        representative = float(np.median(key["knee_capacity_mwh"]))

        # Pick the nearest available scanned capacity.
        capacities = scan_df["storage_capacity_mwh"].to_numpy(dtype=float)
        representative = float(capacities[np.argmin(np.abs(capacities - representative))])
    else:
        lower = upper = representative = np.nan

    final_row = {
        "method": "final_recommendation",
        "benefit_indicator": "production_and_curtailment",
        "benefit_name": "年制氨量提升与弃电削减",
        "knee_capacity_mwh": representative,
        "recommended_interval_lower_mwh": lower,
        "recommended_interval_upper_mwh": upper,
        "interpretation": (
            "推荐容量由年制氨量提升与弃电削减两个维度的单位成本收益拐点共同确定；"
            "若两个拐点接近，则取其附近标准容量作为工程推荐容量。"
        ),
    }

    summary = pd.concat([summary, pd.DataFrame([final_row])], ignore_index=True)

    return summary


def plot_capacity_tradeoff(scan_df: pd.DataFrame, knee_summary: pd.DataFrame, figure_dir: Path) -> None:
    setup_chinese_font()

    final = knee_summary[knee_summary["method"] == "final_recommendation"]
    rec_cap = float(final["knee_capacity_mwh"].iloc[0]) if len(final) else np.nan

    fig, ax1 = plt.subplots(figsize=(12, 7))

    ax1.plot(
        scan_df["storage_capacity_mwh"],
        scan_df["annual_avg_ton_cost_yuan_per_ton"],
        marker="o",
        label="全年吨氨成本",
    )
    ax1.set_xlabel("储能容量 / MWh")
    ax1.set_ylabel("全年吨氨成本 / 元·t$^{-1}$")
    ax1.grid(alpha=0.3)

    ax2 = ax1.twinx()
    ax2.plot(
        scan_df["storage_capacity_mwh"],
        scan_df["annual_total_production_ton"],
        marker="s",
        linestyle="--",
        label="全年制氨量",
    )
    ax2.set_ylabel("全年制氨量 / t")

    if np.isfinite(rec_cap):
        ax1.axvline(rec_cap, linestyle=":", linewidth=2)
        ax1.scatter(
            [rec_cap],
            scan_df.loc[
                scan_df["storage_capacity_mwh"].sub(rec_cap).abs().idxmin(),
                "annual_avg_ton_cost_yuan_per_ton",
            ],
            s=120,
            zorder=5,
            label=f"拐点容量约 {rec_cap:.0f} MWh",
        )

    lines_1, labels_1 = ax1.get_legend_handles_labels()
    lines_2, labels_2 = ax2.get_legend_handles_labels()
    ax1.legend(lines_1 + lines_2, labels_1 + labels_2, loc="best")

    plt.title("问题四：储能容量—成本—制氨量细步长扫描")
    plt.tight_layout()
    plt.savefig(figure_dir / "q4_storage_knee_capacity_tradeoff.png", dpi=300)
    plt.close(fig)


def plot_marginal_benefit(scan_df: pd.DataFrame, knee_summary: pd.DataFrame, figure_dir: Path) -> None:
    setup_chinese_font()

    final = knee_summary[knee_summary["method"] == "final_recommendation"]
    rec_cap = float(final["knee_capacity_mwh"].iloc[0]) if len(final) else np.nan

    valid = scan_df[scan_df["storage_capacity_mwh"] > 0].copy()

    fig, axes = plt.subplots(2, 1, figsize=(12, 9), sharex=True)

    axes[0].plot(
        valid["storage_capacity_mwh"],
        valid["marginal_production_gain_per_100yuan"],
        marker="o",
        label="边际年制氨量提升",
    )
    axes[0].set_ylabel("t / (100元·t$^{-1}$)$^{-1}$")
    axes[0].grid(alpha=0.3)
    axes[0].legend(loc="best")

    axes[1].plot(
        valid["storage_capacity_mwh"],
        valid["marginal_curtailment_reduction_per_100yuan"],
        marker="s",
        label="边际弃电削减量",
    )
    axes[1].set_xlabel("储能容量 / MWh")
    axes[1].set_ylabel("MWh / (100元·t$^{-1}$)$^{-1}$")
    axes[1].grid(alpha=0.3)
    axes[1].legend(loc="best")

    if np.isfinite(rec_cap):
        for ax in axes:
            ax.axvline(rec_cap, linestyle=":", linewidth=2)

    fig.suptitle("问题四：储能容量边际收益递减曲线", y=0.98)
    plt.tight_layout()
    plt.savefig(figure_dir / "q4_storage_knee_marginal_benefit.png", dpi=300)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--step", type=float, default=5.0)
    parser.add_argument("--max-capacity", type=float, default=220.0)
    parser.add_argument("--no-figures", action="store_true")
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

    params = OffgridStorageParams()
    capacities = parse_capacities(args.max_capacity, args.step)

    scan_df = annual_capacity_scan(
        scenario_profiles=scenario_profiles,
        params=params,
        capacities=capacities,
    )

    knee_summary = build_knee_summary(scan_df)

    scan_path = table_dir / "q4_storage_capacity_fine_scan.csv"
    summary_path = table_dir / "q4_storage_knee_summary.csv"

    scan_df.to_csv(scan_path, index=False, encoding="utf-8-sig")
    knee_summary.to_csv(summary_path, index=False, encoding="utf-8-sig")

    if not args.no_figures:
        plot_capacity_tradeoff(scan_df, knee_summary, figure_dir)
        plot_marginal_benefit(scan_df, knee_summary, figure_dir)

    final = knee_summary[knee_summary["method"] == "final_recommendation"].iloc[0]

    print("=" * 96)
    print("Q4 storage knee analysis finished.")
    print("=" * 96)
    print(
        knee_summary[
            [
                "benefit_name",
                "method",
                "knee_capacity_mwh",
                "score",
                "bic",
                "slope_before",
                "slope_after",
                "slope_ratio",
            ]
        ].to_string(index=False)
    )
    print("-" * 96)
    print(
        f"Recommended knee capacity: {final['knee_capacity_mwh']} MWh | "
        f"Interval: [{final.get('recommended_interval_lower_mwh', np.nan)}, "
        f"{final.get('recommended_interval_upper_mwh', np.nan)}] MWh"
    )
    print(f"Fine scan saved to: {scan_path}")
    print(f"Knee summary saved to: {summary_path}")
    print(f"Figures saved to: {figure_dir}")
    print("=" * 96)


if __name__ == "__main__":
    main()
