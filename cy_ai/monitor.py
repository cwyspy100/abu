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
        if isinstance(config, str):
            import json
            config = json.loads(config) if config else {}
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

    from .config import get_config
    cfg = get_config()
    webhook = cfg.feishu_webhook_url
    monitor = StockMonitor(webhook)

    print("执行单次扫描...")
    results = monitor.scan()
    print(f"扫描完成：共{results['total']}只，触发告警{len(results['alerts'])}个")

    for alert in results.get("alerts", []):
        print(f"  - {alert['name']}: {alert['alert_type']} @ {alert['price']}")
