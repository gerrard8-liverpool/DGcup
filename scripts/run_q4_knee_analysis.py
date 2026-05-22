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
from matplotlib.patches import Patch


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
    plt.rcParams["figure.dpi"] = 120
    plt.rcParams["savefig.dpi"] = 300


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

        annual_df = summarize_offgrid_annual(
            summary_df=summary_df,
            scenario_days=scenario_days,
            mode="offgrid_storage_capacity_scan",
        )

        row = annual_df.iloc[0].to_dict()
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

    cap_denom = df["delta_capacity_mwh"]

    df["marginal_production_gain_per_mwh"] = np.where(
        cap_denom > 1e-9,
        df["delta_production_ton"] / cap_denom,
        np.nan,
    )

    df["marginal_curtailment_reduction_per_mwh"] = np.where(
        cap_denom > 1e-9,
        df["delta_curtailment_reduction_mwh"] / cap_denom,
        np.nan,
    )

    cost_denom = df["delta_cost_yuan_per_ton"] / 100.0

    df["marginal_production_gain_per_100yuan"] = np.where(
        cost_denom > 1e-9,
        df["delta_production_ton"] / cost_denom,
        np.nan,
    )

    df["marginal_curtailment_reduction_per_100yuan"] = np.where(
        cost_denom > 1e-9,
        df["delta_curtailment_reduction_mwh"] / cost_denom,
        np.nan,
    )

    return df


def normalize(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    finite = np.isfinite(values)

    out = np.full_like(values, np.nan, dtype=float)
    if finite.sum() == 0:
        return out

    vmin = np.nanmin(values)
    vmax = np.nanmax(values)

    if abs(vmax - vmin) < 1e-12:
        out[finite] = 0.0
        return out

    out[finite] = (values[finite] - vmin) / (vmax - vmin)
    return out


def nearest_capacity(capacities: np.ndarray, value: float) -> float:
    capacities = np.asarray(capacities, dtype=float)
    return float(capacities[np.nanargmin(np.abs(capacities - value))])


def knee_by_chord_distance(df: pd.DataFrame, benefit_col: str) -> dict:
    valid = df[
        (df["storage_capacity_mwh"] > 0)
        & np.isfinite(df[benefit_col])
    ].copy()

    if len(valid) < 3:
        return {"method": "chord_distance", "knee_capacity_mwh": np.nan, "score": np.nan}

    x = normalize(valid["storage_capacity_mwh"].to_numpy())
    y = normalize(valid[benefit_col].to_numpy())

    score = y - x
    idx = int(np.nanargmax(score))
    row = valid.iloc[idx]

    return {
        "method": "chord_distance",
        "knee_capacity_mwh": float(row["storage_capacity_mwh"]),
        "score": float(score[idx]),
        "bic": np.nan,
        "slope_before": np.nan,
        "slope_after": np.nan,
        "slope_ratio": np.nan,
    }


def knee_by_normalized_net_benefit(df: pd.DataFrame, benefit_col: str) -> dict:
    valid = df[
        (df["storage_capacity_mwh"] > 0)
        & np.isfinite(df[benefit_col])
        & np.isfinite(df["annual_avg_ton_cost_yuan_per_ton"])
    ].copy()

    if len(valid) < 3:
        return {
            "method": "normalized_benefit_cost_balance",
            "knee_capacity_mwh": np.nan,
            "score": np.nan,
        }

    benefit_norm = normalize(valid[benefit_col].to_numpy())
    cost_norm = normalize(valid["annual_avg_ton_cost_yuan_per_ton"].to_numpy())

    score = benefit_norm - cost_norm
    idx = int(np.nanargmax(score))
    row = valid.iloc[idx]

    return {
        "method": "normalized_benefit_cost_balance",
        "knee_capacity_mwh": float(row["storage_capacity_mwh"]),
        "score": float(score[idx]),
        "bic": np.nan,
        "slope_before": np.nan,
        "slope_after": np.nan,
        "slope_ratio": np.nan,
    }


def knee_by_piecewise_bic(df: pd.DataFrame, benefit_col: str) -> dict:
    valid = df[
        (df["storage_capacity_mwh"] >= 0)
        & np.isfinite(df[benefit_col])
    ].copy()

    x = valid["storage_capacity_mwh"].to_numpy(dtype=float)
    y = valid[benefit_col].to_numpy(dtype=float)

    if len(valid) < 7 or np.nanmax(y) - np.nanmin(y) < 1e-12:
        return {
            "method": "piecewise_bic",
            "knee_capacity_mwh": np.nan,
            "score": np.nan,
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
        fitted = X @ beta
        sse = float(np.sum((y - fitted) ** 2))
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
            "score": np.nan,
            "bic": float(bic),
            "slope_before": slope_before,
            "slope_after": slope_after,
            "slope_ratio": float(slope_ratio),
        }

        if best is None or item["bic"] < best["bic"]:
            best = item

    return best


def saturation_capacity(df: pd.DataFrame, benefit_col: str, threshold: float = 0.99) -> float:
    max_value = float(df[benefit_col].max())
    if abs(max_value) < 1e-12:
        return np.nan

    satisfied = df[df[benefit_col] >= threshold * max_value]
    if satisfied.empty:
        return np.nan

    return float(satisfied["storage_capacity_mwh"].iloc[0])


def build_knee_summary(scan_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
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

        rows.append(
            {
                "method": "saturation_99pct",
                "benefit_indicator": col,
                "benefit_name": label,
                "knee_capacity_mwh": saturation_capacity(scan_df, col, threshold=0.99),
                "score": np.nan,
                "bic": np.nan,
                "slope_before": np.nan,
                "slope_after": np.nan,
                "slope_ratio": np.nan,
            }
        )

    method_summary = pd.DataFrame(rows)

    consensus_pool = method_summary[
        method_summary["benefit_indicator"].isin(
            ["production_gain_ton", "curtailment_reduction_mwh"]
        )
        & method_summary["method"].isin(
            ["chord_distance", "normalized_benefit_cost_balance", "piecewise_bic"]
        )
        & np.isfinite(method_summary["knee_capacity_mwh"])
    ].copy()

    capacities = scan_df["storage_capacity_mwh"].to_numpy(dtype=float)

    if consensus_pool.empty:
        lower = upper = representative = np.nan
    else:
        lower = float(consensus_pool["knee_capacity_mwh"].min())
        upper = float(consensus_pool["knee_capacity_mwh"].max())

        # Conservative engineering recommendation:
        # choose the upper edge of the consensus knee interval to ensure both
        # production gain and curtailment reduction have entered the post-knee region.
        representative = nearest_capacity(capacities, upper)

    saturated_production = method_summary[
        (method_summary["benefit_indicator"] == "production_gain_ton")
        & (method_summary["method"] == "saturation_99pct")
    ]["knee_capacity_mwh"].iloc[0]

    tier_rows = [
        {
            "tier": "economic_entry",
            "capacity_mwh": lower,
            "interpretation": "累计收益拐点区间下界，代表储能由快速增益段接近拐点区间的起点。",
        },
        {
            "tier": "balanced_knee_recommendation",
            "capacity_mwh": representative,
            "interpretation": "年制氨量提升与弃电削减两类收益共同支持的深度消纳型技术经济拐点容量。",
        },
        {
            "tier": "technical_saturation",
            "capacity_mwh": saturated_production,
            "interpretation": "年制氨量达到最大提升 99% 的最小容量，代表接近技术饱和。",
        },
    ]

    tier_summary = pd.DataFrame(tier_rows)

    final_row = {
        "method": "final_consensus_interval",
        "benefit_indicator": "production_and_curtailment",
        "benefit_name": "年制氨量提升与弃电削减",
        "knee_capacity_mwh": representative,
        "recommended_interval_lower_mwh": lower,
        "recommended_interval_upper_mwh": upper,
        "score": np.nan,
        "bic": np.nan,
        "slope_before": np.nan,
        "slope_after": np.nan,
        "slope_ratio": np.nan,
    }

    method_summary = pd.concat(
        [method_summary, pd.DataFrame([final_row])],
        ignore_index=True,
    )

    return method_summary, tier_summary


def get_final_capacity(knee_summary: pd.DataFrame) -> tuple[float, float, float]:
    row = knee_summary[knee_summary["method"] == "final_consensus_interval"].iloc[0]
    rec = float(row["knee_capacity_mwh"])
    lower = float(row["recommended_interval_lower_mwh"])
    upper = float(row["recommended_interval_upper_mwh"])
    return rec, lower, upper


def plot_capacity_tradeoff(
    scan_df: pd.DataFrame,
    knee_summary: pd.DataFrame,
    tier_summary: pd.DataFrame,
    figure_dir: Path,
) -> None:
    setup_chinese_font()

    rec_cap, lower, upper = get_final_capacity(knee_summary)

    rec_row = scan_df.loc[
        scan_df["storage_capacity_mwh"].sub(rec_cap).abs().idxmin()
    ]

    sat_rows = tier_summary[tier_summary["tier"] == "technical_saturation"]
    sat_cap = float(sat_rows["capacity_mwh"].iloc[0]) if len(sat_rows) else np.nan

    blue = "#2F6DA5"
    orange = "#F28E2B"
    red = "#D62728"
    green = "#2CA02C"
    gray = "#E8E8E8"

    fig, ax1 = plt.subplots(figsize=(13.5, 7.5))

    if np.isfinite(lower) and np.isfinite(upper):
        ax1.axvspan(lower, upper, color=gray, alpha=0.8, label="拐点共识区间")

    ax1.plot(
        scan_df["storage_capacity_mwh"],
        scan_df["annual_avg_ton_cost_yuan_per_ton"],
        color=blue,
        marker="o",
        linewidth=2.2,
        markersize=5,
        label="全年吨氨成本",
    )

    ax1.scatter(
        [rec_cap],
        [rec_row["annual_avg_ton_cost_yuan_per_ton"]],
        color=green,
        edgecolor="black",
        s=150,
        zorder=6,
        label=f"推荐拐点容量约 {rec_cap:.0f} MWh",
    )

    ax1.axvline(rec_cap, color=green, linestyle=":", linewidth=2.2)

    if np.isfinite(sat_cap):
        ax1.axvline(sat_cap, color=red, linestyle="--", linewidth=1.8, alpha=0.85)

    ax1.set_xlabel("储能容量 / MWh", fontsize=13)
    ax1.set_ylabel("全年吨氨成本 / 元·t$^{-1}$", fontsize=13)
    ax1.grid(alpha=0.25)

    ax2 = ax1.twinx()
    ax2.plot(
        scan_df["storage_capacity_mwh"],
        scan_df["annual_total_production_ton"],
        color=orange,
        marker="s",
        linestyle="--",
        linewidth=2.2,
        markersize=5,
        label="全年制氨量",
    )
    ax2.set_ylabel("全年制氨量 / t", fontsize=13)

    annotation = (
        f"推荐容量：{rec_cap:.0f} MWh\n"
        f"拐点区间：{lower:.0f}–{upper:.0f} MWh\n"
        f"吨氨成本：{rec_row['annual_avg_ton_cost_yuan_per_ton']:.2f} 元/t\n"
        f"年制氨量：{rec_row['annual_total_production_ton']:.2f} t"
    )

    ax1.text(
        0.98,
        0.08,
        annotation,
        transform=ax1.transAxes,
        ha="right",
        va="bottom",
        fontsize=11,
        bbox=dict(boxstyle="round,pad=0.45", facecolor="white", edgecolor="#B0B0B0", alpha=0.95),
    )

    custom_handles = [
        Patch(facecolor=gray, edgecolor="none", label="拐点共识区间"),
    ]

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()

    handles = custom_handles + lines1 + lines2
    labels = [h.get_label() for h in custom_handles] + labels1 + labels2

    # Remove duplicate labels while preserving order.
    unique = []
    seen = set()
    for h, label in zip(handles, labels):
        if label not in seen:
            unique.append((h, label))
            seen.add(label)

    ax1.legend(
        [x[0] for x in unique],
        [x[1] for x in unique],
        loc="upper left",
        frameon=True,
        framealpha=0.95,
        fontsize=10,
    )

    plt.title("问题四：储能容量—成本—制氨量细步长扫描", fontsize=16, pad=12)
    plt.tight_layout()
    plt.savefig(figure_dir / "q4_storage_knee_capacity_tradeoff.png", bbox_inches="tight")
    plt.close(fig)


def plot_marginal_benefit(
    scan_df: pd.DataFrame,
    knee_summary: pd.DataFrame,
    figure_dir: Path,
) -> None:
    setup_chinese_font()

    rec_cap, lower, upper = get_final_capacity(knee_summary)

    valid = scan_df[scan_df["storage_capacity_mwh"] > 0].copy()

    blue = "#2F6DA5"
    orange = "#F28E2B"
    green = "#2CA02C"
    gray = "#E8E8E8"

    fig, axes = plt.subplots(2, 1, figsize=(13.5, 9.2), sharex=True)

    for ax in axes:
        if np.isfinite(lower) and np.isfinite(upper):
            ax.axvspan(lower, upper, color=gray, alpha=0.8)
        ax.axvline(rec_cap, color=green, linestyle=":", linewidth=2.2)
        ax.grid(alpha=0.25)

    axes[0].plot(
        valid["storage_capacity_mwh"],
        valid["marginal_production_gain_per_mwh"],
        color=blue,
        marker="o",
        linewidth=2.2,
        markersize=5,
        label="边际年制氨量提升",
    )
    axes[0].set_ylabel("边际年制氨量提升 / t·MWh$^{-1}$", fontsize=12)
    axes[0].legend(loc="upper right", frameon=True, framealpha=0.95)

    axes[1].plot(
        valid["storage_capacity_mwh"],
        valid["marginal_curtailment_reduction_per_mwh"],
        color=orange,
        marker="s",
        linewidth=2.2,
        markersize=5,
        label="边际弃电削减量",
    )
    axes[1].set_xlabel("储能容量 / MWh", fontsize=13)
    axes[1].set_ylabel("边际弃电削减量 / MWh·MWh$^{-1}$", fontsize=12)
    axes[1].legend(loc="upper right", frameon=True, framealpha=0.95)

    fig.text(
        0.5,
        0.02,
        f"灰色区间为多方法识别出的拐点共识区间：{lower:.0f}–{upper:.0f} MWh；绿色虚线为工程推荐容量：{rec_cap:.0f} MWh。",
        ha="center",
        va="bottom",
        fontsize=11,
        bbox=dict(boxstyle="round,pad=0.35", facecolor="white", edgecolor="#B0B0B0", alpha=0.95),
    )

    fig.suptitle("问题四：储能容量边际收益递减曲线", fontsize=16, y=0.985)
    plt.tight_layout(rect=[0, 0.055, 1, 0.96])
    plt.savefig(figure_dir / "q4_storage_knee_marginal_benefit.png", bbox_inches="tight")
    plt.close(fig)


def plot_normalized_benefit(
    scan_df: pd.DataFrame,
    knee_summary: pd.DataFrame,
    figure_dir: Path,
) -> None:
    setup_chinese_font()

    rec_cap, lower, upper = get_final_capacity(knee_summary)

    df = scan_df.copy()
    df["production_gain_norm"] = normalize(df["production_gain_ton"].to_numpy())
    df["curtailment_reduction_norm"] = normalize(df["curtailment_reduction_mwh"].to_numpy())
    df["cost_norm"] = normalize(df["annual_avg_ton_cost_yuan_per_ton"].to_numpy())

    blue = "#2F6DA5"
    orange = "#F28E2B"
    red = "#D62728"
    green = "#2CA02C"
    gray = "#E8E8E8"

    fig, ax = plt.subplots(figsize=(13.5, 7.2))

    if np.isfinite(lower) and np.isfinite(upper):
        ax.axvspan(lower, upper, color=gray, alpha=0.8, label="拐点共识区间")

    ax.plot(
        df["storage_capacity_mwh"],
        df["production_gain_norm"],
        color=blue,
        marker="o",
        linewidth=2.2,
        label="标准化年制氨量提升",
    )
    ax.plot(
        df["storage_capacity_mwh"],
        df["curtailment_reduction_norm"],
        color=orange,
        marker="s",
        linewidth=2.2,
        label="标准化弃电削减量",
    )
    ax.plot(
        df["storage_capacity_mwh"],
        df["cost_norm"],
        color=red,
        marker="^",
        linewidth=2.0,
        linestyle="--",
        label="标准化吨氨成本",
    )

    ax.axvline(rec_cap, color=green, linestyle=":", linewidth=2.2, label=f"推荐容量约 {rec_cap:.0f} MWh")

    ax.set_xlabel("储能容量 / MWh", fontsize=13)
    ax.set_ylabel("标准化数值", fontsize=13)
    ax.set_ylim(-0.04, 1.06)
    ax.grid(alpha=0.25)
    ax.legend(loc="lower right", frameon=True, framealpha=0.95, fontsize=10)

    plt.title("问题四：储能容量收益—成本标准化对比", fontsize=16, pad=12)
    plt.tight_layout()
    plt.savefig(figure_dir / "q4_storage_knee_normalized_benefit.png", bbox_inches="tight")
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

    knee_summary, tier_summary = build_knee_summary(scan_df)

    scan_path = table_dir / "q4_storage_capacity_fine_scan.csv"
    summary_path = table_dir / "q4_storage_knee_summary.csv"
    tier_path = table_dir / "q4_storage_capacity_tiers.csv"

    scan_df.to_csv(scan_path, index=False, encoding="utf-8-sig")
    knee_summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
    tier_summary.to_csv(tier_path, index=False, encoding="utf-8-sig")

    if not args.no_figures:
        plot_capacity_tradeoff(scan_df, knee_summary, tier_summary, figure_dir)
        plot_marginal_benefit(scan_df, knee_summary, figure_dir)
        plot_normalized_benefit(scan_df, knee_summary, figure_dir)

    final = knee_summary[knee_summary["method"] == "final_consensus_interval"].iloc[0]

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
    print(tier_summary.to_string(index=False))
    print("-" * 96)
    print(
        f"Recommended balanced knee capacity: {final['knee_capacity_mwh']} MWh | "
        f"Consensus interval: [{final['recommended_interval_lower_mwh']}, "
        f"{final['recommended_interval_upper_mwh']}] MWh"
    )
    print(f"Fine scan saved to: {scan_path}")
    print(f"Knee summary saved to: {summary_path}")
    print(f"Tier summary saved to: {tier_path}")
    print(f"Figures saved to: {figure_dir}")
    print("=" * 96)


if __name__ == "__main__":
    main()
