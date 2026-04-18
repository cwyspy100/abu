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
    from .config import get_config
    cfg = get_config()
    webhook = cfg.feishu_webhook_url
    if webhook:
        notifier = FeishuNotifier(webhook)
        result = notifier.send("🔔 测试消息：飞书通知模块正常工作")
        print("发送成功" if result else "发送失败")
    else:
        print("未配置 feishu_webhook_url，跳过测试")
