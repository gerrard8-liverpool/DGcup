from pathlib import Path
import pandas as pd
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter


COLORS = {
    "base": "#4E79A7",
    "hydrogen": "#A0CBE8",
    "renewable": "#E15759",
    "wind": "#59A14F",
    "pv": "#F28E2B",
    "purchase": "#D62728",
    "export": "#2CA02C",
    "pass": "#2CA02C",
    "fail": "#D62728",
    "neutral": "#4E79A7",
    "threshold": "#111111",
    "grid": "#B0B0B0",
}


def setup_publication_style():
    plt.rcParams.update({
        "font.sans-serif": [
            "Microsoft YaHei",
            "SimHei",
            "Arial Unicode MS",
            "DejaVu Sans",
        ],
        "axes.unicode_minus": False,
        "figure.dpi": 130,
        "savefig.dpi": 320,
        "axes.titlesize": 15,
        "axes.labelsize": 12,
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
        "legend.fontsize": 10,
        "axes.linewidth": 1.1,
        "grid.alpha": 0.25,
    })


def _save(fig, path: Path):
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def plot_q1_power_balance(hourly: pd.DataFrame, output_dir: str | Path):
    """
    Publication-level Q1 power balance figure.

    Upper panel:
        load stack and renewable generation curves.

    Lower panel:
        renewable-load mismatch.
        Positive values indicate renewable surplus.
        Negative values indicate renewable deficit.
    """
    setup_publication_style()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    x = list(range(24))
    labels = hourly["time"].astype(str).tolist()

    total_load = hourly["total_load_mw"]
    renewable = hourly["renewable_power_mw"]
    net_surplus = renewable - total_load

    fig, (ax1, ax2) = plt.subplots(
        2,
        1,
        figsize=(14.2, 8.6),
        sharex=True,
        gridspec_kw={"height_ratios": [2.35, 1.05], "hspace": 0.22},
    )

    # =========================
    # Upper panel
    # =========================
    ax1.stackplot(
        x,
        hourly["base_load_mw"],
        hourly["hydrogen_ammonia_load_mw"],
        labels=["常规电负荷", "制氢氨负荷"],
        colors=["#6B8FB8", "#BFD7EA"],
        alpha=0.90,
        zorder=1,
    )

    ax1.plot(
        x,
        total_load,
        color="#1F4E79",
        linewidth=2.4,
        label="总用电负荷",
        zorder=4,
    )

    ax1.plot(
        x,
        renewable,
        color="#D62728",
        linewidth=2.9,
        marker="o",
        markersize=4.2,
        label="风光总出力",
        zorder=5,
    )

    ax1.plot(
        x,
        hourly["wind_power_mw"],
        color="#2E7D32",
        linewidth=2.0,
        linestyle="--",
        label="风电出力",
        zorder=4,
    )

    ax1.plot(
        x,
        hourly["pv_power_mw"],
        color="#F28E2B",
        linewidth=2.0,
        linestyle="--",
        label="光伏出力",
        zorder=4,
    )

    ax1.set_title("问题一：典型日园区负荷与风光出力功率平衡", pad=12)
    ax1.set_ylabel("功率 / MW")
    ax1.grid(axis="y", color=COLORS["grid"])
    ax1.set_ylim(bottom=0)

    ax1.legend(
        loc="upper right",
        ncol=2,
        frameon=True,
        fancybox=True,
        framealpha=0.96,
        borderpad=0.7,
        handlelength=2.4,
        columnspacing=1.2,
    )

    ax1.text(
        0.012,
        0.955,
        "蓝色堆叠为园区总负荷，红线为风光总出力",
        transform=ax1.transAxes,
        va="top",
        ha="left",
        fontsize=10.5,
        bbox=dict(
            boxstyle="round,pad=0.35",
            facecolor="white",
            edgecolor="#CCCCCC",
            alpha=0.96,
        ),
    )

    # =========================
    # Lower panel
    # =========================
    surplus = net_surplus.clip(lower=0)
    deficit = net_surplus.clip(upper=0)

    ax2.bar(
        x,
        surplus,
        color="#2CA02C",
        alpha=0.82,
        width=0.72,
        label="新能源盈余：可上网",
        zorder=3,
    )

    ax2.bar(
        x,
        deficit,
        color="#D62728",
        alpha=0.82,
        width=0.72,
        label="新能源缺口：需购电",
        zorder=3,
    )

    ax2.axhline(0, color="#222222", linewidth=1.1, zorder=4)
    ax2.set_ylabel("净功率 / MW")
    ax2.set_xlabel("时段")
    ax2.grid(axis="y", color=COLORS["grid"], zorder=0)

    max_abs = max(abs(net_surplus.min()), abs(net_surplus.max()))
    ax2.set_ylim(-max_abs * 1.18, max_abs * 1.18)

    ax2.set_xticks(x)
    ax2.set_xticklabels(labels, rotation=55, ha="right")

    ax2.legend(
        loc="upper left",
        ncol=2,
        frameon=True,
        fancybox=True,
        framealpha=0.96,
        borderpad=0.7,
        handlelength=2.2,
        columnspacing=1.4,
    )

    ax2.text(
        0.988,
        0.92,
        "净功率 = 风光总出力 - 总用电负荷",
        transform=ax2.transAxes,
        va="top",
        ha="right",
        fontsize=10.2,
        bbox=dict(
            boxstyle="round,pad=0.35",
            facecolor="white",
            edgecolor="#CCCCCC",
            alpha=0.96,
        ),
    )

    fig.subplots_adjust(top=0.93, bottom=0.16, left=0.075, right=0.985)

    _save(fig, output_dir / "q1_power_balance.png")


def plot_q1_grid_interaction(hourly: pd.DataFrame, output_dir: str | Path):
    """
    Grid interaction figure:
    purchase is positive, export is negative.
    """
    setup_publication_style()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    x = list(range(24))
    labels = hourly["time"].astype(str).tolist()

    purchase = hourly["grid_purchase_mw"]
    export = hourly["grid_export_mw"]
    total_purchase = purchase.sum()
    total_export = export.sum()

    fig, ax = plt.subplots(figsize=(13.5, 5.8))

    ax.bar(
        x,
        purchase,
        color=COLORS["purchase"],
        alpha=0.82,
        width=0.72,
        label="购电功率",
        zorder=3,
    )

    ax.bar(
        x,
        -export,
        color=COLORS["export"],
        alpha=0.82,
        width=0.72,
        label="上网功率",
        zorder=3,
    )

    ax.axhline(0, color="#222222", linewidth=1.2, zorder=4)

    y_abs = max(purchase.max(), export.max()) * 1.22
    ax.set_ylim(-y_abs, y_abs)

    ax.set_title("问题一：典型日购电与上网功率分布")
    ax.set_xlabel("时段")
    ax.set_ylabel("功率 / MW")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=55, ha="right")
    ax.grid(axis="y", color=COLORS["grid"], zorder=0)

    ax.text(
        0.985,
        0.94,
        f"日购电量：{total_purchase:.2f} MWh\n日上网量：{total_export:.2f} MWh",
        transform=ax.transAxes,
        va="top",
        ha="right",
        fontsize=11,
        bbox=dict(boxstyle="round,pad=0.45", facecolor="white", edgecolor="#CCCCCC", alpha=0.95),
    )

    ax.legend(loc="upper left", frameon=True, fancybox=True, framealpha=0.95)

    _save(fig, output_dir / "q1_grid_interaction.png")


def plot_q1_indicators(summary: dict, output_dir: str | Path):
    """
    Green power indicators.
    Thresholds are drawn as independent black short lines with high z-order,
    instead of a connected line, because the three indicators have different meanings.
    """
    setup_publication_style()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    labels = ["新能源自发自用比例", "总用电量绿电比例", "新能源上网比例"]
    values = [
        summary["renewable_self_use_ratio"],
        summary["green_power_ratio"],
        summary["renewable_export_ratio"],
    ]
    thresholds = [0.60, 0.30, 0.20]
    directions = ["≥", "≥", "≤"]
    pass_flags = [
        summary["renewable_self_use_pass"],
        summary["green_power_pass"],
        summary["renewable_export_pass"],
    ]

    bar_colors = [COLORS["pass"] if p else COLORS["fail"] for p in pass_flags]

    fig, ax = plt.subplots(figsize=(10.6, 5.8))

    x = list(range(len(labels)))
    bar_width = 0.56

    bars = ax.bar(
        x,
        values,
        width=bar_width,
        color=bar_colors,
        alpha=0.86,
        edgecolor="#222222",
        linewidth=0.8,
        zorder=3,
        label="计算值",
    )

    for i, (value, threshold, direction, passed) in enumerate(
        zip(values, thresholds, directions, pass_flags)
    ):
        ax.hlines(
            y=threshold,
            xmin=i - bar_width * 0.62,
            xmax=i + bar_width * 0.62,
            color=COLORS["threshold"],
            linewidth=2.8,
            linestyles="--",
            zorder=6,
        )
        ax.scatter(
            i,
            threshold,
            s=58,
            color="white",
            edgecolor=COLORS["threshold"],
            linewidth=1.8,
            zorder=7,
        )

        ax.text(
            i,
            threshold + 0.035,
            f"要求 {direction}{threshold:.0%}",
            ha="center",
            va="bottom",
            fontsize=10,
            color=COLORS["threshold"],
            zorder=8,
        )

        status = "达标" if passed else "未达标"
        status_color = COLORS["pass"] if passed else COLORS["fail"]

        ax.text(
            i,
            value + 0.025,
            f"{value:.2%}\n{status}",
            ha="center",
            va="bottom",
            fontsize=11,
            fontweight="bold",
            color=status_color,
            zorder=8,
        )

    ax.set_title("问题一：绿电直连关键指标达标判定")
    ax.set_ylabel("比例")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax.set_ylim(0, max(max(values), max(thresholds)) + 0.18)
    ax.grid(axis="y", color=COLORS["grid"], zorder=0)

    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    legend_handles = [
        Patch(facecolor=COLORS["pass"], edgecolor="#222222", label="达标指标"),
        Patch(facecolor=COLORS["fail"], edgecolor="#222222", label="未达标指标"),
        Line2D([0], [0], color=COLORS["threshold"], linestyle="--", linewidth=2.5, label="政策阈值"),
    ]

    ax.legend(
        handles=legend_handles,
        loc="upper right",
        frameon=True,
        fancybox=True,
        framealpha=0.95,
    )

    _save(fig, output_dir / "q1_green_indicators.png")


def plot_q1_cost_breakdown(cost_summary: dict, output_dir: str | Path):
    """
    Cost breakdown using horizontal bars.
    Positive values are costs, negative values are grid-export revenue.
    Unit is converted from yuan to 10k yuan for readability.
    """
    setup_publication_style()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    items = [
        ("购电成本", cost_summary["grid_purchase_cost_yuan"]),
        ("风电发电成本", cost_summary["wind_generation_cost_yuan"]),
        ("光伏发电成本", cost_summary["pv_generation_cost_yuan"]),
        ("ALK 电解槽运维", cost_summary["alk_om_cost_yuan"]),
        ("PEM 电解槽运维", cost_summary["pem_om_cost_yuan"]),
        ("合成氨装置运维", cost_summary["ammonia_om_cost_yuan"]),
        ("合成氨装置折旧", cost_summary.get("ammonia_capex_daily_yuan", 0.0)),
        ("余电上网收益", -cost_summary["grid_export_revenue_yuan"]),
    ]

    labels = [i[0] for i in items]
    values = [i[1] / 10000 for i in items]

    colors = [
        COLORS["export"] if v < 0 else COLORS["purchase"]
        for v in values
    ]

    fig, ax = plt.subplots(figsize=(11.2, 6.4))

    y = list(range(len(labels)))
    ax.barh(
        y,
        values,
        color=colors,
        alpha=0.86,
        edgecolor="#222222",
        linewidth=0.7,
        zorder=3,
    )

    max_abs = max(abs(v) for v in values)
    ax.set_xlim(-max_abs * 1.18, max_abs * 1.18)

    ax.axvline(0, color="#222222", linewidth=1.1, zorder=4)
    ax.set_yticks(y)
    ax.set_yticklabels(labels)
    ax.invert_yaxis()
    ax.set_xlabel("金额 / 万元")
    ax.set_title("问题一：典型日吨氨成本构成")
    ax.grid(axis="x", color=COLORS["grid"], zorder=0)

    x_min, x_max = ax.get_xlim()
    offset = (x_max - x_min) * 0.015

    for yi, value in zip(y, values):
        if abs(value) < 0.01 and value != 0:
            label = f"{value:.4f}"
        else:
            label = f"{value:.2f}"

        if value >= 0:
            ax.text(
                value + offset,
                yi,
                label,
                va="center",
                ha="left",
                fontsize=10,
                clip_on=False,
            )
        else:
            ax.text(
                value - offset,
                yi,
                label,
                va="center",
                ha="right",
                fontsize=10,
                clip_on=False,
            )

    total_cost = cost_summary["total_cost_yuan"] / 10000
    ton_cost = cost_summary["ton_ammonia_cost_yuan_per_ton"]

    ax.text(
        0.985,
        0.075,
        f"日总成本：{total_cost:.2f} 万元\n吨氨成本：{ton_cost:.2f} 元/tNH3",
        transform=ax.transAxes,
        va="bottom",
        ha="right",
        fontsize=11,
        bbox=dict(
            boxstyle="round,pad=0.45",
            facecolor="white",
            edgecolor="#CCCCCC",
            alpha=0.95,
        ),
    )

    _save(fig, output_dir / "q1_cost_breakdown.png")

