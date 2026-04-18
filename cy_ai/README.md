# 股票池 AI 分析与监控系统

基于 AIHubMix + MiniMax 两阶段分析的股票筛选系统，支持监控池管理和飞书通知。

## 功能特性

- **两阶段 AI 分析**: AIHubMix 批量初筛 + MiniMax 深度分析
- **多市场支持**: A股、港股、美股
- **监控池管理**: 自动同步高分股票到监控池
- **实时告警**: 价格触发条件时通过飞书通知
- **买卖计划**: 包含买入区间、止损位、目标价

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                    完整流程                                  │
│                                                             │
│  CSV ──▶ DB(一级筛选池) ──▶ AIHubMix初筛 ──▶ MiniMax深度分析 │
│                                     │                        │
│                                     ▼                        │
│                            同步 Top 100 到监控池              │
│                                     │                        │
│                                     ▼                        │
│                            发送飞书周报通知                    │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                    实时监控流程                              │
│                                                             │
│  定时扫描监控池（每30分钟）──▶ 获取实时价格 ──▶ 价格触发告警？ │
│                                          │                  │
│                                          是                  │
│                                          ▼                  │
│                                 发送飞书通知                  │
└─────────────────────────────────────────────────────────────┘
```

## 目录结构

```
cy_ai/
├── __init__.py           # 包初始化
├── main.py              # 主入口
├── db.py                # 数据库模块
├── csv_importer.py      # CSV导入
├── local_features.py    # 特征提取
├── minimax_api.py       # MiniMax API
├── analyzer.py          # 分析器
├── aihubmix_api.py      # AIHubMix API（新增）
├── monitor.py           # 监控服务（新增）
├── notify.py            # 飞书通知（新增）
└── pool_manager.py      # 股票池管理（新增）
```

## 安装

```bash
pip install -r requirements.txt
```

依赖包括：
- akshare（获取实时行情）
- pymysql（数据库连接）
- requests（HTTP 请求）

## 配置

所有配置统一从 `todolist/config.json` 读取：

```json
{
  "aihubmix_api_key": "your-api-key",
  "aihubmix_model": "glm-4-flash",

  "minimax_api_key": "your-api-key",

  "deepseek_api_key": "your-api-key",
  "doubao_api_key": "",

  "feishu_webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/xxx",
  "ma120_pool_csv": "/path/to/ma120_pool.csv",
  "monitor_interval_minutes": 30
}
```

| 字段 | 说明 |
|------|------|
| `aihubmix_api_key` | AIHubMix API Key（用于初筛） |
| `aihubmix_model` | AIHubMix 模型，默认 `glm-4-flash` |
| `minimax_api_key` | MiniMax API Key（用于深度分析） |
| `deepseek_api_key` | DeepSeek API Key（备用） |
| `doubao_api_key` | 豆包 API Key（备用） |
| `feishu_webhook_url` | 飞书 Webhook URL |
| `ma120_pool_csv` | 一级筛选池 CSV 文件路径 |
| `monitor_interval_minutes` | 监控扫描间隔（分钟），默认 30 |

## 使用方法

### 运行每周分析

```bash
python -m cy_ai.main weekly
```

执行流程：
1. 导入一级筛选池（CSV → DB）
2. AIHubMix 阶段1初筛
3. MiniMax 阶段2深度分析（Top 20）
4. 同步到监控池
5. 发送飞书周报通知

### 启动监控服务

```bash
python -m cy_ai.main monitor
```

启动后台监控服务，每30分钟扫描监控池，价格触发条件时发送飞书告警。

### 执行单次扫描

```bash
python -m cy_ai.main scan
```

立即执行一次监控扫描，输出扫描结果。

### 单股测试分析

使用 AIHubMix 对单只股票进行快速评分测试：

```python
python3 -c "
from cy_ai.aihubmix_api import AIHubMixAPI
import json

api = AIHubMixAPI()

test_stock = {
    'ts_code': '600036',
    'name': '招商银行',
    'industry': '银行',
    'price': 35.50,
    'ma20': 34.20,
    'ma60': 33.80,
    'ma120': 32.50,
    'price_vs_ma120': '+9.2%',
    'ret_5d': 2.3,
    'ret_20d': 8.5,
    'volume_ratio': 1.35,
    'pe': 5.8,
    'pb': 0.65,
    'roe': 11.2,
}

result = api.score_stock(test_stock)
print(json.dumps(result, ensure_ascii=False, indent=2))
"
```

输出示例：

```json
{
  "score": 85,
  "trend_score": 90,
  "risk_score": 70,
  "quality_score": 80,
  "action": "买入",
  "short_reason": "趋势向上，估值合理，盈利能力强"
}
```

## 数据库表

### stock_pool_ma120（一级筛选池）
- 120日均线突破股票池
- 字段：ts_code, name, industry, break_date, status

### stock_ai_analysis（AI分析结果）
- AI 分析结果存储
- 字段：invest_status, valuation, tenbagger_potential_score, buy_range, sell_range, risk_points 等
- 新增字段：analysis_stage, stage1_score, trend_score, risk_score, quality_score

### stock_watch_pool（监控池）
- 需要监控的股票池
- 字段：
  - ai_verdict, ai_confidence, ai_summary（AI评级）
  - buy_zone_low/high/ideal（买入区间）
  - sell_zone_conservative/aggressive（目标价）
  - stop_loss（止损价）
  - alert_config（告警配置）
  - current_price, watch_status（当前状态）

## 告警配置

监控池中的 `alert_config` 字段支持以下配置：

```json
{
  "enable_price_alert": true,
  "price_alert_type": "in_buy_zone",
  "alert_cooldown_hours": 24
}
```

告警类型：
- `below_ideal`: 价格低于理想买入价
- `in_buy_zone`: 价格进入买入区间
- `above_target`: 价格高于目标价
- `below_stop_loss`: 价格低于止损价

## 飞书消息示例

### 买入提醒
```
✅ 买入提醒：招商银行（600036）

📊 当前价格：35.20
🎯 买入区间：34.00 ~ 36.00
✅ 当前价格已进入买入区间！

理想买入价：35.00
止损价：32.00
```

### 止损提醒
```
🚨 止损提醒：招商银行（600036）

⚠️ 当前价格：31.50
🔴 止损价：32.00
⚠️ 价格已触及止损价！

建议：严格止损，控制风险
```

### 每周分析摘要
```
## 📈 股票池 AI 分析完成

### 分析统计
- 一级筛选池：120 只
- AIHubMix 初筛通过：待确认
- MiniMax 深度分析：20 只
- 入监控池：15 只

### 🎯 Top 推荐
1. 贵州茅台 - 评分 85
2. 招商银行 - 评分 78
3. ...

---
由 AI 自动生成，仅供参考，不构成投资建议
```

## 许可证

MIT
