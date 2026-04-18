"""
AI 股票分析器
整合数据库、MiniMax API，实现股票分析缓存逻辑
"""

import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

from .db import Database
from .minimax_api import MiniMaxAPI
from .csv_importer import CSVImporter
from .superpowers_ai import SuperpowersAI
from .local_features import LocalFeatureBuilder

logger = logging.getLogger(__name__)


class StockAnalyzer:
    """股票 AI 分析器"""

    def __init__(self, db: Database, minimax_api: Optional[MiniMaxAPI] = None):
        """
        初始化分析器

        :param db: Database 实例
        :param minimax_api: MiniMaxAPI 实例，为 None 时自动创建
        """
        self.db = db
        self.api = minimax_api or MiniMaxAPI()

    @staticmethod
    def _normalize_ts_code(ts_code: str) -> str:
        return CSVImporter.normalize_ts_code(ts_code)

    def is_already_analyzed(self, ts_code: str) -> bool:
        """
        检查股票是否已有有效的 AI 分析结果

        :param ts_code: 股票代码
        :return: True 表示已有分析结果，False 表示需要分析
        """
        sql = """
            SELECT id FROM stock_ai_analysis
            WHERE ts_code = %s AND is_valid = 1
            LIMIT 1
        """
        ts_code = self._normalize_ts_code(ts_code)
        result = self.db.query_one(sql, (ts_code,))
        return result is not None

    def save_analysis_result(
        self, ts_code: str, name: str, industry: str, analysis: Dict[str, Any]
    ) -> bool:
        """
        保存 AI 分析结果到数据库

        :param ts_code: 股票代码
        :param name: 股票名称
        :param industry: 所属行业
        :param analysis: 分析结果字典
        :return: True 保存成功，False 失败
        """
        sql = """
            INSERT INTO stock_ai_analysis (
                ts_code, name, industry,
                invest_status, valuation, tenbagger_potential_score,
                buy_range, sell_range,
                reason, tenbagger_logic, risk_points,
                analyzed_at, is_valid
            ) VALUES (
                %s, %s, %s,
                %s, %s, %s,
                %s, %s,
                %s, %s, %s,
                %s, 1
            )
            ON DUPLICATE KEY UPDATE
                name = VALUES(name),
                industry = VALUES(industry),
                invest_status = VALUES(invest_status),
                valuation = VALUES(valuation),
                tenbagger_potential_score = VALUES(tenbagger_potential_score),
                buy_range = VALUES(buy_range),
                sell_range = VALUES(sell_range),
                reason = VALUES(reason),
                tenbagger_logic = VALUES(tenbagger_logic),
                risk_points = VALUES(risk_points),
                analyzed_at = VALUES(analyzed_at),
                updated_at = CURRENT_TIMESTAMP
        """

        params = (
            self._normalize_ts_code(ts_code),
            name,
            industry,
            analysis.get("invest_status", ""),
            analysis.get("valuation", ""),
            analysis.get("tenbagger_potential_score", 0),
            analysis.get("buy_range", ""),
            analysis.get("sell_range", ""),
            analysis.get("reason", ""),
            analysis.get("tenbagger_logic", ""),
            analysis.get("risk_points", ""),
            datetime.now(),
        )

        try:
            self.db.execute(sql, params)
            self.db.commit()
            logger.info(f"已保存股票 {ts_code} 的分析结果")

            # 更新 stock_pool_ma120 的 status 为已分析
            self._update_pool_status(ts_code, 1)
            return True
        except Exception as e:
            logger.error(f"保存分析结果失败: {e}")
            self.db.rollback()
            return False

    def _update_pool_status(self, ts_code: str, status: int) -> bool:
        """
        更新股票池中的分析状态

        :param ts_code: 股票代码
        :param status: 状态值，0=未分析，1=已分析
        :return: True 成功，False 失败
        """
        sql = "UPDATE stock_pool_ma120 SET status = %s, updated_at = NOW() WHERE ts_code = %s"
        try:
            self.db.execute(sql, (status, self._normalize_ts_code(ts_code)))
            self.db.commit()
            logger.info(f"已更新股票 {ts_code} 的状态为 {status}")
            return True
        except Exception as e:
            logger.error(f"更新股票池状态失败: {e}")
            self.db.rollback()
            return False

    def analyze_stock(self, stock: Dict[str, Any]) -> bool:
        """
        分析单只股票

        :param stock: 股票信息字典
        :return: True 分析并保存成功，False 失败或跳过
        """
        ts_code = stock.get("ts_code", "")
        ts_code = self._normalize_ts_code(ts_code)

        # 检查是否已有分析
        if self.is_already_analyzed(ts_code):
            logger.info(f"股票 {ts_code} 已有分析结果，跳过")
            return False

        # 调用 API 分析
        analysis = self.api.analyze_stock(stock)

        if analysis is None:
            logger.error(f"股票 {ts_code} AI 分析失败")
            return False

        # 保存结果
        return self.save_analysis_result(
            ts_code=ts_code,
            name=stock.get("name", ""),
            industry=stock.get("industry", ""),
            analysis=analysis,
        )

    def analyze_pool(
        self, delay_between: float = 3.0, limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        分析股票池中所有待分析的股票

        :param delay_between: 每次分析间隔（秒）
        :param limit: 限制分析数量，为 None 表示分析全部
        :return: 分析统计信息
        """
        from .csv_importer import CSVImporter

        importer = CSVImporter(self.db)
        pending_stocks = importer.get_pending_stocks()

        if limit:
            pending_stocks = pending_stocks[:limit]

        if not pending_stocks:
            logger.info("没有待分析的股票")
            return {"total": 0, "analyzed": 0, "skipped": 0, "failed": 0}

        logger.info(f"共有 {len(pending_stocks)} 只股票待分析")

        stats = {"total": len(pending_stocks), "analyzed": 0, "skipped": 0, "failed": 0}

        for i, stock in enumerate(pending_stocks, 1):
            ts_code = stock.get("ts_code", "")

            # 再次检查是否已被其他进程分析
            if self.is_already_analyzed(ts_code):
                logger.info(f"[{i}/{len(pending_stocks)}] 股票 {ts_code} 已有分析，跳过")
                stats["skipped"] += 1
                continue

            logger.info(f"[{i}/{len(pending_stocks)}] 正在分析股票 {ts_code}...")

            success = self.analyze_stock(stock)

            if success:
                stats["analyzed"] += 1
            else:
                stats["failed"] += 1

            # 间隔
            if i < len(pending_stocks):
                import time

                time.sleep(delay_between)

        logger.info(f"分析完成: 共 {stats['total']} 只，已分析 {stats['analyzed']} 只，跳过 {stats['skipped']} 只，失败 {stats['failed']} 只")

        return stats

    def analyze_pool_superpowers(
        self, delay_between: float = 1.0, limit: Optional[int] = None, top_n: int = 20
    ) -> Dict[str, Any]:
        """
        superpowers 两阶段流程：
        1) 全量候选低成本打分
        2) TopN 进行深度估值与投资计划
        """
        importer = CSVImporter(self.db)
        pending_stocks = importer.get_pending_stocks()
        if limit:
            pending_stocks = pending_stocks[:limit]
        if not pending_stocks:
            return {"total": 0, "scored": 0, "deep_analyzed": 0, "failed": 0}

        ai = SuperpowersAI()
        feature_builder = LocalFeatureBuilder()
        scored = []
        failed = 0

        for i, stock in enumerate(pending_stocks, 1):
            ts_code = self._normalize_ts_code(stock.get("ts_code", ""))
            payload = {
                "ts_code": ts_code,
                "name": stock.get("name", ""),
                "industry": stock.get("industry", ""),
                "break_date": str(stock.get("break_date", "")),
                "local_features": feature_builder.build(ts_code),
            }
            s = ai.score_stock(payload)
            if not s:
                failed += 1
                continue
            scored.append((stock, payload, s))
            logger.info("[%s/%s] %s score=%s", i, len(pending_stocks), ts_code, s.get("score"))
            if i < len(pending_stocks):
                import time
                time.sleep(delay_between)

        scored = sorted(scored, key=lambda x: int(x[2].get("score", 0)), reverse=True)
        top = scored[: max(0, top_n)]

        deep_count = 0
        for stock, payload, score in top:
            deep = ai.deep_analyze(payload) or {}
            merged = {
                "invest_status": deep.get("invest_status", "值得观察"),
                "valuation": deep.get("valuation", "合理"),
                "tenbagger_potential_score": int(deep.get("tenbagger_potential_score", score.get("score", 0)) or 0),
                "buy_range": deep.get("buy_range", ""),
                "sell_range": deep.get("sell_range", ""),
                "reason": deep.get("reason", score.get("short_reason", "")),
                "tenbagger_logic": deep.get("tenbagger_logic", ""),
                "risk_points": deep.get("risk_points", ""),
            }
            # 把投资计划写入 tenbagger_logic，兼容现有表结构
            plan = deep.get("plan") or {}
            if plan:
                merged["tenbagger_logic"] = (
                    (merged["tenbagger_logic"] + " | " if merged["tenbagger_logic"] else "")
                    + "计划: 仓位=%s; 加仓=%s; 止损=%s; 周期=%s"
                    % (
                        plan.get("position", ""),
                        plan.get("add_condition", ""),
                        plan.get("stop_loss", ""),
                        plan.get("holding_period", ""),
                    )
                )[:1000]

            ok = self.save_analysis_result(
                ts_code=payload["ts_code"],
                name=payload.get("name", ""),
                industry=payload.get("industry", ""),
                analysis=merged,
            )
            if ok:
                deep_count += 1

        return {
            "total": len(pending_stocks),
            "scored": len(scored),
            "deep_analyzed": deep_count,
            "failed": failed,
        }

    def superpowers_stage1_score(
        self, delay_between: float = 1.0, limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        第一阶段：仅批量打分，并写入 stock_ai_analysis（标记为 STAGE1_ONLY）。
        """
        importer = CSVImporter(self.db)
        pending_stocks = importer.get_pending_stocks()
        if limit:
            pending_stocks = pending_stocks[:limit]
        if not pending_stocks:
            return {"total": 0, "scored": 0, "failed": 0}

        ai = SuperpowersAI()
        feature_builder = LocalFeatureBuilder()
        scored = 0
        failed = 0

        for i, stock in enumerate(pending_stocks, 1):
            ts_code = self._normalize_ts_code(stock.get("ts_code", ""))
            payload = {
                "ts_code": ts_code,
                "name": stock.get("name", ""),
                "industry": stock.get("industry", ""),
                "break_date": str(stock.get("break_date", "")),
                "local_features": feature_builder.build(ts_code),
            }
            s = ai.score_stock(payload)
            if not s:
                failed += 1
                continue

            score = int(s.get("score", 0) or 0)
            trend = int(s.get("trend_score", 0) or 0)
            risk = int(s.get("risk_score", 0) or 0)
            quality = int(s.get("quality_score", 0) or 0)
            action = s.get("action", "观察")
            short_reason = s.get("short_reason", "")

            stage1_reason = "[STAGE1] action=%s; trend=%s; risk=%s; quality=%s; %s" % (
                action,
                trend,
                risk,
                quality,
                short_reason,
            )
            analysis = {
                "invest_status": "阶段1候选",
                "valuation": "待二阶段",
                "tenbagger_potential_score": score,
                "buy_range": "",
                "sell_range": "",
                "reason": stage1_reason[:1000],
                "tenbagger_logic": "__STAGE1_ONLY__",
                "risk_points": "",
            }
            ok = self.save_analysis_result(
                ts_code=payload["ts_code"],
                name=payload.get("name", ""),
                industry=payload.get("industry", ""),
                analysis=analysis,
            )
            if ok:
                scored += 1
                logger.info("[%s/%s] %s score=%s action=%s", i, len(pending_stocks), ts_code, score, action)
            else:
                failed += 1

            if i < len(pending_stocks):
                import time
                time.sleep(delay_between)

        return {"total": len(pending_stocks), "scored": scored, "failed": failed}

    def _get_stage1_top_candidates(self, top_n: int = 20) -> List[Dict[str, Any]]:
        """
        从表中取阶段1候选的前 N（按 tenbagger_potential_score 排序）。
        """
        sql = """
            SELECT a.ts_code, a.name, a.industry, p.break_date, a.tenbagger_potential_score
            FROM stock_ai_analysis a
            INNER JOIN stock_pool_ma120 p ON a.ts_code = p.ts_code
            WHERE a.is_valid = 1
              AND a.tenbagger_logic = '__STAGE1_ONLY__'
            ORDER BY a.tenbagger_potential_score DESC, p.break_date DESC
            LIMIT %s
        """
        return self.db.query_all(sql, (top_n,))

    def superpowers_stage2_deep(
        self, delay_between: float = 1.0, top_n: int = 20
    ) -> Dict[str, Any]:
        """
        第二阶段：仅从数据库读取第一阶段前 N，做深度分析并覆盖写回。
        """
        candidates = self._get_stage1_top_candidates(top_n=top_n)
        if not candidates:
            return {"total": 0, "deep_analyzed": 0, "failed": 0}

        ai = SuperpowersAI()
        feature_builder = LocalFeatureBuilder()
        deep_count = 0
        failed = 0

        for i, stock in enumerate(candidates, 1):
            ts_code = self._normalize_ts_code(stock.get("ts_code", ""))
            payload = {
                "ts_code": ts_code,
                "name": stock.get("name", ""),
                "industry": stock.get("industry", ""),
                "break_date": str(stock.get("break_date", "")),
                "local_features": feature_builder.build(ts_code),
            }
            deep = ai.deep_analyze(payload) or {}
            if not deep:
                failed += 1
                continue

            merged = {
                "invest_status": deep.get("invest_status", "值得观察"),
                "valuation": deep.get("valuation", "合理"),
                "tenbagger_potential_score": int(deep.get("tenbagger_potential_score", stock.get("tenbagger_potential_score", 0)) or 0),
                "buy_range": deep.get("buy_range", ""),
                "sell_range": deep.get("sell_range", ""),
                "reason": deep.get("reason", ""),
                "tenbagger_logic": deep.get("tenbagger_logic", ""),
                "risk_points": deep.get("risk_points", ""),
            }
            plan = deep.get("plan") or {}
            if plan:
                merged["tenbagger_logic"] = (
                    (merged["tenbagger_logic"] + " | " if merged["tenbagger_logic"] else "")
                    + "计划: 仓位=%s; 加仓=%s; 止损=%s; 周期=%s"
                    % (
                        plan.get("position", ""),
                        plan.get("add_condition", ""),
                        plan.get("stop_loss", ""),
                        plan.get("holding_period", ""),
                    )
                )[:1000]

            ok = self.save_analysis_result(
                ts_code=ts_code,
                name=payload.get("name", ""),
                industry=payload.get("industry", ""),
                analysis=merged,
            )
            if ok:
                deep_count += 1
                logger.info("[%s/%s] deep analyzed %s", i, len(candidates), ts_code)
            else:
                failed += 1

            if i < len(candidates):
                import time
                time.sleep(delay_between)

        return {"total": len(candidates), "deep_analyzed": deep_count, "failed": failed}

    def get_analysis_results(
        self,
        invest_status: Optional[str] = None,
        min_score: Optional[int] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        获取 AI 分析结果

        :param invest_status: 过滤投资状态
        :param min_score: 最低评分过滤
        :param limit: 返回数量限制
        :return: 分析结果列表
        """
        conditions = ["is_valid = 1"]
        params = []

        if invest_status:
            conditions.append("invest_status = %s")
            params.append(invest_status)

        if min_score is not None:
            conditions.append("tenbagger_potential_score >= %s")
            params.append(min_score)

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        params.append(limit)

        sql = f"""
            SELECT ts_code, name, industry,
                   invest_status, valuation, tenbagger_potential_score,
                   buy_range, sell_range,
                   reason, tenbagger_logic, risk_points,
                   analyzed_at
            FROM stock_ai_analysis
            WHERE {where_clause}
            ORDER BY tenbagger_potential_score DESC
            LIMIT %s
        """

        return self.db.query_all(sql, tuple(params))

    def export_results_to_csv(self, output_path: str, **filters) -> int:
        """
        导出分析结果到 CSV 文件

        :param output_path: 输出文件路径
        :param filters: 过滤条件
        :return: 导出的记录数
        """
        import pandas as pd

        results = self.get_analysis_results(
            invest_status=filters.get("invest_status"),
            min_score=filters.get("min_score"),
            limit=filters.get("limit", 1000),
        )

        if not results:
            logger.warning("没有可导出的分析结果")
            return 0

        df = pd.DataFrame(results)

        # 调整列顺序
        columns_order = [
            "ts_code",
            "name",
            "industry",
            "invest_status",
            "valuation",
            "tenbagger_potential_score",
            "buy_range",
            "sell_range",
            "reason",
            "tenbagger_logic",
            "risk_points",
            "analyzed_at",
        ]
        df = df[[col for col in columns_order if col in df.columns]]

        df.to_csv(output_path, index=False, encoding="utf-8-sig")
        logger.info(f"已导出 {len(df)} 条分析结果到 {output_path}")

        return len(df)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    from .db import Database, init_tables
    from .minimax_api import MiniMaxAPI

    # 初始化
    db = Database()
    init_tables(db)

    # 创建分析器
    api = MiniMaxAPI()
    analyzer = StockAnalyzer(db, api)

    # 示例：分析待分析股票
    # stats = analyzer.analyze_pool(delay_between=5.0)
    # print(json.dumps(stats, ensure_ascii=False, indent=2))

    # 示例：导出分析结果
    # results = analyzer.get_analysis_results(min_score=80)
    # print(f"找到 {len(results)} 只高评分股票")

    db.close()
