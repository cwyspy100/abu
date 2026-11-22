# MA120 实盘化组合测试进展

更新时间：2026-05-28

## 研究问题

前面验证过：超过 MA120 的股票中，确实更容易出现大涨股票。但直接“买入后跌破 MA120 卖出”历史段回撤太大，不适合直接实盘。

本轮目标不是寻找最优参数，而是测试朴素、可解释、能执行的组合：

- 大盘过滤
- 个股二次筛选
- 更快退出
- 仓位控制

## 测试数据

历史数据：

- K线：`/Users/water/abu/csv_his`
- 事件面板：`cy_quant/output/ma120_event_validation_20260515_221018/event_panel.csv`

当前数据：

- K线：`/Users/water/abu/data/csv`
- 事件面板：`cy_quant/output/obs10_ahk_us_latest_20260528_094802/a_obs10_event_panel.csv`

## 新增脚本

- `cy_quant/ma120_practical_system_grid.py`

执行示例：

```bash
python3.9 cy_quant/ma120_practical_system_grid.py \
  --label hist_def \
  --panel-csv cy_quant/output/ma120_event_validation_20260515_221018/event_panel.csv \
  --csv-dir /Users/water/abu/csv_his \
  --output-dir cy_quant/output \
  --top-ns 1 3 5 \
  --min-close-above-p0-days 15 \
  --min-ret-obs 0.0 \
  --cost-oneway 0.0015 \
  --markets SH,SZ \
  --index-code 000001.SH
```

当前数据：

```bash
python3.9 cy_quant/ma120_practical_system_grid.py \
  --label current_def \
  --panel-csv cy_quant/output/obs10_ahk_us_latest_20260528_094802/a_obs10_event_panel.csv \
  --csv-dir /Users/water/abu/data/csv \
  --output-dir cy_quant/output \
  --top-ns 1 3 5 \
  --min-close-above-p0-days 8 \
  --min-ret-obs 0.0 \
  --cost-oneway 0.0015 \
  --markets SH,SZ \
  --index-code 000001.SH
```

## 本轮输出目录

- 历史防守版：`cy_quant/output/ma120_practical_grid_hist_def_20260528_123532`
- 当前防守版：`cy_quant/output/ma120_practical_grid_current_def_20260528_123532`

## 最值得跟踪的候选规则

候选规则：`top5 + market_stop5_exit_ma20`

规则含义：

- 每月从候选池选 Top5
- 大盘过滤：上证指数 `close > MA120` 且 `MA120_slope20 > 0`
- 买入后若亏损达到 5%，卖出
- 买入后若跌破个股 MA20，卖出
- 同一只股票上一笔没结束，不开下一笔
- 单边成本按 `0.15%`

全仓策略结果：

| 数据 | 总收益 | CAGR | 最大回撤 |
|---|---:|---:|---:|
| 历史 | 196.73% | 79.84% | -46.72% |
| 当前 | 19.28% | 20.06% | -34.49% |

全仓回撤仍偏高，因此不建议全仓实盘。

## 实盘化建议：只作为 30% 策略仓位

将该策略只作为账户 30% 仓位，剩余 70% 保留现金/低风险资产：

| 数据 | 总收益 | CAGR | 最大回撤 |
|---|---:|---:|---:|
| 历史 | 44.25% | 21.86% | -16.77% |
| 当前 | 8.74% | 9.08% | -11.51% |

这个形态更接近可接受的观察仓策略。

## 当前结论

不能说已经找到“可全仓实盘”的系统。

但可以说找到一个值得小仓位观察的组合：

- `Top5`
- 大盘过滤
- 5%止损
- 跌破 MA20 退出
- 策略总仓位不超过账户 30%

这个组合在历史段和当前段都为正，且通过仓位控制后最大回撤降到较可控区间。

## 后续实盘前还需要补足

1. 生成每日/每月候选清单与持仓监控清单。
2. 增加真实交易记录表：买入价、卖出价、止损原因、MA20/MA120 状态。
3. 加入暂停交易规则：策略回撤超过 10% 或大盘跌破 MA120，暂停新开仓。
4. 小资金先用观察仓，不建议一开始满仓执行。

