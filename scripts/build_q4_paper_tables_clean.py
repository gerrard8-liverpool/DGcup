from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
import csv
import re
import shutil

import numpy as np
import pandas as pd

from dgcup.optimization.q4_storage_dispatch import (
    OffgridStorageParams,
    run_offgrid_storage_for_scenarios,
    summarize_offgrid_annual,
    run_grid_connected_same_production_comparison,
)

ROOT = PROJECT_ROOT
TABLE_DIR = ROOT / "outputs" / "tables"
REPORT_DIR = ROOT / "outputs" / "report_assets"
MAIN_TABLE_DIR = REPORT_DIR / "main_tables"
APPENDIX_TABLE_DIR = REPORT_DIR / "appendix_tables"

for d in [TABLE_DIR, MAIN_TABLE_DIR, APPENDIX_TABLE_DIR]:
    d.mkdir(parents=True, exist_ok=True)


def first_existing(names: list[str]) -> Path:
    for name in names:
        for base in [TABLE_DIR, MAIN_TABLE_DIR, APPENDIX_TABLE_DIR]:
            path = base / name
            if path.exists():
                return path
    raise FileNotFoundError("Missing required file: " + ", ".join(names))


def extract_num(x: object) -> int:
    m = re.search(r"\d+", str(x))
    return int(m.group()) if m else 999


def get_recommended_capacity() -> float:
    path = first_existing(["q4_storage_capacity_tiers.csv"])
    df = pd.read_csv(path)

    if {"tier", "capacity_mwh"}.issubset(df.columns):
        hit = df[df["tier"].astype(str).str.contains("balanced", case=False, na=False)]
        if not hit.empty:
            return float(hit.iloc[0]["capacity_mwh"])

    return 115.0


def build_profiles_from_q3_hourly() -> list[dict]:
    path = first_existing(["q3_all_scenarios_hourly_dispatch.csv"])
    df = pd.read_csv(path)

    required = [
        "scenario_id",
        "wind_scenario",
        "pv_scenario",
        "hour",
        "base_load_mw",
        "wind_power_mw",
        "pv_power_mw",
        "renewable_power_mw",
    ]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise RuntimeError(f"{path} missing columns: {missing}")

    if "production_ton" in df.columns:
        max_prod = pd.to_numeric(df["production_ton"], errors="coerce").max()
        df = df[pd.to_numeric(df["production_ton"], errors="coerce") == max_prod].copy()

    profiles = []
    keep = required.copy()
    if "time" in df.columns:
        keep.insert(4, "time")

    for sid, g in df.groupby("scenario_id", sort=False):
        g = g.sort_values("hour").copy()
        if len(g) != 24:
            raise RuntimeError(f"Scenario {sid} has {len(g)} rows, expected 24.")

        profiles.append(
            {
                "scenario_id": sid,
                "wind_scenario": str(g["wind_scenario"].iloc[0]),
                "pv_scenario": str(g["pv_scenario"].iloc[0]),
                "profile": g[keep].copy(),
            }
        )

    profiles = sorted(
        profiles,
        key=lambda s: (extract_num(s["wind_scenario"]), extract_num(s["pv_scenario"])),
    )

    if len(profiles) != 24:
        raise RuntimeError(f"Expected 24 scenarios, got {len(profiles)}.")

    return profiles


def add_wind_pv_util(summary_df: pd.DataFrame, hourly_df: pd.DataFrame) -> pd.DataFrame:
    rows = []

    for sid, h in hourly_df.groupby("scenario_id", sort=False):
        h = h.copy()

        wind_gen = pd.to_numeric(h["wind_power_mw"], errors="coerce").sum()
        pv_gen = pd.to_numeric(h["pv_power_mw"], errors="coerce").sum()
        total_re = pd.to_numeric(h["renewable_power_mw"], errors="coerce").replace(0, np.nan)

        curtail = pd.to_numeric(h["curtailment_mw"], errors="coerce")
        wind_share = pd.to_numeric(h["wind_power_mw"], errors="coerce") / total_re
        pv_share = pd.to_numeric(h["pv_power_mw"], errors="coerce") / total_re

        wind_curtail = (curtail * wind_share.fillna(0.0)).sum()
        pv_curtail = (curtail * pv_share.fillna(0.0)).sum()

        rows.append(
            {
                "scenario_id": sid,
                "wind_generation_mwh": wind_gen,
                "pv_generation_mwh": pv_gen,
                "wind_curtailment_mwh_allocated": wind_curtail,
                "pv_curtailment_mwh_allocated": pv_curtail,
                "wind_util_pct": (wind_gen - wind_curtail) / wind_gen * 100.0 if wind_gen > 1e-8 else np.nan,
                "pv_util_pct": (pv_gen - pv_curtail) / pv_gen * 100.0 if pv_gen > 1e-8 else np.nan,
            }
        )

    return summary_df.merge(pd.DataFrame(rows), on="scenario_id", how="left")


def build_q4_24_scenario_table(storage_summary: pd.DataFrame, storage_hourly: pd.DataFrame) -> pd.DataFrame:
    s = add_wind_pv_util(storage_summary.copy(), storage_hourly)

    out = pd.DataFrame(
        {
            "scene": s["scenario_id"],
            "wind_scenario": s["wind_scenario"],
            "pv_scenario": s["pv_scenario"],
            "storage_capacity_mwh": s["storage_capacity_mwh"],
            "production_ton": s["total_ammonia_output_ton"],
            "ton_cost_yuan_per_ton": s["ton_cost_yuan_per_ton"],
            "curtailment_mwh": s["curtailment_mwh"],
            "unserved_load_mwh": s["unserved_load_mwh"],
            "renewable_util_pct": s["renewable_utilization_ratio"] * 100.0,
            "energy_self_sufficiency_pct": s["energy_self_sufficiency_ratio"] * 100.0,
            "capacity_utilization_pct": s["capacity_utilization_rate"] * 100.0,
            "wind_util_pct": s["wind_util_pct"],
            "pv_util_pct": s["pv_util_pct"],
            "wind_generation_mwh": s["wind_generation_mwh"],
            "pv_generation_mwh": s["pv_generation_mwh"],
            "wind_curtailment_mwh_allocated": s["wind_curtailment_mwh_allocated"],
            "pv_curtailment_mwh_allocated": s["pv_curtailment_mwh_allocated"],
            "satisfaction_type": s["satisfaction_type"],
        }
    )

    out["_w"] = out["wind_scenario"].map(extract_num)
    out["_p"] = out["pv_scenario"].map(extract_num)
    out = out.sort_values(["_w", "_p"]).drop(columns=["_w", "_p"])

    out_path = TABLE_DIR / "q4_paper_24_scenario_summary.csv"
    out.to_csv(out_path, index=False, encoding="utf-8-sig")
    shutil.copy2(out_path, MAIN_TABLE_DIR / out_path.name)

    return out


def build_grid_vs_offgrid_table(profiles: list[dict], storage_summary: pd.DataFrame) -> pd.DataFrame:
    grid_hourly, grid_summary, comparison = run_grid_connected_same_production_comparison(
        scenario_profiles=profiles,
        offgrid_storage_summary_df=storage_summary,
        scenario_days=15,
    )

    grid_hourly.to_csv(APPENDIX_TABLE_DIR / "q4_grid_same_production_hourly_dispatch.csv", index=False, encoding="utf-8-sig")
    grid_summary.to_csv(APPENDIX_TABLE_DIR / "q4_grid_same_production_scenario_summary.csv", index=False, encoding="utf-8-sig")

    comparison_path = TABLE_DIR / "q4_grid_vs_offgrid_annual_comparison.csv"
    comparison.to_csv(comparison_path, index=False, encoding="utf-8-sig")
    shutil.copy2(comparison_path, APPENDIX_TABLE_DIR / comparison_path.name)

    paper = pd.DataFrame(
        {
            "mode": comparison["mode"],
            "annual_cost_yuan": comparison["annual_total_cost_yuan"],
            "annual_production_ton": comparison["annual_total_production_ton"],
            "ton_cost_yuan_per_ton": comparison["annual_avg_ton_cost_yuan_per_ton"],
            "annual_capacity_utilization_pct": comparison["annual_capacity_utilization_rate"] * 100.0,
            "mean_daily_production_ton": comparison["mean_daily_production_ton"],
            "mean_ton_cost_yuan_per_ton": comparison["mean_ton_cost_yuan_per_ton"],
            "all_satisfied_days": comparison["all_satisfied_days"],
            "partially_satisfied_days": comparison["partially_satisfied_days"],
            "none_satisfied_days": comparison["none_satisfied_days"],
        }
    )

    out_path = TABLE_DIR / "q4_paper_grid_vs_offgrid_comparison.csv"
    paper.to_csv(out_path, index=False, encoding="utf-8-sig")
    shutil.copy2(out_path, MAIN_TABLE_DIR / out_path.name)

    return paper


def update_manifest() -> None:
    manifest = REPORT_DIR / "asset_manifest.csv"
    rows = []

    if manifest.exists():
        with manifest.open("r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))

    fieldnames = ["id", "type", "placement", "source_filename", "organized_path", "title", "note", "status"]

    items = [
        {
            "source_filename": "q4_paper_24_scenario_summary.csv",
            "organized_path": "outputs/report_assets/main_tables/q4_paper_24_scenario_summary.csv",
            "title": "Q4 24 场景离网储能逐场景结果表",
            "note": "包含 scene、production、ton_cost、curtailment、wind_util、pv_util。",
        },
        {
            "source_filename": "q4_paper_grid_vs_offgrid_comparison.csv",
            "organized_path": "outputs/report_assets/main_tables/q4_paper_grid_vs_offgrid_comparison.csv",
            "title": "Q4 联网与离网年化经济性对比表",
            "note": "包含 mode、annual_cost、annual_production、ton_cost。",
        },
    ]

    def next_t_id() -> str:
        nums = []
        for r in rows:
            m = re.match(r"^T(\d+)$", str(r.get("id", "")))
            if m:
                nums.append(int(m.group(1)))
        return f"T{max(nums, default=0) + 1}"

    for item in items:
        old = next((r for r in rows if r.get("source_filename") == item["source_filename"]), None)
        asset_id = old["id"] if old else next_t_id()

        rows = [r for r in rows if r.get("source_filename") != item["source_filename"]]
        rows.append(
            {
                "id": asset_id,
                "type": "table",
                "placement": "main",
                "source_filename": item["source_filename"],
                "organized_path": item["organized_path"],
                "title": item["title"],
                "note": item["note"],
                "status": "OK" if Path(item["organized_path"]).exists() else "MISSING",
            }
        )

    rows = sorted(rows, key=lambda r: (r.get("placement") != "main", r.get("type") != "figure", r.get("id", "")))

    with manifest.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    md = REPORT_DIR / "asset_manifest.md"
    lines = ["# Report Assets Manifest\n"]
    for placement in ["main", "appendix"]:
        lines.append(f"\n## {placement.capitalize()} Assets\n")
        for r in rows:
            if r["placement"] == placement:
                lines.append(f"- **{r['id']}** `{r['organized_path']}`：{r['title']}。{r['note']} 状态：{r['status']}")

    md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def update_readme() -> None:
    path = ROOT / "README.md"
    if not path.exists():
        return

    text = path.read_text(encoding="utf-8")

    section = """
### Q4 论文友好型表格补充

为方便论文写作和代码核查，Q4 额外整理两个标准化表格：

| 表格 | 用途 |
|---|---|
| `outputs/report_assets/main_tables/q4_paper_24_scenario_summary.csv` | 24 种风光场景下离网储能逐场景结果，包含场景、制氨量、吨氨成本、弃电量、风电利用率和光伏利用率 |
| `outputs/report_assets/main_tables/q4_paper_grid_vs_offgrid_comparison.csv` | 联网同产量方案与离网储能方案的年化经济性对比，包含运行模式、年化成本、年制氨量和吨氨成本 |

说明：`wind_util_pct` 和 `pv_util_pct` 是按小时风、光出力占比对总弃电量进行分摊后的利用率统计，用于论文展示风光利用改善趋势；严格的调度优化仍以总弃电量、总可再生能源利用率和能源自给率为核心指标。
"""

    text = re.sub(r"(?ms)^### Q4 论文友好型表格补充\n.*?(?=^### |^## |\Z)", "", text)

    marker = "\n## Q4 储能容量选择准则"
    if marker in text:
        text = text.replace(marker, marker + "\n\n" + section.strip(), 1)
    else:
        text = text.rstrip() + "\n\n" + section.strip() + "\n"

    path.write_text(text, encoding="utf-8")


def main() -> None:
    cap = get_recommended_capacity()
    params = OffgridStorageParams()
    profiles = build_profiles_from_q3_hourly()

    print("=" * 88)
    print(f"Q4 recommended storage capacity: {cap} MWh")
    print("=" * 88)

    storage_hourly, storage_summary = run_offgrid_storage_for_scenarios(
        scenario_profiles=profiles,
        storage_capacity_mwh=cap,
        params=params,
    )

    storage_summary.to_csv(APPENDIX_TABLE_DIR / "q4_offgrid_storage_scenario_summary.csv", index=False, encoding="utf-8-sig")
    storage_hourly.to_csv(APPENDIX_TABLE_DIR / "q4_offgrid_storage_hourly_dispatch.csv", index=False, encoding="utf-8-sig")

    storage_annual = summarize_offgrid_annual(storage_summary, scenario_days=15, mode="offgrid_with_storage")
    storage_annual.to_csv(APPENDIX_TABLE_DIR / "q4_offgrid_storage_annual_summary.csv", index=False, encoding="utf-8-sig")

    paper_24 = build_q4_24_scenario_table(storage_summary, storage_hourly)
    paper_grid = build_grid_vs_offgrid_table(profiles, storage_summary)

    update_manifest()
    update_readme()

    print("[OK] q4_paper_24_scenario_summary.csv")
    print(paper_24.head(6).to_string(index=False))
    print("-" * 88)
    print("[OK] q4_paper_grid_vs_offgrid_comparison.csv")
    print(paper_grid.to_string(index=False))
    print("=" * 88)


if __name__ == "__main__":
    main()
