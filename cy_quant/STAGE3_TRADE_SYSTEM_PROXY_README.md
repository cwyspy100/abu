# Stage-3 交易系统（代理回测）进展

更新时间：2026-05-28

## 1) 本阶段在做什么

基于已有事件面板（`event_panel_with_345_features.csv`）先做一个“代理执行”回测，快速评估四类交易动作是否有价值：

1. 初始仓位（按分数每月选 TopN）
2. 加仓（30日表现强则放大仓位）
3. 止损（按 120 日回撤阈值裁剪）
4. 清仓/组合执行（先止损，再加仓）

说明：这不是逐日撮合引擎，属于阶段 C 的“规则筛选器”。

---

## 2) 四类策略口径

- `S1_base`：仅 TopN 组合，收益用 `ret_120d`
- `S2_add_on`：`ret_30d >= add_trigger_30d` 时，收益乘 `add_mult`
- `S3_stop_only`：`max_dd_120d <= stop_loss_120d` 时按止损截断
- `S4_full_system`：先止损，再对未被完全止损的标的做加仓

---

## 3) 当前最关键结论

数据集：`cy_quant/output/verify_12345_20260516/event_panel_with_345_features.csv`

扩展网格（208 组）显示：

- 平均上：`S4_full_system` 相比 `S1_base`，**回撤更低**，但平均 CAGR 略降。
- 最优参数上：可以出现 **“回撤明显降低 + CAGR 仍高”** 的组合。

其中一组较均衡参数（偏稳健）：

- `add_trigger_30d=0.06`
- `add_mult=1.40`
- `stop_loss_120d=-0.08`
- `stop_partial_120d=-0.06`

对应（S4）：

- `cagr=3.8457`
- `max_drawdown=-0.3339`
- `win_rate_monthly=0.5652`

对比同批 `S1_base`：

- `cagr=3.6174`
- `max_drawdown=-0.6273`
- `win_rate_monthly=0.6087`

解读：S4 在该参数下把最大回撤从约 -62.7% 降到约 -33.4%，收益不弱。

---

## 4) 结果文件位置

- 网格目录：
  - `cy_quant/output/stage3_trade_system_proxy_grid_20260528_111451`
- 核心文件：
  - `grid_all.csv`
  - `grid_best_s4.csv`

---

## 5) 如何复跑

```bash
python3.9 cy_quant/stage3_trade_system_proxy_grid.py \
  --input-csv cy_quant/output/verify_12345_20260516/event_panel_with_345_features.csv \
  --output-dir cy_quant/output \
  --top-n 30 \
  --add-trigger-30d 0.06 0.08 0.10 0.12 \
  --add-mult 1.10 1.20 1.30 1.40 \
  --stop-loss-120d -0.08 -0.10 -0.12 -0.15 \
  --stop-partial-120d -0.04 -0.06 -0.08 -0.10
```

---

## 6) 下一步（从代理回测走向可交易系统）

把上述优选参数迁移到“逐日执行引擎”做 A/B：

1. 入场：月初/周初按候选分数建仓（TopN）
2. 持仓：逐日检查止损/清仓触发
3. 加仓：满足 trigger 后分批加仓，不一次性放大
4. 输出真实交易指标：交易次数、换手、滑点、手续费后净值、回撤

当逐日引擎中仍满足“收益不塌 + 回撤下降”，阶段 C 才算完成。

---

## 7) 新增 A/B 脚本（本次已完成）

新增文件：

- `cy_quant/stage3_trade_system_ab_test.py`

作用：

- 在同一候选池上对比四组策略：
  - `S1_base`（仅基线）
  - `S2_add_only`（仅加仓）
  - `S3_stop_only`（仅止损）
  - `S4_full_system`（先止损再加仓）
- 同时输出两套口径：
  - 月度可重叠
  - 非重叠（上一笔120天未结束不新开）

执行命令：

```bash
python3.9 cy_quant/stage3_trade_system_ab_test.py \
  --input-csv cy_quant/output/verify_12345_20260516/event_panel_with_345_features.csv \
  --output-dir cy_quant/output \
  --top-n 30 \
  --min-close-above-p0-days 15 \
  --min-ret-30d-from-p0 0.0 \
  --add-trigger-30d 0.06 \
  --add-mult 1.4 \
  --stop-loss-120d -0.08 \
  --stop-partial-120d -0.06 \
  --cost-oneway 0.0015
```

本次结果目录：

- `cy_quant/output/stage3_trade_system_ab_20260528_113325`

关键结论（非重叠口径更接近真实）：

- `S1_base`：`total_return=15.25%`, `cagr=2.95%`, `max_drawdown=-23.47%`
- `S4_full_system`：`total_return=90.79%`, `cagr=14.17%`, `max_drawdown=-8.30%`

当前阶段 C 建议：

- 先用 `S4_full_system` 作为默认规则原型，进入下一步逐日执行回测（含真实买卖时点、手续费、滑点、仓位动态）。

---

## 8) 逐日资金曲线口径（新增）

新增文件：

- `cy_quant/stage3_trade_system_daily_ab.py`

说明：

- 使用 `buy_date` 到 `sell_date_120d` 作为真实持仓区间；
- 将每笔 `120d` 收益按持有天数展开为日收益；
- 每日对所有在持仓交易等权合成为组合净值；
- 输出四组策略的逐日净值、回撤、年化。

执行命令：

```bash
python3.9 cy_quant/stage3_trade_system_daily_ab.py \
  --input-csv cy_quant/output/verify_12345_20260516/event_panel_with_345_features.csv \
  --output-dir cy_quant/output \
  --top-n 30 \
  --min-close-above-p0-days 15 \
  --min-ret-30d-from-p0 0.0 \
  --add-trigger-30d 0.06 \
  --add-mult 1.4 \
  --stop-loss-120d -0.08 \
  --stop-partial-120d -0.06 \
  --cost-oneway 0.0015
```

本次结果目录：

- `cy_quant/output/stage3_trade_system_daily_ab_20260528_113955`

逐日口径关键结果：

- `S1_base`：`total_return=62.02%`, `cagr=9.79%`, `max_drawdown=-19.04%`
- `S4_full_system`：`total_return=88.75%`, `cagr=13.08%`, `max_drawdown=-11.17%`

结论：

- 在逐日资金曲线口径下，`S4_full_system` 仍明显优于基线（收益更高、回撤更低）。

---

## 9) 真实逐K线执行口径（新增）

新增文件：

- `cy_quant/stage3_trade_system_realpath_ab.py`

说明：

- 从本地 `csv_his` 加载每只股票真实日K；
- 每笔交易按 `buy_date -> sell_date_120d` 逐日计算；
- 按规则在真实路径中触发：
  - 止损清仓（`stop_loss`）
  - 部分减仓（`stop_partial`）
  - 第30个交易日后满足条件才加仓（`add_trigger_30d`）。

执行命令：

```bash
python3.9 cy_quant/stage3_trade_system_realpath_ab.py \
  --input-csv cy_quant/output/verify_12345_20260516/event_panel_with_345_features.csv \
  --csv-dir /Users/water/abu/csv_his \
  --output-dir cy_quant/output \
  --top-n 30 \
  --min-close-above-p0-days 15 \
  --min-ret-30d-from-p0 0.0 \
  --add-trigger-30d 0.06 \
  --add-mult 1.4 \
  --stop-loss -0.08 \
  --stop-partial -0.06 \
  --cost-oneway 0.0015
```

本次结果目录：

- `cy_quant/output/stage3_trade_system_realpath_ab_20260528_115620`

真实路径结果（474笔，约4.99年）：

- `S1_base`：`total_return=260.75%`, `cagr=29.31%`, `max_drawdown=-55.43%`
- `S2_add_only`：`total_return=284.06%`, `cagr=30.94%`, `max_drawdown=-67.35%`
- `S3_stop_only`：`total_return=97.45%`, `cagr=14.60%`, `max_drawdown=-41.46%`
- `S4_full_system`：`total_return=114.40%`, `cagr=16.51%`, `max_drawdown=-52.97%`

关键结论（以真实路径为准）：

- 加仓（S2）会拉高收益，但显著放大回撤；
- 仅止损（S3）回撤改善最明显，但收益下降；
- 完整系统（S4）相对 S3 提高收益，但当前参数下回撤并不优于 S3。

因此下一步应只在“真实逐K线口径”下做小范围参数优化，而不再依赖代理口径结论。
