# 股票AI分析系统设计文档

## 一、项目概述

### 1.1 目标
构建一个多数据源、多阶段的智能股票筛选与分析系统，整合本地K线数据、Tushare财务数据、市场情绪数据，通过千问大模型进行两阶段分析（初筛+深度分析），输出结构化投资建议。

### 1.2 数据来源
| 数据类型 | 来源 | 备注 |
|---------|------|------|
| K线数据 | 本地CSV文件 | 近2年历史数据 |
| 财务数据 | Tushare API | fina_indicator + 利润表 + 资产负债表 + 现金流量表 |
| 市场情绪 | Tushare API + 预留字段 | 北向资金、融资融券、涨跌停等 |

### 1.3 分析流程
```
一级筛选池(CSV) → 特征构建 → 阶段1(千问初筛,score≥80) → 阶段2(千问深度分析) → 入库
                                       ↓ (score<80)
                                    标记放弃+原因
```

---

## 二、数据库表设计

> **注意**：K线数据直接从本地CSV读取，不存入数据库。表结构仅作参考保留。

### 2.1 技术面数据结构（内存对象，非入库）

```python
@dataclass
class StockKlineFeatures:
    """从本地CSV读取的技术指标"""
    ts_code: str
    name: str
    industry: str
    # 价格数据
    price: float           # 当前/最新收盘价
    ma5: float             # 5日均线
    ma20: float            # 20日均线
    ma60: float            # 60日均线
    ma120: float           # 120日均线
    price_vs_ma120_pct: float  # 价格相对MA120偏离%
    # 收益率
    ret_5d: float          # 5日收益率%
    ret_20d: float         # 20日收益率%
    # 波动
    atr14: float           # ATR14波动率
    volume_ratio: float    # 量比
    # 趋势
    trend_status: str      # 多头排列|空头排列|震荡
```

### 2.2 财务指标表 `stock_fina_indicator`

```sql
CREATE TABLE IF NOT EXISTS stock_fina_indicator (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    ts_code VARCHAR(20) NOT NULL COMMENT '股票代码',
    ann_date DATE COMMENT '公告日期',
    end_date DATE COMMENT '报告期',
    -- 估值指标
    pe DECIMAL(10,2) COMMENT '市盈率',
    pb DECIMAL(10,2) COMMENT '市净率',
    ps DECIMAL(10,2) COMMENT '市销率',
    -- 盈利能力
    roe DECIMAL(10,2) COMMENT '净资产收益率%',
    roe_dt DECIMAL(10,2) COMMENT '扣非ROE%',
    gross_margin DECIMAL(10,2) COMMENT '毛利率%',
    net_margin DECIMAL(10,2) COMMENT '净利率%',
    -- 成长性
    netprofit_yoy DECIMAL(10,2) COMMENT '净利润增速%',
    revenue_yoy DECIMAL(10,2) COMMENT '营收增速%',
    op_yoy DECIMAL(10,2) COMMENT '营业利润增速%',
    -- 财务健康
    debt_to_assets DECIMAL(10,2) COMMENT '资产负债率%',
    current_ratio DECIMAL(10,2) COMMENT '流动比率',
    quick_ratio DECIMAL(10,2) COMMENT '速动比率',
    -- 每股指标
    eps DECIMAL(10,4) COMMENT '每股收益',
    bps DECIMAL(10,4) COMMENT '每股净资产',
    ocfps DECIMAL(10,4) COMMENT '每股经营现金流',
    -- 运营效率
    ar_turn DECIMAL(10,2) COMMENT '应收账款周转率',
    inv_turn DECIMAL(10,2) COMMENT '存货周转率',
    assets_turn DECIMAL(10,2) COMMENT '资产周转率',
    -- 现金流
    ocf_to_or DECIMAL(10,2) COMMENT '经营现金流/营收%',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_code_date (ts_code, end_date),
    INDEX idx_ts_code (ts_code),
    INDEX idx_end_date (end_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='财务指标数据';
```

### 2.3 市场情绪表 `market_sentiment`

```sql
CREATE TABLE IF NOT EXISTS market_sentiment (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    trade_date DATE NOT NULL COMMENT '交易日期',
    -- 资金流向
    north_net_inflow DECIMAL(20,2) COMMENT '北向资金净流入(万)',
    south_net_inflow DECIMAL(20,2) COMMENT '南向资金净流入(万)',
    main_net_inflow DECIMAL(20,2) COMMENT '主力净流入(万)',
    -- 融资融券
    margin_balance DECIMAL(20,2) COMMENT '融资余额(万)',
    margin_balance_change DECIMAL(20,2) COMMENT '融资余额变化(万)',
    short_balance DECIMAL(20,2) COMMENT '融券余额(万)',
    -- 情绪指标
    limit_up_count INT COMMENT '涨停家数',
    limit_down_count INT COMMENT '跌停家数',
    advancing_count INT COMMENT '上涨家数',
    declining_count INT COMMENT '下跌家数',
    amplitude DECIMAL(10,2) COMMENT '市场振幅%',
    turnover_rate DECIMAL(10,2) COMMENT '市场换手率%',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_trade_date (trade_date),
    INDEX idx_trade_date (trade_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='市场情绪数据';
```

### 2.4 AI分析结果表 `stock_ai_analysis`

```sql
CREATE TABLE IF NOT EXISTS stock_ai_analysis (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    ts_code VARCHAR(20) NOT NULL COMMENT '股票代码',
    name VARCHAR(50) COMMENT '股票名称',
    source_provider VARCHAR(20) DEFAULT 'qianwen' COMMENT 'AI来源:qianwen|aihubmix|minimax',
    source_model VARCHAR(50) COMMENT '具体模型名',
    -- 分析阶段标记
    analysis_stage VARCHAR(20) DEFAULT 'stage1' COMMENT '分析阶段:stage1初筛|stage2深度',
    -- 原始数据
    raw_request TEXT COMMENT '原始请求JSON',
    raw_response TEXT COMMENT '原始响应JSON',
    -- 初筛评分
    stage1_score DECIMAL(5,2) COMMENT '阶段1评分0-100',
    stage1_action VARCHAR(20) COMMENT '阶段1动作:买入|观察|放弃',
    stage1_reason VARCHAR(200) COMMENT '阶段1理由',
    -- 多维评分
    tech_score DECIMAL(5,2) COMMENT '技术面得分0-100',
    fina_score DECIMAL(5,2) COMMENT '财务面得分0-100',
    sentiment_score DECIMAL(5,2) COMMENT '市场情绪得分0-100',
    trend_score DECIMAL(5,2) COMMENT '趋势得分0-100',
    risk_score DECIMAL(5,2) COMMENT '风险得分0-100',
    quality_score DECIMAL(5,2) COMMENT '质量得分0-100',
    -- 深度分析结果
    invest_status VARCHAR(50) COMMENT '投资状态:强烈推荐|值得投资|值得观察|暂不投资',
    valuation VARCHAR(20) COMMENT '估值:低估|合理|高估',
    tenbagger_potential_score DECIMAL(5,2) COMMENT '10倍股潜力评分0-100',
    -- 交易计划
    buy_range VARCHAR(50) COMMENT '买入区间',
    sell_range VARCHAR(50) COMMENT '卖出区间',
    stop_loss DECIMAL(10,2) COMMENT '止损价',
    position VARCHAR(20) COMMENT '仓位:轻仓|中仓|重仓',
    holding_period VARCHAR(50) COMMENT '持有周期',
    -- 逻辑说明
    reason VARCHAR(500) COMMENT '核心投资逻辑',
    tenbagger_logic VARCHAR(500) COMMENT '成长逻辑',
    risk_points VARCHAR(500) COMMENT '风险提示',
    industry_outlook VARCHAR(200) COMMENT '行业展望',
    competitiveness VARCHAR(200) COMMENT '竞争优势',
    -- 放弃原因
    action VARCHAR(20) DEFAULT '待分析' COMMENT '最终动作:买入|观察|放弃|待分析',
    reject_reason VARCHAR(200) COMMENT '放弃原因',
    -- 综合评分
    final_score DECIMAL(5,2) COMMENT '综合评分0-100',
    -- 元数据
    analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '分析时间',
    is_latest TINYINT DEFAULT 1 COMMENT '是否最新分析:1是|0历史',
    UNIQUE KEY uk_code_analyzed (ts_code, analyzed_at),
    INDEX idx_ts_code (ts_code),
    INDEX idx_final_score (final_score),
    INDEX idx_action (action),
    INDEX idx_analyzed_at (analyzed_at),
    INDEX idx_is_latest (is_latest)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI股票分析结果';
```

### 2.5 分析任务记录表 `stock_analysis_task`

```sql
CREATE TABLE IF NOT EXISTS stock_analysis_task (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    ts_code VARCHAR(20) NOT NULL COMMENT '股票代码',
    name VARCHAR(50) COMMENT '股票名称',
    status VARCHAR(20) DEFAULT 'pending' COMMENT '状态:pending|running|completed|failed|skipped',
    error_message TEXT COMMENT '错误信息',
    -- 分析配置
    skip_if_analyzed TINYINT DEFAULT 1 COMMENT '已分析过则跳过:1是|0否',
    last_analysis_date DATE COMMENT '上次分析日期',
    -- 时间戳
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    completed_at TIMESTAMP NULL COMMENT '完成时间',
    UNIQUE KEY uk_ts_code (ts_code),
    INDEX idx_status (status),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='分析任务记录';
```

---

## 三、提示词设计

### 3.1 阶段1-初筛提示词 `qianwen_score`

```json
{
    "name": "qianwen_score",
    "description": "批量初筛，严格淘汰",
    "system": "你是严格的量化选股筛选器。你的任务是从候选股票中筛选出真正值得投资的标的。\n\n## 核心原则\n- 你是悲观主义者，倾向于说\"不\"\n- 只有当股票明确满足所有好条件且没有一票否决问题时，才推荐\"买入\"\n- 均线突破只是选股起点，不代表值得买入\n\n## 买入条件（必须同时满足）\n1. 价格在MA120均线上方，乖离率 < 20%\n2. 趋势向上：近20日涨幅 > 5%\n3. 估值合理：PE < 50 或低于行业平均\n4. 基本面：ROE > 10% 或 净利润增速 > 15%\n\n## 一票否决条件（满足任一即放弃）\n1. PE > 100（估值泡沫）\n2. 价格乖离MA120 > 30%（追高风险）\n3. 近5日涨幅 > 20%（短期涨幅过大）\n4. 净利润连续2季度下滑\n5. 资产负债率 > 80%\n6. 量比 > 3倍（异动风险）\n7. ROE < 5%（盈利质量差）\n\n## 评分规则\n- 总分0-100，只给严格符合条件的股票打60分以上\n- 大多数股票应该打30-50分\n- 只有基本面优秀且估值合理的才给70+\n- 满足一票否决的直接打10分以下\n\n## 评分维度说明\n- tech_score: 技术面得分，关注趋势、均线、动量\n- fina_score: 财务面得分，关注盈利、成长、估值\n- sentiment_score: 情绪得分，关注资金流向、板块表现\n- trend_score: 趋势得分，关注中长期方向\n- risk_score: 风险得分，高分意味着风险低\n- quality_score: 质量得分，关注公司质地\n\n## 输出格式（严格JSON，不要markdown，不要任何其他内容）\n{\n  \"score\": 0-100整数,\n  \"action\": \"买入(60分+)|观察(30-59)|放弃(30分以下)\",\n  \"tech_score\": 0-100整数,\n  \"fina_score\": 0-100整数,\n  \"sentiment_score\": 0-100整数,\n  \"trend_score\": 0-100整数,\n  \"risk_score\": 0-100整数,\n  \"quality_score\": 0-100整数,\n  \"reason\": \"评分理由，不超过80字\",\n  \"reject_reason\": \"如果放弃，说明具体哪个否决条件，不超过40字\"\n}",
    "input_template": "## 股票特征数据\n\n### 基本信息\n- 股票代码: {ts_code}\n- 股票名称: {name}\n- 行业: {industry}\n\n### 技术面数据\n- 当前价格: {price}元\n- MA120均线: {ma120}元\n- 价格相对MA120偏离: {price_vs_ma120_pct}%\n- 近5日涨幅: {ret_5d}%\n- 近20日涨幅: {ret_20d}%\n- 量比: {volume_ratio}\n- ATR14波动率: {atr14}\n- 趋势状态: {trend_status}\n\n### 财务数据\n- 市盈率PE: {pe}\n- 市净率PB: {pb}\n- 净资产收益率ROE: {roe}%\n- 扣非ROE: {roe_dt}%\n- 毛利率: {gross_margin}%\n- 净利率: {net_margin}%\n- 净利润增速: {netprofit_yoy}%\n- 营收增速: {revenue_yoy}%\n- 资产负债率: {debt_to_assets}%\n- 流动比率: {current_ratio}\n- 速动比率: {quick_ratio}\n- 每股收益EPS: {eps}\n- 每股净资产BPS: {bps}\n- 经营现金流/营收: {ocf_to_or}%\n\n### 市场情绪\n- 北向资金净流入: {north_net_inflow}万\n- 融资余额变化: {margin_balance_change}万\n- 涨停家数(市场): {limit_up_count}\n- 上涨家数: {advancing_count}",
    "output_schema": {
        "score": "0-100整数",
        "action": "买入(60分+)|观察(30-59)|放弃(30分以下)",
        "tech_score": "0-100整数",
        "fina_score": "0-100整数",
        "sentiment_score": "0-100整数",
        "trend_score": "0-100整数",
        "risk_score": "0-100整数",
        "quality_score": "0-100整数",
        "reason": "评分理由，不超过80字",
        "reject_reason": "如果放弃，说明具体哪个否决条件，不超过40字"
    }
}
```

### 3.2 阶段2-深度分析提示词 `qianwen_deep`

```json
{
    "name": "qianwen_deep",
    "description": "深度分析，输出投资计划",
    "system": "你是资深投资分析师。请对候选股票进行深度基本面和技术面分析，输出详细的投资建议。\n\n## 分析维度\n\n### 1. 基本面分析\n- 盈利能力：ROE、毛利率、净利率趋势\n- 成长性：营收增速、净利润增速、行业发展空间\n- 估值：PE、PB、PS 当前水平及历史分位\n- 财务健康：资产负债率、现金流、偿债能力\n- 护城河：竞争优势、市场份额、品牌壁垒\n\n### 2. 技术面分析\n- 趋势判断：MA多头排列、均线支撑\n- 动量分析：近期涨跌幅、成交量配合\n- 位置判断：股价相对高低点、估值历史分位\n- 波动率：ATR反映的潜在涨跌幅度\n\n### 3. 行业与宏观\n- 行业景气度与政策环境\n- 宏观经济影响\n- 竞争对手分析\n\n### 4. 投资决策\n- 投资评级：强烈推荐/推荐/中性/回避\n- 估值判断：低估/合理/高估\n- 10倍股潜力评分(0-100)\n- 核心投资逻辑（为什么涨）\n\n### 5. 风险提示\n- 主要风险点\n- 潜在黑天鹅\n- 行业周期性风险\n\n### 6. 交易计划\n- 买入区间：给出具体价格区间\n- 卖出区间：止盈目标区间\n- 止损位：严格止损价格\n- 仓位建议：轻仓(10%)/中仓(20%)/重仓(30%)\n- 持有周期：短期(1-3月)/中期(3-12月)/长期(1年以上)\n\n## 输出格式（严格JSON，不要markdown）\n{\n  \"invest_status\": \"强烈推荐(10倍潜力)|值得投资|值得观察|暂不投资\",\n  \"valuation\": \"低估|合理|高估\",\n  \"tenbagger_potential_score\": 0-100整数,\n  \"buy_range\": \"xx-xx元\",\n  \"sell_range\": \"xx-xx元\",\n  \"stop_loss\": xx元,\n  \"position\": \"轻仓|中仓|重仓\",\n  \"holding_period\": \"短期|中期|长期\",\n  \"reason\": \"核心逻辑，不超过150字\",\n  \"tenbagger_logic\": \"成长逻辑，不超过200字\",\n  \"risk_points\": \"关键风险，不超过120字\",\n  \"industry_outlook\": \"行业展望，不超过100字\",\n  \"competitiveness\": \"竞争优势，不超过100字\"\n}",
    "input_template": "## 股票完整数据\n\n### 基本信息\n- 股票代码: {ts_code}\n- 股票名称: {name}\n- 行业: {industry}\n\n### 阶段1初筛结果\n- 初筛评分: {stage1_score}\n- 初筛动作: {stage1_action}\n- 初筛理由: {stage1_reason}\n\n### 技术面数据（近2年）\n- 当前价格: {price}元\n- MA5/MA20/MA60/MA120: {ma5}/{ma20}/{ma60}/{ma120}元\n- 价格相对MA120偏离: {price_vs_ma120_pct}%\n- 近5日涨幅: {ret_5d}%\n- 近20日涨幅: {ret_20d}%\n- 量比: {volume_ratio}\n- ATR14波动率: {atr14}元\n- 趋势状态: {trend_status}\n\n### 财务数据（最新财报）\n- PE: {pe}, PB: {pb}, PS: {ps}\n- ROE: {roe}%, 扣非ROE: {roe_dt}%\n- 毛利率: {gross_margin}%, 净利率: {net_margin}%\n- 净利润增速: {netprofit_yoy}%, 营收增速: {revenue_yoy}%\n- 资产负债率: {debt_to_assets}%, 流动比率: {current_ratio}\n- 每股收益: {eps}元, 每股净资产: {bps}元\n- 经营现金流/营收: {ocf_to_or}%\n- 应收账款周转率: {ar_turn}, 存货周转率: {inv_turn}\n\n### 市场情绪\n- 北向资金: {north_net_inflow}万\n- 融资余额变化: {margin_balance_change}万\n- 市场涨停家数: {limit_up_count}\n- 上涨/下跌家数: {advancing_count}/{declining_count}\n\n### 趋势评分详情\n- 技术面: {tech_score}分\n- 财务面: {fina_score}分\n- 情绪面: {sentiment_score}分\n- 趋势面: {trend_score}分\n- 风险面: {risk_score}分\n- 质量面: {quality_score}分",
    "output_schema": {
        "invest_status": "强烈推荐(10倍潜力)|值得投资|值得观察|暂不投资",
        "valuation": "低估|合理|高估",
        "tenbagger_potential_score": "0-100整数",
        "buy_range": "\"xx-xx元\"",
        "sell_range": "\"xx-xx元\"",
        "stop_loss": "xx元数字",
        "position": "轻仓|中仓|重仓",
        "holding_period": "短期|中期|长期",
        "reason": "核心逻辑，不超过150字",
        "tenbagger_logic": "成长逻辑，不超过200字",
        "risk_points": "关键风险，不超过120字",
        "industry_outlook": "行业展望，不超过100字",
        "competitiveness": "竞争优势，不超过100字"
    }
}
```

---

## 四、数据获取与缓存策略

### 4.1 Tushare API 限流
- 每分钟最多调用 200 次
- 单次调用间隔 ≥ 1 秒
- 批量获取时加延迟

### 4.2 缓存策略
| 数据类型 | 缓存有效期 | 更新条件 |
|---------|-----------|---------|
| 财务指标 | 30天 | 数据有更新时提前更新 |
| K线数据 | 实时 | 每日收盘后更新 |
| 市场情绪 | 1天 | 每日收盘后更新 |

### 4.3 缓存目录
```
data/
├── tushare_cache/
│   ├── fina_indicator/
│   │   └── {ts_code}.parquet    # 财务指标缓存
│   ├── income/
│   │   └── {ts_code}.parquet    # 利润表缓存
│   ├── balancesheet/
│   │   └── {ts_code}.parquet    # 资产负债表缓存
│   └── cashflow/
│       └── {ts_code}.parquet    # 现金流量表缓存
```

---

## 五、分析流程设计

### 5.1 单股票分析流程

```
analyze_stock(ts_code)
│
├─ 1. [检查] 是否已分析过且在30天内？
│   └─ 是 → 打印日志"已分析，跳过" → return
│
├─ 2. [构建特征]
│   ├─ 技术面: 从 stock_kline 读取，计算指标
│   ├─ 财务面: 从 stock_fina_indicator 读取
│   └─ 情绪面: 从 market_sentiment 读取
│
├─ 3. [阶段1-千问初筛]
│   ├─ 输入: 组合特征JSON
│   ├─ Prompt: qianwen_score
│   ├─ 日志: 打印原始请求+响应
│   └─ 判断: score >= 80 → 进入阶段2
│           score < 80 → 标记放弃+原因 → return
│
├─ 4. [阶段2-千问深度分析]
│   ├─ 输入: 完整特征 + 阶段1结果
│   ├─ Prompt: qianwen_deep
│   ├─ 日志: 打印原始请求+响应
│   └─ 输出: invest_status + 交易计划
│
├─ 5. [入库]
│   ├─ 写入 stock_ai_analysis
│   └─ 更新 stock_analysis_task
│
└─ 6. [返回] 结构化分析结果
```

### 5.2 批量分析流程

```
analyze_batch(csv_file, limit=50)
│
├─ 1. [读取] 从CSV读取股票列表
│
├─ 2. [过滤] 检查是否已分析过
│   └─ 已分析且30天内 → 跳过
│
├─ 3. [循环] 对每只股票执行 analyze_stock
│   ├─ 打印股票序号 "分析中 1/42: 600036"
│   ├─ 完整日志输出
│   └─ 阶段1被淘汰 → 打印"淘汰原因"
│
├─ 4. [汇总] 打印分析统计
│   └─ 通过阶段1: X只, 进入深度分析: Y只, 买入推荐: Z只
│
└─ 5. [通知] 发送飞书汇总（可选）
```

---

## 六、日志输出设计

### 6.1 日志级别与格式

```python
# 使用 Python logging，格式统一
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"

# 日志内容示例
[INFO] ====== 开始分析: 600036 招商银行 ======
[INFO] [特征构建] 技术面: 价格=35.50, MA120=32.50, 乖离=+9.2%
[INFO] [特征构建] 财务面: PE=5.8, ROE=11.2%, 净利润增速=15.3%
[INFO] [阶段1请求] 千问初筛
[INFO] [阶段1原始返回] {...}
[INFO] [阶段1解析] score=85, action=买入
[INFO] [阶段2请求] 千问深度分析
[INFO] [阶段2原始返回] {...}
[INFO] [阶段2解析] invest_status=值得投资, buy_range=32-38元
[INFO] [入库] stock_ai_analysis id=123
[INFO] ====== 分析完成: 600036 招商银行 ======

# 被淘汰的日志
[INFO] ====== 开始分析: 688001 华兴源创 ======
[INFO] [阶段1解析] score=15, action=放弃
[INFO] [淘汰原因] PE>100(估值泡沫), ROE<5%
[INFO] ====== 分析完成: 688001 (已淘汰) ======
```

### 6.2 日志文件
```
logs/
├── cy_ai_analysis_YYYYMMDD.log    # 每日分析日志
└── cy_ai_error_YYYYMMDD.log        # 错误日志
```

---

## 七、目录结构

```
cy_ai/
├── prompts.json                    # 所有提示词配置
├── prompts.py                      # 提示词加载器
├── tushare_fetcher.py              # Tushare数据获取+缓存
├── qianwen_api.py                  # 千问API调用
├── analyzer_agent.py               # Agent交互式分析器
├── local_features.py               # 本地K线特征提取
├── db.py                           # 数据库操作
├── config.py                       # 配置加载
├── monitor.py                      # 监控服务
├── notify.py                       # 飞书通知
├── pool_manager.py                 # 池管理
├── main.py                         # 主入口
└── README.md                        # 使用文档

data/
└── tushare_cache/                  # Tushare数据缓存

logs/
├── cy_ai_analysis_YYYYMMDD.log
└── cy_ai_error_YYYYMMDD.log
```

---

## 八、实现优先级

### Phase 1: 核心功能
1. [ ] prompts.json + prompts.py（提示词管理）
2. [ ] tushare_fetcher.py（数据获取+缓存）
3. [ ] qianwen_api.py（千问API调用）
4. [ ] local_features.py 扩展（特征构建）
5. [ ] db.py 扩展（新表结构）
6. [ ] analyzer_agent.py（主分析逻辑）
7. [ ] main.py 集成

### Phase 2: 增强功能
8. [ ] 本地K线导入到 stock_kline 表
9. [ ] 财务数据定时同步
10. [ ] 飞书通知集成

### Phase 3: 高级功能
11. [ ] 市场情绪数据获取
12. [ ] 监控池自动同步
13. [ ] 定时任务集成

---

## 九、配置项

### todolist/config.json
```json
{
    "tushare_token": "your_token",
    "qianwen_api_key": "your_key",
    "feishu_webhook_url": "",
    "analysis_threshold": 80,
    "cache_days": {
        "fina_indicator": 30,
        "kline": 0,
        "sentiment": 1
    }
}
```

### prompts.json
```json
{
    "qianwen_score": {...},
    "qianwen_deep": {...}
}
```
