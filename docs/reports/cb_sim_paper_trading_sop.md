# 可转债模拟盘 SOP

- 项目：可转债 `baseline / defensive` 执行验证
- 适用阶段：研究已完成，进入模拟盘验证
- 更新时间：2026-06-11

## 1. 目标

这份 SOP 的目标不是“追求最好看收益”，而是验证三件事：

1. 当前策略在最近市场环境下是否还能稳定执行。
2. 实际成交与回测假设相比，是否存在明显滑点、容量、换手偏差。
3. 月度动作决策脚本给出的 `baseline` / `defensive` 建议，是否能改善组合体验。

## 2. 当前执行口径

默认主策略：

1. `baseline_balanced`
2. 规则：`Top25 + amount>=2000 + real_call_filter + balanced_premium`

防守备选：

1. `overlay_defensive`
2. 规则：`Top15 + amount>=1500 + fixed overlay`

当前建议：

1. 严格模式：默认执行 `baseline`
2. 宽松模式：允许切到 `defensive`

## 3. 模拟盘频率

建议按“月度主流程 + 周度观察”执行。

月度主流程：

1. 每月最后一个交易日收盘后或次日开盘前执行一次。
2. 产出下月持仓建议与动作建议。

周度观察：

1. 每周只做健康检查与偏差记录。
2. 不建议周内频繁改策略。

## 4. 月度操作流程

### 4.1 更新数据

先更新可转债日线和强赎事件数据。

```bash
python3.9 -m cy_quant.cb.TushareCBDataFetcher \
  --start-date 20210527 --end-date 20260611 --calls-per-minute 40
```

```bash
python3.9 -m cy_quant.cb.TushareCBCallFetcher \
  --start-date 20210527 --end-date 20260611 --output-dir /Users/water/abu/data/cb --calls-per-minute 40
```

说明：

1. 实际执行时，把 `--end-date` 改成当月最新日期。
2. 若已有本地文件，`cb_daily` 脚本会按已有逻辑补齐。

### 4.2 生成严格动作建议

```bash
python3.9 -m cy_quant.cb.cb_overlay_live_decision \
  --decision-name strict \
  --cb-daily /Users/water/abu/data/cb/cb_daily_20210527_20260527.csv \
  --cb-basic /Users/water/abu/data/cb/cb_basic.csv \
  --cb-call /Users/water/abu/data/cb/cb_call_20210527_20260527.csv \
  --out-dir cy_quant/output \
  --recent-periods 12 --ann-warn 0 --mdd-warn 0.002 --strict-disable
```

解读：

1. 若输出 `USE_BASELINE`：下月按 `baseline_balanced` 执行。
2. 若未来某次输出 `KEEP_OVERLAY_*`：说明 overlay 条件重新变强，可重新启用。

### 4.3 生成宽松动作建议

```bash
python3.9 -m cy_quant.cb.cb_overlay_live_decision \
  --decision-name loose \
  --cb-daily /Users/water/abu/data/cb/cb_daily_20210527_20260527.csv \
  --cb-basic /Users/water/abu/data/cb/cb_basic.csv \
  --cb-call /Users/water/abu/data/cb/cb_call_20210527_20260527.csv \
  --out-dir cy_quant/output \
  --recent-periods 12 --ann-warn -0.005 --mdd-warn 0.002
```

解读：

1. 若输出 `SWITCH_TO_DEFENSIVE`：表示市场边际转弱，但还没坏到必须彻底回归 baseline。
2. 这更适合愿意接受一些收益牺牲来换更稳体验的模拟盘方案。

### 4.4 选择当月执行模式

建议按以下顺序决策：

1. 如果你偏保守：直接采用严格模式结果。
2. 如果你愿意测试防守效果：严格模式与宽松模式并行记录，主账户按严格，影子账户按宽松。

推荐做法：

1. 主模拟组合：严格模式
2. 影子模拟组合：宽松模式

## 5. 当月选债标准

当月选债不是人工逐只挑，而是按以下顺序：

1. 计算 `combo_dl_trend` 分数
2. 过滤 `amount < 2000` 或 `1500` 的券
3. 过滤真实强赎区间内转债
4. 用 `balanced_premium` 做分层均衡选券
5. 按模式取 `Top25` 或 `Top15`

核心指标：

1. `double_low = close + bond_over_rate`
2. `stock_trend_proxy = cb_value / MA120(cb_value) - 1`
3. 主评分：`combo_dl_trend = rank(double_low) + rank(stock_trend_proxy)` 的等权组合

## 6. 模拟盘记录表

每月建议至少记录以下字段：

1. 日期
2. 动作建议：`baseline / defensive`
3. 严格模式输出
4. 宽松模式输出
5. 实际执行模式
6. 计划持仓数
7. 实际成交数
8. 预估换手
9. 实际换手
10. 组合月收益
11. 最大回撤
12. 是否有明显成交困难
13. 备注

## 7. 每周观察项

每周只做监控，不做频繁切换。

重点看：

1. 当月组合收益是否明显偏离同口径历史区间。
2. 成交是否频繁卡在低流动性券上。
3. 防守模式是否明显优于主模式。
4. 强赎、停牌、下修等事件是否造成预期外持仓问题。

## 8. 暂停条件

满足以下任一情况，建议暂停该策略进入复盘：

1. 连续 3 个月显著跑输同口径回测区间。
2. 实际滑点/冲击明显高于回测假设，导致执行收益大幅劣化。
3. 强赎、停牌、成交失败导致组合结构严重偏离。
4. 月度健康检查连续 2 次给出严格 `USE_BASELINE`，且宽松模式也无明显优势。

## 9. 复盘周期

建议每 3 个月做一次完整复盘，检查：

1. 模拟盘收益 vs 回测收益
2. 实际回撤 vs 回测回撤
3. 实际换手 vs 预估换手
4. 主模式 vs 防守模式
5. 是否需要调整 `amount` 门槛、`TopN`、overlay 开关

## 10. 当前建议

如果现在就开始模拟盘，建议这样做：

1. 主组合：严格模式，当前按 `baseline_balanced`
2. 影子组合：宽松模式，当前按 `overlay_defensive`
3. 先连续观察 3 个月，再决定是否推进到更高权重的真实资金测试
