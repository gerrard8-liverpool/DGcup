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

from scipy.optimize import Bounds, LinearConstraint, milp


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT / "src"))

from dgcup.core.cost import tou_price_by_hour
from dgcup.data.load_excel import read_excel_by_prefix
from dgcup.data.build_scenarios import (
    build_typical_scenario_profile,
    build_24_wind_pv_scenario_profiles,
)
from dgcup.optimization.q2_discrete_dispatch import (
    DiscreteDispatchParams,
    calculate_hourly_dispatch,
    _build_summary,
    run_production_set,
    summarize_annual_results,
)


PRODUCTIONS = (72, 63, 54, 45, 36)


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


def parse_float_list(text: str) -> list[float]:
    return [float(x.strip()) for x in text.split(",") if x.strip()]


def parse_int_list(text: str) -> list[int]:
    return [int(float(x.strip())) for x in text.split(",") if x.strip()]


def total_nh3_power_mw(params: DiscreteDispatchParams) -> float:
    return params.alk_power_mw + params.pem_power_mw + params.ammonia_power_mw


def startup_penalty_yuan(
    profile: pd.DataFrame,
    params: DiscreteDispatchParams,
    startup_equiv_hours: float,
) -> float:
    """
    Convert start-up loss into equivalent full-load-hour cost.

    startup_equiv_hours = 0.5 means each start-up is assumed to consume an
    additional cost equivalent to 0.5 hour of full-load operation.

    This is not used in the main Q2 model; it is only used for robustness
    validation under operating-inertia assumptions.
    """
    avg_tou = profile["hour"].map(tou_price_by_hour).mean()

    electric_equiv_cost = total_nh3_power_mw(params) * 1000.0 * avg_tou

    om_equiv_cost = (
        params.alk_power_mw * 1000.0 * params.alk_om_yuan_per_kwh
        + params.pem_power_mw * 1000.0 * params.pem_om_yuan_per_kwh
        + params.ammonia_power_mw * 1000.0 * params.ammonia_om_yuan_per_kwh
    )

    return float(startup_equiv_hours) * (electric_equiv_cost + om_equiv_cost)


def build_incremental_cost(profile: pd.DataFrame, params: DiscreteDispatchParams) -> pd.DataFrame:
    n = len(profile)
    zero_status = np.zeros(n, dtype=int)
    hourly_zero = calculate_hourly_dispatch(profile, zero_status, params)

    rows = []

    for hour in range(n):
        one_status = np.zeros(n, dtype=int)
        one_status[hour] = 1

        hourly_one = calculate_hourly_dispatch(profile, one_status, params)

        delta_cost = (
            hourly_one.loc[hour, "hourly_net_cost_yuan"]
            - hourly_zero.loc[hour, "hourly_net_cost_yuan"]
        )

        rows.append(
            {
                "hour": int(hour),
                "time": str(profile.loc[hour, "time"]),
                "delta_cost_yuan": float(delta_cost),
            }
        )

    return pd.DataFrame(rows)


def solve_inertia_dispatch(
    profile: pd.DataFrame,
    production_ton: float,
    params: DiscreteDispatchParams,
    min_run_hours: int,
    startup_equiv_hours: float,
    cyclic_day: bool = True,
) -> tuple[pd.DataFrame, dict]:
    """
    Enhanced Q2 validation model.

    Variables:
    x_t     = 1 if the hydrogen-ammonia system is on at hour t.
    s_t     = 1 if a start-up occurs at hour t.

    Constraints:
    sum_t x_t = H
    s_t = max(0, x_t - x_{t-1}) through linear inequalities
    min-run constraint: if s_t = 1, the following min_run_hours must stay on.

    The default cyclic_day=True treats the 24-hour profile as a repeated
    representative day, so hour 23 connects to hour 0.
    """
    n = len(profile)
    if n != 24:
        raise ValueError("This script assumes 24 hourly periods.")

    on_hours_float = production_ton / params.ammonia_output_ton_per_hour
    on_hours = int(round(on_hours_float))

    if abs(on_hours_float - on_hours) > 1e-8:
        raise ValueError("production_ton must be compatible with full-load hourly output.")

    if not 0 <= on_hours <= n:
        raise ValueError("on_hours must be between 0 and 24.")

    delta_df = build_incremental_cost(profile, params)
    startup_cost = startup_penalty_yuan(profile, params, startup_equiv_hours)

    # Decision variables: [x_0 ... x_23, s_0 ... s_23]
    num_vars = 2 * n
    x_offset = 0
    s_offset = n

    c = np.zeros(num_vars)
    c[x_offset : x_offset + n] = delta_df["delta_cost_yuan"].to_numpy()
    c[s_offset : s_offset + n] = startup_cost

    lb = np.zeros(num_vars)
    ub = np.ones(num_vars)

    constraints = []
    lower_bounds = []
    upper_bounds = []

    def add_constraint(coefs: dict[int, float], lb_val: float, ub_val: float) -> None:
        row = np.zeros(num_vars)
        for idx, val in coefs.items():
            row[idx] = val
        constraints.append(row)
        lower_bounds.append(lb_val)
        upper_bounds.append(ub_val)

    # Fixed daily production: sum x_t = H.
    add_constraint(
        {x_offset + t: 1.0 for t in range(n)},
        float(on_hours),
        float(on_hours),
    )

    # Start-up definition.
    # s_t >= x_t - x_{t-1}
    # s_t <= x_t
    # s_t <= 1 - x_{t-1}
    for t in range(n):
        x_t = x_offset + t
        s_t = s_offset + t

        if t == 0 and not cyclic_day:
            # Previous status is fixed to off.
            add_constraint({s_t: 1.0, x_t: -1.0}, 0.0, np.inf)
            add_constraint({s_t: 1.0, x_t: -1.0}, -np.inf, 0.0)
            # s_t <= 1 is already covered by variable bound.
            prev_x = None
        else:
            prev = n - 1 if t == 0 else t - 1
            prev_x = x_offset + prev

            add_constraint({s_t: 1.0, x_t: -1.0, prev_x: 1.0}, 0.0, np.inf)
            add_constraint({s_t: 1.0, x_t: -1.0}, -np.inf, 0.0)
            add_constraint({s_t: 1.0, prev_x: 1.0}, -np.inf, 1.0)

    # Minimum continuous running time.
    min_run_hours = int(max(1, min_run_hours))
    if min_run_hours > 1:
        for t in range(n):
            s_t = s_offset + t

            coefs = {s_t: -float(min_run_hours)}

            for k in range(min_run_hours):
                idx = t + k
                if cyclic_day:
                    idx = idx % n
                    coefs[x_offset + idx] = coefs.get(x_offset + idx, 0.0) + 1.0
                else:
                    if idx < n:
                        coefs[x_offset + idx] = coefs.get(x_offset + idx, 0.0) + 1.0
                    else:
                        # Non-cyclic horizon: starts too close to the end are implicitly discouraged.
                        pass

            add_constraint(coefs, 0.0, np.inf)

    A = np.vstack(constraints)
    linear_constraint = LinearConstraint(A, np.array(lower_bounds), np.array(upper_bounds))
    bounds = Bounds(lb, ub)
    integrality = np.ones(num_vars)

    res = milp(
        c=c,
        integrality=integrality,
        bounds=bounds,
        constraints=linear_constraint,
        options={"time_limit": 60, "disp": False},
    )

    if not res.success:
        raise RuntimeError(
            f"MILP failed for production={production_ton}, "
            f"min_run={min_run_hours}, startup={startup_equiv_hours}: {res.message}"
        )

    x = np.rint(res.x[x_offset : x_offset + n]).astype(int)
    s = np.rint(res.x[s_offset : s_offset + n]).astype(int)

    hourly = calculate_hourly_dispatch(profile, x, params)
    hourly = hourly.merge(delta_df[["hour", "delta_cost_yuan"]], on="hour", how="left")

    hourly["production_ton"] = production_ton
    hourly["hourly_ammonia_output_ton"] = x * params.ammonia_output_ton_per_hour
    hourly["startup_status"] = s
    hourly["startup_penalty_yuan_each"] = startup_cost
    hourly["startup_cost_yuan"] = s * startup_cost
    hourly["min_run_hours"] = min_run_hours
    hourly["startup_equiv_hours"] = startup_equiv_hours
    hourly["cyclic_day"] = cyclic_day

    summary = _build_summary(hourly, production_ton, params)

    start_count = int(s.sum())
    startup_total = float(start_count * startup_cost)

    summary["min_run_hours"] = min_run_hours
    summary["startup_equiv_hours"] = startup_equiv_hours
    summary["startup_penalty_yuan_each"] = startup_cost
    summary["start_count"] = start_count
    summary["startup_cost_yuan"] = startup_total
    summary["total_cost_without_startup_yuan"] = summary["total_cost_yuan"]
    summary["total_cost_yuan"] = summary["total_cost_yuan"] + startup_total
    summary["ton_cost_yuan_per_ton"] = summary["total_cost_yuan"] / production_ton
    summary["cyclic_day"] = cyclic_day

    return hourly, summary


def run_inertia_case_set(
    profile: pd.DataFrame,
    productions: tuple[float, ...],
    params: DiscreteDispatchParams,
    min_run_hours: int,
    startup_equiv_hours: float,
    cyclic_day: bool,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    hourly_list = []
    summary_list = []

    for production in productions:
        hourly, summary = solve_inertia_dispatch(
            profile=profile,
            production_ton=float(production),
            params=params,
            min_run_hours=min_run_hours,
            startup_equiv_hours=startup_equiv_hours,
            cyclic_day=cyclic_day,
        )
        hourly_list.append(hourly)
        summary_list.append(summary)

    return pd.concat(hourly_list, ignore_index=True), pd.DataFrame(summary_list)


def summarize_annual_inertia(
    scenario_summary_df: pd.DataFrame,
    scenario_days: int = 15,
) -> pd.DataFrame:
    rows = []

    group_cols = ["min_run_hours", "startup_equiv_hours", "production_ton"]

    for keys, group in scenario_summary_df.groupby(group_cols):
        min_run, startup_equiv, production = keys

        year_total_cost = (group["total_cost_yuan"] * scenario_days).sum()
        year_total_production = (group["production_ton"] * scenario_days).sum()
        annual_avg_ton_cost = year_total_cost / year_total_production

        count_all = int((group["satisfaction_type"] == "全满足").sum())
        count_partial = int((group["satisfaction_type"] == "部分满足").sum())
        count_none = int((group["satisfaction_type"] == "全不满足").sum())

        rows.append(
            {
                "min_run_hours": int(min_run),
                "startup_equiv_hours": float(startup_equiv),
                "production_ton": float(production),
                "scenario_count": len(group),
                "annual_days": len(group) * scenario_days,
                "annual_total_cost_yuan": year_total_cost,
                "annual_total_production_ton": year_total_production,
                "annual_avg_ton_cost_yuan_per_ton": annual_avg_ton_cost,
                "annual_total_startups": (group["start_count"] * scenario_days).sum(),
                "mean_daily_start_count": group["start_count"].mean(),
                "mean_startup_cost_yuan": group["startup_cost_yuan"].mean(),
                "all_satisfied_scenarios": count_all,
                "partially_satisfied_scenarios": count_partial,
                "none_satisfied_scenarios": count_none,
                "all_satisfied_days": count_all * scenario_days,
                "partially_satisfied_days": count_partial * scenario_days,
                "none_satisfied_days": count_none * scenario_days,
                "mean_grid_purchase_mwh": group["grid_purchase_mwh"].mean(),
                "mean_grid_export_mwh": group["grid_export_mwh"].mean(),
                "mean_renewable_self_use_ratio": group["renewable_self_use_ratio"].mean(),
                "mean_green_power_ratio": group["green_power_ratio"].mean(),
                "mean_renewable_export_ratio": group["renewable_export_ratio"].mean(),
            }
        )

    return pd.DataFrame(rows).sort_values(
        ["min_run_hours", "startup_equiv_hours", "production_ton"],
        ascending=[True, True, False],
    )


def build_vs_baseline(annual_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    baseline = annual_df[
        (annual_df["min_run_hours"] == 1)
        & (annual_df["startup_equiv_hours"] == 0.0)
    ].copy()

    baseline = baseline[
        [
            "production_ton",
            "annual_avg_ton_cost_yuan_per_ton",
            "mean_daily_start_count",
            "all_satisfied_days",
            "partially_satisfied_days",
            "none_satisfied_days",
        ]
    ].rename(
        columns={
            "annual_avg_ton_cost_yuan_per_ton": "baseline_annual_avg_ton_cost_yuan_per_ton",
            "mean_daily_start_count": "baseline_mean_daily_start_count",
            "all_satisfied_days": "baseline_all_satisfied_days",
            "partially_satisfied_days": "baseline_partially_satisfied_days",
            "none_satisfied_days": "baseline_none_satisfied_days",
        }
    )

    comparison = annual_df.merge(baseline, on="production_ton", how="left")

    comparison["cost_increase_yuan_per_ton"] = (
        comparison["annual_avg_ton_cost_yuan_per_ton"]
        - comparison["baseline_annual_avg_ton_cost_yuan_per_ton"]
    )

    comparison["cost_increase_ratio"] = (
        comparison["cost_increase_yuan_per_ton"]
        / comparison["baseline_annual_avg_ton_cost_yuan_per_ton"]
    )

    comparison["start_count_change"] = (
        comparison["mean_daily_start_count"]
        - comparison["baseline_mean_daily_start_count"]
    )

    best_by_case = (
        annual_df.sort_values("annual_avg_ton_cost_yuan_per_ton")
        .groupby(["min_run_hours", "startup_equiv_hours"], as_index=False)
        .first()
    )

    base_best = best_by_case[
        (best_by_case["min_run_hours"] == 1)
        & (best_by_case["startup_equiv_hours"] == 0.0)
    ].iloc[0]

    best_by_case["best_cost_increase_yuan_per_ton"] = (
        best_by_case["annual_avg_ton_cost_yuan_per_ton"]
        - base_best["annual_avg_ton_cost_yuan_per_ton"]
    )

    best_by_case["best_cost_increase_ratio"] = (
        best_by_case["best_cost_increase_yuan_per_ton"]
        / base_best["annual_avg_ton_cost_yuan_per_ton"]
    )

    return comparison, best_by_case


def plot_best_cost(best_by_case: pd.DataFrame, figure_dir: Path) -> None:
    setup_chinese_font()

    fig, ax = plt.subplots(figsize=(11.5, 6.5))

    for min_run, group in best_by_case.groupby("min_run_hours"):
        group = group.sort_values("startup_equiv_hours")
        ax.plot(
            group["startup_equiv_hours"],
            group["annual_avg_ton_cost_yuan_per_ton"],
            marker="o",
            linewidth=2.2,
            label=f"最小连续运行 {int(min_run)} h",
        )

    ax.set_xlabel("启动损耗 / 满负荷小时等效")
    ax.set_ylabel("年化最优吨氨成本 / 元·t$^{-1}$")
    ax.set_title("问题二增强验证：启动损耗与最小连续运行约束下的最优成本")
    ax.grid(alpha=0.3)
    ax.legend(loc="best", framealpha=0.95)
    plt.tight_layout()
    plt.savefig(figure_dir / "q2_inertia_best_cost.png", bbox_inches="tight")
    plt.close(fig)


def plot_best_production(best_by_case: pd.DataFrame, figure_dir: Path) -> None:
    setup_chinese_font()

    fig, ax = plt.subplots(figsize=(11.5, 6.5))

    for min_run, group in best_by_case.groupby("min_run_hours"):
        group = group.sort_values("startup_equiv_hours")
        ax.plot(
            group["startup_equiv_hours"],
            group["production_ton"],
            marker="s",
            linewidth=2.2,
            label=f"最小连续运行 {int(min_run)} h",
        )

    ax.set_xlabel("启动损耗 / 满负荷小时等效")
    ax.set_ylabel("年化最低成本对应日产量 / t")
    ax.set_title("问题二增强验证：运行惯性约束下的最优日产量稳定性")
    ax.set_yticks(sorted(best_by_case["production_ton"].unique()))
    ax.grid(alpha=0.3)
    ax.legend(loc="best", framealpha=0.95)
    plt.tight_layout()
    plt.savefig(figure_dir / "q2_inertia_best_production.png", bbox_inches="tight")
    plt.close(fig)


def plot_cost_increase_heatmap(best_by_case: pd.DataFrame, figure_dir: Path) -> None:
    setup_chinese_font()

    pivot = best_by_case.pivot(
        index="min_run_hours",
        columns="startup_equiv_hours",
        values="best_cost_increase_yuan_per_ton",
    ).sort_index()

    fig, ax = plt.subplots(figsize=(10.5, 6.2))

    im = ax.imshow(pivot.values, aspect="auto")

    ax.set_xticks(np.arange(len(pivot.columns)))
    ax.set_xticklabels([f"{x:g}" for x in pivot.columns])
    ax.set_yticks(np.arange(len(pivot.index)))
    ax.set_yticklabels([f"{int(x)} h" for x in pivot.index])

    for i in range(pivot.shape[0]):
        for j in range(pivot.shape[1]):
            val = pivot.values[i, j]
            ax.text(j, i, f"{val:.1f}", ha="center", va="center", fontsize=10)

    ax.set_xlabel("启动损耗 / 满负荷小时等效")
    ax.set_ylabel("最小连续运行时间")
    ax.set_title("问题二增强验证：年化最优吨氨成本增量 / 元·t$^{-1}$")

    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("相对基准成本增量 / 元·t$^{-1}$")

    plt.tight_layout()
    plt.savefig(figure_dir / "q2_inertia_cost_increase_heatmap.png", bbox_inches="tight")
    plt.close(fig)


def plot_typical_schedule(
    typical_hourly_df: pd.DataFrame,
    best_by_case: pd.DataFrame,
    min_run_levels: list[int],
    startup_levels: list[float],
    figure_dir: Path,
) -> None:
    setup_chinese_font()

    baseline_case = typical_hourly_df[
        (typical_hourly_df["min_run_hours"] == 1)
        & (typical_hourly_df["startup_equiv_hours"] == 0.0)
        & (typical_hourly_df["production_ton"] == 36.0)
    ].copy()

    strict_min_run = max(min_run_levels)
    strict_startup = max(startup_levels)

    strict_best = best_by_case[
        (best_by_case["min_run_hours"] == strict_min_run)
        & (best_by_case["startup_equiv_hours"] == strict_startup)
    ]

    if strict_best.empty:
        return

    strict_production = float(strict_best.iloc[0]["production_ton"])

    strict_case = typical_hourly_df[
        (typical_hourly_df["min_run_hours"] == strict_min_run)
        & (typical_hourly_df["startup_equiv_hours"] == strict_startup)
        & (typical_hourly_df["production_ton"] == strict_production)
    ].copy()

    if baseline_case.empty or strict_case.empty:
        return

    matrix = np.vstack(
        [
            baseline_case.sort_values("hour")["on_status"].to_numpy(),
            strict_case.sort_values("hour")["on_status"].to_numpy(),
        ]
    )

    labels = [
        "基准：无启动损耗、1h最小运行、36 t/day",
        f"增强：启动损耗{strict_startup:g}h、{strict_min_run}h最小运行、{strict_production:.0f} t/day",
    ]

    from matplotlib.colors import ListedColormap
    from matplotlib.patches import Patch

    fig, ax = plt.subplots(figsize=(13, 3.8))

    cmap = ListedColormap(["#D9D9D9", "#2CA02C"])
    ax.imshow(matrix, aspect="auto", vmin=0, vmax=1, cmap=cmap)

    ax.set_xticks(np.arange(24))
    ax.set_xticklabels([f"{h}:00" for h in range(24)], rotation=45, ha="right")
    ax.set_yticks(np.arange(2))
    ax.set_yticklabels(labels)

    ax.set_title("问题二增强验证：典型场景开机时段对比")
    ax.set_xlabel("时段")
    ax.set_ylabel("调度方案")

    legend_handles = [
        Patch(facecolor="#2CA02C", label="开机"),
        Patch(facecolor="#D9D9D9", label="停机"),
    ]
    ax.legend(handles=legend_handles, loc="upper right", framealpha=0.95)

    plt.tight_layout()
    plt.savefig(figure_dir / "q2_inertia_typical_schedule_comparison.png", bbox_inches="tight")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--startup-levels", type=str, default="0,0.5,1,2")
    parser.add_argument("--min-run-levels", type=str, default="1,2,3,4")
    parser.add_argument("--non-cyclic", action="store_true")
    args = parser.parse_args()

    startup_levels = parse_float_list(args.startup_levels)
    min_run_levels = parse_int_list(args.min_run_levels)
    cyclic_day = not args.non_cyclic

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

    typical_profile = build_typical_scenario_profile(
        load_df=load_df,
        renewable_df=typical_renewable_df,
    )

    scenario_profiles = build_24_wind_pv_scenario_profiles(
        load_df=load_df,
        wind_df=wind_scenario_df,
        pv_df=pv_scenario_df,
    )

    all_typical_hourly = []
    all_typical_summary = []
    all_scenario_summary = []

    for min_run in min_run_levels:
        for startup_equiv in startup_levels:
            print(
                f"[Q2 inertia] typical | min_run={min_run} h | "
                f"startup={startup_equiv:g} full-load-hour equivalent"
            )

            typical_hourly, typical_summary = run_inertia_case_set(
                profile=typical_profile,
                productions=PRODUCTIONS,
                params=params,
                min_run_hours=min_run,
                startup_equiv_hours=startup_equiv,
                cyclic_day=cyclic_day,
            )

            all_typical_hourly.append(typical_hourly)
            all_typical_summary.append(typical_summary)

            for scenario in scenario_profiles:
                print(
                    f"[Q2 inertia] {scenario['scenario_id']} | "
                    f"min_run={min_run} h | startup={startup_equiv:g}"
                )

                _, summary_df = run_inertia_case_set(
                    profile=scenario["profile"],
                    productions=PRODUCTIONS,
                    params=params,
                    min_run_hours=min_run,
                    startup_equiv_hours=startup_equiv,
                    cyclic_day=cyclic_day,
                )

                all_scenario_summary.append(summary_df)

    typical_hourly_df = pd.concat(all_typical_hourly, ignore_index=True)
    typical_summary_df = pd.concat(all_typical_summary, ignore_index=True)
    scenario_summary_df = pd.concat(all_scenario_summary, ignore_index=True)

    annual_df = summarize_annual_inertia(scenario_summary_df, scenario_days=15)
    comparison_df, best_by_case_df = build_vs_baseline(annual_df)

    typical_hourly_df.to_csv(
        table_dir / "q2_inertia_typical_hourly_dispatch.csv",
        index=False,
        encoding="utf-8-sig",
    )

    typical_summary_df.to_csv(
        table_dir / "q2_inertia_typical_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )

    scenario_summary_df.to_csv(
        table_dir / "q2_inertia_scenario_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )

    annual_df.to_csv(
        table_dir / "q2_inertia_annual_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )

    comparison_df.to_csv(
        table_dir / "q2_inertia_vs_baseline.csv",
        index=False,
        encoding="utf-8-sig",
    )

    best_by_case_df.to_csv(
        table_dir / "q2_inertia_best_by_case.csv",
        index=False,
        encoding="utf-8-sig",
    )

    plot_best_cost(best_by_case_df, figure_dir)
    plot_best_production(best_by_case_df, figure_dir)
    plot_cost_increase_heatmap(best_by_case_df, figure_dir)
    plot_typical_schedule(
        typical_hourly_df=typical_hourly_df,
        best_by_case=best_by_case_df,
        min_run_levels=min_run_levels,
        startup_levels=startup_levels,
        figure_dir=figure_dir,
    )

    print("=" * 96)
    print("Q2 inertia validation finished.")
    print("=" * 96)
    print(
        best_by_case_df[
            [
                "min_run_hours",
                "startup_equiv_hours",
                "production_ton",
                "annual_avg_ton_cost_yuan_per_ton",
                "best_cost_increase_yuan_per_ton",
                "mean_daily_start_count",
                "all_satisfied_days",
                "partially_satisfied_days",
                "none_satisfied_days",
            ]
        ].to_string(index=False)
    )
    print("=" * 96)
    print(f"Tables saved to: {table_dir}")
    print(f"Figures saved to: {figure_dir}")
    print("=" * 96)


if __name__ == "__main__":
    main()
