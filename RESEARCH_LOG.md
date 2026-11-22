# Research Log

## 2026-06-18 接力整理

### 本次任务

读取当前量化进化系统资料，理解当前正在做什么、下一步应做什么，并建立顶层研究接力文件：

- `PROJECT_STATE.md`
- `RESEARCH_LOG.md`
- `TODO.md`

本次只做研究状态整理，不改策略代码，不跑新实验。

### 已确认的研究方向

继续研究低频量化策略，不做高频。

当前主线不是分钟线、高频撮合或盘口策略，而是基于日 K 线的低频事件研究：

```text
A 股 120MA 回踩不破短线策略
```

该策略持有周期以 3-10 个交易日为主，核心研究对象是：

- 日线事件。
- 市场宽度过滤。
- 次日开盘等更可执行的入场方式。
- 收盘价确认的移动止盈。
- 账户层面组合与风控。

### 当前最重要结论

`T005_pullback_ma120_hold` 是当前最值得推进的主线候选。

它的优势不是来自直接追涨，而是来自：

- 已经站上 120MA。
- 回踩 120MA 附近不破。
- 市场环境不弱。
- 出现短线冲高后及时保护利润。

最关键市场过滤为：

```text
A 股 close > MA120 的股票比例 >= 50%
且 当日上涨股票比例 >= 50%
```

更保守可执行版本：

```text
次日开盘买入
+ 盈利 5% 后按收盘价移动止盈
+ 收盘价较最高收盘价回撤 2% 退出
+ 最多持有 10 日
```

该版本成本后收益中位数 `1.37%`，胜率 `58.23%`。

### 为什么还不能升级 Alpha

当前不能把 T005 升级为正式 Alpha。

主要原因：

- 账户层面还没通过。
- 当前最好账户组合 CAGR 只有 `3.20%`，最大回撤 `-24.79%`。
- 信号排序不够强。
- 尚未完成逐日盯市账户回测。
- 尚未加入涨跌停不可成交过滤。
- 尚未完成足够的滑点和成本压力测试。
- 尚未做严格样本外/滚动验证。

### 当前研究判断

下一步不要马上扩展更多入场事件。

当前主线应该回到：

```text
先解决买哪些股票。
```

优先研究非未来函数排序因子，例如：

- 距离 MA120 更近。
- 缩量更明显。
- MA120 斜率更好。
- 行业强度更高。
- 市场宽度更强。
- 近期回撤更浅。
- 避免巨量和过度偏离 MA120。

### 已沉淀失败经验

本次读取到的失败边界应继续遵守：

- 不要单独使用放量突破。
- 不要把 `1ATR` 作为默认日线短线止损。
- 不要单独使用 MA60 宽度过滤。
- 不要把简单跌破 MA120 或信号日低点作为 T005 默认退出。
- 不要凭单笔事件统计直接进入实盘观察。
- 不要推进朴素 T+1 亏损即卖规则。

### 低频月度策略旁线

`质量价值 + 动量 + 12 月均线风控` 是另一条低频月度策略线。

当前状态：

- 第一轮未达标。
- 第二轮强风控后接近目标，但保守成本年化 `14.00%`，尚未达到 15%。
- 零成本下达到 `15.42%`，说明换手和交易成本是关键瓶颈。

下一步若回到这条线，应优先：

- 降低换手。
- 提高牛市资金利用率。
- 做 2021-2023 调参、2024-2025 验证。
- 输出真实月度持仓并检查行业集中。

### 接力建议

下一次开始研究时，应先打开：

```text
PROJECT_STATE.md
RESEARCH_LOG.md
TODO.md
docs/quant_evolution/plans/2026-06-18-a-share-short-strategy-next-plan.md
docs/quant_evolution/alpha_candidates/QE-ALPHA-CANDIDATE-A-SHORT-001.md
```

然后只围绕 TODO 中的第一优先级推进，不要直接改入场事件，也不要开启高频方向。

## 2026-07-05 A 股 MA120 月末排序第四轮止损结构验证

### 本次任务

在当前最佳排序线基础上，继续验证：

```text
更宽止损、分级止损、保留半仓趋势核心，
能不能改善当前样本外表现。
```

### 实验输出

脚本：

```text
cy_quant/ma120_monthly_stop_structure_followup.py
```

输出目录：

```text
cy_quant/output/ma120_monthly_stop_structure_20260705_235530
```

研究文档：

```text
docs/quant_evolution/experiments/QE-A-MA120-MONTHLY-RANK-004.md
docs/quant_evolution/research_logs/2026-07-05-a-ma120-monthly-rank-004.md
```

### 核心结果

- `stop10_full`：总收益 `18.93%`，最大回撤 `-8.12%`，Sharpe `1.77`
- `stop12_full`：总收益 `13.55%`，最大回撤 `-12.44%`，Sharpe `1.21`
- `stop15_full`：总收益 `8.74%`，最大回撤 `-14.66%`，Sharpe `0.78`
- `stop10_15_half`：总收益 `13.80%`，最大回撤 `-11.20%`，Sharpe `1.25`
- `stop10_20_half`：总收益 `11.09%`，最大回撤 `-12.68%`，Sharpe `1.02`

### 当前结论

这轮明确说明：

```text
当前问题不是 10% 止损太紧。
```

不论是放宽到 `12% / 15%`，还是保留半仓趋势核心，
结果都比原始 `10%` 单一硬止损更差。

因此这条线下一步更应转向：

- 去极值依赖验证
- 去月份依赖验证
- 重新判断真正的瓶颈是在排序还是退出

## 2026-07-06 A 股 MA120 月末排序第五轮集中度压力测试

### 本次任务

验证当前最佳线是否过度依赖少数赢家和少数关键月份。

### 实验输出

脚本：

```text
cy_quant/ma120_monthly_concentration_stress.py
```

输出目录：

```text
cy_quant/output/ma120_monthly_concentration_stress_20260706_000044
```

研究文档：

```text
docs/quant_evolution/experiments/QE-A-MA120-MONTHLY-RANK-005.md
docs/quant_evolution/research_logs/2026-07-06-a-ma120-monthly-rank-005.md
```

### 核心结果

- 基线：总收益 `18.93%`，Sharpe `1.77`
- 去掉 `sz300868`：总收益 `5.89%`，Sharpe `0.70`
- 去掉 `sz300868 + sz301373`：总收益 `-3.49%`，Sharpe `-0.34`
- 去掉前三大赢家：总收益 `-9.47%`，Sharpe `-1.29`
- 去掉 `2026-03` 入选批次：总收益 `11.30%`，Sharpe `1.47`

### 当前结论

这轮已经基本坐实：

```text
当前样本外结果对少数超级赢家依赖非常强。
```

因此这条线当前更像：

- 高选择性观察型候选
- 少数强趋势大赢家驱动
- 还不能升级为正式 Alpha

## 2026-07-06 A 股 MA120 月末排序第六轮超级赢家画像反推

### 本次任务

反推 `sz300868 / sz301373 / sz301396` 这几只超级赢家在入选时的共同特征。

### 实验输出

脚本：

```text
cy_quant/ma120_monthly_winner_profile.py
```

输出目录：

```text
cy_quant/output/ma120_monthly_winner_profile_20260706_000727
```

研究文档：

```text
docs/quant_evolution/experiments/QE-A-MA120-MONTHLY-RANK-006.md
docs/quant_evolution/research_logs/2026-07-06-a-ma120-monthly-rank-006.md
```

### 核心结果

- 超级赢家的 `price_vs_ma120` 更低，说明没有过度远离 MA120。
- `ret20 / ret60 / up_ratio20 / up_down_diff20` 更低，说明不是最拥挤、最火热的一档。
- `volume_ratio20 / volume_ratio5_20` 更低，说明量能更收敛。
- `dist_to_high60 / drawdown20` 更低，说明经历过更明显整理，不是紧贴新高。
- `bull_ma_stack = 1` 且 `above_days` 仍在 `50+`，说明大趋势结构依然完整。

### 当前结论

这条线当前更像：

```text
强趋势中的二次启动狙击
```

而不是：

```text
MA120 上方普适强度排序
```

## 2026-07-06 A 股 MA120 月末排序第七轮窄筛选验证

### 本次任务

把“非拥挤强趋势回撤型”做成一版可执行过滤，
并与当前五因子基线正面对比。

### 实验输出

脚本：

```text
cy_quant/ma120_monthly_trend_sniper_validation.py
```

输出目录：

```text
cy_quant/output/ma120_monthly_trend_sniper_20260706_001333
```

研究文档：

```text
docs/quant_evolution/experiments/QE-A-MA120-MONTHLY-RANK-007.md
docs/quant_evolution/research_logs/2026-07-06-a-ma120-monthly-rank-007.md
```

### 核心结果

- `moderate_non_crowded`：总收益 `22.49%`，Sharpe `2.23`，最大回撤 `-9.37%`
- 基线：总收益 `18.93%`，Sharpe `1.77`，最大回撤 `-8.12%`
- `tight_non_crowded` 和 `pullback_sniper` 都明显弱于基线

### 当前结论

这轮说明：

```text
适度的“非拥挤强趋势回撤型”过滤是有效方向，
但不能收得过窄。
```

它更像是在减少对极端黑马的依赖，
换取更均匀的中等收益票。

## 2026-07-06 A 股 MA120 月末排序第八轮 moderate_non_crowded 精修

### 本次任务

只围绕 `moderate_non_crowded` 推进，比较：

- `Top8 / Top10 / Top12`
- 对头部赢家和关键月份的依赖度

### 实验输出

脚本：

```text
cy_quant/ma120_monthly_moderate_followup.py
```

输出目录：

```text
cy_quant/output/ma120_monthly_moderate_followup_20260706_002143
```

研究文档：

```text
docs/quant_evolution/experiments/QE-A-MA120-MONTHLY-RANK-008.md
docs/quant_evolution/research_logs/2026-07-06-a-ma120-monthly-rank-008.md
```

### 核心结果

- `Top8`：总收益 `36.03%`，Sharpe `2.91`，最大回撤 `-8.20%`
- `Top10`：总收益 `22.49%`，Sharpe `2.23`
- `Top12`：总收益 `18.33%`，Sharpe `1.96`

依赖度方面：

- 去掉前两大贡献者后，`Top10` 仍有 `17.34%` 总收益
- 去掉前三大贡献者后，仍有 `16.35%`
- 去掉 `2026-03` 入选批次后，总收益只剩 `1.16%`

### 当前结论

这轮说明：

```text
moderate_non_crowded 确实降低了头部赢家依赖，
但还没有解决关键月份依赖。
```

当前新主口径可暂定为：

```text
moderate_non_crowded + Top8
```

## 2026-07-06 A 股 MA120 月末排序第九轮持仓与月份结构拆解

### 本次任务

拆解 `moderate_non_crowded + Top8` 的持仓和月份结构，
理解为何它对 `2026-03` 路径依赖较强。

### 实验输出

脚本：

```text
cy_quant/ma120_monthly_top8_decomposition.py
```

输出目录：

```text
cy_quant/output/ma120_monthly_top8_decomp_20260706_002421
```

研究文档：

```text
docs/quant_evolution/experiments/QE-A-MA120-MONTHLY-RANK-009.md
docs/quant_evolution/research_logs/2026-07-06-a-ma120-monthly-rank-009.md
```

### 核心结果

- `2026-02` 入场批次最干净：5 盈利、0 止损、总贡献 `+5.81%`
- `2026-03` 是混合轮次：2 盈利、5 止损、总贡献 `-3.32%`
- `2026-04` 是整批失败：5 笔全止损、总贡献 `-6.25%`

### 当前结论

这轮说明：

```text
当前真正需要研究的，
更像是轮次级过滤，
而不只是个股排序。
```

## 2026-07-06 A 股 MA120 月末排序第十轮轮次级过滤对比

### 本次任务

比较 `2026-01 / 2026-02 / 2026-03` 三个评估轮次，
寻找整轮该做还是该缩的线索。

### 实验输出

脚本：

```text
cy_quant/ma120_monthly_round_filter_compare.py
```

输出目录：

```text
cy_quant/output/ma120_monthly_round_filter_compare_20260706_002756
```

研究文档：

```text
docs/quant_evolution/experiments/QE-A-MA120-MONTHLY-RANK-010.md
docs/quant_evolution/research_logs/2026-07-06-a-ma120-monthly-rank-010.md
```

### 核心结果

- `2026-02` 评估轮次对应的 moderate 通过率只有 `4.43%`，而且前瞻正收益率很差，最终 Top8 也偏弱
- `2026-01` 评估轮次最健康，对应的 `2026-02` 建仓轮次表现最好
- `2026-03` 评估轮次候选池前瞻统计不差，但最终 `2026-04` 建仓轮次仍然整批失败

### 当前结论

这轮让我更明确地把下一步方向定在：

```text
先做第一版轮次级过滤，
尤其是检查 moderate 通过率过低时是否应整轮跳过
```

## 2026-07-06 A 股 MA120 月末排序第十一轮朴素轮次跳过验证

### 本次任务

验证第一版最朴素的轮次级过滤：

```text
moderate 通过率过低时整轮跳过
```

### 实验输出

脚本：

```text
cy_quant/ma120_monthly_round_skip_validation.py
```

输出目录：

```text
cy_quant/output/ma120_monthly_round_skip_20260706_003205
```

研究文档：

```text
docs/quant_evolution/experiments/QE-A-MA120-MONTHLY-RANK-011.md
docs/quant_evolution/research_logs/2026-07-06-a-ma120-monthly-rank-011.md
```

### 核心结果

- 基线：总收益 `36.03%`，Sharpe `2.91`，最大回撤 `-8.20%`
- 跳过 `2026-02` 评估轮次后：总收益 `29.76%`，Sharpe `2.53`，最大回撤 `-12.37%`

### 当前结论

这轮说明：

```text
“通过率过低就整轮跳过”太粗，
当前是负改进。
```

同时确认了另一个重要点：

```text
后续这条旁线应统一到含 mark-to-end 的账户口径
```

补充核对后进一步确认：

```text
这次负改进并不只是“跳过了弱轮次”，
还因为含 mark-to-end 的基线里，
2026-04 建仓轮次其实有 3 只样本末端大赢家。
```

所以当前更合理的研究方向是：

- 联合轮次过滤
- 整轮降仓
- 统一 mark-to-end 口径

## 2026-07-06 A 股 MA120 月末排序第十二轮弱轮次降仓验证

### 本次任务

把“整轮跳过”改成更温和的轮次级风控：

```text
弱轮次降仓
```

### 实验输出

脚本：

```text
cy_quant/ma120_monthly_round_scale_validation.py
```

输出目录：

```text
cy_quant/output/ma120_monthly_round_scale_20260706_085448
```

研究文档：

```text
docs/quant_evolution/experiments/QE-A-MA120-MONTHLY-RANK-012.md
docs/quant_evolution/research_logs/2026-07-06-a-ma120-monthly-rank-012.md
```

### 核心结果

- 基线：总收益 `36.03%`，Sharpe `2.91`，最大回撤 `-8.20%`
- 弱轮次 `75%` 仓位：总收益 `37.40%`，Sharpe `3.17`
- 弱轮次 `50%` 仓位：总收益 `38.72%`，Sharpe `3.41`
- 弱轮次 `25%` 仓位：总收益 `39.99%`，Sharpe `3.61`，最大回撤 `-5.60%`

### 当前结论

这轮第一次给出了一个比较像样的组合层改进：

```text
弱轮次降仓
```

它明显优于：

```text
整轮跳过
```

## 2026-06-18 QQQ/TQQQ Dual Thrust 20 测试

### 本次任务

使用本地 `csv_his` 数据测试 Dual Thrust 20 日策略：

- QQQ：`/Users/water/abu/csv_his/usQQQ_20110808_20170808`
- TQQQ：`/Users/water/abu/csv_his/usTQQQ_20110808_20170808`

本轮仍属于低频日线研究，不做高频。

### 实验输出

脚本：

```text
cy_quant/dual_thrust_qqq_tqqq_backtest.py
```

报告：

```text
docs/reports/dual_thrust_qqq_tqqq_20260618.md
```

输出目录：

```text
cy_quant/output/dual_thrust_qqq_tqqq_20260618_225655
cy_quant/output/dual_thrust_qqq_tqqq_20260618_225708
```

### 核心结果

10 bps 成本下：

- QQQ 买入持有：总收益 `208.05%`，CAGR `20.92%`，最大回撤 `-16.38%`。
- TQQQ 买入持有：总收益 `1339.77%`，CAGR `56.89%`，最大回撤 `-44.54%`。
- 最好 Dual Thrust：`QQQ signal -> TQQQ, K=0.2/0.2`，总收益 `394.50%`，CAGR `30.98%`，最大回撤 `-45.79%`。

20 bps 成本下：

- 最好 Dual Thrust：`QQQ signal -> TQQQ, K=0.2/0.2`，总收益 `295.92%`，CAGR `26.16%`，最大回撤 `-46.33%`。

### 当前结论

第一轮不建议把 Dual Thrust 20 作为 TQQQ 主策略升级。

原因：

- 没有跑赢 TQQQ 买入持有。
- 回撤没有明显改善。
- 低 K 参数对交易成本敏感。
- 高 K 参数交易过少、收益不足。
- 多数组合单笔收益中位数为负，依赖少数大盈利交易。

### 下一步

如果继续研究，应测试：

```text
QQQ close > MA200 作为总开关
```

或者改成：

```text
QQQ 核心仓 + TQQQ Dual Thrust 卫星仓 + QQQ MA200 风控
```

若加入趋势过滤后仍不能同时改善收益和回撤，则该路线应进入失败观察。

## 2026-06-19 QQQ/TQQQ MA120 分层买入测试

### 本次任务

验证一个新想法：

```text
QQQ 和 TQQQ 各一半的组合框架下，
让 TQQQ 只在自己明显跌到 MA120 下方时分批买入，
回到 MA120 上方后用 10% 移动止盈卖半。
```

### 本轮采用的可执行假设

为了让资金路径自洽，本轮采用：

```text
50% 资金直接持有 QQQ；
另 50% 资金作为 TQQQ 战术仓，起始持有现金；
低于 MA120 20% / 30% / 40% 时，分别买入战术仓 20% / 30% / 40%；
回到 MA120 上方后，收盘价较最高收盘价回撤 10% 时卖出当前 TQQQ 持仓 50%。
```

### 核心结果

10 bps 下：

- 策略总收益 `115.30%`
- CAGR `14.87%`
- 最大回撤 `-13.80%`
- 平均 TQQQ 暴露约 `5.5%`

对照：

- `QQQ buy & hold` CAGR `19.34%`，最大回撤 `-16.38%`
- `QQQ 50% + TQQQ 50% buy & hold` CAGR `40.53%`，最大回撤 `-37.03%`
- `TQQQ buy & hold` CAGR `52.91%`，最大回撤 `-44.54%`

### 当前结论

这条线确实把回撤压下来了，但压得太狠，顺手也把收益压没了。

所以当前更合适的判断是：

```text
这是一个低回撤防守组合口径，
不是一个保留较多 TQQQ 收益的主策略口径。
```

### 下一步

## 2026-07-05 A 股 MA120 月末排序因子反推

### 本次任务

研究一个新问题：

```text
从 2025 年的 MA120 月末观察池高回报样本反推排序因子，
再用 2026 数据验证。
```

口径：

- 训练期：`2025-01-01` 至 `2025-12-31`
- 验证期：`2026-01-01` 至 `2026-12-31`
- 观察期：`10 / 20 / 30 / 40 / 50 / 60` 天
- 月末筛选、次月首日开盘执行
- `Top10` 等权
- 单票 `-10%` 止损

### 产出

脚本：

```text
cy_quant/ma120_monthly_factor_reverse_2025_2026.py
```

月末快照池：

```text
cy_quant/output/ma120_monthly_factor_reverse_20260705_233113/monthly_snapshot_panel.csv
```

研究输出：

```text
cy_quant/output/ma120_monthly_factor_research_20260705_233500
```

### 主要结果

最优验证组合：

```text
obs_days = 30
features = ret60, price_vs_ma120, volatility20, ret20, atr20_vs_atr60
```

验证期结果：

- 总收益：`18.93%`
- 年化：`42.44%`
- 最大回撤：`-8.12%`
- Sharpe：`1.77`

### 当前理解

未来赢家并不是已经最热的票，而更像是：

```text
在 MA120 趋势池中，
贴近 MA120、
中期涨幅不过热、
波动更收敛的稳态强势股。
```

### 重要限制

由于本地数据只更新到 `2026-07-04`，
再扣除 `60` 日前瞻窗口，
本轮有效样本外验证更接近：

```text
2026-01-05 至 2026-07-03
```

因此这轮不能算完整 `2026` 自然年验证。

### 风险边界

- 胜率很低：`14.81%`
- `27` 笔交易中 `21` 笔是 `-10%` 止损
- 平均暴露只有 `34.92%`

说明当前收益更依赖少数大赢家，而不是稳定高胜率。

## 2026-07-05 A 股 MA120 月末排序因子第二轮跟进

### 本次任务

沿上一轮最优线继续推进，只比较：

- `Top10 / Top15 / Top20`
- 行业 Top30% 过滤
- 70/30 行业混合打分

脚本：

```text
cy_quant/ma120_monthly_factor_followup.py
```

输出：

```text
cy_quant/output/ma120_monthly_factor_followup_20260705_234635
```

### 主要结果

当前最佳口径没有被改写：

```text
obs_days = 30
base
Top10
```

验证期仍然是：

- 总收益：`18.93%`
- 年化：`42.44%`
- 最大回撤：`-8.12%`

### 新的边界

- `Top15` 明显弱于 `Top10`
- `Top20` 已经转负
- 行业 Top30% 过滤没有改善
- 70/30 行业混合打分明显变差

### 当前理解

这条线当前更像：

```text
高选择性的个股排序问题
```

而不是：

```text
可以轻易扩容或简单叠加行业过滤的问题
```

## 2026-07-05 A 股 MA120 月末排序因子第三轮跟进

### 本次任务

继续沿最佳线，只比较：

- 止损后空仓到下次月调仓
- 止损后次日补位

同时输出月度与个股贡献归因。

脚本：

```text
cy_quant/ma120_monthly_refill_attribution.py
```

输出：

```text
cy_quant/output/ma120_monthly_refill_attr_20260705_235106
```

### 主要结果

`cash_until_rebalance` 仍明显优于 `refill_next_day`：

- 空仓等待：总收益 `18.93%`，最大回撤 `-8.12%`
- 次日补位：总收益 `13.70%`，最大回撤 `-19.66%`

### 归因结论

- 主要正贡献月份集中在 `2026-04`
- 主要贡献个股集中在少数几只强趋势股
- 当前策略仍然是“少数大赢家覆盖大量止损单”的结构

### 当前理解

这条线更适合：

```text
低暴露
+ 严格选择
+ 愿意等待
```

而不适合：

```text
止损后快速把仓位重新塞满
```

如果继续研究，优先改组合结构，而不是继续微调买点：

```text
让 TQQQ 战术仓带底仓
放宽移动止盈
提高战术仓初始暴露
和静态 50/50 组合做直接对比
```

## 2026-06-19 QQQ 杠杆覆盖层轮动测试

### 本次任务

验证两条更直接的低频轮动线：

```text
1. QQQ > MA120 时，把 50% 覆盖层从 QQQ 切到 TQQQ
2. QQQ Dual Thrust 120 信号时，把 50% 覆盖层从 QQQ 切到 TQQQ
```

说明：

```text
本地没有 QLD 的 csv_his，
所以这轮杠杆腿统一使用 TQQQ。
```

### 核心结果

`QQQ 50% core + MA120 -> TQQQ overlay`

- 10 bps：总收益 `278.77%`，CAGR `27.27%`，最大回撤 `-25.67%`
- 20 bps：总收益 `251.88%`，CAGR `25.59%`，最大回撤 `-26.58%`

`QQQ buy & hold`

- 10 bps：总收益 `165.65%`，CAGR `19.35%`，最大回撤 `-16.38%`

`Dual Thrust 120`

- 各参数结果几乎完全一样
- 切换次数只有 `1`
- 更像一次性切仓，而不是动态系统

### 当前结论

这一轮里，`MA120` 是值得继续挖的旁线。

`Dual Thrust 120` 则先不要继续主推，因为它在当前口径下已经退化了。

## 2026-06-19 QQQ 覆盖层止损/回补测试

### 本次任务

在 `QQQ 50% core + 当 QQQ > MA120 时，另外 50% 从 QQQ 切到 TQQQ` 的框架上，
比较两种风险控制：

```text
1. 跌 10% 直接全部切回 QQQ
2. 跌 10% 先卖一半，跌 20% 再卖完，并允许在 TQQQ 深跌到自己 MA120 下方 20% / 30% 时回补
```

### 核心结果

10 bps 下：

- `改进版`：总收益 `277.40%`，CAGR `27.14%`，最大回撤 `-22.43%`
- `基线版`：总收益 `249.24%`，CAGR `25.37%`，最大回撤 `-20.53%`

对比上一轮无止损 MA120 覆盖层：

- 无止损：总收益 `278.77%`，最大回撤 `-25.67%`

### 当前结论

这条线目前最有意思的不是“跌 10% 一刀切”，而是“分级止损 + 分级回补”。

因为它做到了：

```text
几乎保留无止损版本的大部分收益，
同时把最大回撤再往下压了一截。
```

这比基线版更值得继续挖。
