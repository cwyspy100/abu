# cy_ai Superpowers 操作手册

本文档说明如何在 `cy_ai` 中使用两阶段 AI 流程：

1. 第一阶段：批量低成本打分（快）
2. 第二阶段：仅对前 N 只做深度估值 + 投资计划（慢）

---

## 1. 前置准备

### 1.1 数据库准备

首次使用先初始化数据库：

```bash
python -m cy_ai.main --init-db
```

### 1.2 导入数据

#### 导入股票基础信息（可选但推荐）

```bash
python -m cy_ai.main --import-basic <你的stock_basic.csv>
```

#### 导入 120MA 股票池（示例：只导入 sh）

```bash
python -m cy_ai.main --import-pool "cy_quant/sh_120ma_breakthrough_20260405.csv"
```

#### 历史数据修正（建议执行）

会统一 `ts_code` 为 6 位，并回填 `name/industry`：

```bash
python -m cy_ai.main --normalize-db
```

---

## 2. 配置大模型 Key（放在 todolist）

### 2.1 `todolist/config.json`

至少配置一个可用 provider 的 key：

```json
{
  "token": "你的tushare_token",
  "minimax_api_key": "",
  "deepseek_api_key": "",
  "doubao_api_key": ""
}
```

### 2.2 `todolist/llm_config.json`

用于配置模型路由（便宜模型 + 深度模型）：

```json
{
  "cheap_provider": "deepseek",
  "cheap_model": "deepseek-chat",
  "strong_provider": "deepseek",
  "strong_model": "deepseek-reasoner",
  "deepseek_base_url": "https://api.deepseek.com/v1/chat/completions",
  "doubao_base_url": "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
  "minimax_base_url": "https://api.minimaxi.com/v1/text/chatcompletion_v2",
  "timeout": 90,
  "max_retries": 3,
  "retry_delay": 3
}
```

说明：
- 若所选 provider 没有 key，系统会自动尝试回退到 `minimax`（如果有 key）。

---

## 3. Superpowers 两阶段操作

### 3.1 第一阶段（只打分，写库）

```bash
python -m cy_ai.main --analyze --superpowers-stage1 --limit 500 --delay 1
```

作用：
- 对待分析股票做批量打分（低成本模型）
- 把结果写入 `stock_ai_analysis`
- 标记为第一阶段记录（`tenbagger_logic='__STAGE1_ONLY__'`）

建议：
- `--delay` 设为 0.8~2 秒
- 初次可先 `--limit 20` 小样本验证

### 3.2 第二阶段（从库取前 N 深度分析）

```bash
python -m cy_ai.main --analyze --superpowers-stage2 --top-n 20 --delay 1
```

作用：
- 从数据库读取第一阶段候选中分数前 `N` 的股票
- 对这 `N` 只做深度分析（估值、投资计划、风险）
- 覆盖更新到 `stock_ai_analysis`

这是慢步骤，默认建议只跑 `top-n=20` 或更小。

---

## 4. 一体化命令（可选）

如果你不想分开执行，也可以用一体化流程：

```bash
python -m cy_ai.main --analyze --superpowers --limit 200 --top-n 20 --delay 1
```

说明：
- 会先打分，再深度分析前 `top-n`
- 但相比“分阶段”，不利于严格控量，建议优先用分阶段命令

---

## 5. 查看与导出

### 显示股票池

```bash
python -m cy_ai.main --show-pool
```

### 显示分析结果

```bash
python -m cy_ai.main --show --limit 100
```

### 按条件筛选

```bash
python -m cy_ai.main --show --filter-score 80
python -m cy_ai.main --show --filter-status "强烈推荐(10倍潜力)"
```

### 导出结果

```bash
python -m cy_ai.main --export "todolist/ai_results.csv"
```

---

## 6. 推荐执行顺序（实盘）

1. 导入/更新股票池（只导入你要的市场，比如 sh）
2. `--normalize-db`
3. `--superpowers-stage1`（批量打分）
4. 观察打分分布（可先 `--show --limit 50`）
5. `--superpowers-stage2 --top-n 20`（深度分析）
6. `--export` 导出结果给你复核

---

## 7. 常见问题

### Q1：`score=68` 是什么？

是第一阶段综合打分（0~100），来自低成本模型的结构化输出。

### Q2：为什么第二阶段慢？

第二阶段是强模型深度推理（估值 + 投资计划），本来就慢，所以建议只跑前 20。

### Q3：如何降低成本？

- 第一阶段放大，第二阶段缩小（例如 top 10）
- 降低 `strong_model` 成本级别
- 适当增加 `delay` 避免失败重试

### Q4：`ts_code` 丢前导零怎么办？

系统已统一规范化：去后缀并补齐 6 位（如 `2594 -> 002594`）。

