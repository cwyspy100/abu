# 10天观察期候选清单（A股/港股/美股）

本方案固定为：

- 观察期：**10天**
- 收益统计：**仅 `ret_120d`**
- 市场范围：**A股(`sh`/`sz`)、港股(`hk`)、美股(`us`)**

脚本文件：

- `/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/datacsv_obs10_latest_candidates.py`

---

## 一、一次性执行命令

```bash
cd /Users/water/mylearn/PycharmProjects/abu-master
.venv/bin/python cy_quant/datacsv_obs10_latest_candidates.py \
  --csv-dir /Users/water/abu/data/csv \
  --output-dir /Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output \
  --recent-months 1
```

运行后会生成目录：`cy_quant/output/obs10_ahk_us_latest_YYYYmmdd_HHMMSS`

---

## 二、输出文件说明

### 1) 总汇总（按市场）

- `obs10_ahk_us_overall_summary.csv`

字段重点：
- `market`: `a/hk/us`
- `events`: MA120上穿事件数量
- `avg_ret_120d_pick`: 入选股票逐笔 `ret_120d` 平均值
- `win_rate_120d_pick`: 入选股票逐笔胜率
- `cagr_label`: 标签口径年化（研究指标，**非实盘年化**）

### 2) 每市场逐笔选股与收益记录

- `a_obs10_picks_detail.csv`
- `hk_obs10_picks_detail.csv`
- `us_obs10_picks_detail.csv`

每条记录包含：
- `symbol`
- `p0_date`（上穿触发日）
- `eval_date`（10天观察结束）
- `buy_date`
- `sell_date_120d`
- `close_above_p0_days`
- `total_score`
- `ret_120d`

### 3) 每市场月度汇总

- `a_obs10_monthly_summary.csv`
- `hk_obs10_monthly_summary.csv`
- `us_obs10_monthly_summary.csv`

### 4) 最新1个月候选清单

- `a_obs10_latest_1m_candidates.csv`
- `hk_obs10_latest_1m_candidates.csv`
- `us_obs10_latest_1m_candidates.csv`
- 合并版：`all_markets_obs10_latest_1m_candidates.csv`

---

## 三、每月执行流程

1. 更新本地 K 线到 `/Users/water/abu/data/csv`（用你当前的数据更新流程）。
2. 运行上面的脚本命令。
3. 打开新输出目录，直接使用：
   - `all_markets_obs10_latest_1m_candidates.csv`（本月候选总表）
4. 用 `*_picks_detail.csv` 与 `*_monthly_summary.csv` 做历史核验。

---

## 四、当前筛选规则（脚本内固定）

1. 事件定义：`close` 上穿 `MA120` 且 `MA120` 5日斜率 > 0  
2. 观察窗：10天  
3. 二次筛选：
   - `close_above_p0_days >= max(ceil(10*0.6), 训练期60分位)`  
   - `total_score >= 训练期60分位`  
4. 每月按 `total_score` 取前30

