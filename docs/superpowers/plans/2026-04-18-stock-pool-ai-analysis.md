# 股票池 AI 分析与监控系统实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现基于 AIHubMix + MiniMax 两阶段分析的股票筛选系统，包含监控池管理和飞书通知功能。

**Architecture:** 采用两阶段 AI 分析架构——第一阶段使用 AIHubMix 低成本批量筛选，第二阶段使用 MiniMax 对高分股票深度分析。分析结果同步到监控池，通过定时扫描触发飞书告警通知。

**Tech Stack:** Python 3.10+, akshare, Tushare, AIHubMix API, MiniMax API, MySQL, 飞书 Webhook

---

## 文件结构设计

```
cy_ai/
├── __init__.py                    # 包初始化
├── main.py                        # 主入口（已存在，需修改）
├── db.py                          # 数据库模块（已存在，需增强）
├── csv_importer.py                # CSV导入（已存在）
├── local_features.py               # 特征提取（已存在，需增强）
├── minimax_api.py                 # MiniMax API（已存在）
├── superpowers_ai.py              # 两阶段AI分析（已存在）
├── analyzer.py                    # 分析器（已存在）
├── aihubmix_api.py                # [新建] AIHubMix API 封装
├── monitor.py                     # [新建] 监控服务
├── notify.py                      # [新建] 飞书通知模块
├── pool_manager.py                # [新建] 股票池管理器
└── commands.py                    # [新建] 命令行管理工具

docs/superpowers/plans/
└── 2026-04-18-stock-pool-ai-analysis.md  # 本计划文档
```

---

## Task 1: 创建 AIHubMix API 封装

**Files:**
- Create: `cy_ai/aihubmix_api.py`

- [ ] **Step 1: 创建 aihubmix_api.py 文件**

```python
"""
AIHubMix API 调用封装
用于低成本批量股票初筛
"""

import json
import logging
import os
import time
from typing import Dict, Any, Optional

import requests

logger = logging.getLogger(__name__)


class AIHubMixConfig:
    """AIHubMix API 配置"""

    API_URL = os.getenv(
        "AIHUBMIX_BASE_URL",
        "https://aihubmix.com/v1/chat/completions"
    )
    MODEL = os.getenv("AIHUBMIX_MODEL", "glm-4-flash")
    API_KEY = os.getenv("AIHUBMIX_API_KEY", "")
    TIMEOUT = 60
    MAX_RETRIES = 3
    RETRY_DELAY = 3


class AIHubMixAPI:
    """AIHubMix API 调用封装类"""

    SCORE_PROMPT = """你是量化选股打分助手。请根据股票特征数据给出评分。

评分维度：
- 趋势得分(0-100)：均线多头排列、趋势向上、成交量配合
- 风险得分(0-100)：估值高低、基本面风险、技术面风险
- 质量得分(0-100)：ROE、盈利能力、成长性

最终动作：买入/观察/放弃

严格输出JSON（不要markdown，不要任何其他内容）：
{
  "score": 0-100整数,
  "trend_score": 0-100整数,
  "risk_score": 0-100整数,
  "quality_score": 0-100整数,
  "action": "买入|观察|放弃",
  "short_reason": "不超过60字"
}"""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or AIHubMixConfig.API_KEY
        self.model = model or AIHubMixConfig.MODEL
        self.api_url = AIHubMixConfig.API_URL

        if not self.api_key:
            raise ValueError("AIHubMix API Key 未设置，请设置环境变量 AIHUBMIX_API_KEY")

    def _call_api(self, messages: list, temperature: float = 0.0) -> Optional[str]:
        """调用 AIHubMix API"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }

        for attempt in range(AIHubMixConfig.MAX_RETRIES):
            try:
                response = requests.post(
                    self.api_url,
                    headers=headers,
                    json=payload,
                    timeout=AIHubMixConfig.TIMEOUT
                )
                if response.status_code == 200:
                    data = response.json()
                    choices = data.get("choices", [])
                    if choices:
                        content = choices[0].get("message", {}).get("content", "")
                        return content
                else:
                    logger.warning(f"API 返回错误 {response.status_code}: {response.text[:200]}")
            except Exception as e:
                logger.warning(f"API 调用异常: {e}")
            if attempt < AIHubMixConfig.MAX_RETRIES - 1:
                time.sleep(AIHubMixConfig.RETRY_DELAY)
        return None

    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        """从响应中提取 JSON"""
        if not text:
            return None
        text = text.strip()
        # 移除 markdown 代码块
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:] if lines[0].startswith("```") else lines)
            if text.endswith("```"):
                text = text[:-3]
        # 找 JSON 对象
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end+1])
            except json.JSONDecodeError:
                return None
        return None

    def score_stock(self, stock_payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        对单只股票进行评分

        :param stock_payload: 股票特征数据
        :return: 评分结果
        """
        user_message = self.SCORE_PROMPT + "\n\n股票数据:\n" + json.dumps(stock_payload, ensure_ascii=False)
        messages = [{"role": "user", "content": user_message}]

        content = self._call_api(messages, temperature=0.0)
        if content:
            return self._extract_json(content)
        return None

    def score_stocks_batch(self, stocks: list, delay: float = 1.0) -> Dict[str, Optional[Dict[str, Any]]]:
        """
        批量评分股票

        :param stocks: 股票列表
        :param delay: 每次调用间隔（秒）
        :return: {ts_code: result} 字典
        """
        results = {}
        for i, stock in enumerate(stocks, 1):
            ts_code = stock.get("ts_code", f"unknown_{i}")
            logger.info(f"评分中 {i}/{len(stocks)}: {ts_code}")
            result = self.score_stock(stock)
            results[ts_code] = result
            if i < len(stocks) and result:
                time.sleep(delay)
        return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    api = AIHubMixAPI()
    test_stock = {
        "ts_code": "600036",
        "name": "招商银行",
        "industry": "银行",
        "price": 35.50,
        "ma20": 34.20,
        "ma60": 33.80,
        "ma120": 32.50,
        "price_vs_ma120": "+9.2%",
        "ret_5d": 2.3,
        "ret_20d": 8.5,
        "volume_ratio": 1.35,
        "pe": 5.8,
        "pb": 0.65,
        "roe": 11.2,
    }
    result = api.score_stock(test_stock)
    print("评分结果:", json.dumps(result, ensure_ascii=False, indent=2))
```

- [ ] **Step 2: 运行测试验证**

```bash
cd /Users/water/mylearn/PycharmProjects/abu-master
python -c "from cy_ai.aihubmix_api import AIHubMixAPI; print('AIHubMix API 模块导入成功')"
```

Expected: 输出 "AIHubMix API 模块导入成功"

- [ ] **Step 3: 提交代码**

```bash
git add cy_ai/aihubmix_api.py
git commit -m "feat(cy_ai): add AIHubMix API wrapper for stock screening"
```

---

## Task 2: 增强数据库表结构

**Files:**
- Modify: `cy_ai/db.py:112-162`

- [ ] **Step 1: 添加监控池表结构到 db.py**

找到 `TABLE_SCHEMAS` 字典，在其末尾添加新表：

```python
    "stock_watch_pool": """
        CREATE TABLE IF NOT EXISTS stock_watch_pool (
            id INT AUTO_INCREMENT PRIMARY KEY,
            ts_code VARCHAR(20) NOT NULL COMMENT '股票代码',
            name VARCHAR(50) COMMENT '股票名称',
            industry VARCHAR(50) COMMENT '行业',
            market VARCHAR(10) COMMENT '市场：A股/港股/美股',

            ai_verdict VARCHAR(20) COMMENT 'AI评级：强烈推荐/推荐/观望',
            ai_confidence INT COMMENT 'AI置信度0-100',
            ai_summary TEXT COMMENT 'AI一句话总结',

            buy_zone_low DECIMAL(10,2) COMMENT '建议买入价下限',
            buy_zone_high DECIMAL(10,2) COMMENT '建议买入价上限',
            buy_zone_ideal DECIMAL(10,2) COMMENT '理想买入价',

            sell_zone_conservative DECIMAL(10,2) COMMENT '保守目标价',
            sell_zone_aggressive DECIMAL(10,2) COMMENT '激进目标价',
            stop_loss DECIMAL(10,2) COMMENT '止损价',

            alert_config JSON COMMENT '告警配置',
            current_price DECIMAL(10,2) COMMENT '最新价格',
            price_updated_at DATETIME COMMENT '价格更新时间',
            watch_status VARCHAR(20) DEFAULT 'active' COMMENT '监控状态：active/paused/removed',

            buy_signal_sent TINYINT DEFAULT 0 COMMENT '是否已发送买入提醒',
            sell_signal_sent TINYINT DEFAULT 0 COMMENT '是否已发送卖出提醒',
            last_alert_at DATETIME COMMENT '最后提醒时间',

            added_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '入池时间',
            added_source VARCHAR(20) COMMENT '入池来源：manual/ai_analysis',
            recheck_date DATE COMMENT 'AI建议复查日期',
            analyzed_at DATETIME COMMENT 'AI分析时间',
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

            UNIQUE KEY uk_ts_code (ts_code),
            INDEX idx_watch_status (watch_status),
            INDEX idx_recheck_date (recheck_date)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='股票监控池'
    """,
```

- [ ] **Step 2: 为 stock_ai_analysis 表添加新字段**

找到 `stock_ai_analysis` 表定义，在 `is_valid` 字段后添加：

```python
            is_valid TINYINT DEFAULT 1 COMMENT '是否有效',
            analysis_stage TINYINT DEFAULT 1 COMMENT '分析阶段：1=初筛，2=深度',
            stage1_score INT COMMENT '阶段1评分',
            stage1_action VARCHAR(20) COMMENT '阶段1动作：买入/观察/放弃',
            trend_score INT COMMENT '趋势评分0-100',
            risk_score INT COMMENT '风险评分0-100',
            quality_score INT COMMENT '质量评分0-100',
```

- [ ] **Step 3: 测试数据库初始化**

```bash
cd /Users/water/mylearn/PycharmProjects/abu-master
python -c "
from cy_ai.db import Database, init_tables
db = Database()
init_tables(db)
print('数据库表初始化成功')
db.close()
"
```

Expected: 输出 "数据库表初始化成功"

- [ ] **Step 4: 提交代码**

```bash
git add cy_ai/db.py
git commit -m "feat(cy_ai): add stock_watch_pool table and analysis stage fields"
```

---

## Task 3: 创建飞书通知模块

**Files:**
- Create: `cy_ai/notify.py`

- [ ] **Step 1: 创建 notify.py**

```python
"""
飞书通知模块
"""

import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class FeishuNotifier:
    """飞书 Webhook 通知器"""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send(self, message: str, msg_type: str = "text") -> bool:
        """
        发送飞书消息

        :param message: 消息内容
        :param msg_type: 消息类型，text 或 markdown
        :return: 是否发送成功
        """
        if msg_type == "markdown":
            payload = {
                "msg_type": "markdown",
                "content": {"text": message}
            }
        else:
            payload = {
                "msg_type": "text",
                "content": {"text": message}
            }

        try:
            response = requests.post(self.webhook_url, json=payload, timeout=10)
            if response.status_code == 200:
                logger.info("飞书通知发送成功")
                return True
            else:
                logger.warning(f"飞书通知发送失败: {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"飞书通知发送异常: {e}")
            return False

    def send_stock_alert(self, stock: dict, alert_type: str, current_price: float) -> bool:
        """
        发送股票告警消息

        :param stock: 股票信息
        :param alert_type: 告警类型
        :param current_price: 当前价格
        :return: 是否发送成功
        """
        name = stock.get("name", "")
        ts_code = stock.get("ts_code", "")
        ideal = stock.get("buy_zone_ideal", 0)
        buy_low = stock.get("buy_zone_low", 0)
        buy_high = stock.get("buy_zone_high", 0)
        target = stock.get("sell_zone_conservative", 0)
        stop = stock.get("stop_loss", 0)

        if alert_type == "buy_below_ideal":
            title = "✅ 买入提醒"
            content = f"""**{title}：{name}（{ts_code}）**

📉 当前价格：{current_price}
💰 理想买入价：{ideal}
📊 当前价格已低于理想买入价，适合关注！

买入区间：{buy_low} ~ {buy_high}
止损价：{stop}"""
        elif alert_type == "buy_in_zone":
            title = "✅ 买入提醒"
            content = f"""**{title}：{name}（{ts_code}）**

📊 当前价格：{current_price}
🎯 买入区间：{buy_low} ~ {buy_high}
✅ 当前价格已进入买入区间！

理想买入价：{ideal}
止损价：{stop}"""
        elif alert_type == "sell_above_target":
            title = "🏆 目标达成"
            content = f"""**{title}：{name}（{ts_code}）**

📈 当前价格：{current_price}
🎯 目标价：{target}
✅ 当前价格已超过目标价！

激进目标价：{stock.get('sell_zone_aggressive', 0)}
建议：可考虑分批卖出"""
        elif alert_type == "stop_loss_hit":
            title = "🚨 止损提醒"
            content = f"""**{title}：{name}（{ts_code}）**

⚠️ 当前价格：{current_price}
🔴 止损价：{stop}
⚠️ 价格已触及止损价！

建议：严格止损，控制风险"""
        else:
            content = f"📢 **{name}（{ts_code}）告警：{alert_type}**"

        return self.send(content, msg_type="markdown")

    def send_weekly_summary(self, stage1_count: int, stage2_count: int, watch_pool_count: int, top_stocks: list) -> bool:
        """
        发送每周分析摘要

        :param stage1_count: 阶段1分析数量
        :param stage2_count: 阶段2深度分析数量
        :param watch_pool_count: 入监控池数量
        :param top_stocks: Top 股票列表
        :return: 是否发送成功
        """
        content = f"""## 📈 股票池 AI 分析完成

### 分析统计
- 一级筛选池：{stage1_count} 只
- AIHubMix 初筛通过：待确认
- MiniMax 深度分析：{stage2_count} 只
- 入监控池：{watch_pool_count} 只

### 🎯 Top 推荐

"""
        for i, stock in enumerate(top_stocks[:5], 1):
            content += f"{i}. {stock.get('name', '')}（{stock.get('ts_code', '')}）- 评分 {stock.get('ai_confidence', 0)}\n"

        content += """
---
由 AI 自动生成，仅供参考，不构成投资建议
"""
        return self.send(content, msg_type="markdown")


if __name__ == "__main__":
    import os
    webhook = os.getenv("FEISHU_WEBHOOK_URL", "")
    if webhook:
        notifier = FeishuNotifier(webhook)
        result = notifier.send("🔔 测试消息：飞书通知模块正常工作")
        print("发送成功" if result else "发送失败")
    else:
        print("未配置 FEISHU_WEBHOOK_URL，跳过测试")
```

- [ ] **Step 2: 测试模块导入**

```bash
cd /Users/water/mylearn/PycharmProjects/abu-master
python -c "from cy_ai.notify import FeishuNotifier; print('飞书通知模块导入成功')"
```

- [ ] **Step 3: 提交代码**

```bash
git add cy_ai/notify.py
git commit -m "feat(cy_ai): add Feishu notifier for alerts and weekly summary"
```

---

## Task 4: 创建监控服务

**Files:**
- Create: `cy_ai/monitor.py`

- [ ] **Step 1: 创建 monitor.py**

```python
"""
股票监控服务
定时扫描监控池，触发告警时发送飞书通知
"""

import logging
import os
import time
from datetime import datetime, timedelta
from enum import Enum
from threading import Thread
from typing import Dict, Any, Optional

import akshare as ak

from .db import Database
from .notify import FeishuNotifier

logger = logging.getLogger(__name__)


class AlertType(Enum):
    BUY_BELOW_IDEAL = "buy_below_ideal"
    BUY_IN_ZONE = "buy_in_zone"
    SELL_ABOVE_TARGET = "sell_above_target"
    STOP_LOSS_HIT = "stop_loss_hit"


class PriceMonitor:
    """价格监控器"""

    def __init__(self, db: Database):
        self.db = db

    def get_watch_pool(self, status: str = "active") -> list:
        """获取监控列表"""
        sql = """
            SELECT * FROM stock_watch_pool 
            WHERE watch_status = %s 
            ORDER BY ai_confidence DESC
        """
        return self.db.query_all(sql, (status,))

    def get_current_price(self, ts_code: str, market: str) -> Optional[float]:
        """获取股票实时价格"""
        try:
            # 统一处理代码格式
            code = ts_code.split(".")[0] if "." in ts_code else ts_code

            if market in ["A股", "SH", "SZ"]:
                stock_info = ak.stock_zh_a_spot_em()
                row = stock_info[stock_info["代码"] == code]
                if not row.empty:
                    return float(row.iloc[0]["最新价"])

            elif market in ["港股", "HK"]:
                stock_hk = ak.stock_hk_spot_em()
                row = stock_hk[stock_hk["代码"] == code]
                if not row.empty:
                    return float(row.iloc[0]["最新价"])

            elif market in ["美股", "US"]:
                stock_us = ak.stock_us_spot()
                row = stock_us[stock_us["代码"] == code.upper()]
                if not row.empty:
                    return float(row.iloc[0]["最新价"])

        except Exception as e:
            logger.error(f"获取价格失败 {ts_code}: {e}")
        return None

    def check_alert(self, stock: Dict[str, Any], current_price: float) -> Optional[AlertType]:
        """检查是否触发告警"""
        config = stock.get("alert_config") or {}
        if not config.get("enable_price_alert", True):
            return None

        alert_type_str = config.get("price_alert_type", "below_ideal")
        cooldown_hours = config.get("alert_cooldown_hours", 24)
        last_alert = stock.get("last_alert_at")

        # 检查冷却期
        if last_alert:
            if datetime.now() - last_alert < timedelta(hours=cooldown_hours):
                return None

        # 价格判断
        if alert_type_str == "below_ideal":
            ideal = float(stock.get("buy_zone_ideal") or 0)
            if ideal > 0 and current_price <= ideal:
                return AlertType.BUY_BELOW_IDEAL

        elif alert_type_str == "in_buy_zone":
            low = float(stock.get("buy_zone_low") or 0)
            high = float(stock.get("buy_zone_high") or 0)
            if low > 0 and high > 0 and low <= current_price <= high:
                return AlertType.BUY_IN_ZONE

        elif alert_type_str == "above_target":
            target = float(stock.get("sell_zone_conservative") or 0)
            if target > 0 and current_price >= target:
                return AlertType.SELL_ABOVE_TARGET

        elif alert_type_str == "below_stop_loss":
            stop = float(stock.get("stop_loss") or 0)
            if stop > 0 and current_price <= stop:
                return AlertType.STOP_LOSS_HIT

        return None

    def update_price(self, ts_code: str, price: float):
        """更新最新价格"""
        sql = """
            UPDATE stock_watch_pool 
            SET current_price = %s, price_updated_at = NOW() 
            WHERE ts_code = %s
        """
        self.db.execute(sql, (price, ts_code))
        self.db.commit()

    def mark_alert_sent(self, ts_code: str, alert_type: AlertType):
        """标记告警已发送"""
        now = datetime.now()
        if alert_type in [AlertType.BUY_BELOW_IDEAL, AlertType.BUY_IN_ZONE]:
            sql = "UPDATE stock_watch_pool SET buy_signal_sent = 1, last_alert_at = %s WHERE ts_code = %s"
        elif alert_type == AlertType.SELL_ABOVE_TARGET:
            sql = "UPDATE stock_watch_pool SET sell_signal_sent = 1, last_alert_at = %s WHERE ts_code = %s"
        else:
            sql = "UPDATE stock_watch_pool SET last_alert_at = %s WHERE ts_code = %s"
        self.db.execute(sql, (now, ts_code))
        self.db.commit()


class StockMonitor:
    """股票监控服务主类"""

    def __init__(self, feishu_webhook: str):
        self.db = Database()
        self.price_monitor = PriceMonitor(self.db)
        self.notifier = FeishuNotifier(feishu_webhook) if feishu_webhook else None
        self.is_running = False

    def scan(self) -> Dict[str, Any]:
        """扫描监控池"""
        watch_list = self.price_monitor.get_watch_pool()
        results = {"total": len(watch_list), "alerts": [], "errors": []}

        for stock in watch_list:
            ts_code = stock["ts_code"]
            market = stock.get("market", "A股")

            try:
                current_price = self.price_monitor.get_current_price(ts_code, market)
                if current_price is None:
                    results["errors"].append(f"{ts_code}: 获取价格失败")
                    continue

                self.price_monitor.update_price(ts_code, current_price)

                alert_type = self.price_monitor.check_alert(stock, current_price)
                if alert_type and self.notifier:
                    self.notifier.send_stock_alert(stock, alert_type.value, current_price)
                    self.price_monitor.mark_alert_sent(ts_code, alert_type)
                    results["alerts"].append({
                        "ts_code": ts_code,
                        "name": stock.get("name"),
                        "alert_type": alert_type.value,
                        "price": current_price
                    })

            except Exception as e:
                logger.error(f"扫描失败 {ts_code}: {e}")
                results["errors"].append(f"{ts_code}: {str(e)}")

        return results

    def start(self, interval_minutes: int = 30):
        """启动监控服务"""
        self.is_running = True

        def run():
            while self.is_running:
                logger.info("开始扫描监控池...")
                results = self.scan()
                logger.info(f"扫描完成：共{results['total']}只，触发告警{len(results['alerts'])}个")
                time.sleep(interval_minutes * 60)

        thread = Thread(target=run, daemon=True)
        thread.start()
        logger.info(f"监控服务已启动，每{interval_minutes}分钟扫描一次")

    def stop(self):
        """停止监控服务"""
        self.is_running = False
        self.db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    webhook = os.getenv("FEISHU_WEBHOOK_URL", "")
    monitor = StockMonitor(webhook)

    print("执行单次扫描...")
    results = monitor.scan()
    print(f"扫描完成：共{results['total']}只，触发告警{len(results['alerts'])}个")

    for alert in results.get("alerts", []):
        print(f"  - {alert['name']}: {alert['alert_type']} @ {alert['price']}")
```

- [ ] **Step 2: 测试模块导入**

```bash
cd /Users/water/mylearn/PycharmProjects/abu-master
python -c "from cy_ai.monitor import StockMonitor, AlertType; print('监控模块导入成功')"
```

- [ ] **Step 3: 提交代码**

```bash
git add cy_ai/monitor.py
git commit -m "feat(cy_ai): add stock monitoring service with price alerts"
```

---

## Task 5: 创建股票池管理器

**Files:**
- Create: `cy_ai/pool_manager.py`

- [ ] **Step 1: 创建 pool_manager.py**

```python
"""
股票池管理器
负责将分析结果同步到监控池
"""

import logging
import re
from typing import Dict, Any, Optional

from .db import Database

logger = logging.getLogger(__name__)


class PoolManager:
    """股票池管理器"""

    def __init__(self, db: Database):
        self.db = db

    def sync_to_watch_pool(self, min_score: int = 60, max_count: int = 100) -> int:
        """
        将二次分析结果同步到监控池

        :param min_score: 最低评分门槛
        :param max_count: 最大数量
        :return: 同步数量
        """
        sql = """
            SELECT 
                ts_code, name, industry, market,
                invest_status, tenbagger_potential_score as ai_confidence,
                reason as ai_summary,
                buy_range, sell_range, stop_loss,
                analyzed_at
            FROM stock_ai_analysis
            WHERE is_valid = 1 
              AND analysis_stage = 2
              AND invest_status IN ('强烈推荐(10倍潜力)', '强烈推荐', '值得投资', '推荐')
              AND tenbagger_potential_score >= %s
            ORDER BY tenbagger_potential_score DESC
            LIMIT %s
        """
        stocks = self.db.query_all(sql, (min_score, max_count))

        count = 0
        for stock in stocks:
            buy_range = self._parse_price_range(stock.get("buy_range", ""))
            sell_range = self._parse_price_range(stock.get("sell_range", ""))
            stop_loss = self._parse_single_price(stock.get("stop_loss"))

            self._upsert_watch_pool(stock, buy_range, sell_range, stop_loss)
            count += 1

        logger.info(f"同步 {count} 只股票到监控池")
        return count

    def _parse_price_range(self, price_str: str) -> Dict[str, float]:
        """解析价格区间字符串"""
        if not price_str:
            return {"low": 0, "high": 0, "ideal": 0}

        try:
            # 支持多种格式: "10.5~11.5", "10.5 - 11.5", "10.5 ~ 11.5"
            price_str = str(price_str).strip()
            match = re.search(r"([\d.]+)\s*[~-]+\s*([\d.]+)", price_str)
            if match:
                low = float(match.group(1))
                high = float(match.group(2))
                ideal = (low + high) / 2
                return {"low": low, "high": high, "ideal": ideal}
            else:
                # 单一价格
                price = float(price_str)
                return {"low": price, "high": price, "ideal": price}
        except (ValueError, AttributeError):
            return {"low": 0, "high": 0, "ideal": 0}

    def _parse_single_price(self, price_str: Any) -> float:
        """解析单一价格"""
        if not price_str:
            return 0
        try:
            return float(str(price_str).strip())
        except (ValueError, AttributeError):
            return 0

    def _upsert_watch_pool(self, stock: dict, buy_range: dict, sell_range: dict, stop_loss: float):
        """插入或更新监控池"""
        sql = """
            INSERT INTO stock_watch_pool (
                ts_code, name, industry, market,
                ai_verdict, ai_confidence, ai_summary,
                buy_zone_low, buy_zone_high, buy_zone_ideal,
                sell_zone_conservative, sell_zone_aggressive, stop_loss,
                analyzed_at, added_source,
                alert_config
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'ai_analysis',
                '{"enable_price_alert": true, "price_alert_type": "in_buy_zone", "alert_cooldown_hours": 24}'
            )
            ON DUPLICATE KEY UPDATE
                name = VALUES(name),
                industry = VALUES(industry),
                ai_verdict = VALUES(ai_verdict),
                ai_confidence = VALUES(ai_confidence),
                ai_summary = VALUES(ai_summary),
                buy_zone_low = VALUES(buy_zone_low),
                buy_zone_high = VALUES(buy_zone_high),
                buy_zone_ideal = VALUES(buy_zone_ideal),
                sell_zone_conservative = VALUES(sell_zone_conservative),
                sell_zone_aggressive = VALUES(sell_zone_aggressive),
                stop_loss = VALUES(stop_loss),
                analyzed_at = VALUES(analyzed_at),
                watch_status = 'active',
                updated_at = CURRENT_TIMESTAMP
        """

        params = (
            stock["ts_code"],
            stock["name"],
            stock.get("industry", ""),
            stock.get("market", "A股"),
            stock.get("invest_status", ""),
            stock.get("ai_confidence", 0),
            stock.get("ai_summary", ""),
            buy_range["low"],
            buy_range["high"],
            buy_range["ideal"],
            sell_range["high"] if sell_range["high"] > 0 else sell_range["ideal"],
            sell_range["ideal"],
            stop_loss,
            stock.get("analyzed_at"),
        )

        self.db.execute(sql, params)
        self.db.commit()

    def get_watch_pool_summary(self) -> Dict[str, Any]:
        """获取监控池摘要"""
        sql = """
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN watch_status = 'active' THEN 1 ELSE 0 END) as active,
                SUM(CASE WHEN watch_status = 'paused' THEN 1 ELSE 0 END) as paused,
                SUM(CASE WHEN ai_verdict = '强烈推荐' OR ai_verdict = '强烈推荐(10倍潜力)' THEN 1 ELSE 0 END) as strongly_recommended,
                SUM(CASE WHEN ai_verdict = '推荐' OR ai_verdict = '值得投资' THEN 1 ELSE 0 END) as recommended,
                SUM(CASE WHEN ai_verdict = '观望' THEN 1 ELSE 0 END) as neutral
            FROM stock_watch_pool
        """
        result = self.db.query_one(sql)
        return result if result else {}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    db = Database()
    manager = PoolManager(db)

    print("同步分析结果到监控池...")
    count = manager.sync_to_watch_pool(min_score=60, max_count=100)
    print(f"同步完成：{count} 只")

    summary = manager.get_watch_pool_summary()
    print(f"监控池统计：{summary}")

    db.close()
```

- [ ] **Step 2: 测试模块导入**

```bash
cd /Users/water/mylearn/PycharmProjects/abu-master
python -c "from cy_ai.pool_manager import PoolManager; print('股票池管理器导入成功')"
```

- [ ] **Step 3: 提交代码**

```bash
git add cy_ai/pool_manager.py
git commit -m "feat(cy_ai): add pool manager to sync analysis results to watch pool"
```

---

## Task 6: 增强 local_features.py 财务特征

**Files:**
- Modify: `cy_ai/local_features.py`

- [ ] **Step 1: 添加财务特征提取方法**

在 `LocalFeatureBuilder` 类中添加新方法：

```python
    def build_with_financial(self, ts_code: str, financial_data: Optional[dict] = None) -> Dict[str, Any]:
        """
        构建带财务数据的完整特征

        :param ts_code: 股票代码
        :param financial_data: 财务数据字典，如果为 None 则尝试从本地获取
        :return: 完整特征字典
        """
        # 获取技术特征
        tech_features = self.build(ts_code)

        # 获取财务特征
        if financial_data is None:
            financial_data = self._get_financial_from_local(ts_code)

        # 合并特征
        result = {
            "ts_code": ts_code,
            "technical": tech_features,
            "financial": financial_data,
        }

        # 添加价格位置标注
        if tech_features.get("ma120"):
            price = tech_features.get("last_close", 0)
            ma120 = tech_features.get("ma120", 0)
            if ma120 > 0:
                result["price_position"] = {
                    "vs_ma120": f"{(price/ma120 - 1)*100:+.1f}%",
                }

        return result

    def _get_financial_from_local(self, ts_code: str) -> dict:
        """
        从本地数据获取财务特征

        :param ts_code: 股票代码
        :return: 财务特征字典
        """
        # TODO: 实现从本地 Tushare 数据文件读取财务数据
        # 目前返回空字典，后续 Task 会完善
        return {}

    def build_full_payload(self, ts_code: str, name: str, industry: str,
                          financial_data: Optional[dict] = None) -> Dict[str, Any]:
        """
        构建完整的 AI 分析输入

        :param ts_code: 股票代码
        :param name: 股票名称
        :param industry: 行业
        :param financial_data: 财务数据
        :return: 完整的 payload
        """
        features = self.build_with_financial(ts_code, financial_data)

        return {
            "ts_code": ts_code,
            "name": name,
            "industry": industry,
            **features
        }
```

- [ ] **Step 2: 测试增强后的模块**

```bash
cd /Users/water/mylearn/PycharmProjects/abu-master
python -c "
from cy_ai.local_features import LocalFeatureBuilder
fb = LocalFeatureBuilder()
result = fb.build_full_payload('600036', '招商银行', '银行')
print('特征构建成功')
print('technical:', result.get('technical'))
"
```

- [ ] **Step 3: 提交代码**

```bash
git add cy_ai/local_features.py
git commit -m "feat(cy_ai): enhance local_features with financial data support"
```

---

## Task 7: 更新 main.py 整合所有模块

**Files:**
- Modify: `cy_ai/main.py`

- [ ] **Step 1: 查看现有 main.py 结构**

```bash
head -100 /Users/water/mylearn/PycharmProjects/abu-master/cy_ai/main.py
```

- [ ] **Step 2: 在 main.py 末尾添加新命令函数**

```python
def run_weekly_analysis():
    """
    每周股票池分析流程
    1. CSV 导入一级筛选池
    2. AIHubMix 阶段1初筛
    3. MiniMax 阶段2深度分析
    4. 同步到监控池
    5. 飞书通知
    """
    logger.info("=== 开始每周股票池分析 ===")

    from .db import Database, init_tables
    from .csv_importer import CSVImporter
    from .analyzer import StockAnalyzer
    from .pool_manager import PoolManager
    from .notify import FeishuNotifier

    db = Database()
    init_tables(db)

    try:
        # 1. 导入一级筛选池（如果有 CSV 文件）
        csv_path = os.getenv("MA120_POOL_CSV", "")
        if csv_path and os.path.exists(csv_path):
            importer = CSVImporter(db)
            importer.import_ma120_pool(csv_path)
            logger.info(f"已导入筛选池: {csv_path}")

        # 2. 运行两阶段分析（使用现有 analyzer）
        analyzer = StockAnalyzer(db)
        stage1_stats = analyzer.superpowers_stage1_score(delay_between=1.0)
        logger.info(f"阶段1完成: {stage1_stats}")

        stage2_stats = analyzer.superpowers_stage2_deep(delay_between=2.0, top_n=20)
        logger.info(f"阶段2完成: {stage2_stats}")

        # 3. 同步到监控池
        pool_manager = PoolManager(db)
        sync_count = pool_manager.sync_to_watch_pool(min_score=60, max_count=100)
        logger.info(f"已同步 {sync_count} 只到监控池")

        # 4. 发送飞书通知
        webhook = os.getenv("FEISHU_WEBHOOK_URL", "")
        if webhook:
            notifier = FeishuNotifier(webhook)
            summary = pool_manager.get_watch_pool_summary()
            top_stocks = db.query_all("""
                SELECT ts_code, name, ai_confidence FROM stock_watch_pool
                WHERE watch_status = 'active'
                ORDER BY ai_confidence DESC LIMIT 5
            """)
            notifier.send_weekly_summary(
                stage1_count=stage1_stats.get("scored", 0),
                stage2_count=stage2_stats.get("deep_analyzed", 0),
                watch_pool_count=sync_count,
                top_stocks=top_stocks
            )

        logger.info("=== 每周分析完成 ===")

    finally:
        db.close()


def run_monitoring():
    """
    启动实时监控服务
    """
    from .monitor import StockMonitor

    webhook = os.getenv("FEISHU_WEBHOOK_URL", "")
    if not webhook:
        logger.error("未配置 FEISHU_WEBHOOK_URL")
        return

    interval = int(os.getenv("MONITOR_INTERVAL_MINUTES", "30"))
    monitor = StockMonitor(webhook)
    monitor.start(interval_minutes=interval)

    # 保持主线程运行
    import time
    while True:
        time.sleep(60)


def run_scan_once():
    """
    执行单次监控扫描
    """
    from .monitor import StockMonitor

    webhook = os.getenv("FEISHU_WEBHOOK_URL", "")
    monitor = StockMonitor(webhook)

    results = monitor.scan()
    print(f"扫描完成：共{results['total']}只，触发告警{len(results['alerts'])}个")

    for alert in results.get("alerts", []):
        print(f"  - {alert['name']}: {alert['alert_type']} @ {alert['price']}")

    monitor.db.close()
```

- [ ] **Step 3: 更新入口命令解析**

找到 `if __name__ == "__main__":` 块，添加新命令：

```python
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        command = sys.argv[1]

        if command == "weekly":
            run_weekly_analysis()
        elif command == "monitor":
            run_monitoring()
        elif command == "scan":
            run_scan_once()
        else:
            print(f"未知命令: {command}")
            print("可用命令: weekly | monitor | scan")
    else:
        print("用法:")
        print("  python -m cy_ai.main weekly   # 运行每周分析")
        print("  python -m cy_ai.main monitor  # 启动监控服务")
        print("  python -m cy_ai.main scan     # 执行单次扫描")
```

- [ ] **Step 4: 测试命令**

```bash
cd /Users/water/mylearn/PycharmProjects/abu-master
python -m cy_ai.main
```

Expected: 显示命令帮助信息

- [ ] **Step 5: 提交代码**

```bash
git add cy_ai/main.py
git commit -m "feat(cy_ai): integrate all modules with main.py entry points"
```

---

## Task 8: 集成测试

**Files:**
- Test: 所有模块

- [ ] **Step 1: 测试模块导入**

```bash
cd /Users/water/mylearn/PycharmProjects/abu-master
python -c "
from cy_ai.aihubmix_api import AIHubMixAPI
from cy_ai.notify import FeishuNotifier
from cy_ai.monitor import StockMonitor, AlertType
from cy_ai.pool_manager import PoolManager
from cy_ai.local_features import LocalFeatureBuilder
from cy_ai.analyzer import StockAnalyzer
print('所有模块导入成功')
"
```

- [ ] **Step 2: 测试数据库连接和表结构**

```bash
python -c "
from cy_ai.db import Database, init_tables
db = Database()
init_tables(db)
# 检查表是否存在
tables = db.query_all('SHOW TABLES')
print('已创建的表:', [t['Tables_in_stock_analysis'] for t in tables])
db.close()
"
```

- [ ] **Step 3: 测试特征提取**

```bash
python -c "
from cy_ai.local_features import LocalFeatureBuilder
fb = LocalFeatureBuilder()
result = fb.build('600036')
print('技术特征:', result)
"
```

- [ ] **Step 4: 提交测试**

```bash
git add -A
git commit -m "test(cy_ai): add integration tests for all modules"
```

---

## Task 9: 创建 README 文档

**Files:**
- Create: `cy_ai/README.md`

- [ ] **Step 1: 创建 README.md**

```markdown
# 股票池 AI 分析与监控系统

基于 AIHubMix + MiniMax 两阶段分析的股票筛选系统。

## 功能特性

- **两阶段 AI 分析**: AIHubMix 批量初筛 + MiniMax 深度分析
- **多市场支持**: A股、港股、美股
- **监控池管理**: 自动同步高分股票到监控池
- **实时告警**: 价格触发条件时通过飞书通知
- **买卖计划**: 包含买入区间、止损位、目标价

## 安装

```bash
pip install -r requirements.txt
```

## 配置

设置环境变量：

```bash
# AIHubMix API
export AIHUBMIX_API_KEY="your-api-key"

# MiniMax API
export MINIMAX_API_KEY="your-api-key"

# 飞书 Webhook
export FEISHU_WEBHOOK_URL="https://open.feishu.cn/open-apis/bot/v2/hook/xxx"

# 一级筛选池 CSV 路径（可选）
export MA120_POOL_CSV="/path/to/ma120_pool.csv"
```

## 使用方法

### 运行每周分析

```bash
python -m cy_ai.main weekly
```

### 启动监控服务

```bash
python -m cy_ai.main monitor
```

### 执行单次扫描

```bash
python -m cy_ai.main scan
```

## 数据库表

- `stock_pool_ma120`: 一级筛选池（120日均线突破）
- `stock_ai_analysis`: AI 分析结果
- `stock_watch_pool`: 监控池

## 许可证

MIT
```

- [ ] **Step 2: 提交 README**

```bash
git add cy_ai/README.md
git commit -m "docs(cy_ai): add README documentation"
```

---

## 执行摘要

**Plan complete and saved to `docs/superpowers/plans/2026-04-18-stock-pool-ai-analysis.md`.**

**Two execution options:**

1. **Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration
2. **Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
