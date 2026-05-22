from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter

from dgcup.visualization.plots import setup_publication_style, COLORS


def _save(fig, path: Path):
    fig.savefig(path, bbox_inches="tight", facecolor="white", dpi=320)
    plt.close(fig)


def plot_q4_no_storage_production_bar(no_storage_summary_df: pd.DataFrame, output_dir: str | Path):
    setup_publication_style()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    df = no_storage_summary_df.sort_values("scenario_id")
    fig, ax = plt.subplots(figsize=(13.0, 6.2))

    ax.bar(
        df["scenario_id"],
        df["total_ammonia_output_ton"],
        color="#4E79A7",
        alpha=0.85,
        edgecolor="#222222",
        linewidth=0.5,
        label="实际日制氨量",
    )

    ax.axhline(
        72,
        color="#D62728",
        linestyle="--",
        linewidth=1.4,
        label="72 t/day 额定产能",
    )

    ax.set_title("问题四：无储能离网运行下 24 场景日制氨量")
    ax.set_xlabel("风光组合场景")
    ax.set_ylabel("日制氨量 / t")
    ax.set_xticks(range(len(df)))
    ax.set_xticklabels(df["scenario_id"], rotation=55, ha="right")
    ax.grid(axis="y", color=COLORS["grid"])

    ax.legend(
        ncol=2,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.16),
        frameon=True,
    )

    _save(fig, output_dir / "q4_offgrid_no_storage_production_bar.png")

def plot_q4_no_storage_curtailment_unserved(no_storage_summary_df: pd.DataFrame, output_dir: str | Path):
    setup_publication_style()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    df = no_storage_summary_df.sort_values("scenario_id")
    x = np.arange(len(df))

    fig, (ax1, ax2) = plt.subplots(
        2,
        1,
        figsize=(13.2, 7.6),
        sharex=True,
        gridspec_kw={"height_ratios": [2.4, 1.0], "hspace": 0.16},
    )

    ax1.bar(
        x,
        df["curtailment_mwh"],
        color="#2CA02C",
        alpha=0.82,
        label="弃电量",
    )
    ax1.set_title("问题四：无储能离网运行下弃电量与缺供电量")
    ax1.set_ylabel("弃电量 / MWh")
    ax1.grid(axis="y", color=COLORS["grid"])
    ax1.legend(loc="upper right", frameon=True)

    ax2.bar(
        x,
        df["unserved_load_mwh"],
        color="#D62728",
        alpha=0.82,
        label="缺供电量",
    )
    ax2.set_xlabel("风光组合场景")
    ax2.set_ylabel("缺供 / MWh")
    ax2.set_xticks(x)
    ax2.set_xticklabels(df["scenario_id"], rotation=55, ha="right")
    ax2.grid(axis="y", color=COLORS["grid"])
    ax2.legend(loc="upper right", frameon=True)

    ax1.text(
        0.01,
        0.95,
        "说明：缺供量远小于弃电量，故单独放大显示",
        transform=ax1.transAxes,
        ha="left",
        va="top",
        fontsize=9.5,
        bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor="#CCCCCC", alpha=0.95),
    )

    fig.subplots_adjust(bottom=0.20, top=0.92)

    _save(fig, output_dir / "q4_offgrid_no_storage_curtailment_unserved.png")

def plot_q4_storage_capacity_scan(scan_summary_df: pd.DataFrame, output_dir: str | Path):
    setup_publication_style()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    df = scan_summary_df.sort_values("storage_capacity_mwh").copy()

    if "is_recommended_storage" in df.columns and df["is_recommended_storage"].any():
        sat_row = df[df["is_recommended_storage"]].iloc[0]
    else:
        sat_row = df.loc[df["total_ammonia_output_ton"].idxmax()]

    fig, ax1 = plt.subplots(figsize=(10.8, 6.8))

    ax1.plot(
        df["storage_capacity_mwh"],
        df["ton_cost_yuan_per_ton"],
        marker="o",
        linewidth=2.4,
        color="#4E79A7",
        label="吨氨成本",
        zorder=3,
    )
    ax1.scatter(
        sat_row["storage_capacity_mwh"],
        sat_row["ton_cost_yuan_per_ton"],
        s=130,
        color="#2CA02C",
        edgecolor="#222222",
        zorder=5,
        label="技术饱和容量",
    )

    ax1.set_xlabel("储能容量 / MWh")
    ax1.set_ylabel("吨氨成本 / 元·t$^{-1}$")
    ax1.grid(axis="y", color=COLORS["grid"])

    ax2 = ax1.twinx()
    ax2.plot(
        df["storage_capacity_mwh"],
        df["total_ammonia_output_ton"],
        marker="s",
        linewidth=2.2,
        color="#F28E2B",
        label="日制氨量",
        zorder=3,
    )
    ax2.set_ylabel("日制氨量 / t")

    ax1.set_title("问题四：最大弃电场景下储能技术饱和容量扫描", pad=14)

    ax1.text(
        0.965,
        0.08,
        f"技术饱和容量：{sat_row['storage_capacity_mwh']:.0f} MWh\n"
        f"吨氨成本：{sat_row['ton_cost_yuan_per_ton']:.2f} 元/t\n"
        f"日制氨量：{sat_row['total_ammonia_output_ton']:.2f} t",
        transform=ax1.transAxes,
        ha="right",
        va="bottom",
        fontsize=10.2,
        bbox=dict(boxstyle="round,pad=0.42", facecolor="white", edgecolor="#CCCCCC", alpha=0.96),
        zorder=8,
    )

    fig.text(
        0.5,
        0.035,
        "饱和规则：达到最大日制氨量 99% 的最小储能容量，用于识别容量继续增加后的边际收益平台区",
        ha="center",
        va="bottom",
        fontsize=10.0,
        bbox=dict(boxstyle="round,pad=0.35", facecolor="white", edgecolor="#CCCCCC", alpha=0.95),
    )

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(
        lines1 + lines2,
        labels1 + labels2,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.15),
        ncol=3,
        frameon=True,
    )

    fig.subplots_adjust(bottom=0.24, top=0.90, right=0.88)

    _save(fig, output_dir / "q4_storage_capacity_scan.png")

def plot_q4_storage_dispatch_curve(storage_hourly_df: pd.DataFrame, output_dir: str | Path, scenario_id: str | None = None):
    setup_publication_style()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if scenario_id is None:
        scenario_id = storage_hourly_df["scenario_id"].iloc[0]

    df = storage_hourly_df[storage_hourly_df["scenario_id"] == scenario_id].copy()
    df = df.sort_values("hour").head(24)

    x = list(range(len(df)))
    labels = df["time"].astype(str).tolist()

    fig, (ax1, ax2, ax3) = plt.subplots(
        3,
        1,
        figsize=(14.0, 11.8),
        sharex=True,
        gridspec_kw={"height_ratios": [2.0, 1.1, 1.25], "hspace": 0.50},
    )

    ax1.plot(x, df["renewable_power_mw"], color="#D62728", linewidth=2.4, marker="o", label="风光总出力")
    ax1.plot(x, df["base_load_mw"], color="#1F4E79", linewidth=2.2, label="常规负荷")
    ax1.plot(x, df["hydrogen_ammonia_load_mw"], color="#2CA02C", linewidth=2.2, label="制氨负荷")
    ax1.plot(x, df["total_load_mw"], color="#9467BD", linewidth=2.2, linestyle="--", label="总负荷")
    ax1.set_title(f"问题四：离网储能调度曲线（{scenario_id}）", pad=12)
    ax1.set_ylabel("功率 / MW")
    ax1.grid(axis="y", color=COLORS["grid"])
    ax1.legend(
        ncol=4,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.18),
        frameon=True,
        columnspacing=1.4,
    )

    ax2.bar(x, df["storage_charge_mw"], color="#F28E2B", alpha=0.82, label="储能充电")
    ax2.bar(x, -df["storage_discharge_mw"], color="#4E79A7", alpha=0.82, label="储能放电")
    ax2.axhline(0, color="#222222", linewidth=1.0)
    ax2.set_ylabel("充放电 / MW")
    ax2.grid(axis="y", color=COLORS["grid"])
    ax2.legend(ncol=2, loc="upper right", frameon=True)

    # Left axis: curtailment and unserved power. Right axis: storage SOC.
    ax3.bar(x, df["curtailment_mw"], color="#999999", alpha=0.55, label="弃电功率")
    ax3.bar(x, -df["unserved_load_mw"], color="#D62728", alpha=0.65, label="缺供功率")
    ax3.axhline(0, color="#222222", linewidth=1.0)
    ax3.set_xlabel("时段")
    ax3.set_ylabel("弃电/缺供功率 / MW")
    ax3.set_xticks(x)
    ax3.set_xticklabels(labels, rotation=55, ha="right")
    ax3.grid(axis="y", color=COLORS["grid"])

    ax3_soc = ax3.twinx()
    ax3_soc.plot(
        x,
        df["soc_mwh"],
        color="#2CA02C",
        linewidth=2.4,
        marker="o",
        label="SOC",
        zorder=5,
    )
    ax3_soc.set_ylabel("SOC / MWh")

    lines1, labels1 = ax3.get_legend_handles_labels()
    lines2, labels2 = ax3_soc.get_legend_handles_labels()
    ax3.legend(
        lines1 + lines2,
        labels1 + labels2,
        ncol=3,
        loc="upper right",
        frameon=True,
    )

    fig.subplots_adjust(top=0.93, bottom=0.13)

    _save(fig, output_dir / "q4_storage_dispatch_curve.png")

def plot_q4_storage_production_bar(no_storage_summary_df: pd.DataFrame, storage_summary_df: pd.DataFrame, output_dir: str | Path):
    setup_publication_style()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    no_df = no_storage_summary_df.sort_values("scenario_id")
    st_df = storage_summary_df.sort_values("scenario_id")

    x = np.arange(len(no_df))
    width = 0.38

    fig, ax = plt.subplots(figsize=(13.0, 5.8))

    ax.bar(x - width / 2, no_df["total_ammonia_output_ton"], width, label="无储能", color="#A0CBE8")
    ax.bar(x + width / 2, st_df["total_ammonia_output_ton"], width, label="有储能", color="#2CA02C", alpha=0.82)
    ax.axhline(72, color="#D62728", linestyle="--", linewidth=1.3, label="72 t/day 额定产能")

    ax.set_title("问题四：储能前后 24 场景日制氨量对比")
    ax.set_xlabel("风光组合场景")
    ax.set_ylabel("日制氨量 / t")
    ax.set_xticks(x)
    ax.set_xticklabels(no_df["scenario_id"], rotation=55, ha="right")
    ax.grid(axis="y", color=COLORS["grid"])
    ax.legend(ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.18), frameon=True)

    _save(fig, output_dir / "q4_storage_production_bar.png")


def plot_q4_wind_pv_utilization_improvement(no_storage_summary_df: pd.DataFrame, storage_summary_df: pd.DataFrame, output_dir: str | Path):
    setup_publication_style()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    no_df = no_storage_summary_df.sort_values("scenario_id")
    st_df = storage_summary_df.sort_values("scenario_id")

    x = np.arange(len(no_df))
    width = 0.38

    fig, ax = plt.subplots(figsize=(13.0, 5.8))

    ax.bar(x - width / 2, no_df["renewable_utilization_ratio"], width, label="无储能", color="#A0CBE8")
    ax.bar(x + width / 2, st_df["renewable_utilization_ratio"], width, label="有储能", color="#2CA02C", alpha=0.82)

    ax.set_title("问题四：储能前后风光利用率对比")
    ax.set_xlabel("风光组合场景")
    ax.set_ylabel("风光利用率")
    ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax.set_xticks(x)
    ax.set_xticklabels(no_df["scenario_id"], rotation=55, ha="right")
    ax.set_ylim(0, 1.05)
    ax.grid(axis="y", color=COLORS["grid"])
    ax.legend(ncol=2, loc="upper center", bbox_to_anchor=(0.5, -0.18), frameon=True)

    _save(fig, output_dir / "q4_wind_pv_utilization_improvement.png")


def plot_q4_grid_vs_offgrid_cost_comparison(comparison_df: pd.DataFrame, output_dir: str | Path):
    setup_publication_style()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    df = comparison_df.copy()

    mode_labels = {
        "offgrid_with_storage": "离网+储能",
        "grid_connected_same_production": "联网同产量",
    }

    df["label"] = df["mode"].map(mode_labels).fillna(df["mode"])

    fig, ax = plt.subplots(figsize=(7.8, 6.1))

    bars = ax.bar(
        df["label"],
        df["annual_avg_ton_cost_yuan_per_ton"],
        color=["#2CA02C", "#4E79A7"][: len(df)],
        alpha=0.85,
        edgecolor="#222222",
        linewidth=0.8,
    )

    ax.set_title("问题四：联网与离网同产量吨氨成本对比", pad=14)
    ax.set_ylabel("全年加权平均吨氨成本 / 元·t$^{-1}$")
    ax.grid(axis="y", color=COLORS["grid"])

    max_y = df["annual_avg_ton_cost_yuan_per_ton"].max()
    ax.set_ylim(0, max_y * 1.18)

    for bar, value in zip(bars, df["annual_avg_ton_cost_yuan_per_ton"]):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value + max_y * 0.018,
            f"{value:.2f}",
            ha="center",
            va="bottom",
            fontsize=10.5,
        )

    _save(fig, output_dir / "q4_grid_vs_offgrid_cost_comparison.png")


def plot_q4_storage_annual_tradeoff(annual_scan_df: pd.DataFrame, output_dir: str | Path):
    setup_publication_style()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    df = annual_scan_df.sort_values("storage_capacity_mwh").copy()

    if "is_recommended_by_unit_benefit" in df.columns and df["is_recommended_by_unit_benefit"].any():
        rec = df[df["is_recommended_by_unit_benefit"]].iloc[0]
    elif "is_recommended_by_composite" in df.columns and df["is_recommended_by_composite"].any():
        rec = df[df["is_recommended_by_composite"]].iloc[0]
    else:
        rec = df.loc[df["production_gain_per_100yuan"].idxmax()]

    fig, ax1 = plt.subplots(figsize=(10.8, 6.6))

    ax1.plot(
        df["storage_capacity_mwh"],
        df["annual_avg_ton_cost_yuan_per_ton"],
        marker="o",
        linewidth=2.4,
        color="#4E79A7",
        label="全年吨氨成本",
    )
    ax1.scatter(
        rec["storage_capacity_mwh"],
        rec["annual_avg_ton_cost_yuan_per_ton"],
        s=135,
        color="#2CA02C",
        edgecolor="#222222",
        zorder=5,
        label="单位收益推荐容量",
    )
    ax1.axvline(
        rec["storage_capacity_mwh"],
        color="#2CA02C",
        linestyle="--",
        linewidth=1.2,
        alpha=0.75,
    )

    ax1.set_xlabel("储能容量 / MWh")
    ax1.set_ylabel("全年吨氨成本 / 元·t$^{-1}$")
    ax1.grid(axis="y", color=COLORS["grid"])

    ax2 = ax1.twinx()
    ax2.plot(
        df["storage_capacity_mwh"],
        df["annual_total_production_ton"],
        marker="s",
        linewidth=2.3,
        color="#F28E2B",
        label="全年制氨量",
    )
    ax2.set_ylabel("全年制氨量 / t")

    ax1.set_title("问题四：储能容量—成本—年制氨量权衡关系", pad=14)

    ax1.text(
        0.97,
        0.08,
        f"推荐容量：{rec['storage_capacity_mwh']:.0f} MWh\n"
        f"吨氨成本：{rec['annual_avg_ton_cost_yuan_per_ton']:.2f} 元/t\n"
        f"年制氨量：{rec['annual_total_production_ton']:.2f} t\n"
        f"弃电削减：{rec['curtailment_reduction_mwh']:.2f} MWh",
        transform=ax1.transAxes,
        ha="right",
        va="bottom",
        fontsize=10.0,
        bbox=dict(boxstyle="round,pad=0.42", facecolor="white", edgecolor="#CCCCCC", alpha=0.96),
    )

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(
        lines1 + lines2,
        labels1 + labels2,
        ncol=3,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.15),
        frameon=True,
    )

    fig.subplots_adjust(bottom=0.20, top=0.90, right=0.88)

    _save(fig, output_dir / "q4_storage_annual_tradeoff.png")

def plot_q4_storage_benefit_per_cost(annual_scan_df: pd.DataFrame, output_dir: str | Path):
    setup_publication_style()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    df = annual_scan_df.sort_values("storage_capacity_mwh").copy()
    plot_df = df[df["storage_capacity_mwh"] > 0].copy()
    plot_df = plot_df.replace([np.inf, -np.inf], np.nan).dropna(
        subset=["production_gain_per_100yuan", "curtailment_reduction_per_100yuan"]
    )

    if "is_recommended_by_unit_benefit" in df.columns and df["is_recommended_by_unit_benefit"].any():
        rec = df[df["is_recommended_by_unit_benefit"]].iloc[0]
    elif "is_recommended_by_composite" in df.columns and df["is_recommended_by_composite"].any():
        rec = df[df["is_recommended_by_composite"]].iloc[0]
    else:
        rec = plot_df.loc[plot_df["production_gain_per_100yuan"].idxmax()]

    fig, (ax1, ax2) = plt.subplots(
        2,
        1,
        figsize=(10.8, 8.0),
        sharex=True,
        gridspec_kw={"height_ratios": [1, 1], "hspace": 0.16},
    )

    ax1.plot(
        plot_df["storage_capacity_mwh"],
        plot_df["production_gain_per_100yuan"],
        marker="o",
        linewidth=2.4,
        color="#4E79A7",
        label="年制氨量提升",
    )
    ax1.scatter(
        rec["storage_capacity_mwh"],
        rec["production_gain_per_100yuan"],
        s=125,
        color="#2CA02C",
        edgecolor="#222222",
        zorder=5,
        label="推荐容量",
    )
    ax1.axvline(
        rec["storage_capacity_mwh"],
        color="#2CA02C",
        linestyle="--",
        linewidth=1.2,
        alpha=0.75,
    )
    ax1.set_title("问题四：储能容量的单位成本技术收益变化", pad=12)
    ax1.set_ylabel("年制氨量提升\n/ t·(100元/t)$^{-1}$")
    ax1.grid(axis="y", color=COLORS["grid"])
    ax1.legend(loc="upper right", frameon=True)

    ax2.plot(
        plot_df["storage_capacity_mwh"],
        plot_df["curtailment_reduction_per_100yuan"],
        marker="s",
        linewidth=2.4,
        color="#F28E2B",
        label="弃电削减量",
    )
    ax2.scatter(
        rec["storage_capacity_mwh"],
        rec["curtailment_reduction_per_100yuan"],
        s=125,
        color="#2CA02C",
        edgecolor="#222222",
        zorder=5,
    )
    ax2.axvline(
        rec["storage_capacity_mwh"],
        color="#2CA02C",
        linestyle="--",
        linewidth=1.2,
        alpha=0.75,
    )
    ax2.set_xlabel("储能容量 / MWh")
    ax2.set_ylabel("弃电削减量\n/ MWh·(100元/t)$^{-1}$")
    ax2.grid(axis="y", color=COLORS["grid"])
    ax2.legend(loc="upper right", frameon=True)

    fig.text(
        0.53,
        0.03,
        f"推荐容量：{rec['storage_capacity_mwh']:.0f} MWh；"
        f"每增 100 元/t 年制氨量提升 {rec['production_gain_per_100yuan']:.2f} t，"
        f"弃电削减 {rec['curtailment_reduction_per_100yuan']:.2f} MWh",
        ha="center",
        va="bottom",
        fontsize=10.0,
        bbox=dict(boxstyle="round,pad=0.38", facecolor="white", edgecolor="#CCCCCC", alpha=0.95),
    )

    fig.subplots_adjust(bottom=0.17, top=0.91)

    _save(fig, output_dir / "q4_storage_benefit_per_cost.png")
