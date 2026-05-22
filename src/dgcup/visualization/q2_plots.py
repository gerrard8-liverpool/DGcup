from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from matplotlib.ticker import PercentFormatter

from dgcup.visualization.plots import setup_publication_style, COLORS


def _save(fig, path: Path):
    fig.savefig(path, bbox_inches="tight", facecolor="white", dpi=320)
    plt.close(fig)


def plot_q2_typical_schedule_gantt(
    typical_hourly_df: pd.DataFrame,
    output_dir: str | Path,
):
    setup_publication_style()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    productions = sorted(
        typical_hourly_df["production_ton"].unique(),
        reverse=True,
    )

    matrix = []
    for production in productions:
        sub = typical_hourly_df[
            typical_hourly_df["production_ton"] == production
        ].sort_values("hour")
        matrix.append(sub["on_status"].astype(int).values)

    matrix = np.asarray(matrix)

    fig, ax = plt.subplots(figsize=(13.5, 5.2))

    cmap = ListedColormap(["#F2F2F2", "#2CA02C"])
    ax.imshow(matrix, aspect="auto", cmap=cmap, interpolation="nearest")

    ax.set_title("问题二：典型风光场景下不同日产量的最优开机时段")
    ax.set_xlabel("时段")
    ax.set_ylabel("日产量 / t")

    ax.set_xticks(range(24))
    time_labels = (
        typical_hourly_df[typical_hourly_df["production_ton"] == productions[0]]
        .sort_values("hour")["time"]
        .astype(str)
        .tolist()
    )
    ax.set_xticklabels(time_labels, rotation=55, ha="right")

    ax.set_yticks(range(len(productions)))
    ax.set_yticklabels([f"{int(p)}" for p in productions])

    ax.set_xticks(np.arange(-0.5, 24, 1), minor=True)
    ax.set_yticks(np.arange(-0.5, len(productions), 1), minor=True)
    ax.grid(which="minor", color="white", linestyle="-", linewidth=1.2)
    ax.tick_params(which="minor", bottom=False, left=False)

    from matplotlib.patches import Patch

    handles = [
        Patch(facecolor="#2CA02C", edgecolor="#222222", label="开机"),
        Patch(facecolor="#F2F2F2", edgecolor="#222222", label="停机"),
    ]
    ax.legend(handles=handles, loc="upper right", frameon=True, framealpha=0.95)

    _save(fig, output_dir / "q2_typical_schedule_gantt.png")


def plot_q2_typical_cost_vs_production(
    typical_summary_df: pd.DataFrame,
    output_dir: str | Path,
):
    """
    Plot Q2 typical-day ton-ammonia cost under different production targets.

    Design note:
    Only use a highlighted marker and an information box for the optimal point.
    No auxiliary vertical line or arrow is used, avoiding ambiguous extra visual variables.
    """
    setup_publication_style()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    df = typical_summary_df.sort_values("production_ton")

    fig, ax = plt.subplots(figsize=(9.8, 5.8))

    ax.plot(
        df["production_ton"],
        df["ton_cost_yuan_per_ton"],
        marker="o",
        linewidth=2.6,
        color=COLORS["neutral"],
        label="吨氨成本",
        zorder=3,
    )

    best_idx = df["ton_cost_yuan_per_ton"].idxmin()
    best_row = df.loc[best_idx]

    ax.scatter(
        best_row["production_ton"],
        best_row["ton_cost_yuan_per_ton"],
        s=135,
        color=COLORS["export"],
        edgecolor="#222222",
        linewidth=1.1,
        zorder=5,
        label="最低成本方案",
    )

    ax.text(
        0.965,
        0.075,
        f"最低成本方案\n日产量：{best_row['production_ton']:.0f} t/day\n吨氨成本：{best_row['ton_cost_yuan_per_ton']:.2f} 元/t",
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=10.5,
        bbox=dict(
            boxstyle="round,pad=0.42",
            facecolor="white",
            edgecolor="#CCCCCC",
            alpha=0.96,
        ),
        zorder=8,
    )

    ax.set_title("问题二：典型风光场景下吨氨成本随日产量变化")
    ax.set_xlabel("日产量 / t")
    ax.set_ylabel("吨氨成本 / 元·t$^{-1}$")
    ax.grid(axis="y", color=COLORS["grid"])
    ax.legend(loc="upper left", frameon=True, framealpha=0.95)

    y_min = df["ton_cost_yuan_per_ton"].min()
    y_max = df["ton_cost_yuan_per_ton"].max()
    y_pad = (y_max - y_min) * 0.12
    ax.set_ylim(y_min - y_pad, y_max + y_pad)

    _save(fig, output_dir / "q2_typical_cost_vs_production.png")

def plot_q2_typical_green_indicators(
    typical_summary_df: pd.DataFrame,
    output_dir: str | Path,
):
    setup_publication_style()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    df = typical_summary_df.sort_values("production_ton")

    fig, ax = plt.subplots(figsize=(10.8, 6.0))

    ax.plot(
        df["production_ton"],
        df["renewable_self_use_ratio"],
        marker="o",
        linewidth=2.5,
        label="新能源自发自用比例",
        zorder=4,
    )
    ax.plot(
        df["production_ton"],
        df["green_power_ratio"],
        marker="o",
        linewidth=2.5,
        label="总用电量绿电比例",
        zorder=4,
    )
    ax.plot(
        df["production_ton"],
        df["renewable_export_ratio"],
        marker="o",
        linewidth=2.5,
        label="新能源上网比例",
        zorder=4,
    )

    ax.axhline(0.60, color="#111111", linestyle="--", linewidth=1.5, zorder=2)
    ax.axhline(0.30, color="#666666", linestyle="--", linewidth=1.5, zorder=2)
    ax.axhline(0.20, color="#999999", linestyle="--", linewidth=1.5, zorder=2)

    ax.set_xlim(df["production_ton"].min() - 1, df["production_ton"].max() + 1.8)

    ax.text(
        0.985,
        0.60,
        "自发自用下限 60%",
        transform=ax.get_yaxis_transform(),
        ha="right",
        va="bottom",
        fontsize=9.5,
        bbox=dict(boxstyle="round,pad=0.25", facecolor="white", edgecolor="#DDDDDD", alpha=0.96),
    )
    ax.text(
        0.985,
        0.30,
        "绿电比例下限 30%",
        transform=ax.get_yaxis_transform(),
        ha="right",
        va="bottom",
        fontsize=9.5,
        bbox=dict(boxstyle="round,pad=0.25", facecolor="white", edgecolor="#DDDDDD", alpha=0.96),
    )
    ax.text(
        0.985,
        0.20,
        "上网比例上限 20%",
        transform=ax.get_yaxis_transform(),
        ha="right",
        va="bottom",
        fontsize=9.5,
        bbox=dict(boxstyle="round,pad=0.25", facecolor="white", edgecolor="#DDDDDD", alpha=0.96),
    )

    ax.set_title("问题二：典型风光场景下绿电直连指标随日产量变化")
    ax.set_xlabel("日产量 / t")
    ax.set_ylabel("比例")
    ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax.set_ylim(0, 1.05)
    ax.grid(axis="y", color=COLORS["grid"])
    ax.legend(
        ncol=3,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.15),
        frameon=True,
        framealpha=0.95,
    )

    _save(fig, output_dir / "q2_typical_green_indicators.png")


def plot_q2_scenario_cost_boxplot(
    scenario_summary_df: pd.DataFrame,
    output_dir: str | Path,
):
    """
    Plot ton-ammonia cost distribution across 24 scenarios.

    The legend note is placed at the lower-right corner to avoid covering the upper whiskers.
    """
    setup_publication_style()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    productions = sorted(scenario_summary_df["production_ton"].unique())

    data = [
        scenario_summary_df.loc[
            scenario_summary_df["production_ton"] == p,
            "ton_cost_yuan_per_ton",
        ].values
        for p in productions
    ]

    fig, ax = plt.subplots(figsize=(9.8, 6.0))

    box = ax.boxplot(
        data,
        labels=[f"{int(p)}" for p in productions],
        patch_artist=True,
        showmeans=True,
        meanprops=dict(
            marker="^",
            markerfacecolor="#2CA02C",
            markeredgecolor="#2CA02C",
            markersize=8,
        ),
        medianprops=dict(color="#FF7F0E", linewidth=1.6),
    )

    for patch in box["boxes"]:
        patch.set_facecolor("#A0CBE8")
        patch.set_alpha(0.82)

    ax.set_title("问题二：24 种风光场景下吨氨成本分布")
    ax.set_xlabel("日产量 / t")
    ax.set_ylabel("吨氨成本 / 元·t$^{-1}$")
    ax.grid(axis="y", color=COLORS["grid"])

    ax.text(
        0.98,
        0.06,
        "绿色三角：均值\n橙色横线：中位数",
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=9.8,
        bbox=dict(
            boxstyle="round,pad=0.35",
            facecolor="white",
            edgecolor="#CCCCCC",
            alpha=0.96,
        ),
        zorder=8,
    )

    _save(fig, output_dir / "q2_scenario_cost_boxplot.png")

def plot_q2_satisfaction_stacked_bar(
    annual_summary_df: pd.DataFrame,
    output_dir: str | Path,
):
    setup_publication_style()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    df = annual_summary_df.sort_values("production_ton")

    x = np.arange(len(df))
    labels = [f"{int(p)}" for p in df["production_ton"]]

    all_days = df["all_satisfied_days"].values
    partial_days = df["partially_satisfied_days"].values
    none_days = df["none_satisfied_days"].values

    fig, ax = plt.subplots(figsize=(9.8, 5.8))

    ax.bar(x, all_days, label="全满足", color="#2CA02C", alpha=0.85)
    ax.bar(x, partial_days, bottom=all_days, label="部分满足", color="#F28E2B", alpha=0.85)
    ax.bar(
        x,
        none_days,
        bottom=all_days + partial_days,
        label="全不满足",
        color="#D62728",
        alpha=0.85,
    )

    ax.set_title("问题二：不同日产量下全年绿电指标达标分类")
    ax.set_xlabel("日产量 / t")
    ax.set_ylabel("全年等效天数 / 天")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylim(0, 380)
    ax.grid(axis="y", color=COLORS["grid"])
    ax.legend(ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.14), frameon=True)

    _save(fig, output_dir / "q2_satisfaction_stacked_bar.png")


def plot_q2_annual_avg_cost(
    annual_summary_df: pd.DataFrame,
    output_dir: str | Path,
):
    """
    Plot annual weighted average ton-ammonia cost.

    Design note:
    Only use a highlighted marker and an information box for the optimal point.
    No auxiliary vertical line or arrow is used.
    """
    setup_publication_style()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    df = annual_summary_df.sort_values("production_ton")

    fig, ax = plt.subplots(figsize=(9.8, 5.8))

    ax.plot(
        df["production_ton"],
        df["annual_avg_ton_cost_yuan_per_ton"],
        marker="o",
        linewidth=2.6,
        color=COLORS["neutral"],
        label="全年加权平均吨氨成本",
        zorder=3,
    )

    best_idx = df["annual_avg_ton_cost_yuan_per_ton"].idxmin()
    best_row = df.loc[best_idx]

    ax.scatter(
        best_row["production_ton"],
        best_row["annual_avg_ton_cost_yuan_per_ton"],
        s=135,
        color=COLORS["export"],
        edgecolor="#222222",
        linewidth=1.1,
        zorder=5,
        label="年化最低成本方案",
    )

    ax.text(
        0.965,
        0.075,
        f"年化最低成本方案\n日产量：{best_row['production_ton']:.0f} t/day\n全年加权平均吨氨成本：{best_row['annual_avg_ton_cost_yuan_per_ton']:.2f} 元/t",
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=10.2,
        bbox=dict(
            boxstyle="round,pad=0.42",
            facecolor="white",
            edgecolor="#CCCCCC",
            alpha=0.96,
        ),
        zorder=8,
    )

    ax.set_title("问题二：全年加权平均吨氨成本随日产量变化")
    ax.set_xlabel("日产量 / t")
    ax.set_ylabel("全年加权平均吨氨成本 / 元·t$^{-1}$")
    ax.grid(axis="y", color=COLORS["grid"])
    ax.legend(loc="upper left", frameon=True, framealpha=0.95)

    y_min = df["annual_avg_ton_cost_yuan_per_ton"].min()
    y_max = df["annual_avg_ton_cost_yuan_per_ton"].max()
    y_pad = (y_max - y_min) * 0.12
    ax.set_ylim(y_min - y_pad, y_max + y_pad)

    _save(fig, output_dir / "q2_annual_avg_cost.png")
