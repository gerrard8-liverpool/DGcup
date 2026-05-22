# DGcup A Problem - Green Power Direct-Connection Hydrogen-Ammonia Park Optimization

本仓库用于 2026 中国大学生电工杯 A 题：**绿电直连型电氢氨园区优化运行**。

本项目不把 A 题拆成孤立的小计算，而是构建一个统一的电-氢-氨综合能源系统优化框架，围绕风电、光伏、常规负荷、电解制氢、合成氨、购售电、储能配置和绿电直连政策指标进行联合建模与调度优化。

---

## 1. Problem Understanding

A 题的核心不是普通预测问题，而是一个典型的 **multi-scenario energy system dispatch optimization problem**。

园区包含：

- 风电系统
- 光伏系统
- 常规电负荷
- 碱性电解槽 ALKEL
- 质子交换膜电解槽 PEMEL
- 合成氨装置
- 外部电网购售电接口
- 储能系统

题目要求分析并优化以下目标：

1. 降低吨氨成本；
2. 提高新能源自发自用比例；
3. 提高总用电量绿电比例；
4. 控制新能源上网比例；
5. 比较联网运行、离网运行和储能支撑运行的经济性；
6. 在 24 种风光出力场景下进行年化统计分析。

---

## 2. Core Modeling Idea

本项目采用统一的功率平衡模型：

```text
renewable generation + grid purchase + storage discharge
=
base load + hydrogen-ammonia load + storage charge + grid export + curtailment