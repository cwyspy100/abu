# MA120 第一阶段研究计划（csv_his）

## 目标

在 `/Users/water/abu/csv_his` 上，基于价格、均线、ATR、成交量等基础数据，研究“突破 MA120 后收益分布”与“可复用买卖时机”，并以滚动稳定性作为第一优先级。

## 研究口径

1. 事件定义（P0）
- `close(P0) > MA120(P0)`
- `close(P0-1) <= MA120(P0-1)`
- `MA120(P0) > MA120(P0-20)`

2. 样本规则
- 市场：A股 `sh/sz`
- 冷却期：同一股票事件间隔 60 交易日
- 观察窗：先测 `20/30/40` 天

3. 二次筛选候选门槛
- `ret_30d_from_p0 > {0, 3%}`
- `close_above_p0_days >= {15, 18, 20}`

4. 成本与持有
- 单边成本 0.15%（往返 0.30%）
- 持有观察：30/60/120天

## 稳定性定义

按时间做 3 段滚动验证；规则需满足：
- 至少 2 段有效（`effective_folds >= 2`）
- 每段样本数达标（最低有效事件数阈值）
- 验证段收益相对基线不恶化

## 分阶段执行

### 阶段A（先执行）
- 日线主特征 + 门槛网格 + 3段滚动稳定性
- 输出稳定规则候选

### 阶段B（在A基础上增量）
- 引入周线/月线方向与波动特征
- 检验是否提高稳定性（而非只提高样本内收益）

### 阶段C（仅在A/B出现稳定结果时）
- 非重叠实盘化回测
- 输出逐笔复盘与候选全量排名

## 产出文件

- `score_quantile_summary.csv`
- `gate_grid_search_summary.csv`
- `rolling_gate_validation.csv`
- `rolling_gate_stability_summary.csv`
- `practical_non_overlap_backtest.csv`
- `practical_non_overlap_trade_review.csv`
- `practical_non_overlap_candidates_ranked.csv`
