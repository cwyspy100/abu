#!/usr/bin/env python3
"""
cy_ai - 股票智能分析系统主程序
基于 MiniMax 大模型分析 120 日均线突破股票，挖掘 10 倍潜力股

使用方法:
    # 初始化数据库
    python -m cy_ai.main --init-db

    # 导入股票基础信息 CSV
    python -m cy_ai.main --import-basic stock_basic.csv

    # 导入 120 日均线突破股票池 CSV
    python -m cy_ai.main --import-pool ma120_breakthrough.csv

    # 执行 AI 分析（分析所有待分析股票）
    python -m cy_ai.main --analyze

    # 执行 AI 分析（限制数量）
    python -m cy_ai.main --analyze --limit 10

    # 导出分析结果
    python -m cy_ai.main --export results.csv

    # 组合使用
    python -m cy_ai.main --init-db --import-basic data.csv --import-pool pool.csv --analyze --export results.csv
"""

import argparse
import json
import logging
import os
import sys
from typing import Optional

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cy_ai.db import Database, init_tables
from cy_ai.csv_importer import CSVImporter
from cy_ai.analyzer import StockAnalyzer
from cy_ai.minimax_api import MiniMaxAPI

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def init_database(args: argparse.Namespace) -> bool:
    """初始化数据库"""
    logger.info("=" * 60)
    logger.info("初始化数据库...")
    logger.info("=" * 60)

    db = Database()
    try:
        init_tables(db)
        logger.info("数据库初始化完成！")
        return True
    except Exception as e:
        logger.error(f"数据库初始化失败: {e}")
        return False
    finally:
        db.close()


def import_basic_csv(args: argparse.Namespace) -> bool:
    """导入股票基础信息 CSV"""
    if not args.import_basic:
        return True

    csv_path = args.import_basic
    if not os.path.exists(csv_path):
        logger.error(f"文件不存在: {csv_path}")
        return False

    logger.info("=" * 60)
    logger.info(f"导入股票基础信息: {csv_path}")
    logger.info("=" * 60)

    db = Database()
    try:
        importer = CSVImporter(db)
        count = importer.import_stock_basic(csv_path)
        logger.info(f"导入完成，共 {count} 条记录")
        return True
    except Exception as e:
        logger.error(f"导入失败: {e}")
        return False
    finally:
        db.close()


def import_pool_csv(args: argparse.Namespace) -> bool:
    """导入 120 日均线突破股票池 CSV"""
    if not args.import_pool:
        return True

    csv_path = args.import_pool
    if not os.path.exists(csv_path):
        logger.error(f"文件不存在: {csv_path}")
        return False

    logger.info("=" * 60)
    logger.info(f"导入 120 日均线突破股票池: {csv_path}")
    logger.info("=" * 60)

    db = Database()
    try:
        importer = CSVImporter(db)
        count = importer.import_ma120_pool(csv_path)
        logger.info(f"导入完成，共 {count} 条记录")
        return True
    except Exception as e:
        logger.error(f"导入失败: {e}")
        return False
    finally:
        db.close()


def run_analysis(args: argparse.Namespace) -> bool:
    """执行 AI 分析"""
    if not args.analyze:
        return True

    logger.info("=" * 60)
    logger.info("开始执行 AI 分析...")
    logger.info("=" * 60)

    db = Database()
    try:
        api = MiniMaxAPI()
        analyzer = StockAnalyzer(db, api)

        delay = args.delay
        limit = args.limit

        stats = analyzer.analyze_pool(delay_between=delay, limit=limit)

        print("\n" + "=" * 60)
        print("分析统计:")
        print(f"  待分析股票总数: {stats['total']}")
        print(f"  已分析: {stats['analyzed']}")
        print(f"  跳过(已有分析): {stats['skipped']}")
        print(f"  失败: {stats['failed']}")
        print("=" * 60)

        return stats["failed"] == 0

    except Exception as e:
        logger.error(f"AI 分析过程异常: {e}")
        return False
    finally:
        db.close()


def export_results(args: argparse.Namespace) -> bool:
    """导出分析结果"""
    if not args.export:
        return True

    output_path = args.export
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    logger.info("=" * 60)
    logger.info(f"导出分析结果到: {output_path}")
    logger.info("=" * 60)

    db = Database()
    try:
        analyzer = StockAnalyzer(db)

        count = analyzer.export_results_to_csv(
            output_path,
            invest_status=args.filter_status,
            min_score=args.filter_score,
        )

        if count > 0:
            logger.info(f"导出完成，共 {count} 条记录")
        else:
            logger.warning("没有找到符合条件的分析结果")

        return True

    except Exception as e:
        logger.error(f"导出失败: {e}")
        return False
    finally:
        db.close()


def show_results(args: argparse.Namespace) -> bool:
    """显示分析结果"""
    if not args.show:
        return True

    db = Database()
    try:
        analyzer = StockAnalyzer(db)
        results = analyzer.get_analysis_results(
            invest_status=args.filter_status,
            min_score=args.filter_score,
            limit=args.limit,
        )

        if not results:
            print("没有找到分析结果")
            return True

        print("\n" + "=" * 100)
        print(f"分析结果 (共 {len(results)} 只):")
        print("=" * 100)

        for r in results:
            print(f"\n【{r['ts_code']}】{r['name']} | {r['industry']}")
            print(f"  投资状态: {r['invest_status']} | 估值: {r['valuation']} | 10倍潜力评分: {r['tenbagger_potential_score']}")
            print(f"  买入区间: {r['buy_range']} | 卖出区间: {r['sell_range']}")
            print(f"  核心逻辑: {r['reason']}")
            print(f"  10倍逻辑: {r['tenbagger_logic']}")
            print(f"  风险点: {r['risk_points']}")

        return True

    except Exception as e:
        logger.error(f"显示结果失败: {e}")
        return False
    finally:
        db.close()


def show_pool(args: argparse.Namespace) -> bool:
    """显示股票池"""
    if not args.show_pool:
        return True

    db = Database()
    try:
        importer = CSVImporter(db)
        stocks = importer.get_pool_stocks()

        if not stocks:
            print("股票池为空")
            return True

        print("\n" + "=" * 100)
        print(f"股票池 (共 {len(stocks)} 只):")
        print("=" * 100)

        for s in stocks:
            status = "已分析" if s.get("analysis_id") else "待分析"
            print(f"{s['ts_code']} | {s['name']} | {s['industry']} | 突破日期: {s['break_date']} | {status}")

        return True

    except Exception as e:
        logger.error(f"显示股票池失败: {e}")
        return False
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(
        description="cy_ai - 股票智能分析系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python -m cy_ai.main --init-db
  python -m cy_ai.main --import-basic stock_basic.csv
  python -m cy_ai.main --import-pool ma120.csv --analyze
  python -m cy_ai.main --show --filter-score 80
  python -m cy_ai.main --export results.csv --filter-status "强烈推荐(10倍潜力)"
        """,
    )

    # 数据库操作
    parser.add_argument("--init-db", action="store_true", help="初始化数据库表")

    # CSV 导入
    parser.add_argument("--import-basic", metavar="FILE", help="导入股票基础信息 CSV")
    parser.add_argument("--import-pool", metavar="FILE", help="导入 120 日均线突破股票池 CSV")

    # AI 分析
    parser.add_argument("--analyze", action="store_true", help="执行 AI 分析")
    parser.add_argument("--limit", type=int, default=None, metavar="N", help="限制分析股票数量")
    parser.add_argument("--delay", type=float, default=5.0, metavar="SEC", help="API 调用间隔（秒，默认 5）")

    # 结果查看
    parser.add_argument("--show", action="store_true", help="显示分析结果")
    parser.add_argument("--show-pool", action="store_true", help="显示股票池")
    parser.add_argument("--filter-status", metavar="STATUS", help="过滤投资状态")
    parser.add_argument("--filter-score", type=int, metavar="SCORE", help="过滤最低评分")

    # 导出
    parser.add_argument("--export", metavar="FILE", help="导出分析结果到 CSV")

    args = parser.parse_args()

    # 如果没有任何操作，显示帮助
    if not any([args.init_db, args.import_basic, args.import_pool, args.analyze, args.show, args.show_pool, args.export]):
        parser.print_help()
        return 0

    # 执行操作
    success = True

    if args.init_db:
        success = init_database(args) and success

    if args.import_basic:
        success = import_basic_csv(args) and success

    if args.import_pool:
        success = import_pool_csv(args) and success

    if args.analyze:
        success = run_analysis(args) and success

    if args.show_pool:
        success = show_pool(args) and success

    if args.show:
        success = show_results(args) and success

    if args.export:
        success = export_results(args) and success

    if success:
        logger.info("所有任务执行完成！")
    else:
        logger.error("部分任务执行失败，请检查日志")

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
