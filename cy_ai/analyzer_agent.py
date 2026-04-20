"""
股票分析 Agent
两阶段分析：阶段1初筛 + 阶段2深度分析
支持交互式单股票分析和批量分析
"""

import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

from .qianwen_api import QianwenAPI
from .local_features import build_stock_features, LocalFeatureBuilder
from .tushare_fetcher import TushareFetcher
from .db import Database

logger = logging.getLogger(__name__)


class StockAnalyzerAgent:
    """股票分析 Agent"""

    # 阶段1通过分数
    STAGE1_PASS_SCORE = 80

    # 分析有效期（天）
    ANALYSIS_VALID_DAYS = 30

    def __init__(self, db: Optional[Database] = None):
        """
        初始化分析 Agent

        :param db: 数据库实例
        """
        self.db = db
        self.feature_builder = LocalFeatureBuilder()
        self.tushare_fetcher = TushareFetcher()

        # 千问 API（延迟初始化，key可能未配置）
        self._qianwen_api: Optional[QianwenAPI] = None

    @property
    def qianwen_api(self) -> QianwenAPI:
        """获取千问 API 实例（延迟初始化）"""
        if self._qianwen_api is None:
            self._qianwen_api = QianwenAPI()
        return self._qianwen_api

    def check_already_analyzed(self, ts_code: str) -> Optional[dict]:
        """
        检查股票是否已分析过

        :param ts_code: 股票代码
        :return: 已分析记录或 None
        """
        if not self.db:
            return None

        sql = """
            SELECT * FROM stock_ai_analysis
            WHERE ts_code = %s AND is_latest = 1
            AND analyzed_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
            ORDER BY analyzed_at DESC LIMIT 1
        """

        try:
            result = self.db.query_one(sql, (ts_code, self.ANALYSIS_VALID_DAYS))
            return result
        except Exception as e:
            logger.warning(f"检查已分析记录失败: {e}")
            return None

    def build_features(self, ts_code: str, name: str = "", industry: str = "") -> Dict[str, Any]:
        """
        构建股票完整特征

        :param ts_code: 股票代码
        :param name: 股票名称
        :param industry: 行业
        :return: 特征字典
        """
        # 自动添加后缀（如果缺少），用于API调用
        ts_code_str = str(ts_code)
        if not any(ts_code_str.endswith(s) for s in ['.SH', '.SZ', '.HK', '.US']):
            # 5位数字代码通常是港股
            if len(ts_code_str) == 5:
                api_code = ts_code_str + '.HK'
            else:
                api_code = ts_code_str + '.SH'  # 默认沪市
        else:
            api_code = ts_code_str

        logger.info(f"[特征构建] 开始构建 {ts_code} 特征...")

        # 1. 技术面特征（从本地CSV）
        tech_features = self.feature_builder.build(ts_code_str)
        if not tech_features:
            logger.warning(f"[特征构建] 未找到 {ts_code} 的本地K线数据")
            tech_features = {}

        # 2. 财务数据（从Tushare或缓存）
        fina_data = {}
        try:
            fina_data = self.tushare_fetcher.get_latest_financial_summary(api_code)
            if fina_data:
                logger.info(f"[特征构建] 获取财务数据: PE={fina_data.get('pe')}, ROE={fina_data.get('roe')}")
            else:
                logger.info(f"[特征构建] 未获取到 {api_code} 的财务数据")
        except Exception as e:
            logger.warning(f"[特征构建] 获取财务数据失败: {e}")

        # 3. 合并特征
        # 注意: name 改为 stock_name 避免与 str.format() 方法冲突
        features = {
            "ts_code": ts_code,
            "stock_name": name,
            "industry": industry,
            **tech_features,
            **fina_data,
        }

        # 4. 市场情绪数据（预留字段，默认值）
        features.setdefault("north_net_inflow", 0)
        features.setdefault("margin_balance_change", 0)
        features.setdefault("limit_up_count", 50)
        features.setdefault("advancing_count", 2000)
        features.setdefault("declining_count", 1500)

        logger.info(f"[特征构建] 完成: price={features.get('price')}, "
                   f"ma120={features.get('ma120')}, "
                   f"pe={features.get('pe')}, roe={features.get('roe')}")

        return features

    def stage1_score(self, features: Dict[str, Any], verbose: bool = False) -> Optional[Dict[str, Any]]:
        """
        阶段1：千问初筛

        :param features: 股票特征
        :param verbose: 是否打印详细信息
        :return: 初筛结果
        """
        ts_code = features.get("ts_code", "unknown")

        try:
            result = self.qianwen_api.score_stock(features, verbose=verbose)

            if not result:
                logger.error(f"[阶段1] {ts_code} 调用失败")
                return None

            score = result.get("score", 0)
            action = result.get("action", "")

            logger.info(f"[阶段1] {ts_code} 评分: {score}, 动作: {action}")

            # 将原始结果存入 features 供阶段2使用
            features["stage1_score"] = score
            features["stage1_action"] = action
            features["stage1_reason"] = result.get("reason", "")
            features["tech_score"] = result.get("tech_score", 0)
            features["fina_score"] = result.get("fina_score", 0)
            features["sentiment_score"] = result.get("sentiment_score", 0)
            features["trend_score"] = result.get("trend_score", 0)
            features["risk_score"] = result.get("risk_score", 0)
            features["quality_score"] = result.get("quality_score", 0)

            return result

        except ValueError as e:
            logger.error(f"[阶段1] {ts_code} API配置错误: {e}")
            return None
        except Exception as e:
            logger.error(f"[阶段1] {ts_code} 分析异常: {e}")
            return None

    def stage2_deep(self, features: Dict[str, Any], verbose: bool = False) -> Optional[Dict[str, Any]]:
        """
        阶段2：千问深度分析

        :param features: 股票特征（含阶段1结果）
        :param verbose: 是否打印详细信息
        :return: 深度分析结果
        """
        ts_code = features.get("ts_code", "unknown")

        try:
            result = self.qianwen_api.deep_analyze(features, verbose=verbose)

            if not result:
                logger.error(f"[阶段2] {ts_code} 调用失败")
                return None

            invest_status = result.get("invest_status", "")
            buy_range = result.get("buy_range", "")

            logger.info(f"[阶段2] {ts_code} 投资状态: {invest_status}, 买入区间: {buy_range}")

            return result

        except ValueError as e:
            logger.error(f"[阶段2] {ts_code} API配置错误: {e}")
            return None
        except Exception as e:
            logger.error(f"[阶段2] {ts_code} 分析异常: {e}")
            return None

    def save_analysis(self, ts_code: str, name: str, features: Dict[str, Any],
                     stage1_result: Dict[str, Any], stage2_result: Optional[Dict[str, Any]] = None) -> Optional[int]:
        """
        保存分析结果到数据库

        :param ts_code: 股票代码
        :param name: 股票名称
        :param features: 特征数据
        :param stage1_result: 阶段1结果
        :param stage2_result: 阶段2结果
        :return: 插入记录的ID
        """
        if not self.db:
            logger.warning("[入库] 数据库未配置，跳过入库")
            return None

        now = datetime.now()

        # 先将之前的记录标记为非最新
        try:
            self.db.execute(
                "UPDATE stock_ai_analysis SET is_latest = 0 WHERE ts_code = %s",
                (ts_code,)
            )
        except Exception as e:
            logger.warning(f"[入库] 更新旧记录失败: {e}")

        # 合并所有结果
        final_action = "待分析"
        final_score = stage1_result.get("score", 0)
        reject_reason = ""

        if stage1_result.get("score", 0) < self.STAGE1_PASS_SCORE:
            final_action = "放弃"
            reject_reason = stage1_result.get("reject_reason", "")
        elif stage2_result:
            final_action = "买入"
            final_score = stage2_result.get("tenbagger_potential_score", final_score)

        # 构建入库数据（确保所有字段都存在）
        record = {
            "ts_code": ts_code,
            "name": name,
            "industry": features.get("industry", ""),
            "source_provider": "qianwen",
            "source_model": "qwen-plus",
            "analysis_stage": "stage2" if stage2_result else "stage1",
            "raw_request": json.dumps(features, ensure_ascii=False),
            "raw_response": json.dumps(stage1_result, ensure_ascii=False),
            "stage1_score": stage1_result.get("score", 0),
            "stage1_action": stage1_result.get("action", ""),
            "stage1_reason": stage1_result.get("reason", ""),
            "tech_score": stage1_result.get("tech_score", 0) or 0,
            "fina_score": stage1_result.get("fina_score", 0) or 0,
            "sentiment_score": stage1_result.get("sentiment_score", 0) or 0,
            "trend_score": stage1_result.get("trend_score", 0) or 0,
            "risk_score": stage1_result.get("risk_score", 0) or 0,
            "quality_score": stage1_result.get("quality_score", 0) or 0,
            "action": final_action,
            "reject_reason": reject_reason,
            "final_score": final_score,
            "analyzed_at": now,
            "is_latest": 1,
            # 阶段2字段预置为空字符串
            "invest_status": "",
            "valuation": "",
            "tenbagger_potential_score": 0,
            "buy_range": "",
            "sell_range": "",
            "stop_loss": 0,
            "position": "",
            "holding_period": "",
            "reason": "",
            "tenbagger_logic": "",
            "risk_points": "",
            "industry_outlook": "",
            "competitiveness": "",
        }

        # 添加阶段2结果
        if stage2_result:
            record.update({
                "invest_status": str(stage2_result.get("invest_status", "")),
                "valuation": str(stage2_result.get("valuation", "")),
                "tenbagger_potential_score": stage2_result.get("tenbagger_potential_score", 0) or 0,
                "buy_range": str(stage2_result.get("buy_range", "")),
                "sell_range": str(stage2_result.get("sell_range", "")),
                "stop_loss": stage2_result.get("stop_loss", 0) or 0,
                "position": str(stage2_result.get("position", "")),
                "holding_period": str(stage2_result.get("holding_period", "")),
                "reason": str(stage2_result.get("reason", "")),
                "tenbagger_logic": str(stage2_result.get("tenbagger_logic", "")),
                "risk_points": str(stage2_result.get("risk_points", "")),
                "industry_outlook": str(stage2_result.get("industry_outlook", "")),
                "competitiveness": str(stage2_result.get("competitiveness", "")),
            })

        # 插入记录
        sql = """
            INSERT INTO stock_ai_analysis (
                ts_code, name, source_provider, source_model, analysis_stage,
                raw_request, raw_response,
                stage1_score, stage1_action, stage1_reason,
                tech_score, fina_score, sentiment_score, trend_score, risk_score, quality_score,
                invest_status, valuation, tenbagger_potential_score,
                buy_range, sell_range, stop_loss, position, holding_period,
                reason, tenbagger_logic, risk_points, industry_outlook, competitiveness,
                action, reject_reason, final_score, analyzed_at, is_latest
            ) VALUES (
                %(ts_code)s, %(name)s, %(source_provider)s, %(source_model)s, %(analysis_stage)s,
                %(raw_request)s, %(raw_response)s,
                %(stage1_score)s, %(stage1_action)s, %(stage1_reason)s,
                %(tech_score)s, %(fina_score)s, %(sentiment_score)s, %(trend_score)s, %(risk_score)s, %(quality_score)s,
                %(invest_status)s, %(valuation)s, %(tenbagger_potential_score)s,
                %(buy_range)s, %(sell_range)s, %(stop_loss)s, %(position)s, %(holding_period)s,
                %(reason)s, %(tenbagger_logic)s, %(risk_points)s, %(industry_outlook)s, %(competitiveness)s,
                %(action)s, %(reject_reason)s, %(final_score)s, %(analyzed_at)s, %(is_latest)s
            )
        """

        try:
            self.db.execute(sql, record)
            self.db.commit()
            record_id = self.db.query_one("SELECT LAST_INSERT_ID() as id")
            logger.info(f"[入库] {ts_code} 分析结果已保存, id={record_id}")
            return record_id.get("id") if record_id else None
        except Exception as e:
            logger.error(f"[入库] {ts_code} 保存失败: {e}")
            self.db.rollback()
            return None

    def analyze_stock(self, ts_code: str, name: str = "", industry: str = "",
                    force: bool = False, verbose: bool = True) -> Dict[str, Any]:
        """
        分析单只股票（完整流程）

        :param ts_code: 股票代码
        :param name: 股票名称
        :param industry: 行业
        :param force: 是否强制重新分析
        :param verbose: 是否打印详细信息
        :return: 分析结果
        """
        logger.info(f"\n{'='*60}")
        logger.info(f"开始分析: {ts_code} {name}")
        logger.info(f"{'='*60}\n")

        result = {
            "ts_code": ts_code,
            "name": name,
            "industry": industry,
            "stage1_result": None,
            "stage2_result": None,
            "status": "pending",
            "message": "",
        }

        # 1. 检查是否已分析过
        if not force:
            existing = self.check_already_analyzed(ts_code)
            if existing:
                logger.info(f"[跳过] {ts_code} 已在 {existing['analyzed_at']} 分析过")
                result["status"] = "skipped"
                result["message"] = f"已在 {existing['analyzed_at']} 分析过，跳过"
                return result

        # 2. 构建特征
        features = self.build_features(ts_code, name, industry)

        # 3. 阶段1初筛
        stage1_result = self.stage1_score(features, verbose=verbose)
        if not stage1_result:
            result["status"] = "failed"
            result["message"] = "阶段1初筛失败"
            return result

        result["stage1_result"] = stage1_result

        # 4. 判断是否进入阶段2
        score = stage1_result.get("score", 0)
        if score < self.STAGE1_PASS_SCORE:
            logger.info(f"[淘汰] {ts_code} 评分 {score} < {self.STAGE1_PASS_SCORE}，不进入阶段2")

            # 保存阶段1结果
            self.save_analysis(ts_code, name, features, stage1_result, None)

            result["status"] = "rejected"
            result["message"] = f"阶段1评分 {score} < {self.STAGE1_PASS_SCORE}，已淘汰"
            return result

        # 5. 阶段2深度分析
        logger.info(f"[通过] {ts_code} 评分 {score} >= {self.STAGE1_PASS_SCORE}，进入阶段2")
        stage2_result = self.stage2_deep(features, verbose=verbose)
        result["stage2_result"] = stage2_result

        if not stage2_result:
            result["status"] = "failed"
            result["message"] = "阶段2深度分析失败"
            return result

        # 6. 入库
        record_id = self.save_analysis(ts_code, name, features, stage1_result, stage2_result)
        result["record_id"] = record_id

        # 7. 完成
        invest_status = stage2_result.get("invest_status", "")
        buy_range = stage2_result.get("buy_range", "")

        logger.info(f"\n{'='*60}")
        logger.info(f"分析完成: {ts_code} {name}")
        logger.info(f"投资状态: {invest_status}")
        logger.info(f"买入区间: {buy_range}")
        logger.info(f"{'='*60}\n")

        result["status"] = "completed"
        result["message"] = f"分析完成，投资状态: {invest_status}"

        return result

    def analyze_batch(self, stocks: List[Dict[str, str]], force: bool = False,
                    verbose: bool = True, delay: float = 1.0) -> Dict[str, Any]:
        """
        批量分析股票

        :param stocks: 股票列表 [{ts_code, name, industry}, ...]
        :param force: 是否强制重新分析
        :param verbose: 是否打印详细信息
        :param delay: 每支股票间隔（秒）
        :return: 批量分析统计
        """
        total = len(stocks)
        stats = {
            "total": total,
            "skipped": 0,
            "completed": 0,
            "rejected": 0,
            "failed": 0,
            "results": [],
        }

        logger.info(f"\n{'='*60}")
        logger.info(f"开始批量分析: 共 {total} 只股票")
        logger.info(f"{'='*60}\n")

        for i, stock in enumerate(stocks, 1):
            ts_code = stock.get("ts_code", "")
            name = stock.get("name", "")
            industry = stock.get("industry", "")

            logger.info(f"\n[{i}/{total}] 分析中: {ts_code} {name}")

            try:
                result = self.analyze_stock(ts_code, name, industry, force=force, verbose=verbose)
                stats["results"].append(result)

                if result["status"] == "skipped":
                    stats["skipped"] += 1
                elif result["status"] == "completed":
                    stats["completed"] += 1
                elif result["status"] == "rejected":
                    stats["rejected"] += 1
                else:
                    stats["failed"] += 1

            except Exception as e:
                logger.error(f"[错误] {ts_code} 分析异常: {e}")
                stats["failed"] += 1
                stats["results"].append({
                    "ts_code": ts_code,
                    "name": name,
                    "status": "error",
                    "message": str(e),
                })

            # 间隔
            if i < total:
                time.sleep(delay)

        # 汇总
        logger.info(f"\n{'='*60}")
        logger.info(f"批量分析完成")
        logger.info(f"总计: {total}")
        logger.info(f"完成: {stats['completed']}")
        logger.info(f"淘汰: {stats['rejected']}")
        logger.info(f"跳过: {stats['skipped']}")
        logger.info(f"失败: {stats['failed']}")
        logger.info(f"{'='*60}\n")

        return stats


def interactive_mode():
    """交互式分析模式"""
    import argparse

    parser = argparse.ArgumentParser(description="股票AI分析 Agent")
    parser.add_argument("--stock", type=str, help="股票代码，如 600036.SH")
    parser.add_argument("--name", type=str, default="", help="股票名称")
    parser.add_argument("--industry", type=str, default="", help="行业")
    parser.add_argument("--force", action="store_true", help="强制重新分析")
    parser.add_argument("--batch", type=str, help="批量CSV文件路径")
    parser.add_argument("--limit", type=int, default=50, help="批量分析数量限制")

    args = parser.parse_args()

    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    # 初始化 Agent
    try:
        db = Database()
        agent = StockAnalyzerAgent(db)
    except Exception as e:
        logger.warning(f"数据库连接失败: {e}，将使用无数据库模式")
        agent = StockAnalyzerAgent()

    if args.stock:
        # 单股票分析
        result = agent.analyze_stock(
            ts_code=args.stock,
            name=args.name,
            industry=args.industry,
            force=args.force,
            verbose=True,
        )
        print("\n最终结果:")
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif args.batch:
        # 批量分析
        import pandas as pd
        df = pd.read_csv(args.batch)
        stocks = df.head(args.limit).to_dict("records")
        stats = agent.analyze_batch(stocks, force=args.force, verbose=True)
        print("\n批量分析统计:")
        print(json.dumps(stats, ensure_ascii=False, indent=2))

    else:
        # 交互式输入
        print("=" * 50)
        print("股票分析 Agent - 交互模式")
        print("=" * 50)
        print("输入股票代码进行分析，输入 'quit' 退出")
        print()

        while True:
            try:
                ts_code = input("股票代码 (如 600036.SH): ").strip()
                if ts_code.lower() == "quit":
                    break
                if not ts_code:
                    continue

                name = input("股票名称 (可选): ").strip() or ""
                industry = input("行业 (可选): ").strip() or ""

                result = agent.analyze_stock(
                    ts_code=ts_code,
                    name=name,
                    industry=industry,
                    force=False,
                    verbose=True,
                )

                print("\n最终结果:")
                print(json.dumps(result, ensure_ascii=False, indent=2))
                print()

            except KeyboardInterrupt:
                print("\n退出")
                break
            except Exception as e:
                print(f"错误: {e}")


if __name__ == "__main__":
    interactive_mode()
