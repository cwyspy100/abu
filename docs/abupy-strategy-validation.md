# 使用 abupy 做策略验证与测试记录指南

本文说明如何在本仓库中**系统化验证策略**，并**可追溯地记录**已跑过的回测与结论。适用于 `abupy` 回测骨架 + 自研脚本（如 `cy_quant/`）的组合用法。

---

## 1. 目标与原则

| 原则 | 说明 |
|------|------|
| **先证数据，再证策略** | K 线缺失、市场/数据源配错时，回测结果无意义。 |
| **由小到大** | 单标的 → 短区间 → 少参数；通过后再扩符号池与样本长度。 |
| **一次实验一个变量** | 对比两组回测时，尽量只改买入/卖出/仓位/参数中的一项。 |
| **可复现** | 记录代码版本（commit）、市场配置、标的列表、日期区间与随机种子（若用到）。 |
| **结论与数据分开存** | 详细订单/动作可 CSV；摘要进「策略测试登记表」，便于检索。 |

---

## 2. 回测前检查清单（每次必做）

在调用 `abu.run_loop_back` 或批量脚本前，确认：

1. **市场与数据源**  
   - `abupy.env.g_market_target`（如美股 `E_MARKET_TARGET_US`）是否与标的前缀一致（`us` / `sh` / `sz` / `hk`）。  
   - `abupy.env.g_market_source` 是否可用（网络/本地 RomData/CSV）。

2. **标的可用性**  
   - 对关键代码执行 `ABuSymbolPd.make_kl_df(symbol, n_folds=1)` 或等价接口，检查行数、`trade_date`/`close` 是否合理。  
   - 美股注意 RomData 中 `exchange` 等字段异常会导致解析失败（需修数据或框架兜底）。

3. **因子依赖**  
   - 使用 `AbuAtrPosition` 时，K 线需具备 `atr21`（或因子内已计算）。  
   - 使用 `AbuKellyPosition` 时，`win_rate` / `gains_mean` / `losses_mean` 应用**同一策略历史**估计，并注意 `losses_mean` 的符号与除零问题。

4. **输出路径**  
   - 订单、动作、摘要落盘路径统一（例如 `todolist/` 或 `cy_quant/output/`），避免覆盖时无备份。

---

## 3. 推荐的策略验证流程

```text
假设 → 最小可运行回测 → 读 metrics & 订单 → 决策（保留/调整/放弃）→ 写入测试记录
```

### 3.1 最小可运行回测

- **标的**：1～3 只代表性股票（含流动性好、数据完整的一只）。  
- **时间**：`n_folds` 或 `start`/`end` 明确写出。  
- **因子**：仅保留当前要验证的买入 + 最简卖出（或书中默认止损组合）。

### 3.2 阅读结果时的优先顺序

1. `AbuMetricsBase.fit_metrics()` 后的：**总收益、最大回撤、胜率、交易笔数**。  
2. **交易笔数过少**：指标不稳定，结论仅作参考。  
3. `orders_pd` / `action_pd`：是否有异常成交、是否未触发卖出、是否集中在少数日期。

### 3.3 扩展实验

通过最小回测后再：

- 扩大 `choice_symbols` 或股票池 CSV；  
- 调整卖出/止损参数网格（建议列表记录每组参数 ID）；  
- 加入滑点、仓位类（ATR/Kelly），观察与「固定仓位」的差异。

---

## 4. 自定义研究与 abupy 的分工建议

| 层次 | 建议 |
|------|------|
| **选股/扫描** | 在 `cy_quant/` 用 pandas/本地 CSV 产出标的列表或信号表。A 股基本面池可参考 `cy_quant/pick_stock_cn_fina_value.py`（本地 `~/abu/tushare/finance` 的 `fina_indicator` 合并表，缺失时可 `fina_indicator` API）。 |
| **回测执行** | 调用 `abupy`：`run_loop_back`、`AbuMetricsBase`。 |
| **结果归档** | 原始 `orders_pd`/`action_pd` 存 CSV；摘要进本文第 6 节的登记表。 |

避免在 `abupy/` 内部做大改动；确需修复数据或通用 bug，单独 commit，便于与上游同步。

---

## 5. 代码层面可复用习惯

- **回测脚本**：为每个策略目录或文件名带上简短代号（如 `bt_mean_120_us.py`），与登记表 `策略ID` 一致。  
- **配置**：市场、初始资金、`buy_factors`/`sell_factors` 尽量集中在文件顶部或字典，便于 diff。  
- **版本**：登记表中记录 `git rev-parse --short HEAD`（或手动写分支名 + 日期）。

---

## 6. 已测试策略记录方式

### 6.1 登记表（主推荐）

在版本库中维护一张**只增不改旧行**的表（新实验**新增一行**）。

- **Markdown 表**：本仓库已提供 [`docs/strategy_runs.md`](./strategy_runs.md)，直接在该表追加行即可。  
- 若更习惯 Excel/表格软件，可复制同结构为 `docs/strategy_runs.csv` 并用 Git 管理。

**建议字段：**

| 字段 | 说明 |
|------|------|
| `run_id` | 唯一 ID，如 `20260506-001` |
| `date` | 实验日期 |
| `strategy_id` | 策略逻辑代号，如 `BUY_MEAN_120_ATR_STOP_V1` |
| `git_commit` | 可选，短 SHA |
| `market` | US / CN / HK |
| `symbols` | 标的列表或池子文件路径 |
| `period` | 如 `n_folds=2` 或 `2020-01-01~2024-12-31` |
| `buy_factors` | 简述或 JSON/文件路径 |
| `sell_factors` | 简述或 JSON/文件路径 |
| `position` | None / ATR / Kelly + 关键参数 |
| `metrics_note` | 收益、回撤、胜率、笔数等摘要 |
| `conclusion` | 保留 / 待优化 / 放弃 + 一句话原因 |
| `artifacts` | 订单 CSV、日志路径 |

### 6.2 原始数据文件命名

建议模式：

```text
cy_quant/output/backtest_<strategy_id>_<YYYYMMDD>_<run_id>_orders.csv
cy_quant/output/backtest_<strategy_id>_<YYYYMMDD>_<run_id>_actions.csv
```

与登记表 `artifacts` 列一致，日后可按 `strategy_id` 或日期 `glob`。

### 6.3 最小示例行（追加到 `strategy_runs.md`）

```markdown
| 20260506-001 | 2026-05-06 | MEAN120_US_V1 | abc1234 | US | usTSLA,usQQQ | n_folds=2 | ATR default | +12.3% | -18% | 48% | 56 | 保留，待扩池 | cy_quant/output/..._orders.csv |
```

---

## 7. 常见陷阱（本仓库实践中已遇到）

- **Symbol 大小写 / 交易所字段**：美股 CSV 中 `exchange` 为 `-` 等会导致 `EMarketSubType` 异常；验证前先 `make_kl_df`。  
- **metrics 全空或告警**：多为 K 线未加载成功或零笔成交，先查异常日志再调策略。  
- **Kelly 参数照搬 metrics**：`losses_mean` 在 metrics 中常为负，填入 Kelly 时常需取绝对值并与公式假设一致。

---

## 8. 延伸阅读（仓库内）

- 项目总览：`readme.md`（安装、lecture 链接、`ipython`/`python` 示例）。  
- 官方教程章节：择时 → 优化 → 滑点与手续费（readme 内链接）。  
- 你本地的回测入口示例：`cy_quant/MonitorStockUsPool.py`、`learn_python/ExecuteUSBackTest.py` 等，可复制改为自己的 `strategy_id` 与输出路径。

---

## 9. 变更记录

| 日期 | 说明 |
|------|------|
| 2026-05-06 | 初版：验证流程 + 测试记录规范 |
