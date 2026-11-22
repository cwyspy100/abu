# stock_pool_ma120 评分脚本（Qianwen / MiniMax）

脚本：`/Users/water/mylearn/PycharmProjects/abu-master/cy_ai/score_stock_pool_ma120_qianwen.py`

## 功能

- 从 `stock_pool_ma120` 读取 A 股标的
- 本地优先读取财务缓存，不足时从 Tushare 补拉并合并去重
- 缓存四类文件：
  - `*_finance.csv`（财务指标）
  - `*_income.csv`（利润表）
  - `*_balancesheet.csv`（资产负债表）
  - `*_cashflow.csv`（现金流量表）
- 支持模型切换：`qianwen` / `minimax`
- 输出评分并回写：
  - `score`（0-10）
  - `remark`（<=500字）
  - `research_status=1`

## 前置准备

1. MySQL 可连接（读取和回写 `stock_pool_ma120`）。
2. 配置 API Key（`todolist/config.json` 或环境变量）：
   - 千问：`qianwen_api_key` / `QIANWEN_API_KEY`
   - MiniMax：`minimax_api_key` / `MINIMAX_API_KEY`
3. 若要自动补拉财务：运行环境需可导入 `tushare`。

## 单股票测试（可直接写库）

### 1) Qianwen（写库）

```bash
cd /Users/water/mylearn/PycharmProjects/abu-master
python3.9 cy_ai/score_stock_pool_ma120_qianwen.py \
  --provider qianwen \
  --test-stock 688041 \
  --verbose \
  --finance-dir /Users/water/abu/tushare/finance \
  --force-refresh-finance
```

### 2) MiniMax（写库）

```bash
cd /Users/water/mylearn/PycharmProjects/abu-master
python3.9 cy_ai/score_stock_pool_ma120_qianwen.py \
  --provider minimax \
  --test-stock 688041 \
  --verbose \
  --finance-dir /Users/water/abu/tushare/finance \
  --force-refresh-finance
```

可选：指定 MiniMax 模型

```bash
--minimax-model MiniMax-M2.5
```

如果你只想预览不写库，额外加 `--dry-run`。

## 批量执行（写库）

```bash
cd /Users/water/mylearn/PycharmProjects/abu-master
python3.9 cy_ai/score_stock_pool_ma120_qianwen.py \
  --provider minimax \
  --only-unresearched \
  --limit 50 \
  --delay 1.0 \
  --finance-dir /Users/water/abu/tushare/finance
```

按“未研究标记”补跑（`research_status != 1`）：

```bash
cd /Users/water/mylearn/PycharmProjects/abu-master
python3.9 cy_ai/score_stock_pool_ma120_qianwen.py \
  --provider qianwen \
  --only-unresearched \
  --limit 200 \
  --delay 1.0 \
  --finance-dir /Users/water/abu/tushare/finance
```

## 常见问题

- `Tushare 未安装`：切到有 `tushare` 的解释器（例如 `python3.9`）或安装到当前环境。
- 返回 0 条：`--test-stock` 代码需存在于 `stock_pool_ma120` 且市场为 A 股。
- 评分失败：检查对应模型 API Key、网络与限流。
