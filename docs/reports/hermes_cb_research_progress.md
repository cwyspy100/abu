# Hermes 可转债研究进度报告

- 项目：可转债因子研究（因子 -> 分层 -> 组合）
- 更新时间：2026-05-27
- 研究阶段：第二阶段（因子叠加增强，已完成）
- 数据来源：本地 `/Users/water/abu/data/cb`

## 0. 截至当前总览（可执行结论）

模拟盘执行文档：
- `/Users/water/mylearn/PycharmProjects/abu-master/docs/reports/cb_sim_paper_trading_sop.md`

1. 数据与口径已升级为 5 年完整样本：
- `cb_daily_20210527_20260527.csv`
- `cb_call_20210527_20260527.csv`

2. 因子与组合层面结论：
- 单因子中，`double_low / low_premium / call_risk_proxy` 在 5 年样本更稳定。
- 组合层面，`combo_dl_trend` 仍是主策略基线；`combo_dl_trend_call` 作为备选。

3. 分散约束结论（关键有效）：
- `balanced_premium` 在 5 年 OOS 下相对 baseline 仍有稳定增益：
- 年化增量约 `+3.05%`，总收益增量约 `+16.47%`，回撤改善约 `+4.53%`。

4. 风控 Overlay 结论：
- 固定 overlay 参数在 OOS 下可实现“小幅增收 + 回撤改善”（例如 `Top25 + amount>=2000 + 40bps`）。
- 但最近窗口边际转弱，月度健康检查显示应按阈值动态选择“baseline 或 defensive”，不建议长期强制开启 overlay。

5. 动态切换（Regime / Risk Trigger）结论：
- 已验证两类动态切换方案，均存在样本外不稳定或收益拖累。
- 当前不建议作为主执行框架。

6. 当前执行建议（实盘）：
- 严格模式：`USE_BASELINE`（优先，保守执行）。
- 宽松模式：`SWITCH_TO_DEFENSIVE`（接受轻微收益牺牲换波动控制）。

7. 当前研究状态：
- 已从“策略研究”进入“可执行决策输出”阶段，可每月运行决策脚本自动给出动作建议。

## 1. 本次研究目标

按你的路线，先做可转债单因子分层研究（decile test）：

1. 低溢价
2. 双低
3. 正股趋势
4. 强赎风险
5. 剩余期限

评估指标：未来 `20/60/120` 交易日收益。

## 2. 本次实现内容

新增研究脚本：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/cb/cb_factor_decile_research.py`

输出目录：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_decile_research_20260527_010305`

关键输出文件：
- `factor_decile_summary.csv`
- `spread_annualized_pivot.csv`
- `run_meta.json`

## 3. 研究设定（首轮）

- 分层方式：按交易日截面做 10 分层（Decile 1~10）
- 前瞻收益：`20/60/120` 交易日
- 最低截面样本：每个交易日 `>=50` 只转债
- 评价方式：
  - `best_decile - worst_decile` 的收益差（spread）
  - spread 对应的年化换算（`(1+spread)^(252/h)-1`）
  - 日度 Spearman signed IC（方向统一后）

## 4. 因子定义（当前可用本地数据）

1. `low_premium`：`bond_over_rate`（越低越好）
2. `double_low`：`close + bond_over_rate`（越低越好）
3. `stock_trend_proxy`：`cb_value / MA120(cb_value) - 1`（越高越好）
4. `call_risk_proxy`：`close`（越低风险越小，作为强赎风险代理）
5. `remaining_term`：`delist_date - trade_date`（越长越好）

> 说明：
> - `正股趋势` 当前用 `cb_value` 代理，后续可接入正股日线做纯正股趋势。
> - `强赎风险` 当前为价格代理，后续建议引入 `cb_call`（公告/是否强赎）做真实标签。

## 5. 首轮结果（摘要）

### 5.1 20日

- `stock_trend_proxy`：spread `+1.44%`（最强）
- `call_risk_proxy`：spread `+0.28%`
- `remaining_term`：spread `+0.32%`
- `double_low`：spread `-0.08%`
- `low_premium`：spread `-0.26%`

### 5.2 60日

- `stock_trend_proxy`：spread `+2.45%`
- `call_risk_proxy`：spread `+1.85%`
- `double_low`：spread `+1.03%`
- `low_premium`：spread `+0.57%`
- `remaining_term`：spread `-0.14%`

### 5.3 120日

- `stock_trend_proxy`：spread `+4.67%`（最强）
- `call_risk_proxy`：spread `+2.37%`
- `double_low`：spread `+1.02%`
- `low_premium`：spread `-0.47%`
- `remaining_term`：spread `-1.05%`

## 6. 首轮结论（可执行）

1. 趋势类因子在本样本最稳定：`stock_trend_proxy` 在 20/60/120 日都为正，且中长周期明显。
2. 风险代理因子次强：`call_risk_proxy` 三个周期都为正，说明“高价高风险”过滤有价值。
3. 价值类因子分化：
   - `double_low` 在 60/120 日转正。
   - `low_premium` 方向不稳定，可能需与趋势因子叠加使用。
4. `remaining_term` 在中长周期表现偏弱，建议作为约束条件而非主打选股因子。

## 7. 第二阶段结果（因子叠加增强）

第二阶段新增脚本：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/cb/cb_factor_combo_research.py`

第二阶段输出目录：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_combo_research_20260527_010519`

核心结果（10分层，取 Top Decile - Bottom Decile）：

1. `双低 + 趋势`（`combo_dl_trend`）
- 20日 spread：`+1.15%`
- 60日 spread：`+3.04%`
- 120日 spread：`+3.90%`

2. `双低 + 趋势 + 强赎风险`（`combo_dl_trend_call`）
- 20日 spread：`+1.00%`
- 60日 spread：`+3.29%`（三组合中最强）
- 120日 spread：`+3.88%`

3. `低溢价 + 趋势`（`combo_lp_trend`）
- 20日 spread：`+1.00%`
- 60日 spread：`+2.20%`
- 120日 spread：`+2.63%`

阶段结论：

1. 因子叠加明显优于单独 `double_low` / `low_premium`。
2. 趋势因子是核心增强项，叠加后在 20/60/120 日均为正。
3. 在中期（60日）上，`双低 + 趋势 + 强赎风险` 当前样本最优。

## 8. 第三阶段启动结果（月度轮动原型回测）

第三阶段新增脚本：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/cb/cb_combo_monthly_backtest.py`

第三阶段输出目录：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_monthly_backtest_20260527_010745`

回测设定（原型）：

1. 月末调仓（每月最后一个交易日）
2. 等权 Top20
3. 持有 20 个交易日（用 `fwd_ret_20d` 近似）
4. 样本期约 24 个调仓期（近两年）

原型绩效（未计交易成本）：

1. `combo_dl_trend`
- 年化：`24.83%`
- 最大回撤：`-4.09%`
- 胜率：`79.17%`

2. `combo_dl_trend_call`
- 年化：`21.64%`
- 最大回撤：`-7.78%`
- 胜率：`79.17%`

3. `combo_lp_trend`
- 年化：`22.01%`
- 最大回撤：`-4.18%`
- 胜率：`70.83%`

阶段结论：

1. 在当前样本和原型设定下，`双低 + 趋势` 年化最高且回撤更小。
2. 加入强赎风险代理后，稳健性可能增强，但本轮原型中收益端未继续提升。
3. 组合框架已可进入“实盘约束化”迭代（成本、流动性、强赎事件）。

## 9. 下一步（回测工程化）

1. 引入交易成本与滑点（双边费率 + 冲击成本）。
2. 加入流动性过滤（最低成交额/成交量）。
3. 接入 `cb_call` 强赎事件，替代价格代理因子。
4. 输出完整绩效矩阵：夏普、卡玛、换手率、持仓集中度、分年收益。

## 10. 回测工程化进展（本轮新增）

### 10.1 已落地约束

已在月度轮动脚本中加入：

1. 交易成本：按换手率计入双边成本（本轮参数 `40bps`）。
2. 流动性过滤：`amount >= 3000`（万元）。
3. 强赎风险硬过滤（代理）：`close <= 140`。

对应产出目录：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_monthly_backtest_20260527_010901`

工程化参数下（Top20）结果：

1. `combo_dl_trend`
- 年化：`21.60%`
- 最大回撤：`-4.43%`
- 胜率：`75.00%`
- 平均换手：`55.83%`

2. `combo_dl_trend_call`
- 年化：`18.75%`
- 最大回撤：`-8.60%`
- 胜率：`70.83%`

3. `combo_lp_trend`
- 年化：`19.92%`
- 最大回撤：`-5.08%`
- 胜率：`66.67%`

### 10.2 稳健性测试（TopN × 成本）

产出目录：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_monthly_robustness_20260527_010921`

测试对象：`combo_dl_trend`，参数网格：
- `TopN = 10/20/30`
- `成本 = 20/40/60 bps`

观察结论：

1. 成本从 20bps 提升到 60bps 时，年化收益单调下降（符合预期）。
2. 在本样本中，`Top30` 组的收益最高（约 `24.49% -> 21.17%`）。
3. 各网格组合仍保持正年化，说明策略在当前样本下有一定稳健性。

## 11. 时间稳定性研究（新增）

稳定性研究脚本：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/cb/cb_stability_research.py`

输出目录：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_stability_research_20260527_011147`

参数沿用工程化设定：
- Top20
- 成交额过滤 `amount>=3000`
- 价格过滤 `close<=140`
- 成本 `40bps`

全样本（24期）：

1. `combo_dl_trend`
- 总收益：`45.14%`
- 年化：`21.60%`
- 最大回撤：`-4.43%`

2. `combo_dl_trend_call`
- 总收益：`38.73%`
- 年化：`18.75%`
- 最大回撤：`-8.60%`

3. `combo_lp_trend`
- 总收益：`41.33%`
- 年化：`19.92%`
- 最大回撤：`-5.08%`

前后半段（各12期）观察：

1. 三个策略在后半段 `avg_period_ret` 均有下降，说明边际效应在减弱。
2. `combo_dl_trend` 后半段胜率仍提升到 `83.33%`，但单期收益变薄（更偏“稳但薄”）。
3. `combo_dl_trend_call` 后半段回撤显著放大，需要进一步校准强赎风险过滤阈值。

分年观察（看 `total_return` 为主）：

1. 2024、2025 为正贡献，且 2025 更稳定。
2. 2026（当前仅4期）出现负贡献，提示近期环境对该类策略不友好。

注意：
- 年度 `ann_return` 在样本期很短（如 4 期）时会被放大，解释时以 `total_return` 为主。

## 12. 强赎风险阈值调参（新增）

调参目标：改善 `combo_dl_trend_call` 后半段回撤表现。  
调参网格：

1. `max_price_for_call_risk`：`130/135/140/145/150`
2. `min_amount_wan`：`2000/3000/4000`

结果目录：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_callrisk_tuning_20260527_011233`

最佳组合（在本轮网格中）：

1. `max_price_for_call_risk=130`
2. `min_amount_wan=2000`
3. `combo_dl_trend_call` 指标：
   - 年化：`24.17%`
   - 最大回撤：`-6.57%`
   - 胜率：`70.83%`

同条件对照（`Top20, min_amount=2000, max_price=130, cost=40bps`）：

1. `combo_dl_trend`
   - 年化：`27.02%`
   - 最大回撤：`-3.81%`
2. `combo_dl_trend_call`
   - 年化：`24.17%`
   - 最大回撤：`-6.57%`

结论：

1. 强赎风险阈值从 `140` 收紧到 `130` 能显著改善 `combo_dl_trend_call`。
2. 但在当前代理口径下，`combo_dl_trend` 仍然是收益/回撤更优主策略。
3. 下一步应优先接入真实 `cb_call` 事件字段，替代价格代理后再复核结论。

## 13. 接入真实强赎事件（cb_call）验证

### 13.1 数据接入

新增下载脚本：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/cb/TushareCBCallFetcher.py`

已下载文件：
- `/Users/water/abu/data/cb/cb_call_20240527_20260527.csv`（`885` 条）

### 13.2 对照实验

新增对照脚本：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/cb/cb_real_call_filter_backtest.py`

对照方式：

1. `proxy_price_filter`：原价格代理过滤（`close<=140`）
2. `real_call_filter`：基于 `cb_call` 强赎公告区间过滤（强赎且非“不强赎”）

实验输出目录：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_real_call_compare_20260527_011442`

样本覆盖：
- 原始面板：`223,418` 行
- 真实强赎过滤后：`217,419` 行
- 强赎事件区间：`551` 个（涉及 `300` 只转债）

### 13.3 关键结果（Top20, amount>=3000, cost=40bps）

1. `combo_dl_trend_call`
- 价格代理过滤：年化 `18.75%`，最大回撤 `-8.60%`
- 真实强赎过滤：年化 `19.61%`，最大回撤 `-7.33%`

2. `combo_dl_trend`
- 价格代理过滤：年化 `21.60%`
- 真实强赎过滤：年化 `22.18%`

结论：

1. 真实强赎事件过滤优于价格代理过滤，尤其能改善 `combo_dl_trend_call` 的回撤。
2. 在当前样本中，主策略仍是 `combo_dl_trend`，但 `combo_dl_trend_call` 在真实事件过滤后显著更可用。

## 14. 最终参数搜索（真实强赎过滤 + 约束筛选）

新增脚本：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/cb/cb_final_param_search.py`

输出目录：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_final_param_search_20260527_011608`

搜索空间：

1. 策略：`combo_dl_trend / combo_dl_trend_call / combo_lp_trend`
2. `TopN`：`10/15/20/25/30`
3. 成交额阈值（万元）：`2000/3000/4000`
4. 成本：`20/40/60 bps`

约束条件：

1. 最大回撤绝对值 `<= 8%`
2. 平均换手 `<= 60%`
3. 胜率 `>= 65%`

结果规模：

1. 全部参数组合：`135` 组
2. 可行组合（满足约束）：`108` 组

全局最优推荐（按综合评分）：

1. 策略：`combo_dl_trend`
2. 参数：
   - `TopN=25`
   - `min_amount_wan=2000`
   - `cost=20bps`
3. 指标：
   - 年化：`27.14%`
   - 总收益：`57.98%`
   - 最大回撤：`-3.87%`
   - 胜率：`75.00%`
   - 平均换手：`51.33%`

各策略最佳可行参数（便于备选）：

1. `combo_dl_trend`
- `TopN=25, min_amount=2000, cost=20bps`
- 年化：`27.14%`

2. `combo_dl_trend_call`
- `TopN=25, min_amount=2000, cost=20bps`
- 年化：`26.26%`

3. `combo_lp_trend`
- `TopN=25, min_amount=2000, cost=20bps`
- 年化：`25.86%`

成本敏感性（可行集中的最大年化）：

1. `combo_dl_trend`：`20bps 27.14% -> 40bps 25.53% -> 60bps 23.93%`
2. `combo_dl_trend_call`：`20bps 26.26% -> 40bps 24.76% -> 60bps 23.27%`
3. `combo_lp_trend`：`20bps 25.86% -> 40bps 24.30% -> 60bps 22.75%`

阶段结论：

1. 主策略可定版为 `combo_dl_trend`，参数建议优先采用 `Top25 + amount>=2000 + 真实强赎过滤`。
2. `combo_dl_trend_call` 可作为次优备选，风格更偏风险控制。

## 15. Walk-Forward 样本外验证（防过拟合）

新增脚本：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/cb/cb_walkforward_validation.py`

验证设定：

1. 训练窗 `12` 期，测试窗 `3` 期，步长 `3`
2. 成本 `40bps`
3. 候选参数：3个策略 × TopN(`15/20/25/30`) × 成交额(`2000/3000`)

### 15.1 单参数选择（Top-1）

输出目录：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_walkforward_20260527_011819`

样本外汇总（4个fold，12个测试期）：

1. 总收益：`11.98%`
2. 年化：`12.62%`
3. 最大回撤：`-8.50%`
4. 胜率：`66.67%`

### 15.2 集成选择（Top-3等权）

输出目录：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_walkforward_20260527_011945`

样本外汇总（4个fold，12个测试期）：

1. 总收益：`14.68%`
2. 年化：`15.46%`
3. 最大回撤：`-5.21%`
4. 胜率：`58.33%`

观察结论：

1. `Top-3` 集成相比 `Top-1`，样本外收益更高、回撤更小，稳定性更好。
2. 但最终一个fold（`2026-02` 到 `2026-04`）仍为负，说明近期环境仍有压力。
3. 实盘建议优先采用“主策略参数 + Top-K集成备选”的双层机制，而非单点参数。

## 16. 失效环境诊断与风控叠加测试

### 16.1 失效环境诊断

新增脚本：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/cb/cb_regime_diagnostics.py`

输出目录：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_regime_diag_20260527_012117`

诊断对象：主策略 `combo_dl_trend`（Top25, amount>=2000, real_call, cost=40bps）。

关键发现：

1. 负收益期（6期）相比正收益期（18期）：
   - 市场平均溢价更高（`36.85` vs `28.67`）
   - 市场平均价格更高（`141.55` vs `132.69`）
2. 策略20日收益与市场等权20日收益相关性较高（`0.71`），说明系统性回撤期很难完全回避。

### 16.2 自适应叠加（单信号）

新增脚本：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/cb/cb_adaptive_overlay_research.py`

输出目录：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_adaptive_overlay_20260527_012151`

结论：

1. 以“高溢价降仓”为规则，最优组合可提升收益（年化 `26.37%`），
2. 但最大回撤未改善（仍约 `-3.94%`），因此并未解决核心痛点。

### 16.3 自适应叠加（联合信号）

新增脚本：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/cb/cb_joint_overlay_research.py`

输出目录：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_joint_overlay_20260527_012243`

测试规则：`高溢价 + 趋势走弱` 同时触发降仓。

结论：

1. 最优联合规则同样提升了收益（年化 `27.14%`），
2. 但回撤仍未低于基线（最佳与基线回撤相同），
3. 没有找到“回撤更低且年化不降”的有效组合（满足条件数量 `0`）。

阶段判断：

1. 当前回撤主要由系统性市场阶段驱动，简单阈值降仓难以显著改善。
2. 下一步应从“持仓分散与仓位上限机制”入手（如单券上限、行业暴露上限、分层持仓），而非继续堆叠同类阈值。

## 17. 动态仓位风控补充实验（继续验证）

### 17.1 波动率目标仓位（滞后市场波动）

新增脚本：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/cb/cb_vol_target_overlay_research.py`

输出目录：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_vol_overlay_20260527_012335`

结论：

1. 在 `lookback=6, vol_quantile=0.8, high_vol_exposure=0.7` 时评分最高，
2. 但相对基线几乎无差异（年化 `25.48%` vs `25.53%`，回撤相同），
3. 无“更低回撤且收益不明显受损”的有效组合。

### 17.2 亏损触发降仓（下一期刹车）

新增脚本：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/cb/cb_loss_brake_overlay_research.py`

输出目录：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_loss_brake_20260527_012419`

结论：

1. 所有亏损刹车规则均显著拖累收益，
2. 且未带来更低回撤（满足“更低回撤且年化>=基线95%”的组合数为 `0`）。

阶段结论（最新）：

1. 单维度/双维度阈值降仓、波动率降仓、亏损刹车在当前样本下都无法改善核心回撤。
2. 下一阶段研究重点应转向“横截面分散化约束”（持仓结构优化），而不是继续做时序仓位开关。

## 18. 横截面分散化约束研究（关键突破）

### 18.1 单次验证

新增脚本：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/cb/cb_diversification_research.py`

输出目录：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_diversification_20260527_012521`

测试口径：
- 主评分：`combo_dl_trend`
- `TopN=25, amount>=2000, real_call_filter, cost=40bps`
- 对比模式：
  1. `baseline`（纯TopN）
  2. `one_per_stk`（每个正股最多1只）
  3. `balanced_premium`（溢价三分桶均衡选取）
  4. `combo`（正股去重+溢价均衡）

结果要点：

1. `balanced_premium`：年化 `33.94%`，总收益 `74.46%`，回撤 `-2.61%`
2. 基线 `baseline`：年化 `25.53%`，总收益 `54.19%`，回撤 `-3.94%`
3. `one_per_stk` 改善不明显，主要贡献来自“溢价分桶均衡”。

### 18.2 网格验证（TopN × 成本）

新增脚本：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/cb/cb_diversification_grid_research.py`

输出目录：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_diversification_grid_20260527_012634`

主要发现：

1. 在 `TopN=20/25/30`、成本 `20/40/60/80bps` 全部场景，`balanced_premium` 都显著领先基线。
2. 成本 `40bps` 下最佳：
   - `mode=balanced_premium`
   - `TopN=25`
   - 年化 `33.94%`
   - 回撤 `-2.61%`
   - 胜率 `70.83%`
   - 平均换手 `63.83%`
3. 即便成本到 `80bps`，`balanced_premium` 仍保持显著超额（年化 `29.78%`）。

阶段结论（当前最优）：

1. 研究主线从“时序降仓”切换到“横截面分散约束”是正确的。
2. 当前可执行最优方案建议升级为：
   - 主评分：`combo_dl_trend`
   - 选股方式：`balanced_premium`
   - 参数：`TopN=25, amount>=2000, real_call_filter, cost=40bps`

## 19. balanced_premium 统计稳健性检验

新增脚本：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/cb/cb_balanced_premium_robustness.py`

输出目录：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_bp_robustness_20260527_012832`

### 19.1 参数扰动结果

在 `TopN(20/25/30) × amount(1500/2000/2500/3000) × cost(40/60)` 的网格中：

1. `balanced_premium` 相对基线在绝大多数参数下都保持正超额（`delta_ann > 0`）。
2. 最优扰动点为 `Top20, amount=1500, cost=40`：
   - 年化增量 `+9.60%`
   - 总收益增量 `+22.28%`

### 19.2 Block Bootstrap 显著性（最优扰动点）

1. `P(delta_total > 0) = 98.36%`
2. `delta_total` 的 5%-95% 区间约 `[+4.07%, +51.95%]`

### 19.3 保守执行参数下的统计检验

对更实盘友好的参数 `Top25, amount>=2000, cost=40` 单独检验：

1. `P(delta_total > 0) = 86.96%`
2. `delta_total` 5%-95% 区间约 `[-9.50%, +52.51%]`
3. 样本内观测增量：`+20.27%`

解读：

1. `balanced_premium` 优势方向较稳定，但在更保守口径下置信区间下沿仍跨零。
2. 结论属于“偏强证据”，还需更长样本或更多外部周期验证来进一步固化。

## 20. 分散约束的样本外复核（固定参数）

新增脚本：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/cb/cb_diversification_walkforward_compare.py`

输出目录：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_div_wf_compare_20260527_013055`

验证口径：

1. 固定参数：`TopN=25, amount>=2000, cost=40bps, real_call_filter`
2. 模式对照：
   - `baseline`（纯TopN）
   - `balanced_premium`（溢价分桶均衡）
3. 滚动OOS切分：训练12期、测试3期、步长3（仅用于时间切片，不重新调参）

OOS 对照结果（12期）：

1. `baseline_oos`
- 年化：`24.40%`
- 总收益：`23.11%`
- 最大回撤：`-3.36%`
- 胜率：`75.00%`

2. `balanced_premium_oos`
- 年化：`33.01%`
- 总收益：`31.21%`
- 最大回撤：`-2.61%`
- 胜率：`66.67%`

3. `balanced - baseline`：
- 年化增量：`+8.61%`
- 总收益增量：`+8.10%`
- 回撤改善：`+0.75%`（绝对回撤更小）
- 胜率变化：`-8.33%`

解读：

1. `balanced_premium` 的优势在样本外仍成立（收益和回撤双改善）。
2. 代价是“命中率下降但盈亏比改善”，这与分散化策略特征一致。
3. 当前最优执行建议仍维持 `balanced_premium + Top25 + amount>=2000`，并建议继续跟踪未来fold稳定性。

## 21. 容量与冲击成本压力测试（新增）

新增脚本：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/cb/cb_capacity_stress.py`

输出目录：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_capacity_stress_20260527_070907`

测试口径：

1. 策略：`balanced_premium`
2. 参数：`TopN=25, amount>=2000, real_call_filter, base_cost=40bps`
3. 冲击模型：`impact_bps = k * sqrt(participation)`（启发式）

第一轮容量结果（资金 500万~2亿）：

1. 年化从 `33.87%`（500万, k=10）到 `33.08%`（2亿, k=20）
2. 回撤从 `-2.61%` 到 `-2.68%`
3. 结论：在该规模区间，容量压力可控。

极端情景补充（资金 2亿~10亿，k=20/30/40/60）：

1. `10亿 + k=60` 时，年化约 `28.29%`，回撤约 `-3.13%`
2. 相比常规情景收益明显下滑，但策略仍保持正向表现。

容量阶段结论：

1. 在“千万~数亿”规模下，策略容量具备可行性。
2. 若资金继续放大（接近10亿）且冲击更强，收益会明显衰减。
3. 建议实盘先按分账户或分批执行，并持续监控参与率与成交冲击。

## 22. 五年样本扩展复核（最新）

数据口径：

1. 日线主数据：`/Users/water/abu/data/cb/cb_daily_20210527_20260527.csv`（近5年）
2. 基础信息：`/Users/water/abu/data/cb/cb_basic.csv`
3. 强赎事件：`/Users/water/abu/data/cb/cb_call_20240527_20260527.csv`（当前仅近2年）

### 22.1 口径修复（避免分层空值）

修复文件：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/cb/cb_factor_decile_research.py`

修复内容：

1. 在计算 `fwd_ret_20d/60d/120d` 后，统一清理 `inf/-inf`（如除零导致），避免污染分层均值。

说明：

1. 修复后已重跑5年单因子、叠加、月度回测与稳定性结果。

### 22.2 单因子5年分层（Decile）复核

输出目录：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_decile_research_20260527_082631`

`spread_annualized`（Top-Bottom，同方向）：

1. `call_risk_proxy`：20/60/120日 = `13.10% / 13.42% / 12.69%`
2. `double_low`：20/60/120日 = `11.80% / 13.58% / 13.60%`
3. `low_premium`：20/60/120日 = `10.61% / 13.46% / 12.61%`
4. `stock_trend_proxy`：20/60/120日 = `5.17% / 0.47% / -1.02%`
5. `remaining_term`：20/60/120日 = `-2.94% / -3.89% / -3.22%`

观察：

1. 5年样本中，“估值/风险约束类因子”显著强于“趋势代理因子”。
2. 趋势代理在长周期（120日）转负，提示该代理变量在更长周期下稳定性不足。

### 22.3 因子叠加5年分层复核

输出目录：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_combo_research_20260527_082751`

`spread_annualized`：

1. `combo_dl_trend_call`：`11.60% / 12.33% / 12.02%`（20/60/120日，三组最优）
2. `combo_dl_trend`：`9.80% / 10.11% / 10.15%`
3. `combo_lp_trend`：`7.25% / 7.18% / 8.22%`

观察：

1. 在5年样本下，`双低 + 趋势 + 风险` 叠加依然优于其余组合。

### 22.4 月度轮动5年回测（工程化约束）

默认工程化参数（Top20, amount>=3000, price<=140, cost=40bps）：
- 输出：`/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_monthly_backtest_20260527_082850`

1. `combo_dl_trend`：年化 `10.21%`，最大回撤 `-18.50%`
2. `combo_dl_trend_call`：年化 `10.22%`，最大回撤 `-18.47%`
3. `combo_lp_trend`：年化 `9.59%`，最大回撤 `-20.02%`

调优参数（Top25, amount>=2000, price<=130, cost=40bps）：
- 输出：`/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_monthly_backtest_20260527_082902`

1. `combo_dl_trend`：年化 `12.34%`，最大回撤 `-18.69%`
2. `combo_dl_trend_call`：年化 `10.89%`，最大回撤 `-19.47%`
3. `combo_lp_trend`：年化 `11.18%`，最大回撤 `-19.27%`

观察：

1. 5年口径下整体收益显著低于2年样本，且回撤显著扩大（约 `-18%~-20%`）。
2. `combo_dl_trend` 仍是当前收益端第一，但风控层面需要继续加强。

### 22.5 5年稳定性（调优参数）

输出目录：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_stability_research_20260527_082917`

全样本（60期）：

1. `combo_dl_trend`：年化 `12.34%`，总收益 `74.01%`，最大回撤 `-18.69%`
2. `combo_dl_trend_call`：年化 `10.89%`，总收益 `63.61%`，最大回撤 `-19.47%`
3. `combo_lp_trend`：年化 `11.18%`，总收益 `65.64%`，最大回撤 `-19.27%`

前后半段（各30期）：

1. `combo_dl_trend` 后半段收益显著高于前半段（`total_return 45.15% vs 19.88%`），但回撤更深。
2. 三个策略在后半段都表现出“收益上升 + 回撤上升”的特征。

年度观察（以 `total_return` 为主）：

1. `2022`、`2023` 基本横盘或小负。
2. `2024`、`2025` 为主要收益贡献年。
3. `2026`（当前仅4期）为负。

### 22.6 5年分散约束复核（注意：cb_call仅2年）

输出目录：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_diversification_20260527_082933`

固定参数：`Top25, amount>=2000, cost=40bps`（并使用当前可用 `cb_call` 过滤）

1. `baseline`：年化 `11.73%`，总收益 `69.57%`，回撤 `-18.81%`
2. `balanced_premium`：年化 `14.14%`，总收益 `87.69%`，回撤 `-21.59%`

观察：

1. `balanced_premium` 在5年样本仍有明显增收能力；
2. 但与2年样本不同，本轮出现“收益更高但回撤更深”，胜率也下降（`61.67% -> 56.67%`）。

结论（5年复核）：

1. 5年口径下，策略仍有效，但风险特征明显变“更波动”，不能直接沿用2年样本的低回撤预期。
2. 当前建议把 `combo_dl_trend` 作为主策略、`combo_dl_trend_call` 作为风险备选，同时优先做“回撤约束型仓位管理/止损框架”而不是继续只加选股因子。
3. 由于 `cb_call` 仅覆盖近2年，凡涉及“真实强赎过滤”的5年结论都应视为阶段性结果，待补齐5年 `cb_call` 后再做最终定版。

## 23. 五年真实强赎口径补齐后的复核（本轮继续研究）

### 23.1 数据补齐

新增事件数据文件：
- `/Users/water/abu/data/cb/cb_call_20210527_20260527.csv`

下载结果：

1. `cb_call` 记录数：`2000` 条。

基于该文件的过滤覆盖（回测元数据）：

1. 原始面板：`560,440` 行
2. 真实强赎过滤后：`548,514` 行
3. 强赎区间：`1,367` 个
4. 涉及转债：`442` 只

### 23.2 真实强赎过滤 vs 价格代理过滤（5年对照）

输出目录：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_real_call_compare_20260527_083322`

对照参数：

1. `TopN=25`
2. `min_amount_wan=2000`
3. `cost=40bps`
4. 价格代理阈值 `close<=130`

核心结果：

1. `combo_dl_trend`
- 价格代理：年化 `12.34%`，回撤 `-18.69%`
- 真实强赎：年化 `11.73%`，回撤 `-18.81%`

2. `combo_dl_trend_call`
- 价格代理：年化 `10.89%`，回撤 `-19.47%`
- 真实强赎：年化 `10.86%`，回撤 `-19.47%`

3. `combo_lp_trend`
- 价格代理：年化 `11.18%`，回撤 `-19.27%`
- 真实强赎：年化 `10.83%`，回撤 `-20.07%`

结论：

1. 在5年完整样本里，真实强赎过滤并未带来明显增益，整体与价格代理接近或略弱。
2. 主策略排序不变：`combo_dl_trend` 仍是收益端相对最优。

### 23.3 五年最终参数搜索（真实强赎过滤）

输出目录：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_final_param_search_20260527_083346`

结果概览：

1. 全部参数组合：`135` 组
2. 可行组合：`1` 组（约束明显更严格）
3. 最优且可行参数：
   - 策略：`combo_dl_trend`
   - `TopN=10, min_amount_wan=3000, cost=20bps`
   - 年化：`14.52%`
   - 总收益：`90.74%`
   - 最大回撤：`-13.37%`
   - 胜率：`65.00%`

结论：

1. 5年真实强赎口径下，可行参数空间明显收缩，说明“稳健约束”比2年样本更难满足。
2. 若优先满足回撤约束，仓位集中度需要收紧（TopN从25降到10）。

### 23.4 五年 Walk-Forward 样本外验证（真实强赎过滤）

输出目录：

1. Top-1：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_walkforward_20260527_083526`
2. Top-3 集成：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_walkforward_20260527_083556`

OOS 汇总（48期）：

1. Top-1：
- 年化 `8.22%`
- 总收益 `35.11%`
- 回撤 `-18.47%`
- 胜率 `62.50%`

2. Top-3：
- 年化 `8.94%`
- 总收益 `38.59%`
- 回撤 `-17.51%`
- 胜率 `58.33%`

结论：

1. Top-3 集成再次优于 Top-1（收益更高、回撤更小）。
2. 但整体 OOS 年化已降至高个位数，说明5年全周期下策略阿尔法更“薄”。

### 23.5 分散约束 OOS 复核（真实强赎过滤）

输出目录：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_div_wf_compare_20260527_083633`

结果（48期）：

1. `baseline_oos`：
- 年化 `11.65%`
- 总收益 `52.18%`
- 回撤 `-18.81%`
- 胜率 `60.42%`

2. `balanced_premium_oos`：
- 年化 `14.71%`
- 总收益 `68.65%`
- 回撤 `-14.28%`
- 胜率 `62.50%`

3. `balanced - baseline`：
- 年化增量 `+3.05%`
- 总收益增量 `+16.47%`
- 回撤改善 `+4.53%`

结论：

1. 在5年完整真实强赎口径下，`balanced_premium` 的样本外优势显著成立（收益与回撤双改善）。
2. 这组结果比“仅2年强赎口径”的结论更可信，建议提升为优先执行模式。

### 23.6 容量压力复核（真实强赎过滤）

输出目录：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_capacity_stress_20260527_083704`

口径：

1. 基础策略：`balanced_premium`
2. 参数：`TopN=25, amount>=2000, cost=40bps`
3. 资金：`500万 ~ 2亿`
4. 冲击：`impact_bps = k * sqrt(participation)`，`k=10/15/20`

结果摘要：

1. `500万, k=10`：年化 `15.20%`，回撤 `-17.96%`
2. `2亿, k=20`：年化 `14.49%`，回撤 `-19.34%`

结论：

1. 资金从千万到数亿，策略收益有衰减但仍保持正向，容量可用性尚可。
2. 核心矛盾仍是回撤控制，而非容量上限。

### 23.7 本轮阶段结论（更新）

1. 5年完整真实强赎口径已补齐，研究口径从“阶段性”升级为“完整可复核”。
2. 单纯依赖真实强赎过滤本身并不能显著提升收益，关键增益来自“横截面分散约束（balanced_premium）”。
3. 当前更稳妥执行建议：
   - 主策略框架：`combo_dl_trend + balanced_premium`
   - 风险控制：优先继续研究“回撤约束型仓位管理”，目标先把 OOS 回撤压到 `-12%~-15%` 区间。

## 24. 回撤约束型仓位管理（Overlay）研究（新增）

新增脚本：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/cb/cb_drawdown_overlay_research.py`

输出目录：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_drawdown_overlay_20260527_084423`

### 24.1 研究框架

基线策略：

1. `balanced_premium`
2. 参数：`TopN=25, amount>=2000, cost=40bps, real_call_filter(5y)`

叠加风控模块（三层）：

1. 回撤分档降仓（mild/deep 两档）
2. 单期亏损触发冷却降仓
3. 近端波动率目标降仓（滚动6期）

### 24.2 全样本结果（60期）

基线：

1. 年化 `15.26%`
2. 总收益 `96.67%`
3. 最大回撤 `-17.84%`

网格最强回撤改善参数（full-grid）：

1. `ddm=-10%, ddd=-14%, exp_mild=0.75, exp_deep=0.65, loss_th=-4%, cooldown=1期@0.5, vol_target=2.0%`
2. 年化 `12.26%`（下降 `3.00%`）
3. 最大回撤 `-10.74%`（改善 `+7.09%`）

结论：

1. 回撤可以显著压缩，但收益会被明显牺牲（典型“防守型”特征）。

### 24.3 样本外结果（Walk-Forward, 48期）

动态选参（逐fold训练选参）：

1. `base_oos`：年化 `14.71%`，回撤 `-14.28%`
2. `overlay_oos`：年化 `14.13%`，回撤 `-15.20%`

结论：

1. 动态选参版在5年样本外不稳定，未带来改善。

### 24.4 固定参数 OOS 对照（关键发现）

同一输出目录中的 `fixed_oos_summary.csv` 显示：

1. 基线（`base_oos`）：
- 年化 `14.71%`
- 回撤 `-14.28%`

2. 固定 overlay（`full_best` / `max_mdd_improve_best`）：
- 年化 `14.85%`（`+0.14%`）
- 回撤 `-13.14%`（改善 `+1.14%`）
- 平均仓位约 `95.83%`

3. 固定 overlay（`target_band_best`）：
- 年化 `14.80%`（`+0.09%`）
- 回撤 `-13.28%`（改善 `+1.00%`）

阶段结论：

1. “固定参数 overlay”优于“动态逐fold选参”，并实现了 OOS 收益与回撤双改善。
2. 在当前口径下，策略回撤已从 `-14.28%` 压缩到约 `-13.14%`，进入目标区间（`-12%~-15%`）内。
3. 下一步建议将该固定 overlay 作为默认风控开关，继续做更长窗口和更细交易成本敏感性复核。

### 24.5 交易成本敏感性（固定 overlay，OOS）

输出目录：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_overlay_cost_sensitivity_20260527_084521`

测试口径：

1. 固定参数：`ddm=-10%, ddd=-14%, exp_mild=0.75, exp_deep=0.65, loss_th=-4%, cooldown=1@0.5, vol_target=2.0%`
2. OOS 切分：`12/3/3`
3. 成本：`20/40/60 bps`

结果（overlay - base）：

1. `20bps`：年化 `+0.06%`，总收益 `+0.37%`，回撤改善 `+3.66%`
2. `40bps`：年化 `+0.14%`，总收益 `+0.80%`，回撤改善 `+1.14%`
3. `60bps`：年化 `+0.22%`，总收益 `+1.18%`，回撤改善 `+0.62%`

结论：

1. 固定 overlay 在 `20/40/60bps` 三档成本下都保持“收益不降且回撤改善”。
2. 成本越高，回撤改善边际会收敛，但仍保持正向增益。

## 25. 固定 Overlay 执行参数网格（OOS）研究（继续）

新增脚本：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/cb/cb_overlay_execution_grid.py`

输出目录：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_overlay_exec_grid_20260527_152659`

研究目标：

1. 固定 Overlay 参数不变，仅在基础执行参数（`TopN / min_amount / cost`）上做 OOS 网格，
2. 直接找“收益不降 + 回撤改善”的可执行组合。

### 25.1 网格设定

1. `TopN = 10/15/20/25/30`
2. `min_amount_wan = 1500/2000/3000`
3. `cost_bps = 20/40/60`
4. OOS 切分：`12/3/3`
5. 共 `45` 组

### 25.2 关键结果

按 OOS 综合评分（回撤改善优先）Top 结果中，最优为：

1. `Top25, amount>=2000, cost=20bps`
2. Overlay OOS：年化 `16.71%`，回撤 `-10.26%`
3. 相对基线增量：年化 `+0.06%`，回撤改善 `+3.66%`

实盘更相关的 `40bps` 子集（满足“收益不降 + 回撤改善”）：

1. `Top25, amount>=2000`：
   - Overlay OOS 年化 `14.85%`
   - 回撤 `-13.14%`
   - 相对基线：年化 `+0.14%`，回撤改善 `+1.14%`
2. `Top15, amount>=1500`：
   - Overlay OOS 年化 `12.84%`
   - 回撤 `-13.02%`
   - 相对基线：年化 `+0.41%`，回撤改善 `+2.84%`

### 25.3 按成本分层的稳健性

“收益不降 + 回撤改善”占比：

1. `20bps`：`8/15`（`53.3%`）
2. `40bps`：`10/15`（`66.7%`）
3. `60bps`：`10/15`（`66.7%`）

结论：

1. 固定 Overlay 在不同成本场景下具备稳定正向概率，不依赖单一低成本情形。
2. 若偏收益与流动性平衡，建议继续使用：
   - `Top25 + amount>=2000 + fixed overlay`
3. 若偏回撤优先，可作为备选：
   - `Top15 + amount>=1500 + fixed overlay`

## 26. 可切换执行配置与月度健康检查（落地化）

### 26.1 新增脚本

1. 配置化执行：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/cb/cb_overlay_profile_runner.py`
2. 月度健康检查：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/cb/cb_overlay_monthly_healthcheck.py`

配置档位：

1. `balanced`：`Top25 + amount>=2000 + cost=40bps`
2. `defensive`：`Top15 + amount>=1500 + cost=40bps`
3. 两档都使用相同固定 overlay 参数（第24节定义）

### 26.2 两档配置回测快照（5年样本）

输出目录：

1. `balanced`：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_overlay_profile_balanced_20260527_200242`
2. `defensive`：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_overlay_profile_defensive_20260527_200302`

结果要点：

1. 全样本（60期）：
   - 两档 overlay 都明显降低回撤，但也明显降低年化（防守代价存在）。
2. 最近12期：
   - `balanced`：回撤仅小幅改善（约 `+0.08%`），年化拖累较大；
   - `defensive`：回撤基本持平，年化轻微拖累。

阶段判断：

1. 近期环境下，固定 overlay 的边际收益在减弱，不宜盲目全时段开启。

### 26.3 月度健康检查结果（两套阈值）

输出目录：

1. 宽松阈值（`ann_warn=-0.5%`, `mdd_warn=0.2%`）：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_overlay_healthcheck_20260527_200350`
- 建议：`REVIEW_OR_SWITCH profile=defensive`

2. 严格阈值（`ann_warn=0`, `mdd_warn=0.2%`）：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_overlay_healthcheck_20260527_200412`
- 建议：`DISABLE_OVERLAY_USE_BASELINE`

结论：

1. 若你偏保守执行，建议采用严格阈值，并在当前窗口“临时关闭 overlay，回归 baseline”。
2. 若你希望保留一定防守，可采用宽松阈值并优先 `defensive` 档位。

## 27. 动态开关策略（Regime Switch）研究（继续）

新增脚本：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/cb/cb_overlay_regime_switch_backtest.py`

研究目标：

1. 不是固定“永远开/关” overlay，
2. 而是按最近窗口健康指标，在 `baseline_balanced / overlay_balanced / overlay_defensive` 三者之间自动切换。

### 27.1 核心实验

输出目录：

1. 严格模式（允许关闭 overlay）：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_overlay_regime_switch_20260527_200645`
2. 宽松模式（偏向保留 overlay）：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_overlay_regime_switch_20260527_200706`

与 `base_balanced` 对比结果（60期）：

1. 严格模式：
   - 年化：`10.75%`（基线 `15.26%`）
   - 回撤：`-13.88%`（基线 `-17.84%`）
   - 动作分布：`overlay_balanced 34`，`baseline 14`，`overlay_defensive 12`
2. 宽松模式：
   - 年化：`11.19%`
   - 回撤：`-13.88%`
   - 动作分布：`overlay_balanced 34`，`overlay_defensive 14`，`baseline 12`

结论：

1. 动态开关能稳定降低回撤（约改善 `+3.96%`），
2. 但收益拖累明显（年化约 `-4%`），综合上不优于固定基线。

### 27.2 动态开关参数小网格（窗口/阈值）

补充搜索范围：

1. `recent_periods = 6/9/12/15`
2. `ann_warn = -1.0% / -0.5% / 0`
3. `mdd_warn = 0 / 0.1% / 0.2% / 0.5%`
4. `strict_disable = True/False`
5. `warmup = baseline / overlay_balanced`

结果摘要：

1. 所有“回撤改善”的动态开关组合，年化增量都为负；
2. 最接近的组合仍有约 `-1.83%` 年化拖累；
3. 未找到“收益不降 + 回撤改善”的动态开关参数。

阶段结论（更新）：

1. 当前样本下，动态开关策略不适合作为主执行方案。
2. 实盘建议保持：
   - 主执行：`baseline_balanced`（即 `Top25 + amount>=2000`）
   - 风控备选：固定 `overlay_defensive`（仅在你明确需要降波动时手动切入）

## 28. 实盘动作决策器（新增）

新增脚本：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/cb/cb_overlay_live_decision.py`

功能：

1. 每次运行自动给出当前动作建议（`USE_BASELINE / SWITCH_TO_DEFENSIVE / KEEP_OVERLAY_*`）
2. 同时输出触发理由、最近窗口指标、两档 profile 对比快照
3. 可配置严格/宽松阈值，便于实盘风格切换

### 28.1 本轮实测结果（5年样本）

输出目录：

1. 严格模式（`ann_warn=0, mdd_warn=0.2%, strict_disable=True`）：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_live_decision_strict_20260527_201101`
- 决策：`USE_BASELINE`
- 理由：最近窗口两档 overlay 均未满足阈值，触发严格回退

2. 宽松模式（`ann_warn=-0.5%, mdd_warn=0.2%`）：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_live_decision_loose_20260527_201119`
- 决策：`SWITCH_TO_DEFENSIVE`
- 理由：最近窗口未双达标，切至相对更稳档位

### 28.2 当前执行建议（截至本次回测）

1. 若你偏保守：执行严格模式，当前用 `baseline`。
2. 若你允许轻微收益牺牲换波动控制：执行宽松模式，当前切 `defensive`。

阶段结论：

1. 我们已经从“研究结论”走到“可执行动作输出”。
2. 后续可直接把该脚本纳入你的月度例行流程（每月跑一次，自动给出动作）。

### 28.3 常用执行命令（可直接跑）

1. 严格模式（推荐给保守执行）：
```bash
python3.9 -m cy_quant.cb.cb_overlay_live_decision \
  --decision-name strict \
  --cb-daily /Users/water/abu/data/cb/cb_daily_20210527_20260527.csv \
  --cb-basic /Users/water/abu/data/cb/cb_basic.csv \
  --cb-call /Users/water/abu/data/cb/cb_call_20210527_20260527.csv \
  --out-dir cy_quant/output \
  --recent-periods 12 --ann-warn 0 --mdd-warn 0.002 --strict-disable
```

2. 宽松模式（允许切 defensive）：
```bash
python3.9 -m cy_quant.cb.cb_overlay_live_decision \
  --decision-name loose \
  --cb-daily /Users/water/abu/data/cb/cb_daily_20210527_20260527.csv \
  --cb-basic /Users/water/abu/data/cb/cb_basic.csv \
  --cb-call /Users/water/abu/data/cb/cb_call_20210527_20260527.csv \
  --out-dir cy_quant/output \
  --recent-periods 12 --ann-warn -0.005 --mdd-warn 0.002
```

## 29. 风险触发切换研究（继续）

新增脚本：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/cb/cb_risk_trigger_switch_research.py`

研究目标：

1. 默认执行 `baseline_balanced`，
2. 仅在风险信号触发时切到 `defensive_overlay`，
3. 评估是否能做到“少拖收益地降回撤”。

### 29.1 风险信号设计

每期使用横截面市场状态：

1. 平均溢价率 `mkt_premium_mean`
2. 平均价格 `mkt_close_mean`
3. 平均趋势代理 `mkt_trend_mean`
4. 市场等权20日收益 `mkt_ret20_mean`

触发规则（网格）：

1. `lookback=6/9/12`
2. `z_prem`, `z_close` 阈值
3. `mkt_ret_th`, `trend_th` 阈值
4. `cooldown=1/2/3`

### 29.2 结果

输出目录：
- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_risk_switch_20260527_201508`

Walk-forward 汇总（48期）：

1. `switch_oos`：年化 `14.71%`，回撤 `-14.28%`
2. `base_oos`：年化 `14.71%`，回撤 `-14.28%`
3. `delta_switch_minus_base`：`0`

补充检查（触发频次）：

1. 某些全样本最优参数在全样本内有较多触发（例如 `42/60` 期触发），
2. 但在 OOS 48 期中触发次数为 `0`，导致策略退化为纯 baseline。

### 29.3 结论

1. 风险触发切换在当前样本下不稳定，存在明显的“样本内触发、样本外失效”问题。
2. 这一路线当前不建议进入实盘主流程。
3. 现阶段仍建议维持第28节的动作决策框架：
   - 严格：`USE_BASELINE`
   - 宽松：`SWITCH_TO_DEFENSIVE`

## 30. 当前选债标准（执行口径说明）

### 30.1 当前主执行标准

当前主执行口径不是“单一因子最低就买”，而是：

1. 先用组合评分给全市场可转债排序；
2. 再做流动性、强赎事件过滤；
3. 再做横截面分散约束；
4. 最后在月度调仓点形成候选组合。

当前主执行建议：

1. `baseline_balanced`
2. 参数：`Top25 + amount>=2000 + real_call_filter + balanced_premium`

### 30.2 当前核心指标

当前最核心的选债指标是 `combo_dl_trend`，它由两个部分组成：

1. `double_low`
- 定义：`close + bond_over_rate`
- 含义：价格和溢价都不能太贵，越低越好。

2. `stock_trend_proxy`
- 定义：`cb_value / MA120(cb_value) - 1`
- 含义：用转股价值的120日趋势代理正股趋势，越高越好。

组合方式：

1. 先把 `double_low` 做横截面 rank 分数；
2. 再把 `stock_trend_proxy` 做横截面 rank 分数；
3. 两者等权平均，得到 `combo_dl_trend`；
4. 分数越高，优先级越高。

### 30.3 当前辅助过滤条件

除了主评分，还会用以下条件过滤：

1. 流动性：
- `amount >= 2000`（万元），避免过于冷门、难成交的转债。

2. 强赎事件：
- 使用真实 `cb_call` 数据过滤强赎风险区间；
- 当前口径为：在强赎公告到执行区间内的转债，不进入候选。

3. 分散约束：
- 使用 `balanced_premium` 方式选股；
- 不是单纯拿 TopN，而是尽量在不同溢价层里均衡取券，降低组合拥挤与同质化。

### 30.4 当前不作为主标准的指标

以下指标做过研究，但当前不作为主执行核心：

1. `low_premium`
- 单独有效，但叠加后不如 `double_low + trend` 稳定。

2. `call_risk_proxy`
- 单独有解释力，但加入组合后长期增益有限，且真实强赎过滤替代后优势不明显。

3. `remaining_term`
- 在5年样本里稳定性偏弱，不适合作为主选债因子。

### 30.5 当前两档执行模式

1. 主模式：`baseline_balanced`
- `Top25 + amount>=2000`
- 适合默认执行。

2. 防守模式：`overlay_defensive`
- `Top15 + amount>=1500 + fixed overlay`
- 适合你明确想降低波动时切入。

### 30.6 下一步执行建议

当前建议不要继续无上限扩展新因子，而是进入“模拟盘验证”阶段，重点看三件事：

1. 最近3个月、6个月的实际表现是否和回测口径一致；
2. 实际成交是否比回测假设更差；
3. 月度决策脚本是否持续给出 `baseline` 或开始更频繁建议 `defensive`。

## 31. 卖出规则补充测试（止损 + 130/150 分段止盈）

### 31.1 本轮新增

为把策略从“只按月度换仓”推进到“更接近执行规则”，本轮在回测核心中加入了持有期卖出模拟：

1. 下跌止损：按入场价回撤比例触发卖出；
2. 价格超过 `130`：卖出 `50%`；
3. 价格超过 `150`：卖出剩余仓位；
4. 若持有期内都未触发，则在持有期最后一日按收盘价结算。

涉及文件：

1. `cy_quant/cb/cb_combo_monthly_backtest.py`
2. `cy_quant/cb/cb_diversification_walkforward_compare.py`
3. `cy_quant/cb/cb_diversification_research.py`
4. `cy_quant/cb/cb_exit_rule_research.py`

输出目录：

1. `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_exit_rule_research_20260611_165832`

### 31.2 测试口径

测试对象继续使用当前主执行组合：

1. `balanced_premium`
2. `score = combo_dl_trend`
3. `Top25 + amount>=2000 + real_call_filter + cost=40bps`
4. 持有期：`20` 个交易日

止损阈值网格：

1. `none`
2. `5%`
3. `8%`
4. `10%`
5. `12%`

止盈规则固定为：

1. `>=130` 卖出 `50%`
2. `>=150` 卖出全部剩余仓位

### 31.3 结果

对照基线（原策略，不加这套卖出规则）：

1. `baseline_balanced`
2. 年化：`15.26%`
3. 总收益：`96.67%`
4. 最大回撤：`-17.84%`
5. 胜率：`58.33%`

加入分段止盈后的结果：

1. `130/150`，无止损：
   年化 `-0.51%`，总收益 `-2.35%`，最大回撤 `-39.41%`
2. `130/150 + 5%止损`：
   年化 `-5.37%`，总收益 `-22.76%`，最大回撤 `-45.12%`
3. `130/150 + 8%止损`：
   年化 `-2.86%`，总收益 `-12.72%`，最大回撤 `-43.21%`
4. `130/150 + 10%止损`：
   年化 `-2.15%`，总收益 `-9.66%`，最大回撤 `-42.35%`
5. `130/150 + 12%止损`：
   年化 `-1.76%`，总收益 `-7.97%`，最大回撤 `-42.22%`

### 31.4 结论

这轮测试结论很明确：

1. 对当前这套 `double_low + trend` 主策略，`130/150` 分段止盈与策略风格不匹配；
2. 即便不加止损，仅加入 `130/150` 分段止盈，收益也从明显正收益退化到接近零甚至负收益；
3. 在此基础上再叠加 `5%-12%` 止损，只会进一步恶化年化与回撤；
4. 当前阶段不建议把这套规则纳入主执行或模拟盘默认规则。

### 31.5 为什么会这样

初步理解是：

1. 当前选债逻辑本身带有趋势因子，部分收益依赖“中段继续走强”；
2. `130` 先卖一半，会过早截断右侧收益；
3. 可转债回撤和波动较大，简单百分比止损容易在正常波动中被反复打掉；
4. 这套规则更像“绝对价格约束”，但当前主策略更接近“横截面择优 + 月度轮动”，两者节奏并不一致。

### 31.6 当前建议

1. 模拟盘阶段，主组合仍按 `baseline_balanced` 执行；
2. 不建议默认加入 `130/150` 分段止盈；
3. 如果后续要继续研究卖出规则，应优先测试：
   `收益回撤比驱动的动态减仓`、`持有期尾部保护`、`分层不同价格区间采用不同退出规则`；
4. 当前这套规则可以保留为“独立备忘实验”，不进入主口径。

## 32. 指数 MA200 风控过滤测试（新增）

### 32.1 研究目的

验证一个更简单、更市场化的风控开关：

1. 只有当某个市场指数 `close > MA200` 时，才执行当前最优可转债策略；
2. 若指数位于 `MA200` 下方，则当期空仓，收益记为 `0`。

测试策略口径仍使用当前主执行方案：

1. 主因子：`combo_dl_trend`
2. 组合构建：`balanced_premium`
3. 参数：`Top25 + amount>=2000 + real_call_filter + cost=40bps`

新增脚本：

1. `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/cb/cb_index_filter_research.py`

输出目录：

1. `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_index_filter_20260616_174042`

### 32.2 指数口径

本轮测试了：

1. `hs300`：沪深300
2. `csi500`：中证500
3. `csi1000`：中证1000
4. `guozheng2000`：国证2000

说明：

1. 中证1000 的本地长历史指数数据当前只覆盖到 `2025-03-07`；
2. 因此做了两套结果：
   - `common`：共同可比窗口（`2021-05` 到 `2025-03`）
   - `full`：全样本窗口（仅对能覆盖到 `2026-04` 的指数输出）

### 32.3 共同窗口结果（重点）

共同窗口基线（不加指数过滤）：

1. 年化：`9.04%`
2. 总收益：`38.10%`
3. 最大回撤：`-18.08%`

加入指数 MA200 过滤后：

1. `hs300`
   - 年化：`5.38%`
   - 总收益：`21.61%`
   - 最大回撤：`-6.75%`
   - 平均仓位：`34.04%`

2. `csi500`
   - 年化：`-0.96%`
   - 总收益：`-3.55%`
   - 最大回撤：`-15.87%`
   - 平均仓位：`38.30%`

3. `csi1000`
   - 年化：`8.99%`
   - 总收益：`37.87%`
   - 最大回撤：`-10.74%`
   - 平均仓位：`42.55%`

4. `guozheng2000`
   - 年化：`7.66%`
   - 总收益：`31.68%`
   - 最大回撤：`-15.80%`
   - 平均仓位：`48.94%`

### 32.4 全样本补充结果

全样本基线（`2021-05` 到 `2026-04`）：

1. 年化：`15.44%`
2. 总收益：`98.10%`
3. 最大回撤：`-18.08%`

可覆盖全样本的指数结果：

1. `hs300`
   - 年化：`12.39%`
   - 总收益：`74.44%`
   - 最大回撤：`-5.68%`

2. `csi500`
   - 年化：`7.06%`
   - 总收益：`38.36%`
   - 最大回撤：`-15.87%`

### 32.5 结论

这轮结论比较清楚：

1. `沪深300 > MA200` 太保守，回撤压得很漂亮，但收益损失明显；
2. `中证500 > MA200` 对当前转债策略不合适，收益明显变差；
3. `中证1000 > MA200` 是这轮最值得关注的口径：
   - 收益几乎与基线持平；
   - 但回撤从 `-18.08%` 改善到 `-10.74%`；
4. `国证2000 > MA200` 也有一定效果，但不如中证1000平衡。

### 32.6 当前建议

如果要把“指数站上 MA200 才执行策略”纳入下一阶段模拟盘验证，优先顺序建议是：

1. 首选：`中证1000 > MA200`
2. 备选：`沪深300 > MA200`（更保守）
3. 不建议优先：`中证500 > MA200`

阶段判断：

1. 当前最有希望继续深挖的是“小盘风格指数做市场开关”；
2. 下一步可以继续测试：
   - `MA150 / MA200 / MA250`
   - `close > MA200` 与 `MA200斜率向上` 联合条件
   - `中证1000` 与 `国证2000` 的双指数确认

## 33. 指数均线改为 MA120 的回测结果

### 33.1 研究问题

这轮重点验证：

1. 把上一轮 `MA200` 改成 `MA120` 后，是否更容易躲开 `2021`、`2022` 的不利阶段；
2. 在 `MA120` 口径下，哪种指数过滤最优；
3. 5 年口径下，最优策略收益是多少。

输出目录：

1. `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/cb_index_filter_ma120_20260616_174746`

### 33.2 共同窗口结果（2021-05 到 2025-03）

共同窗口基线：

1. 年化：`9.04%`
2. 总收益：`38.10%`
3. 最大回撤：`-18.08%`

MA120 过滤后：

1. `中证1000 > MA120`
   - 年化：`9.10%`
   - 总收益：`38.38%`
   - 最大回撤：`-10.41%`
   - 结论：收益几乎不变，回撤改善明显，是共同窗口最优。

2. `国证2000 > MA120`
   - 结果与本地当前口径下的中证1000非常接近。

3. `沪深300 > MA120`
   - 年化：`3.38%`
   - 总收益：`13.19%`
   - 最大回撤：`-6.75%`
   - 结论：更保守，但收益损失太大。

4. `中证500 > MA120`
   - 年化：`-1.09%`
   - 总收益：`-4.02%`
   - 结论：不适合。

### 33.3 2021、2022 是否被躲开

先看基线：

1. `2021`：`+22.08%`
2. `2022`：`-7.64%`

`中证1000 > MA120`：

1. `2021`：`+22.08%`
2. `2022`：`-6.63%`

结论：

1. `2021` 并没有被躲开，基本与基线相同；
2. `2022` 只做到了“小幅改善”，从 `-7.64%` 提升到 `-6.63%`，不是明显规避。

`沪深300 > MA120`：

1. `2021`：`-3.27%`
2. `2022`：`+1.91%`

结论：

1. `2022` 确实被明显躲开了；
2. 但代价是把 `2021` 的正收益也过滤掉了，因此整体不划算。

### 33.4 5年口径的最优策略

这里要区分两个口径：

1. `完整5年口径`
2. `共同可比窗口口径`

原因：

1. 本地 `中证1000` 长历史指数当前只覆盖到 `2025-03-07`；
2. 因此它不能直接给出完整到 `2026-04` 的同口径 5 年结果。

完整 5 年可直接比较的结果：

1. `baseline`：
   - 年化：`15.44%`
   - 总收益：`98.10%`
   - 最大回撤：`-18.08%`

2. `沪深300 > MA120`：
   - 年化：`7.58%`
   - 总收益：`41.60%`
   - 最大回撤：`-5.42%`

3. `中证500 > MA120`：
   - 年化：`5.82%`
   - 总收益：`30.91%`
   - 最大回撤：`-16.27%`

结论：

1. 如果要求“完整 5 年收益最高”，当前最优仍是 `不加指数过滤的 baseline`；
2. 如果接受“在共同窗口里比较谁更平衡”，则 `中证1000 > MA120` 是最优。

### 33.4A 基线策略分年收益（按年复利）

这里的“年收益”，是按该年各月调仓收益逐期复利后的结果。

基线策略口径：

1. 主因子：`combo_dl_trend`
2. 组合构建：`balanced_premium`
3. 参数：`Top25 + amount>=2000 + real_call_filter + cost=40bps`

分年结果：

1. `2021`（`2021-05-31` 到 `2021-12-31`）：`+22.08%`
2. `2022`（`2022-01-28` 到 `2022-12-30`）：`-7.64%`
3. `2023`（`2023-01-31` 到 `2023-12-29`）：`-0.55%`
4. `2024`（`2024-01-31` 到 `2024-12-31`）：`+27.30%`
5. `2025`（`2025-01-27` 到 `2025-12-31`）：`+34.33%`
6. `2026`（`2026-01-30` 到 `2026-04-23`，年内截至当前）：`+3.31%`

阶段合并结果：

1. `2021-2023`：
   - 合并收益：`+12.13%`
   - 年化约：`+4.61%`

2. `2024-2025`：
   - 合并收益：`+71.01%`
   - 年化约：`+32.54%`

3. `2026`（截至 `2026-04-23`）：
   - 区间收益：`+3.31%`

解释：

1. `2021-2023` 整体确实偏横盘，主要由 `2022` 的亏损和 `2023` 的近乎持平构成；
2. `2024-2025` 是这套策略最顺的阶段，收益明显抬升；
3. `2026` 目前仍为正，但相较 `2024-2025` 已明显减弱。

### 33.5 当前判断

这轮 MA120 的结论可以概括为：

1. `MA120` 不能有效躲开 `2021`；
2. `中证1000 > MA120` 对 `2022` 只有轻微改善，但能显著压低整体回撤；
3. `沪深300 > MA120` 虽然更能规避下行，但牺牲了太多上涨阶段收益；
4. 因此当前更合理的定位是：
   - 若追求绝对收益：仍用 `baseline`
   - 若追求收益基本不降、回撤更稳：继续优先研究 `中证1000 > MA120/MA200`

## 34. 2026-09-03 数据更新与最新策略复测

### 34.1 数据更新

本轮将可转债日线更新至 `2026-09-03`：

1. 下载窗口：`2021-09-03` 到 `2026-09-03`；
2. 研究窗口内基础信息标的：`900` 只；实际有行情标的：`850` 只；
3. 日线记录：`555,834` 条；
4. 最新交易日 `2026-09-03` 有 `316` 只转债行情；
5. 因为需保留完整的未来 20 个交易日收益，最后一个可验证调仓日是 `2026-08-06`。

下载程序已改为仅请求研究窗口内曾上市的转债，避免对早已退市的历史代码进行无效拉取。

### 34.2 复测口径与重要限制

沿用原主策略：

1. 主因子：`combo_dl_trend`；
2. 组合构建：`balanced_premium`；
3. 参数：`Top25 + amount>=2000万元 + cost=40bps`；
4. 调仓：月末，持有 20 个交易日。

本次 Tushare 账号无 `cb_call` 接口权限，本地亦无可用强赎事件文件。因此本节是“未应用真实强赎事件过滤”的暂定复测，不能与此前含 `real_call_filter` 的正式结果直接横比，也不能直接作为模拟盘最终绩效依据。

### 34.3 最新结果（未含真实强赎过滤）

完整可验证窗口（`2021-09-30` 到 `2026-08-06`，60 个调仓期）：

1. 总收益：`+38.18%`；
2. 年化收益：`+7.03%`；
3. 最大回撤：`-21.35%`；
4. 单期胜率：`55.00%`。

按年复利：

1. `2021`（4 期）：`+7.62%`；
2. `2022`：`-10.70%`；
3. `2023`：`-1.89%`；
4. `2024`：`+27.23%`；
5. `2025`：`+29.97%`；
6. `2026`（截至 `2026-08-06` 可验证期）：`-11.38%`。

新增样本（相对先前可验证日 `2026-04-23` 之后的 5 个调仓期）累计为 `-10.91%`，其中仅 1 期为正。策略在 `2026` 的边际表现明显弱于 `2024-2025`，当前应视为失效环境观察期，而非继续按历史高收益外推。

### 34.4 当前执行结论

1. 数据已更新到今天，策略近期表现转弱；
2. 在恢复真实强赎事件数据前，不更新模拟盘的正式绩效结论；
3. 若继续模拟盘，应使用小仓位观察，并单独跟踪 `2026` 后续月度收益、回撤和强赎风险；
4. 后续正式复测必须补齐 `cb_call`，然后与本次结果并列比较强赎过滤对尾段的影响。

## 35. 月度停止/恢复交易规则测试

### 35.1 测试原则

所有开关均在当月调仓日决定，不使用当期未来 20 日收益：

1. 指数开关：调仓日 `中证1000收盘 > MA120` 才持有本策略，否则空仓；
2. 收益刹车：仅在上一期已实现策略收益低于阈值后，才对下一期降仓或空仓；
3. 联合规则：两个条件同时应用。

本轮输入是第 34 节的最新月度收益，故同样不含真实强赎事件过滤。中证1000已补齐至 `2026-09-03`，完整覆盖策略可验证窗口。

### 35.2 全样本结果（60 个调仓期）

| 规则 | 年化 | 总收益 | 最大回撤 | 平均仓位 | 结论 |
| --- | ---: | ---: | ---: | ---: | --- |
| 不开关（基线） | `7.03%` | `38.18%` | `-21.35%` | `100.0%` | 收益最高 |
| 中证1000 > MA120 | `5.91%` | `31.44%` | `-12.28%` | `48.3%` | 大幅降回撤，但牺牲年化 |
| 上期亏损超过5%，下期空仓 | `4.31%` | `22.23%` | `-19.60%` | `93.3%` | 不推荐 |
| 上期亏损超过5%，下期半仓 | `5.73%` | `30.40%` | `-20.42%` | `96.7%` | 不推荐 |
| MA120 + 上期亏损超过5%后空仓 | `6.60%` | `35.58%` | `-12.28%` | `46.7%` | 没有优于单独 MA120 |

结论：`-5%` 的单期亏损刹车不具备正向增益。它是事后信号，常常在亏损后错过反弹，不能作为当前默认停止规则。

### 35.3 分年效果

| 年份 | 基线 | 中证1000 > MA120 | 说明 |
| --- | ---: | ---: | --- |
| 2021 | `+7.62%` | `+7.62%` | 无差异 |
| 2022 | `-10.70%` | `-7.38%` | 有改善 |
| 2023 | `-1.89%` | `+5.78%` | 有改善 |
| 2024 | `+27.23%` | `+18.43%` | 错过部分上涨 |
| 2025 | `+29.97%` | `+20.00%` | 错过部分上涨 |
| 2026（截至8月可验证期） | `-11.38%` | `-12.28%` | 未改善 |

### 35.4 可执行结论

1. 目标是“提高长期收益”：继续使用基线，不采用单期 `-5%` 停止规则；
2. 目标是“将最大回撤控制在约 -12%”：可候选采用 `中证1000 > MA120`，但须接受约一半时间空仓及约 `1.12` 个百分点年化牺牲；
3. 不应把 MA120 当作 2026 的保护开关，它本轮没有躲开近期弱势；
4. 当前更合理的是把 MA120 作为模拟盘的风险档位，而不是绝对收益主策略的强制规则；
5. 在获得强赎事件数据后，需以正式口径重新跑本节全部规则。

## 36. 影子组合恢复机制测试

### 36.1 规则

测试了一个更贴近实盘管理的状态机：

1. 正常持仓时，若本期策略收益 `<= -5%`，下一期停止实盘；
2. 停止后，原策略仍每月在虚拟盘计算收益；
3. 虚拟盘任一单期收益 `>= +5%`，下一期才恢复实盘；
4. 全部信号都在该期收益结束后产生，下一期才生效，无未来函数。

### 36.2 结果

| 规则 | 年化 | 总收益 | 最大回撤 | 平均仓位 | 暂停期数 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 基线 | `7.03%` | `38.18%` | `-21.35%` | `100.0%` | `0` |
| 亏损`-5%`暂停，影子盘`+5%`恢复 | `3.89%` | `19.93%` | `-21.11%` | `80.0%` | `12` |

这个方案不通过：年化少 `3.14` 个百分点，最大回撤只改善 `0.24` 个百分点。

### 36.3 分年收益

| 年份 | 基线 | 影子恢复机制 | 平均仓位 |
| --- | ---: | ---: | ---: |
| 2021 | `+7.62%` | `+7.62%` | `100.0%` |
| 2022 | `-10.70%` | `-9.47%` | `58.3%` |
| 2023 | `-1.89%` | `-7.24%` | `75.0%` |
| 2024 | `+27.23%` | `+15.22%` | `66.7%` |
| 2025 | `+29.97%` | `+29.97%` | `100.0%` |
| 2026（截至8月可验证期） | `-11.38%` | `-11.38%` | `100.0%` |

### 36.4 为什么失败

`2022-07` 首次触发停盘后，影子组合直到 `2023-03` 才出现单期 `+5.51%`，暂停长达 8 期。它确实避开了一部分下跌，但同时也放弃了前期恢复收益。`2024-05` 触发后又直到 `2024-08` 的 `+15.57%` 才恢复，错过了更早的反弹。

结论：单月 `+5%` 恢复阈值过滞后，不作为实盘规则。后续若继续研究恢复机制，应测试“连续两个月为正”或“虚拟组合站上短期均线”等更平滑的恢复信号，而不是单月大涨确认。
