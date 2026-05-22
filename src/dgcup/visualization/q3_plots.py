from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt

from dgcup.visualization.plots import setup_publication_style, COLORS


def _save(fig, path: Path):
    fig.savefig(path, bbox_inches="tight", facecolor="white", dpi=320)
    plt.close(fig)


def plot_q3_representative_dispatch_curve(
    hourly_df: pd.DataFrame,
    output_dir: str | Path,
    production_ton: float = 54.0,
):
    """
    Plot representative Q3 continuous dispatch curve.

    The upper-panel legend is placed in the widened gap between two panels,
    avoiding overlap with the lower grid-interaction subplot.
    """
    setup_publication_style()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    scenario_id = hourly_df["scenario_id"].iloc[0]
    if "W1_PV1" in hourly_df["scenario_id"].unique():
        scenario_id = "W1_PV1"

    df = hourly_df[
        (hourly_df["scenario_id"] == scenario_id)
        & (hourly_df["production_ton"] == production_ton)
    ].copy()

    if df.empty:
        df = hourly_df[hourly_df["production_ton"] == production_ton].copy()

    if df.empty:
        df = hourly_df.copy()

    df = df.sort_values("hour").head(24)

    x = list(range(len(df)))
    labels = df["time"].astype(str).tolist()

    fig, (ax1, ax2) = plt.subplots(
        2,
        1,
        figsize=(14.0, 9.0),
        sharex=True,
        gridspec_kw={"height_ratios": [2.35, 1.0], "hspace": 0.42},
    )

    ax1.plot(
        x,
        df["renewable_power_mw"],
        color="#D62728",
        marker="o",
        linewidth=2.5,
        label="风光总出力",
        zorder=4,
    )
    ax1.plot(
        x,
        df["base_load_mw"],
        color="#1F4E79",
        linewidth=2.2,
        label="常规负荷",
        zorder=4,
    )
    ax1.plot(
        x,
        df["hydrogen_ammonia_load_mw"],
        color="#2CA02C",
        linewidth=2.3,
        label="连续制氨负荷",
        zorder=4,
    )
    ax1.plot(
        x,
        df["total_load_mw"],
        color="#9467BD",
        linewidth=2.3,
        linestyle="--",
        label="总用电负荷",
        zorder=4,
    )

    ax1.set_title(
        f"问题三：代表性场景连续制氨功率调度曲线（{scenario_id}, {production_ton:.0f} t/day）",
        pad=12,
    )
    ax1.set_ylabel("功率 / MW")
    ax1.grid(axis="y", color=COLORS["grid"])

    ax1.legend(
        ncol=4,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.14),
        frameon=True,
        framealpha=0.96,
        columnspacing=1.6,
        handlelength=2.4,
    )

    ax2.bar(
        x,
        df["grid_purchase_mw"],
        color="#D62728",
        alpha=0.82,
        label="购电功率",
        zorder=3,
    )
    ax2.bar(
        x,
        -df["grid_export_mw"],
        color="#2CA02C",
        alpha=0.82,
        label="上网功率",
        zorder=3,
    )
    ax2.axhline(0, color="#222222", linewidth=1.0, zorder=4)

    y_abs = max(df["grid_purchase_mw"].max(), df["grid_export_mw"].max(), 1.0)
    ax2.set_ylim(-1.22 * y_abs, 1.22 * y_abs)

    ax2.set_xlabel("时段")
    ax2.set_ylabel("电网交互 / MW")
    ax2.set_xticks(x)
    ax2.set_xticklabels(labels, rotation=55, ha="right")
    ax2.grid(axis="y", color=COLORS["grid"], zorder=0)
    ax2.legend(
        ncol=2,
        loc="upper right",
        frameon=True,
        framealpha=0.96,
    )

    fig.subplots_adjust(top=0.92, bottom=0.16, left=0.075, right=0.985)

    _save(fig, output_dir / "q3_representative_dispatch_curve.png")


def plot_q3_scenario_cost_boxplot(
    scenario_summary_df: pd.DataFrame,
    output_dir: str | Path,
):
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

    ax.set_title("问题三：24 种风光场景下吨氨成本分布")
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
        bbox=dict(boxstyle="round,pad=0.35", facecolor="white", edgecolor="#CCCCCC", alpha=0.96),
    )

    _save(fig, output_dir / "q3_scenario_cost_boxplot.png")


def plot_q3_satisfaction_stacked_bar(
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

    ax.set_title("问题三：不同日产量下全年绿电指标达标分类")
    ax.set_xlabel("日产量 / t")
    ax.set_ylabel("全年等效天数 / 天")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylim(0, 380)
    ax.grid(axis="y", color=COLORS["grid"])
    ax.legend(ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.14), frameon=True)

    _save(fig, output_dir / "q3_satisfaction_stacked_bar.png")


def plot_q3_annual_avg_cost(
    annual_summary_df: pd.DataFrame,
    output_dir: str | Path,
):
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
        bbox=dict(boxstyle="round,pad=0.42", facecolor="white", edgecolor="#CCCCCC", alpha=0.96),
    )

    ax.set_title("问题三：全年加权平均吨氨成本随日产量变化")
    ax.set_xlabel("日产量 / t")
    ax.set_ylabel("全年加权平均吨氨成本 / 元·t$^{-1}$")
    ax.grid(axis="y", color=COLORS["grid"])
    ax.legend(loc="upper left", frameon=True, framealpha=0.95)

    y_min = df["annual_avg_ton_cost_yuan_per_ton"].min()
    y_max = df["annual_avg_ton_cost_yuan_per_ton"].max()
    y_pad = (y_max - y_min) * 0.12
    ax.set_ylim(y_min - y_pad, y_max + y_pad)

    _save(fig, output_dir / "q3_annual_avg_cost.png")


def plot_q3_vs_q2_cost_reduction(
    comparison_df: pd.DataFrame,
    output_dir: str | Path,
):
    setup_publication_style()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    df = comparison_df.sort_values("production_ton")

    fig, ax = plt.subplots(figsize=(9.8, 5.8))

    ax.bar(
        df["production_ton"].astype(str),
        df["cost_reduction_yuan_per_ton"],
        color="#2CA02C",
        alpha=0.85,
        edgecolor="#222222",
        linewidth=0.7,
    )

    ax.axhline(0, color="#222222", linewidth=1.0)
    ax.set_title("问题三：连续调节相对问题二的吨氨成本下降")
    ax.set_xlabel("日产量 / t")
    ax.set_ylabel("成本下降 / 元·t$^{-1}$")
    ax.grid(axis="y", color=COLORS["grid"])

    for i, row in enumerate(df.itertuples()):
        ax.text(
            i,
            row.cost_reduction_yuan_per_ton,
            f"{row.cost_reduction_yuan_per_ton:.2f}",
            ha="center",
            va="bottom" if row.cost_reduction_yuan_per_ton >= 0 else "top",
            fontsize=9.5,
        )

    _save(fig, output_dir / "q3_vs_q2_cost_reduction.png")


def plot_q3_vs_q2_grid_interaction(
    comparison_df: pd.DataFrame,
    output_dir: str | Path,
):
    setup_publication_style()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    df = comparison_df.sort_values("production_ton")

    x = np.arange(len(df))
    width = 0.36

    fig, ax = plt.subplots(figsize=(10.2, 5.8))

    ax.bar(
        x - width / 2,
        df["grid_purchase_reduction_mwh"],
        width,
        label="平均购电量下降",
        color="#D62728",
        alpha=0.82,
    )

    ax.bar(
        x + width / 2,
        df["grid_export_reduction_mwh"],
        width,
        label="平均上网量下降",
        color="#2CA02C",
        alpha=0.82,
    )

    ax.axhline(0, color="#222222", linewidth=1.0)
    ax.set_title("问题三：连续调节相对问题二的电网交互变化")
    ax.set_xlabel("日产量 / t")
    ax.set_ylabel("平均日电量变化 / MWh")
    ax.set_xticks(x)
    ax.set_xticklabels([f"{int(p)}" for p in df["production_ton"]])
    ax.grid(axis="y", color=COLORS["grid"])
    ax.legend(frameon=True, framealpha=0.95)

    _save(fig, output_dir / "q3_vs_q2_grid_interaction.png")
