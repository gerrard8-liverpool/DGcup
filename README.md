# 电工杯 A 题：绿电直连型电氢氨园区优化运行

本仓库用于中国大学生电工杯 A 题“绿电直连型电氢氨园区优化运行”的建模、计算、优化与可视化分析。

本项目的核心思路不是把五个问题割裂成独立小题，而是构建一个统一的“电—氢—氨”综合能源系统优化框架。以小时级功率平衡为基础，以绿电直连政策指标和吨氨成本为评价核心，逐步完成典型日核算、离散制氨调度、连续制氨调度、多场景年化统计、离网运行和储能配置优化。

---

## 1. 项目目标

A 题本质上是一个绿电直连园区的多场景优化运行问题，涉及风电、光伏、常规电负荷、电解制氢、合成氨、购售电和储能系统之间的协同调度。

本项目主要解决以下问题：

1. 计算典型日园区的负荷、风光出力、购电、上网和绿电直连指标；
2. 分析连续满负荷运行方式下绿电指标不达标的原因；
3. 建立制氨离散开停机调度模型；
4. 建立制氨连续可调功率优化模型；
5. 在 24 种风光出力场景下进行年化统计；
6. 分析离网运行下的制氨能力和储能配置价值；
7. 比较联网、离网和储能参与运行的经济性。

---

## 2. 项目结构

~~~text
DGcup/
├─ configs/
│  └─ config.yaml
│
├─ data/
│  ├─ raw/                 # 原始附件数据，本地保存，不上传 GitHub
│  ├─ processed/           # 清洗后的中间数据
│  └─ external/
│
├─ outputs/
│  ├─ figures/             # 程序生成的图像
│  ├─ tables/              # 程序生成的表格
│  └─ logs/
│
├─ reports/
│  ├─ figures/             # 最终论文使用图像
│  └─ tables/              # 最终论文使用表格
│
├─ scripts/
│  ├─ run_q1_baseline.py
│  ├─ run_q2_discrete.py
│  ├─ run_q3_continuous.py
│  ├─ run_q4_storage.py
│  └─ legacy/
│
├─ src/
│  └─ dgcup/
│     ├─ data/
│     │  ├─ load_excel.py
│     │  └─ build_scenarios.py
│     │
│     ├─ core/
│     │  ├─ power_balance.py
│     │  ├─ indicators.py
│     │  └─ cost.py
│     │
│     ├─ optimization/
│     │  ├─ q2_discrete_dispatch.py
│     │  ├─ q3_continuous_dispatch.py
│     │  └─ q4_storage_dispatch.py
│     │
│     ├─ analysis/
│     │  ├─ yearly_statistics.py
│     │  └─ sensitivity.py
│     │
│     ├─ visualization/
│     │  └─ plots.py
│     │
│     └─ utils/
│
├─ notebooks/
├─ tests/
├─ requirements.txt
├─ .gitignore
└─ README.md
~~~

---

## 3. 数据放置方式

官方 Excel 附件统一放在：

~~~text
data/raw/
~~~

需要包含以下文件：

~~~text
附件1：园区典型日常规电负荷标幺功率曲线.xlsx
附件2：典型日风电、光伏标幺功率表.xlsx
附件3：园区6种场景的风电标幺功率表.xlsx
附件4：园区4种场景的光伏标幺功率表.xlsx
附件5：风光发电与制氢设备技术参数.xlsx
附件6：储能设备和合成氨装置技术参数.xlsx
附件7：分时电价表.xlsx
附件8：风电、光伏余电上网电价.xlsx
~~~

由于仓库是公开仓库，`data/raw/` 已经写入 `.gitignore`，官方附件只保留在本地，不上传 GitHub。

---

## 4. 总体建模思路

园区运行的核心是小时级功率平衡。风电和光伏优先满足园区常规负荷和制氢氨负荷。当新能源不足时，从外部电网购电；当新能源富余时，余电上网。

在一般形式下，园区功率平衡可以写为：

$$
P_{\mathrm{RE}}(t)+P_{\mathrm{buy}}(t)+P_{\mathrm{dis}}(t)
=
P_{\mathrm{base}}(t)+P_{\mathrm{NH3}}(t)+P_{\mathrm{ch}}(t)+P_{\mathrm{sell}}(t)+P_{\mathrm{curt}}(t)
$$

其中，问题一不考虑储能和弃电，因此退化为：

$$
P_{\mathrm{RE}}(t)+P_{\mathrm{buy}}(t)
=
P_{\mathrm{load}}(t)+P_{\mathrm{sell}}(t)
$$

总负荷为：

$$
P_{\mathrm{load}}(t)=P_{\mathrm{base}}(t)+P_{\mathrm{NH3}}(t)
$$

新能源出力为：

$$
P_{\mathrm{RE}}(t)=P_{\mathrm{wind}}(t)+P_{\mathrm{pv}}(t)
$$

购电功率和上网功率分别为：

$$
P_{\mathrm{buy}}(t)=\max\left(P_{\mathrm{load}}(t)-P_{\mathrm{RE}}(t),0\right)
$$

$$
P_{\mathrm{sell}}(t)=\max\left(P_{\mathrm{RE}}(t)-P_{\mathrm{load}}(t),0\right)
$$

由于题目给定时间分辨率为 1 小时，日电量由小时功率直接求和得到：

$$
E=\sum_{t=1}^{24}P(t)\Delta t,\quad \Delta t=1\ \mathrm{h}
$$

---

## 5. 符号定义

| 符号 | 含义 | 单位 |
|---|---|---|
| $t$ | 小时时段编号，$t=1,2,\cdots,24$ | h |
| $P_{\mathrm{base}}(t)$ | 第 $t$ 小时园区常规电负荷 | MW |
| $P_{\mathrm{NH3}}(t)$ | 第 $t$ 小时制氢氨系统电负荷 | MW |
| $P_{\mathrm{load}}(t)$ | 第 $t$ 小时园区总用电负荷 | MW |
| $P_{\mathrm{wind}}(t)$ | 第 $t$ 小时风电出力 | MW |
| $P_{\mathrm{pv}}(t)$ | 第 $t$ 小时光伏出力 | MW |
| $P_{\mathrm{RE}}(t)$ | 第 $t$ 小时新能源总出力 | MW |
| $P_{\mathrm{buy}}(t)$ | 第 $t$ 小时从电网购电功率 | MW |
| $P_{\mathrm{sell}}(t)$ | 第 $t$ 小时余电上网功率 | MW |
| $P_{\mathrm{ch}}(t)$ | 第 $t$ 小时储能充电功率 | MW |
| $P_{\mathrm{dis}}(t)$ | 第 $t$ 小时储能放电功率 | MW |
| $P_{\mathrm{curt}}(t)$ | 第 $t$ 小时弃电功率 | MW |
| $E_{\mathrm{load}}$ | 园区日总用电量 | MWh |
| $E_{\mathrm{RE}}$ | 日新能源发电量 | MWh |
| $E_{\mathrm{buy}}$ | 日网购电量 | MWh |
| $E_{\mathrm{sell}}$ | 日上网电量 | MWh |
| $Q_{\mathrm{NH3}}$ | 日制氨产量 | t |
| $C_{\mathrm{total}}$ | 园区日总成本 | 元 |
| $C_{\mathrm{NH3}}$ | 吨氨成本 | 元/tNH3 |

---

## 6. 绿电直连指标公式

本文严格按照题目给定公式计算绿电直连指标。

### 6.1 新能源自发自用电量占总可用发电量比例

$$
R_{\mathrm{self}}
=
\frac{
E_{\mathrm{load}}-E_{\mathrm{sell}}-E_{\mathrm{buy}}
}{
E_{\mathrm{RE}}
}
$$

要求：

$$
R_{\mathrm{self}}>60\%
$$

### 6.2 总用电量绿电比例

$$
R_{\mathrm{green}}
=
\frac{
E_{\mathrm{RE}}-E_{\mathrm{sell}}
}{
E_{\mathrm{load}}
}
$$

要求：

$$
R_{\mathrm{green}}>30\%
$$

### 6.3 新能源上网电量比例

$$
R_{\mathrm{sell}}
=
\frac{
E_{\mathrm{sell}}
}{
E_{\mathrm{RE}}
}
$$

要求：

$$
R_{\mathrm{sell}}<20\%
$$

需要注意的是，题目给定的“新能源自发自用比例”公式与物理意义上的“新能源本地消纳比例”并不完全相同。本文所有达标判断均严格采用题目给定公式，避免指标口径不一致。

---

## 7. 成本模型

吨氨成本定义为：

$$
C_{\mathrm{NH3}}=
\frac{
C_{\mathrm{total}}
}{
Q_{\mathrm{NH3}}
}
$$

问题一中，日总成本包括购电成本、风电发电成本、光伏发电成本、电解槽运维成本、合成氨装置运维成本、合成氨装置折旧成本，并扣除余电上网收益：

$$
C_{\mathrm{total}}
=
C_{\mathrm{buy}}
+
C_{\mathrm{wind}}
+
C_{\mathrm{pv}}
+
C_{\mathrm{ALK,om}}
+
C_{\mathrm{PEM,om}}
+
C_{\mathrm{NH3,om}}
+
C_{\mathrm{NH3,cap}}
-
R_{\mathrm{sell}}
$$

其中，购电成本为：

$$
C_{\mathrm{buy}}
=
\sum_{t=1}^{24}
P_{\mathrm{buy}}(t)\cdot 1000 \cdot \lambda_{\mathrm{buy}}(t)
$$

风电和光伏发电成本为：

$$
C_{\mathrm{wind}}
=
\sum_{t=1}^{24}
P_{\mathrm{wind}}(t)\cdot 1000 \cdot \lambda_{\mathrm{wind}}
$$

$$
C_{\mathrm{pv}}
=
\sum_{t=1}^{24}
P_{\mathrm{pv}}(t)\cdot 1000 \cdot \lambda_{\mathrm{pv}}
$$

余电上网收益为：

$$
R_{\mathrm{sell}}
=
\sum_{t=1}^{24}
P_{\mathrm{sell}}(t)\cdot 1000 \cdot \lambda_{\mathrm{sell}}
$$

合成氨装置折旧成本采用直线折旧：

$$
C_{\mathrm{NH3,cap}}
=
\frac{
I_{\mathrm{NH3}}
}{
Y_{\mathrm{life}}\cdot D_{\mathrm{year}}
}
$$

其中，$Y_{\mathrm{life}}=30$ 年，$D_{\mathrm{year}}=360$ 天。

---

## 8. 问题一：典型日基准运行分析

### 8.1 基本假设

问题一假设电解槽与合成氨装置每日满负荷连续运行，不考虑园区功率损耗。

初始制氨产能为 36 t/day，对应设备额定功率为：

| 设备 | 额定功率 |
|---|---:|
| 碱性电解槽 ALKEL | 10 MW |
| 质子交换膜电解槽 PEMEL | 10 MW |
| 合成氨装置 | 0.75 MW |

因此，制氢氨系统连续运行功率为：

$$
P_{\mathrm{NH3}}(t)=10+10+0.75=20.75\ \mathrm{MW}
$$

常规负荷由附件 1 的标幺曲线计算：

$$
P_{\mathrm{base}}(t)=6\cdot p_{\mathrm{base}}^{pu}(t)
$$

风电和光伏由附件 2 的标幺曲线计算：

$$
P_{\mathrm{wind}}(t)=40\cdot p_{\mathrm{wind}}^{pu}(t)
$$

$$
P_{\mathrm{pv}}(t)=64\cdot p_{\mathrm{pv}}^{pu}(t)
$$

---

### 8.2 问题一计算结果

问题一典型日主要结果如下：

| 指标 | 数值 |
|---|---:|
| 园区日总用电量 $E_{\mathrm{load}}$ | 558.7200 MWh |
| 新能源日发电量 $E_{\mathrm{RE}}$ | 603.4480 MWh |
| 日网购电量 $E_{\mathrm{buy}}$ | 172.0438 MWh |
| 日上网电量 $E_{\mathrm{sell}}$ | 216.7718 MWh |
| 新能源自发自用比例 $R_{\mathrm{self}}$ | 28.1556% |
| 总用电量绿电比例 $R_{\mathrm{green}}$ | 69.2075% |
| 新能源上网比例 $R_{\mathrm{sell}}$ | 35.9222% |
| 日总成本 $C_{\mathrm{total}}$ | 15.73 万元 |
| 吨氨成本 $C_{\mathrm{NH3}}$ | 4368.63 元/tNH3 |

绿电直连指标达标情况如下：

| 指标 | 政策要求 | 计算结果 | 是否达标 |
|---|---:|---:|---|
| 新能源自发自用比例 | $>60\%$ | 28.16% | 不达标 |
| 总用电量绿电比例 | $>30\%$ | 69.21% | 达标 |
| 新能源上网比例 | $<20\%$ | 35.92% | 不达标 |

问题一的核心结论是：

> 典型日下，园区新能源日发电量为 603.4480 MWh，高于园区日总用电量 558.7200 MWh，说明从日总量上看新能源并不缺乏。但是由于风光出力与连续满负荷制氢氨负荷在时间分布上不匹配，园区同时出现较大规模购电和余电上网。因此，总用电量绿电比例能够达标，但新能源自发自用比例偏低、新能源上网比例偏高，无法完全满足绿电直连项目要求。

---

## 9. 问题一成本构成

问题一计入合成氨装置折旧后的成本构成如下：

| 成本项 | 金额 |
|---|---:|
| 购电成本 | 9.77 万元 |
| 风电发电成本 | 3.68 万元 |
| 光伏发电成本 | 4.30 万元 |
| ALK 电解槽运维 | 2.40 万元 |
| PEM 电解槽运维 | 3.60 万元 |
| 合成氨装置运维 | 0.0036 万元 |
| 合成氨装置折旧 | 0.1667 万元 |
| 余电上网收益 | -8.19 万元 |

其中，合成氨装置运维成本并不是 0，而是由于数值较小，在以“万元”为单位并保留两位小数时接近 0。余电上网收益为负值，表示其作为收益项抵扣总成本。

---

## 10. 问题一图像及意义

运行 `scripts/run_q1_baseline.py` 后，会在以下目录生成图像：

~~~text
outputs/figures/
~~~

### 10.1 `q1_power_balance.png`

该图用于展示典型日园区负荷与风光出力之间的时序匹配关系。

图像分为上下两个子图：

1. 上图展示园区负荷与风光出力：
   - 蓝色堆叠面积表示园区总负荷，其中包括常规电负荷和制氢氨负荷；
   - 深蓝色曲线表示总用电负荷；
   - 红色曲线表示风光总出力；
   - 绿色虚线表示风电出力；
   - 橙色虚线表示光伏出力。

2. 下图展示净功率差额：

$$
P_{\mathrm{net}}(t)=P_{\mathrm{RE}}(t)-P_{\mathrm{load}}(t)
$$

其中：
- 当 $P_{\mathrm{net}}(t)>0$ 时，表示新能源盈余，对应余电上网；
- 当 $P_{\mathrm{net}}(t)<0$ 时，表示新能源缺口，对应外部购电。

该图说明，典型日中午前后风光出力明显高于园区负荷，形成大规模余电上网；夜间和傍晚风光出力低于负荷，需要从电网购电。这种时序错配是问题一绿电指标不完全达标的主要原因。

---

### 10.2 `q1_grid_interaction.png`

该图用于展示典型日 24 小时购电功率和上网功率。

图像含义为：

- 正向红色柱表示购电功率；
- 负向绿色柱表示上网功率；
- 图中标注日购电量和日上网量。

该图进一步说明，园区不是单纯“新能源不足”或“新能源过剩”，而是在不同时间段分别出现新能源缺口和新能源盈余。因此，仅从日总量看新能源发电量并不足以判断绿电直连指标是否达标，必须进行小时级功率平衡分析。

---

### 10.3 `q1_green_indicators.png`

该图用于展示三个绿电直连指标的达标情况。

图像含义为：

- 绿色柱表示达标指标；
- 红色柱表示未达标指标；
- 黑色虚线短线表示政策阈值；
- 柱体上方标注具体计算值和达标状态。

该图直观显示：总用电量绿电比例达标，但新能源自发自用比例和新能源上网比例未达标。其原因是园区虽然具有较高的新能源总发电量，但不能在时序上完全被本地负荷吸收。

---

### 10.4 `q1_cost_breakdown.png`

该图用于展示问题一吨氨成本构成。

图像含义为：

- 红色正向柱表示成本项；
- 绿色负向柱表示余电上网收益抵扣项；
- 图中标注日总成本和吨氨成本。

该图说明，问题一中购电成本是最大的正向成本来源，电解槽运维成本和风光发电成本也占有较大比例。余电上网收益能够抵扣部分成本，但较高的上网量同时说明新能源本地消纳不足。因此，后续问题二和问题三需要通过制氨负荷调度提高新能源自发自用水平；问题四需要进一步分析储能对削减弃售电和提升离网自治能力的作用。

---

## 11. 脚本运行方式

安装依赖：

~~~bash
pip install -r requirements.txt
~~~

运行问题一：

~~~bash
python scripts/run_q1_baseline.py
~~~

运行完成后生成：

~~~text
outputs/tables/q1_hourly_results.csv
outputs/tables/q1_summary.csv
outputs/figures/q1_power_balance.png
outputs/figures/q1_grid_interaction.png
outputs/figures/q1_green_indicators.png
outputs/figures/q1_cost_breakdown.png
~~~

---

## 12. 当前进度

- [x] 项目结构初始化
- [x] 原始附件数据本地放置
- [x] 问题一 Excel 数据读取
- [x] 问题一小时级功率平衡计算
- [x] 问题一绿电直连指标计算
- [x] 问题一吨氨成本计算
- [x] 问题一论文级图像输出
- [ ] 问题二离散制氨调度优化
- [ ] 问题三连续制氨调度优化
- [ ] 问题四离网运行与储能配置优化
- [ ] 24 场景全年统计分析
- [ ] 最终论文结果整理

---

## 13. 建模原则

本项目后续建模遵循以下原则：

1. **统一功率平衡口径**：所有问题均基于同一套电力平衡关系进行扩展；
2. **统一成本口径**：吨氨成本的组成项保持一致，便于不同问题横向比较；
3. **严格按照题面指标计算**：绿电直连指标使用题目给定公式，不随意替换口径；
4. **先算准，再优化**：问题一作为基准运行方案，后续问题二、三、四均与其对比；
5. **图像服务于结论**：所有图像不仅展示数值，还要解释购电、上网、绿电指标和吨氨成本变化的原因。
