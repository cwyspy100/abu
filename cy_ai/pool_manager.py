"""
股票池管理器
负责将分析结果同步到监控池
"""

import logging
import re
from typing import Dict, Any

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