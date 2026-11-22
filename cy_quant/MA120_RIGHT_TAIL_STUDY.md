# MA120 候选池右尾研究

更新时间：2026-06-10

## 研究目的

停止继续调 `TopN / 备用池 / 加仓阈值`，先验证一个更基础的问题：

`MA120 突破 + 观察期通过` 的候选池，本身是否比同期随机股票更容易出现未来大涨？

如果候选池没有明显右尾优势，后续继续寻找复杂静态选股参数的价值就很低。

## 新增脚本

- `cy_quant/ma120_pool_right_tail_study.py`

脚本只做分布研究，不做交易规则优化：

- 候选池：事件面板中的 MA120 候选股票
- 对照池1：同一买入日期随机 A 股
- 对照池2：同一买入日期且也在 MA120 之上的随机 A 股
- 指标：均值、中位数、胜率、右尾比例、亏损比例、赢家集中度、三段滚动分布

## 执行命令

历史观察期通过池 vs 随机趋势股：

```bash
python3.9 cy_quant/ma120_pool_right_tail_study.py \
  --label hist_gate_trendrand_h120 \
  --panel-csv cy_quant/output/ma120_event_validation_20260515_221018/event_panel.csv \
  --csv-dir /Users/water/abu/csv_his \
  --output-dir cy_quant/output \
  --markets SH,SZ \
  --min-close-above-p0-days 15 \
  --min-ret-obs 0 \
  --horizon 120 \
  --random-mult 3 \
  --seed 11 \
  --random-require-ma120
```

当前观察期通过池 vs 随机趋势股：

```bash
python3.9 cy_quant/ma120_pool_right_tail_study.py \
  --label current_gate_trendrand_h120 \
  --panel-csv cy_quant/output/obs10_ahk_us_latest_20260528_094802/a_obs10_event_panel.csv \
  --csv-dir /Users/water/abu/data/csv \
  --output-dir cy_quant/output \
  --markets SH,SZ \
  --min-close-above-p0-days 8 \
  --min-ret-obs 0 \
  --horizon 120 \
  --random-mult 3 \
  --seed 11 \
  --random-require-ma120
```

## 输出目录

- `cy_quant/output/ma120_pool_right_tail_hist_gate_trendrand_h120_20260610_074108`
- `cy_quant/output/ma120_pool_right_tail_current_gate_trendrand_h120_20260610_074131`

## 核心结果

历史段，候选池 vs 随机趋势股：

| group | n | mean | median | win_rate | q90 | q95 | tail_gt20 | tail_gt30 | loss_lt10 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| candidate | 718 | 15.41% | 7.11% | 60.86% | 58.77% | 87.11% | 33.98% | 25.49% | 24.23% |
| random trend | 2154 | 16.92% | 5.85% | 58.82% | 66.99% | 101.52% | 33.80% | 26.09% | 27.72% |

当前段，候选池 vs 随机趋势股：

| group | n | mean | median | win_rate | q90 | q95 | tail_gt20 | tail_gt30 | loss_lt10 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| candidate | 2132 | 17.04% | 8.23% | 67.45% | 55.58% | 78.73% | 31.00% | 22.00% | 15.24% |
| random trend | 6396 | 18.15% | 8.25% | 66.96% | 58.80% | 89.45% | 32.47% | 22.56% | 15.43% |

## 判断

候选池相对“随机趋势股”没有明显右尾优势。

历史段：

- 候选池中位数略好
- 候选池亏损比例更低
- 但 q90/q95 和 30% 以上右尾不强

当前段：

- 候选池和随机趋势股几乎接近
- 候选池右尾略弱

因此，目前不支持继续围绕静态评分、TopN、备用池阈值做大量参数搜索。

## 后续方向

后续应把 MA120 候选池定位为：

`趋势股搜索范围`，而不是 `高胜率选股因子`。

更现实的研究方向：

1. 不再追求提前预测哪只会大涨。
2. 用小仓位试错，亏损快速退出。
3. 对已经走出来的赢家做有限加仓。
4. 重点研究账户级风险，而不是更多静态选股特征。

当前更合理的实盘原型：

- 大盘过滤
- MA120 观察池
- Top3/Top5 小仓位初始买入
- 固定止损或 MA20 失败退出
- 盈利后单次加仓
- 总策略仓位上限

