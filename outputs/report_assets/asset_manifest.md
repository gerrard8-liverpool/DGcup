# Report Assets Manifest


## Main Assets

- **F1** `outputs/report_assets/main_figures/q1_power_balance.png`：Q1 典型日功率平衡。展示基准运行下风光出力、负荷与源荷错配。 状态：OK
- **F2** `outputs/report_assets/main_figures/q2_typical_cost_vs_production.png`：Q2 离散调度吨氨成本随日产量变化。展示离散调度下不同日产量的成本变化。 状态：OK
- **F3** `outputs/report_assets/main_figures/q2_inertia_cost_increase_heatmap.png`：Q2 运行惯性增强验证成本增量热力图。检验启动损耗和最小连续运行时间对 Q2 结论的影响。 状态：OK
- **F4** `outputs/report_assets/main_figures/q3_vs_q2_cost_reduction.png`：Q3 连续调节相对 Q2 的降本效果。展示连续调节对离散调度的成本改善。 状态：OK
- **F5** `outputs/report_assets/main_figures/q4_storage_knee_capacity_tradeoff.png`：Q4 储能容量—成本—制氨量细步长扫描。展示储能容量拐点区间与推荐容量。 状态：OK
- **F6** `outputs/report_assets/main_figures/q4_storage_knee_marginal_benefit.png`：Q4 储能容量边际收益递减曲线。证明拐点后边际收益明显下降。 状态：OK
- **F7** `outputs/report_assets/main_figures/q4_grid_vs_offgrid_cost_comparison.png`：Q4 联网与离网同产量成本对比。说明公共电网的低成本系统平衡价值。 状态：OK
- **F8** `outputs/report_assets/main_figures/q4_weight_sensitivity_recommended_capacity.png`：Q4 目标权重敏感性下的推荐容量。检验 115 MWh 工程推荐容量是否依赖单一目标权重。 状态：OK
- **F9** `outputs/report_assets/main_figures/q4_storage_mechanism_framework.svg`：Q4 储能容量配置作用机理与拐点决策框架图。用于解释源荷错配、储能时移调节、边际收益递减以及 20/110–115/150 MWh 分层容量决策逻辑。 状态：OK
- **T1** `outputs/report_assets/main_tables/q1_summary.csv`：Q1 典型日基准结果。用于 Q1 主要结果。 状态：OK
- **T10** `outputs/report_assets/main_tables/sensitivity_summary.csv`：敏感性分析汇总。用于说明参数扰动下结论稳定。 状态：OK
- **T11** `outputs/report_assets/main_tables/robustness_overview.csv`：鲁棒性检验总览。用于说明随机扰动、场景留一和压力测试下结论稳定。 状态：OK
- **T12** `outputs/report_assets/main_tables/q4_weight_sensitivity_summary.csv`：Q4 目标权重敏感性汇总。用于证明 Q4 工程推荐容量对目标权重扰动具有稳定性。 状态：OK
- **T2** `outputs/report_assets/main_tables/q2_typical_summary.csv`：Q2 典型场景结果。用于 Q2 典型场景结果。 状态：OK
- **T3** `outputs/report_assets/main_tables/q2_annual_summary.csv`：Q2 年化结果。用于 Q2 年化评价。 状态：OK
- **T4** `outputs/report_assets/main_tables/q2_inertia_best_by_case.csv`：Q2 运行惯性增强验证最优结果。用于证明 Q2 结论对启动损耗和最小连续运行时间稳定。 状态：OK
- **T5** `outputs/report_assets/main_tables/q3_annual_summary.csv`：Q3 年化结果。用于 Q3 年化评价。 状态：OK
- **T6** `outputs/report_assets/main_tables/q3_vs_q2_comparison.csv`：Q3 相对 Q2 对比。用于说明连续调节收益。 状态：OK
- **T7** `outputs/report_assets/main_tables/q4_storage_capacity_tiers.csv`：Q4 储能容量层级。用于说明拐点容量、推荐容量和饱和容量。 状态：OK
- **T8** `outputs/report_assets/main_tables/q4_storage_knee_summary.csv`：Q4 拐点识别汇总。用于证明储能推荐容量。 状态：OK
- **T9** `outputs/report_assets/main_tables/q4_storage_capacity_fine_scan.csv`：Q4 细步长容量扫描。用于支撑储能容量拐点分析。 状态：OK

## Appendix Assets

- **AF1** `outputs/report_assets/appendix_figures/q1_cost_breakdown.png`：Q1 成本构成。展示典型日成本来源。 状态：OK
- **AF10** `outputs/report_assets/appendix_figures/q2_inertia_best_production.png`：Q2 运行惯性约束下的最优日产量稳定性。展示增强约束下最优日产量保持稳定。 状态：OK
- **AF11** `outputs/report_assets/appendix_figures/q2_inertia_typical_schedule_comparison.png`：Q2 增强验证开机时段对比。展示运行惯性约束对典型日调度形态的影响。 状态：OK
- **AF12** `outputs/report_assets/appendix_figures/q3_annual_avg_cost.png`：Q3 全年平均成本。展示 Q3 年化成本曲线。 状态：OK
- **AF13** `outputs/report_assets/appendix_figures/q3_representative_dispatch_curve.png`：Q3 代表性场景调度曲线。展示连续制氨功率调度细节。 状态：OK
- **AF14** `outputs/report_assets/appendix_figures/q3_satisfaction_stacked_bar.png`：Q3 全年达标分类。展示连续调节后的达标情况。 状态：OK
- **AF15** `outputs/report_assets/appendix_figures/q3_scenario_cost_boxplot.png`：Q3 场景成本分布。展示 Q3 多场景成本分布。 状态：OK
- **AF16** `outputs/report_assets/appendix_figures/q3_vs_q2_grid_interaction.png`：Q3 相对 Q2 电网交互变化。展示连续调节对购电/上网的影响。 状态：OK
- **AF17** `outputs/report_assets/appendix_figures/q4_offgrid_no_storage_curtailment_unserved.png`：Q4 无储能离网弃电与缺供。展示无储能离网运行的弃电情况。 状态：OK
- **AF18** `outputs/report_assets/appendix_figures/q4_offgrid_no_storage_production_bar.png`：Q4 无储能离网 24 场景制氨量。展示无储能条件下各场景制氨能力。 状态：OK
- **AF19** `outputs/report_assets/appendix_figures/q4_storage_dispatch_curve.png`：Q4 储能调度曲线。展示代表性场景下 SOC、充放电与负荷。 状态：OK
- **AF2** `outputs/report_assets/appendix_figures/q1_green_indicators.png`：Q1 绿电指标。展示三项绿电直连指标达标情况。 状态：OK
- **AF20** `outputs/report_assets/appendix_figures/q4_storage_knee_normalized_benefit.png`：Q4 储能收益—成本标准化对比。展示收益与成本的标准化关系。 状态：OK
- **AF21** `outputs/report_assets/appendix_figures/q4_storage_production_bar.png`：Q4 有储能 24 场景制氨量。展示储能对各场景制氨量的提升。 状态：OK
- **AF22** `outputs/report_assets/appendix_figures/q4_wind_pv_utilization_improvement.png`：Q4 储能前后风光利用率对比。展示储能对风光消纳的改善。 状态：OK
- **AF3** `outputs/report_assets/appendix_figures/q1_grid_interaction.png`：Q1 电网交互。展示小时级购电与余电上网。 状态：OK
- **AF4** `outputs/report_assets/appendix_figures/q2_annual_avg_cost.png`：Q2 全年平均成本。展示 Q2 年化成本曲线。 状态：OK
- **AF5** `outputs/report_assets/appendix_figures/q2_satisfaction_stacked_bar.png`：Q2 全年达标分类。展示不同日产量下指标达标情况。 状态：OK
- **AF6** `outputs/report_assets/appendix_figures/q2_scenario_cost_boxplot.png`：Q2 场景成本分布。展示 24 场景下成本分布。 状态：OK
- **AF7** `outputs/report_assets/appendix_figures/q2_typical_green_indicators.png`：Q2 典型场景绿电指标。展示典型场景绿电指标变化。 状态：OK
- **AF8** `outputs/report_assets/appendix_figures/q2_typical_schedule_gantt.png`：Q2 典型场景开机时段。展示离散调度时段选择。 状态：OK
- **AF9** `outputs/report_assets/appendix_figures/q2_inertia_best_cost.png`：Q2 运行惯性约束下的最优成本。展示启动损耗与最小连续运行时间对成本的影响。 状态：OK
- **AT1** `outputs/report_assets/appendix_tables/q2_inertia_typical_summary.csv`：Q2 增强验证典型日汇总。Q2 运行惯性增强验证典型日结果。 状态：OK
- **AT2** `outputs/report_assets/appendix_tables/q2_inertia_annual_summary.csv`：Q2 增强验证年化汇总。Q2 启动损耗和最小连续运行时间组合下的年化结果。 状态：OK
- **AT3** `outputs/report_assets/appendix_tables/q2_inertia_vs_baseline.csv`：Q2 增强验证相对基准对比。Q2 增强模型相对原模型的成本增量。 状态：OK
- **AT4** `outputs/report_assets/appendix_tables/robustness_case_summary.csv`：鲁棒性检验逐案例结果。随机扰动、场景留一、压力测试逐案例结果。 状态：OK
- **AT5** `outputs/report_assets/appendix_tables/q4_weight_sensitivity_knee_detail.csv`：Q4 目标权重敏感性拐点明细。记录不同权重扰动下各类拐点识别方法的结果。 状态：OK
- **AT6** `outputs/report_assets/appendix_tables/q4_weight_sensitivity_tier_detail.csv`：Q4 目标权重敏感性容量层级明细。记录不同权重扰动下经济入口、工程推荐和技术饱和容量。 状态：OK
