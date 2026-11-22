# MA120 MVP Radar

最小可行版本：基于本地 abupy K 线缓存，扫描 A 股中收盘价站上 120 日均线的股票，并输出买入观察/风险观察清单。

## 数据来源

默认读取：

- `~/abu/data/csv/astock`
- `~/abu/data/csv`

文件名格式兼容当前项目已有缓存，例如：

- `sh600596_20240126_20260509`
- `sz002454_20240126_20260509`

## 运行

扫描全部本地 A 股缓存：

```bash
.venv/bin/python -m ma120_mvp.cli
```

只扫描一个股票池：

```bash
.venv/bin/python -m ma120_mvp.cli --pool todolist/stock_a_pool.csv
```

调试前 200 个文件：

```bash
.venv/bin/python -m ma120_mvp.cli --limit 200
```

默认会跳过最后一根 K 线早于当前日期 14 天的旧文件，避免历史缓存污染日报。
如果要研究历史缓存，可传：

```bash
.venv/bin/python -m ma120_mvp.cli --max-stale-days 9999
```

默认读取 `todolist/stock_A_basic_list.csv`，并排除 `ST/*ST`。如果需要包含 ST 做研究：

```bash
.venv/bin/python -m ma120_mvp.cli --include-st
```

输出默认在：

```text
ma120_mvp/output/ma120_daily_<日期>.csv
```

终端默认展示 Top 50，CSV 保存全部结果：

```bash
.venv/bin/python -m ma120_mvp.cli --top 100
```

## 当前规则

只输出：

- `close > MA120`
- MA120 斜率大于 0，默认要求当前 MA120 高于 20 个交易日前的 MA120
- 最后一根 K 线日期未超过 `--max-stale-days`

可调整斜率窗口：

```bash
.venv/bin/python -m ma120_mvp.cli --ma120-slope-lookback 30
```

买入观察信号：

- 新站上 MA120，且偏离 MA120 不超过 10%
- 突破前 20 日高点，且量比满足阈值
- 回踩 MA20/MA60 附近后收稳

风险标签：

- 跌破 MA20
- 跌破 MA60
- 偏离 MA120 过大
- 20 日回撤过大

## 评分

当前会追加规则评分字段：

- `trend_score`：趋势强度，满分 35
- `entry_score`：买点质量，满分 30
- `risk_score`：风险控制，满分 20
- `quality_score`：基础质量/量价，满分 15
- `total_score`：总分，满分 100
- `candidate_level`：强候选/重点观察/普通观察/剔除观察
- `score_reason`：入选原因摘要

这不是自动交易信号，只是每日雷达。后续再接持仓、飞书提醒和回测评估。

## 前瞻验证

验证历史上评分信号之后的未来收益/回撤：

```bash
.venv/bin/python -m ma120_mvp.forward_cli --limit 300 --recent-days 120 --horizon 20
```

常用参数：

- `--min-score 80`：只看高分信号
- `--min-level 强候选`：只看强候选
- `--horizon 20`：未来观察 20 个交易日
- `--recent-days 120`：每只股票只回看最近 120 个可验证信号日
- `--signal-cooldown 10`：同一股票两次入选之间至少间隔 10 个交易日，减少连续信号重复计数

输出默认在：

```text
ma120_mvp/output/forward_test_<日期>.csv
```

## 分组研究

对前瞻验证结果做分组统计：

```bash
.venv/bin/python -m ma120_mvp.research_cli \
  --forward-csv ma120_mvp/output/forward_limit300_h20.csv
```

会按信号组合、MA120 偏离、MA120 斜率、站上天数、20日回撤、量比、分数区间等维度输出统计。

## 每日精简观察列表

全量趋势池可能有上千只股票，不适合人工逐只查看。可以生成只包含研究形态的精简观察列表：

```bash
.venv/bin/python -m ma120_mvp.watch_cli
```

默认会从全量趋势池中挑选：

- `低位新站上` 最多 10 只
- `进攻突破窗口` 最多 10 只
- `长期趋势延续` 最多 5 只

并过滤 ST、低价股、量比过热和硬风险标签。输出默认在：

```text
ma120_mvp/output/ma120_watchlist_<日期>.csv
```

可调整每日总数和各形态数量：

```bash
.venv/bin/python -m ma120_mvp.watch_cli --max-total 20 --low-new-cap 8 --attack-cap 8 --trend-cap 4
```
