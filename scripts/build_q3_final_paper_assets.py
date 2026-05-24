from __future__ import annotations

from pathlib import Path
import csv
import re
import shutil

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TABLE_DIR = PROJECT_ROOT / "outputs" / "tables"
FIGURE_DIR = PROJECT_ROOT / "outputs" / "figures"
REPORT_ASSET_DIR = PROJECT_ROOT / "outputs" / "report_assets"

SCENARIO_DAYS = 15


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


def require_file(path: Path, run_hint: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}\n请先运行：{run_hint}")


def normalize_scenario_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    if "scenario_id" not in df.columns:
        if {"wind_scenario", "pv_scenario"}.issubset(df.columns):
            df["scenario_id"] = (
                df["wind_scenario"].astype(str).str.extract(r"(\d+)")[0].astype(int) - 1
            ) * 4 + df["pv_scenario"].astype(str).str.extract(r"(\d+)")[0].astype(int)
        else:
            df["scenario_id"] = np.arange(1, len(df) + 1)

    if "wind_scenario" not in df.columns:
        if "scenario_label" in df.columns:
            df["wind_scenario"] = df["scenario_label"].astype(str).str.extract(r"(风电场景\d+|W\d+)")[0]
        else:
            df["wind_scenario"] = df["scenario_id"].apply(lambda x: f"W{int((x - 1) // 4 + 1)}")

    if "pv_scenario" not in df.columns:
        if "scenario_label" in df.columns:
            df["pv_scenario"] = df["scenario_label"].astype(str).str.extract(r"(光伏场景\d+|PV\d+)")[0]
        else:
            df["pv_scenario"] = df["scenario_id"].apply(lambda x: f"PV{int((x - 1) % 4 + 1)}")

    df["wind_idx"] = df["wind_scenario"].astype(str).str.extract(r"(\d+)")[0].astype(int)
    df["pv_idx"] = df["pv_scenario"].astype(str).str.extract(r"(\d+)")[0].astype(int)

    df["scenario_short"] = df.apply(
        lambda r: f"W{int(r['wind_idx'])}_PV{int(r['pv_idx'])}",
        axis=1,
    )

    return df


def ratio_to_pct(series: pd.Series) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    if s.dropna().empty:
        return s
    if s.dropna().max() <= 1.5:
        return s * 100.0
    return s


def add_pct_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    ratio_cols = [
        "renewable_self_use_ratio",
        "green_power_ratio",
        "renewable_export_ratio",
        "mean_renewable_self_use_ratio",
        "mean_green_power_ratio",
        "mean_renewable_export_ratio",
    ]
    for col in ratio_cols:
        if col in df.columns:
            df[col.replace("ratio", "pct")] = ratio_to_pct(df[col])
    return df


def build_cost_optimal_summary() -> pd.DataFrame:
    """
    每个风光场景选择吨氨成本最低的日产量方案。
    这个表回答：24 种场景下“纯经济最优”的方案是什么。
    """
    candidate_path = TABLE_DIR / "q3_paper_all_candidates_summary.csv"
    raw_path = TABLE_DIR / "q3_all_scenarios_summary.csv"

    if candidate_path.exists():
        df = pd.read_csv(candidate_path)
    else:
        require_file(raw_path, "python scripts/run_q3_continuous.py")
        df = pd.read_csv(raw_path)

    df = normalize_scenario_columns(df)
    df = add_pct_columns(df)

    required = ["scenario_id", "production_ton", "ton_cost_yuan_per_ton"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise RuntimeError(f"Q3 summary 缺少字段：{missing}\n现有字段：{list(df.columns)}")

    cost_optimal = (
        df.sort_values(["scenario_id", "ton_cost_yuan_per_ton"], ascending=[True, True])
        .groupby("scenario_id", as_index=False)
        .first()
        .sort_values(["wind_idx", "pv_idx"])
        .reset_index(drop=True)
    )

    cost_optimal.to_csv(
        TABLE_DIR / "q3_paper_scenario_min_cost_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )

    return cost_optimal


def build_min_cost_annual_classification(cost_optimal: pd.DataFrame) -> pd.DataFrame:
    """
    按全满足 / 部分满足 / 全不满足统计最小成本方案的年化结果。
    """
    df = cost_optimal.copy()

    if "satisfaction_type" not in df.columns:
        raise RuntimeError("缺少 satisfaction_type 字段，无法统计全满足/部分满足/全不满足。")

    rows = []
    for sat_type, g in df.groupby("satisfaction_type", sort=False):
        scenario_count = len(g)
        annual_days = scenario_count * SCENARIO_DAYS
        annual_production = float((g["production_ton"] * SCENARIO_DAYS).sum())

        if "total_cost_yuan" in g.columns:
            annual_cost = float((g["total_cost_yuan"] * SCENARIO_DAYS).sum())
            weighted_ton_cost = annual_cost / annual_production if annual_production > 0 else np.nan
        else:
            annual_cost = np.nan
            weighted_ton_cost = float(g["ton_cost_yuan_per_ton"].mean())

        row = {
            "satisfaction_type": sat_type,
            "scenario_count": scenario_count,
            "annual_days": annual_days,
            "representative_production_ton": (
                float(g["production_ton"].iloc[0])
                if g["production_ton"].nunique() == 1
                else np.nan
            ),
            "annual_production_ton": annual_production,
            "annual_total_cost_yuan": annual_cost,
            "weighted_avg_ton_cost_yuan_per_ton": weighted_ton_cost,
        }

        optional_mean_cols = [
            "grid_purchase_mwh",
            "grid_export_mwh",
            "renewable_self_use_pct",
            "green_power_pct",
            "renewable_export_pct",
            "on_hours",
            "mean_running_power_ratio",
        ]
        for col in optional_mean_cols:
            if col in g.columns:
                row[f"mean_{col}"] = float(pd.to_numeric(g[col], errors="coerce").mean())

        rows.append(row)

    out = pd.DataFrame(rows)

    order = {"全满足": 0, "部分满足": 1, "全不满足": 2}
    out["_order"] = out["satisfaction_type"].map(order).fillna(9)
    out = out.sort_values("_order").drop(columns="_order").reset_index(drop=True)

    total = {
        "satisfaction_type": "合计",
        "scenario_count": int(out["scenario_count"].sum()),
        "annual_days": int(out["annual_days"].sum()),
        "representative_production_ton": np.nan,
        "annual_production_ton": float(out["annual_production_ton"].sum()),
        "annual_total_cost_yuan": float(out["annual_total_cost_yuan"].sum())
        if out["annual_total_cost_yuan"].notna().any()
        else np.nan,
    }
    if total["annual_production_ton"] > 0 and not np.isnan(total["annual_total_cost_yuan"]):
        total["weighted_avg_ton_cost_yuan_per_ton"] = (
            total["annual_total_cost_yuan"] / total["annual_production_ton"]
        )
    else:
        total["weighted_avg_ton_cost_yuan_per_ton"] = np.nan

    for col in out.columns:
        if col.startswith("mean_") and col not in total:
            # 按场景数平均，作为年化代表均值
            total[col] = float(out[col].dropna().mean()) if out[col].notna().any() else np.nan

    out = pd.concat([out, pd.DataFrame([total])], ignore_index=True)

    out.to_csv(
        TABLE_DIR / "q3_paper_min_cost_annual_classification.csv",
        index=False,
        encoding="utf-8-sig",
    )

    return out


def build_production_classification_annual() -> pd.DataFrame:
    """
    对每个日产量，按全满足/部分满足/全不满足分类统计年化结果。
    这个表适合正文或者附录解释“不同日产量的满足类型差异”。
    """
    candidate_path = TABLE_DIR / "q3_paper_all_candidates_summary.csv"
    raw_path = TABLE_DIR / "q3_all_scenarios_summary.csv"

    if candidate_path.exists():
        df = pd.read_csv(candidate_path)
    else:
        require_file(raw_path, "python scripts/run_q3_continuous.py")
        df = pd.read_csv(raw_path)

    df = normalize_scenario_columns(df)
    df = add_pct_columns(df)

    rows = []
    for (prod, sat_type), g in df.groupby(["production_ton", "satisfaction_type"], sort=False):
        scenario_count = len(g)
        annual_days = scenario_count * SCENARIO_DAYS
        annual_production = float(prod * annual_days)

        if "total_cost_yuan" in g.columns:
            annual_cost = float((g["total_cost_yuan"] * SCENARIO_DAYS).sum())
            weighted_ton_cost = annual_cost / annual_production if annual_production > 0 else np.nan
        else:
            annual_cost = np.nan
            weighted_ton_cost = float(g["ton_cost_yuan_per_ton"].mean())

        row = {
            "production_ton": prod,
            "satisfaction_type": sat_type,
            "scenario_count": scenario_count,
            "annual_days": annual_days,
            "annual_production_ton": annual_production,
            "annual_total_cost_yuan": annual_cost,
            "weighted_avg_ton_cost_yuan_per_ton": weighted_ton_cost,
        }

        for col in [
            "grid_purchase_mwh",
            "grid_export_mwh",
            "renewable_self_use_pct",
            "green_power_pct",
            "renewable_export_pct",
            "on_hours",
            "mean_running_power_ratio",
        ]:
            if col in g.columns:
                row[f"mean_{col}"] = float(pd.to_numeric(g[col], errors="coerce").mean())

        rows.append(row)

    out = pd.DataFrame(rows)
    order = {"全满足": 0, "部分满足": 1, "全不满足": 2}
    out["_order"] = out["satisfaction_type"].map(order).fillna(9)
    out = out.sort_values(["production_ton", "_order"], ascending=[False, True])
    out = out.drop(columns="_order").reset_index(drop=True)

    out.to_csv(
        TABLE_DIR / "q3_paper_production_classification_annual.csv",
        index=False,
        encoding="utf-8-sig",
    )

    return out



def plot_min_cost_heatmap_v2(cost_optimal: pd.DataFrame) -> None:
    setup_chinese_font()

    df = normalize_scenario_columns(cost_optimal)

    cost_mat = (
        df.pivot(index="wind_idx", columns="pv_idx", values="ton_cost_yuan_per_ton")
        .sort_index()
        .sort_index(axis=1)
    )
    prod_mat = (
        df.pivot(index="wind_idx", columns="pv_idx", values="production_ton")
        .reindex(index=cost_mat.index, columns=cost_mat.columns)
    )
    sat_mat = (
        df.pivot(index="wind_idx", columns="pv_idx", values="satisfaction_type")
        .reindex(index=cost_mat.index, columns=cost_mat.columns)
    )

    fig, ax = plt.subplots(figsize=(10.2, 7.5))

    im = ax.imshow(cost_mat.values, aspect="auto")
    cbar = fig.colorbar(im, ax=ax, shrink=0.88)
    cbar.set_label("最小吨氨成本 / 元·t$^{-1}$")

    ax.set_xticks(np.arange(len(cost_mat.columns)))
    ax.set_xticklabels([f"PV{int(c)}" for c in cost_mat.columns], fontsize=11)
    ax.set_yticks(np.arange(len(cost_mat.index)))
    ax.set_yticklabels([f"W{int(i)}" for i in cost_mat.index], fontsize=11)

    ax.set_xlabel("光伏场景", fontsize=12)
    ax.set_ylabel("风电场景", fontsize=12)
    ax.set_title("问题三：24 种风光场景下最小吨氨成本方案热力图", fontsize=15, pad=12)

    for i in range(cost_mat.shape[0]):
        for j in range(cost_mat.shape[1]):
            cost = float(cost_mat.iloc[i, j])
            prod = float(prod_mat.iloc[i, j])
            sat = sat_mat.iloc[i, j]

            # 根据背景亮度自动选择文字颜色，避免黄色背景配白字看不清
            rgba = im.cmap(im.norm(cost))
            r, g, b = rgba[:3]
            luminance = 0.299 * r + 0.587 * g + 0.114 * b
            text_color = "black" if luminance > 0.52 else "white"
            box_color = "white" if text_color == "black" else "black"

            label = f"{cost:.0f} 元/t\n{prod:.0f} t/day\n{sat}"

            ax.text(
                j,
                i,
                label,
                ha="center",
                va="center",
                fontsize=9.5,
                color=text_color,
                linespacing=1.22,
                bbox=dict(
                    boxstyle="round,pad=0.20",
                    facecolor=box_color,
                    edgecolor="none",
                    alpha=0.16,
                ),
            )

    note = "注：颜色表示该场景下的最小吨氨成本；格内依次为最小吨氨成本、对应日产量、绿电直连指标满足类型。"
    fig.text(
        0.5,
        0.025,
        note,
        ha="center",
        va="bottom",
        fontsize=10.5,
    )

    plt.tight_layout(rect=[0, 0.06, 1, 1])
    plt.savefig(FIGURE_DIR / "q3_paper_scenario_min_cost_heatmap.png", bbox_inches="tight")
    plt.close(fig)


def read_q2_q3_annual() -> tuple[pd.DataFrame, pd.DataFrame]:
    q2_path = TABLE_DIR / "q2_annual_summary.csv"
    q3_path = TABLE_DIR / "q3_annual_summary.csv"

    require_file(q2_path, "python scripts/run_q2_discrete.py")
    require_file(q3_path, "python scripts/run_q3_continuous.py")

    q2 = add_pct_columns(pd.read_csv(q2_path))
    q3 = add_pct_columns(pd.read_csv(q3_path))

    return q2, q3



def ensure_metric_columns(df: pd.DataFrame, label: str) -> None:
    required = [
        "production_ton",
        "annual_avg_ton_cost_yuan_per_ton",
        "mean_grid_purchase_mwh",
        "mean_grid_export_mwh",
        "mean_renewable_self_use_pct",
        "mean_green_power_pct",
        "mean_renewable_export_pct",
    ]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise RuntimeError(f"{label} 缺少字段 {missing}\n现有字段：{list(df.columns)}")



def build_q2_q3_metric_delta_table(q2: pd.DataFrame, q3: pd.DataFrame) -> pd.DataFrame:
    ensure_metric_columns(q2, "Q2 annual summary")
    ensure_metric_columns(q3, "Q3 annual summary")

    keep_cols = [
        "production_ton",
        "annual_avg_ton_cost_yuan_per_ton",
        "mean_grid_purchase_mwh",
        "mean_grid_export_mwh",
        "mean_renewable_self_use_pct",
        "mean_green_power_pct",
        "mean_renewable_export_pct",
    ]

    q2s = q2[keep_cols].copy()
    q3s = q3[keep_cols].copy()

    q2s = q2s.rename(columns={c: f"q2_{c}" for c in keep_cols if c != "production_ton"})
    q3s = q3s.rename(columns={c: f"q3_{c}" for c in keep_cols if c != "production_ton"})

    merged = pd.merge(q2s, q3s, on="production_ton", how="inner")
    merged = merged.sort_values("production_ton", ascending=True).reset_index(drop=True)

    metric_cols = [c for c in keep_cols if c != "production_ton"]
    for c in metric_cols:
        merged[f"delta_{c}"] = merged[f"q3_{c}"] - merged[f"q2_{c}"]

    merged.to_csv(
        TABLE_DIR / "q3_vs_q2_multi_metric_delta.csv",
        index=False,
        encoding="utf-8-sig",
    )

    return merged



def plot_q2_q3_multi_metric_comparison(q2: pd.DataFrame, q3: pd.DataFrame) -> None:
    setup_chinese_font()

    ensure_metric_columns(q2, "Q2 annual summary")
    ensure_metric_columns(q3, "Q3 annual summary")

    q2 = q2.sort_values("production_ton")
    q3 = q3.sort_values("production_ton")

    prods = q2["production_ton"].astype(int).to_numpy()
    x = np.arange(len(prods))
    width = 0.34

    metrics = [
        ("annual_avg_ton_cost_yuan_per_ton", "年均吨氨成本", "元·t$^{-1}$", None),
        ("mean_grid_purchase_mwh", "平均日购电量", "MWh", None),
        ("mean_grid_export_mwh", "平均日上网电量", "MWh", None),
        ("mean_renewable_self_use_pct", "新能源自发自用率", "%", 60),
        ("mean_green_power_pct", "总用电量绿电比例", "%", 30),
        ("mean_renewable_export_pct", "新能源上网比例", "%", 20),
    ]

    fig, axes = plt.subplots(2, 3, figsize=(16.8, 9.6))
    axes = axes.flatten()

    legend_handles = None
    legend_labels = None

    for idx, (col, title, ylabel, threshold) in enumerate(metrics):
        ax = axes[idx]

        b1 = ax.bar(x - width / 2, q2[col].to_numpy(), width, label="Q2 离散启停")
        b2 = ax.bar(x + width / 2, q3[col].to_numpy(), width, label="Q3 连续调节")

        if legend_handles is None:
            legend_handles, legend_labels = ax.get_legend_handles_labels()

        ax.set_title(title, fontsize=12, pad=8)
        ax.set_xticks(x)
        ax.set_xticklabels([str(p) for p in prods])
        ax.set_xlabel("日产量 / t·day$^{-1}$", fontsize=10)
        ax.set_ylabel(ylabel, fontsize=10)
        ax.grid(axis="y", alpha=0.25)
        ax.tick_params(axis="both", labelsize=9)

        if threshold is not None:
            ax.axhline(threshold, linestyle="--", linewidth=1.4)
            ax.text(
                0.98,
                0.06,
                f"阈值 {threshold}%",
                transform=ax.transAxes,
                ha="right",
                va="bottom",
                fontsize=9,
                bbox=dict(boxstyle="round,pad=0.15", facecolor="white", edgecolor="none", alpha=0.70),
            )

    fig.suptitle("问题三：连续调节相对离散启停的多指标变化", fontsize=17, fontweight="bold", y=0.975)

    if legend_handles is not None:
        fig.legend(
            legend_handles,
            legend_labels,
            loc="upper center",
            bbox_to_anchor=(0.5, 0.935),
            ncol=2,
            frameon=True,
            framealpha=0.95,
        )

    fig.text(
        0.5,
        0.022,
        "注：Q3 连续调节通过更细粒度匹配风光波动，改变吨氨成本、购电量、上网量及绿电直连指标。",
        ha="center",
        va="center",
        fontsize=11,
    )

    plt.tight_layout(rect=[0, 0.055, 1, 0.90])
    plt.savefig(FIGURE_DIR / "q3_vs_q2_multi_metric_comparison.png", bbox_inches="tight")
    plt.close(fig)


def update_report_assets() -> None:
    asset_dir = REPORT_ASSET_DIR
    main_fig_dir = asset_dir / "main_figures"
    appendix_fig_dir = asset_dir / "appendix_figures"
    main_table_dir = asset_dir / "main_tables"
    appendix_table_dir = asset_dir / "appendix_tables"

    for d in [main_fig_dir, appendix_fig_dir, main_table_dir, appendix_table_dir]:
        d.mkdir(parents=True, exist_ok=True)

    assets = [
        {
            "type": "figure",
            "placement": "main",
            "src": FIGURE_DIR / "q3_paper_scenario_min_cost_heatmap.png",
            "dst": main_fig_dir / "q3_paper_scenario_min_cost_heatmap.png",
            "title": "Q3 24 场景最小吨氨成本方案热力图",
            "note": "正文主图，格内展示最小吨氨成本、对应日产量和绿电直连指标满足类型。",
        },
        {
            "type": "figure",
            "placement": "main",
            "src": FIGURE_DIR / "q3_vs_q2_multi_metric_comparison.png",
            "dst": main_fig_dir / "q3_vs_q2_multi_metric_comparison.png",
            "title": "Q3 相对 Q2 的多指标变化图",
            "note": "正文主图，用于回答第三小问中吨氨成本、购电、上网、绿电比例、上网比例等指标变化。",
        },
        {
            "type": "table",
            "placement": "main",
            "src": TABLE_DIR / "q3_paper_min_cost_annual_classification.csv",
            "dst": main_table_dir / "q3_paper_min_cost_annual_classification.csv",
            "title": "Q3 最小成本方案年化分类汇总表",
            "note": "正文主表，按全满足、部分满足、全不满足统计场景数、全年天数、年化产量和吨氨成本。",
        },
        {
            "type": "table",
            "placement": "main",
            "src": TABLE_DIR / "q3_vs_q2_multi_metric_delta.csv",
            "dst": main_table_dir / "q3_vs_q2_multi_metric_delta.csv",
            "title": "Q3 相对 Q2 的多指标变化表",
            "note": "正文或附录表，量化连续调节相对离散启停的成本、购电、上网和绿电指标变化。",
        },
        {
            "type": "table",
            "placement": "appendix",
            "src": TABLE_DIR / "q3_paper_production_classification_annual.csv",
            "dst": appendix_table_dir / "q3_paper_production_classification_annual.csv",
            "title": "Q3 不同日产量下满足类型年化分类表",
            "note": "附录表，用于补充说明不同日产量的全满足、部分满足、全不满足结构。",
        },
    ]

    for a in assets:
        if a["src"].exists():
            shutil.copy2(a["src"], a["dst"])

    manifest_path = asset_dir / "asset_manifest.csv"
    rows = []
    if manifest_path.exists():
        with manifest_path.open("r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))

    fieldnames = ["id", "type", "placement", "source_filename", "organized_path", "title", "note", "status"]

    def prefix(asset_type: str, placement: str) -> str:
        if asset_type == "figure" and placement == "main":
            return "F"
        if asset_type == "figure" and placement == "appendix":
            return "AF"
        if asset_type == "table" and placement == "main":
            return "T"
        if asset_type == "table" and placement == "appendix":
            return "AT"
        return "X"

    def next_id(pref: str) -> str:
        nums = []
        pat = re.compile(rf"^{re.escape(pref)}(\d+)$")
        for r in rows:
            m = pat.match(str(r.get("id", "")))
            if m:
                nums.append(int(m.group(1)))
        return f"{pref}{max(nums, default=0) + 1}"

    def upsert(a: dict) -> None:
        nonlocal rows
        source_filename = a["dst"].name
        existing = next((r for r in rows if r.get("source_filename") == source_filename), None)
        asset_id = existing["id"] if existing else next_id(prefix(a["type"], a["placement"]))

        rows = [r for r in rows if r.get("source_filename") != source_filename]
        rows.append({
            "id": asset_id,
            "type": a["type"],
            "placement": a["placement"],
            "source_filename": source_filename,
            "organized_path": str(a["dst"]).replace("\\", "/"),
            "title": a["title"],
            "note": a["note"],
            "status": "OK" if a["dst"].exists() else "MISSING",
        })

    for a in assets:
        upsert(a)

    placement_order = {"main": 0, "appendix": 1}
    type_order = {"figure": 0, "table": 1}

    def id_num(r):
        m = re.search(r"(\d+)$", str(r.get("id", "")))
        return int(m.group(1)) if m else 9999

    rows = sorted(
        rows,
        key=lambda r: (
            placement_order.get(r.get("placement"), 9),
            type_order.get(r.get("type"), 9),
            str(r.get("id", ""))[:2],
            id_num(r),
        ),
    )

    with manifest_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    md_path = asset_dir / "asset_manifest.md"
    lines = ["# Report Assets Manifest\n"]
    for placement in ["main", "appendix"]:
        lines.append(f"\n## {placement.capitalize()} Assets\n")
        for r in rows:
            if r["placement"] == placement:
                lines.append(
                    f"- **{r['id']}** `{r['organized_path']}`：{r['title']}。{r['note']} 状态：{r['status']}"
                )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    TABLE_DIR.mkdir(parents=True, exist_ok=True)
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)

    cost_optimal = build_cost_optimal_summary()
    annual_classification = build_min_cost_annual_classification(cost_optimal)
    production_classification = build_production_classification_annual()

    plot_min_cost_heatmap_v2(cost_optimal)

    q2, q3 = read_q2_q3_annual()
    delta = build_q2_q3_metric_delta_table(q2, q3)
    plot_q2_q3_multi_metric_comparison(q2, q3)

    update_report_assets()

    print("=" * 88)
    print("Q3 final paper assets generated.")
    print("=" * 88)
    print("[Q3 min-cost annual classification]")
    print(annual_classification.to_string(index=False))
    print("-" * 88)
    print("[Q3 production classification annual: first 20 rows]")
    print(production_classification.head(20).to_string(index=False))
    print("-" * 88)
    print("[Q3 vs Q2 metric delta]")
    print(delta.to_string(index=False))
    print("=" * 88)
    print(f"Tables saved to: {TABLE_DIR}")
    print(f"Figures saved to: {FIGURE_DIR}")
    print(f"Report assets updated at: {REPORT_ASSET_DIR}")
    print("=" * 88)


if __name__ == "__main__":
    main()
