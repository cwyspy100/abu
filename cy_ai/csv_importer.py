"""
CSV 文件导入模块
支持导入全量股票基础信息和 120 日均线突破股票池
"""

import os
import logging
from datetime import datetime
from typing import Optional, List

import pandas as pd

from .db import Database

logger = logging.getLogger(__name__)


class CSVImporter:
    """CSV 文件导入器"""

    # CSV 列映射（CSV列名 -> 数据库列名）
    STOCK_BASIC_COLUMNS = {
        "ts_code": "ts_code",
        "symbol": "symbol",
        "name": "name",
        "industry": "industry",
        "area": "area",
        "list_date": "list_date",
    }

    # 120日均线突破股票池列映射
    MA120_POOL_COLUMNS = {
        "ts_code": "ts_code",
        "name": "name",
        "industry": "industry",
        "breakthrough_date": "break_date",
    }

    def __init__(self, db: Database):
        """
        初始化导入器

        :param db: Database 实例
        """
        self.db = db

    @staticmethod
    def normalize_ts_code(ts_code) -> str:
        """
        统一股票代码格式：去掉交易所后缀并补齐到 6 位。
        示例：2594 / 2594.SZ -> 002594
        """
        if pd.isnull(ts_code):
            return ""
        code = str(ts_code).strip()
        if "." in code:
            code = code.split(".", 1)[0]
        code = "".join(ch for ch in code if ch.isdigit())
        if not code:
            return ""
        if len(code) <= 6:
            return code.zfill(6)
        return code

    def _read_csv(self, file_path: str) -> pd.DataFrame:
        """
        读取 CSV 文件，自动尝试多种编码

        :param file_path: CSV 文件路径
        :return: DataFrame
        """
        encodings = ["utf-8-sig", "utf-8", "gbk", "gb2312"]

        for encoding in encodings:
            try:
                df = pd.read_csv(file_path, encoding=encoding)
                logger.info(f"成功使用 {encoding} 编码读取 {file_path}")
                return df
            except Exception:
                continue

        raise ValueError(f"无法读取 CSV 文件: {file_path}，尝试了 utf-8, gbk, gb2312 等编码")

    def _clean_dataframe(self, df: pd.DataFrame, columns_mapping: dict) -> pd.DataFrame:
        """
        清理 DataFrame，只保留需要的列并重命名

        :param df: 原始 DataFrame
        :param columns_mapping: 列映射字典
        :return: 清理后的 DataFrame
        """
        # 只保留映射中存在的列
        available_columns = [col for col in columns_mapping.keys() if col in df.columns]
        df = df[available_columns].copy()

        # 重命名列
        df = df.rename(columns=columns_mapping)

        # 统一 ts_code（去后缀并补齐 6 位）
        if "ts_code" in df.columns:
            df["ts_code"] = df["ts_code"].apply(self.normalize_ts_code)
            df = df[df["ts_code"] != ""]

        # symbol 也统一为 6 位纯数字
        if "symbol" in df.columns:
            df["symbol"] = df["symbol"].apply(self.normalize_ts_code)

        # 去除重复
        if "ts_code" in df.columns:
            df = df.drop_duplicates(subset=["ts_code"], keep="first")

        # 去除 ts_code 为空的行
        df = df.dropna(subset=["ts_code"])

        return df

    def _get_basic_meta_map(self, ts_codes: List[str]) -> dict:
        """从 stock_basic 批量读取 name/industry 映射。"""
        codes = [self.normalize_ts_code(c) for c in ts_codes if c]
        codes = [c for c in codes if c]
        if not codes:
            return {}
        placeholders = ", ".join(["%s"] * len(codes))
        sql = f"SELECT ts_code, name, industry FROM stock_basic WHERE ts_code IN ({placeholders})"
        rows = self.db.query_all(sql, tuple(codes))
        return {
            self.normalize_ts_code(r.get("ts_code", "")): {
                "name": r.get("name") or "",
                "industry": r.get("industry") or "",
            }
            for r in rows
        }

    def import_stock_basic(self, csv_path: str, batch_size: int = 100) -> int:
        """
        导入全量股票基础信息

        :param csv_path: CSV 文件路径
        :param batch_size: 批量插入大小
        :return: 导入的记录数
        """
        logger.info(f"开始导入股票基础信息: {csv_path}")

        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"文件不存在: {csv_path}")

        df = self._read_csv(csv_path)
        df = self._clean_dataframe(df, self.STOCK_BASIC_COLUMNS)

        if df.empty:
            logger.warning("CSV 文件为空或没有有效数据")
            return 0

        total = 0
        now = datetime.now()

        for i in range(0, len(df), batch_size):
            batch = df.iloc[i : i + batch_size]

            # 构建批量插入 SQL
            placeholders = ", ".join(["%s"] * len(df.columns))
            columns = ", ".join(df.columns)
            sql = f"""
                INSERT INTO stock_basic ({columns}) VALUES ({placeholders})
                ON DUPLICATE KEY UPDATE
                    symbol = VALUES(symbol),
                    name = VALUES(name),
                    industry = VALUES(industry),
                    area = VALUES(area),
                    list_date = VALUES(list_date),
                    updated_at = CURRENT_TIMESTAMP
            """

            # 构建参数列表
            params_list = []
            for _, row in batch.iterrows():
                params = tuple(row[col] if pd.notnull(row[col]) else None for col in df.columns)
                params_list.append(params)

            try:
                conn = self.db.connect()
                with conn.cursor() as cursor:
                    cursor.executemany(sql, params_list)
                self.db.commit()
                total += len(params_list)
                logger.info(f"已导入 {total}/{len(df)} 条记录")
            except Exception as e:
                logger.error(f"批量导入失败: {e}")
                self.db.rollback()
                raise

        logger.info(f"股票基础信息导入完成，共 {total} 条记录")
        return total

    def import_ma120_pool(self, csv_path: str, batch_size: int = 100) -> int:
        """
        导入 120 日均线突破股票池

        :param csv_path: CSV 文件路径
        :param batch_size: 批量插入大小
        :return: 导入的记录数
        """
        logger.info(f"开始导入 120 日均线突破股票池: {csv_path}")

        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"文件不存在: {csv_path}")

        df = self._read_csv(csv_path)
        df = self._clean_dataframe(df, self.MA120_POOL_COLUMNS)

        if df.empty:
            logger.warning("CSV 文件为空或没有有效数据")
            return 0

        # name/industry 统一以 stock_basic 为准
        meta_map = self._get_basic_meta_map(df["ts_code"].tolist())
        if "name" in df.columns:
            df["name"] = df["ts_code"].map(lambda c: meta_map.get(c, {}).get("name", "")) \
                .where(df["ts_code"].map(lambda c: c in meta_map), df["name"])
        else:
            df["name"] = df["ts_code"].map(lambda c: meta_map.get(c, {}).get("name", ""))

        if "industry" in df.columns:
            df["industry"] = df["ts_code"].map(lambda c: meta_map.get(c, {}).get("industry", "")) \
                .where(df["ts_code"].map(lambda c: c in meta_map), df["industry"])
        else:
            df["industry"] = df["ts_code"].map(lambda c: meta_map.get(c, {}).get("industry", ""))

        total = 0

        for i in range(0, len(df), batch_size):
            batch = df.iloc[i : i + batch_size]

            placeholders = ", ".join(["%s"] * len(df.columns))
            columns = ", ".join(df.columns)
            sql = f"""
                INSERT INTO stock_pool_ma120 ({columns}) VALUES ({placeholders})
                ON DUPLICATE KEY UPDATE
                    name = VALUES(name),
                    industry = VALUES(industry),
                    break_date = VALUES(break_date),
                    updated_at = CURRENT_TIMESTAMP
            """

            params_list = []
            for _, row in batch.iterrows():
                params = tuple(row[col] if pd.notnull(row[col]) else None for col in df.columns)
                params_list.append(params)

            try:
                conn = self.db.connect()
                with conn.cursor() as cursor:
                    cursor.executemany(sql, params_list)
                self.db.commit()
                total += len(params_list)
                logger.info(f"已导入 {total}/{len(df)} 条记录")
            except Exception as e:
                logger.error(f"批量导入失败: {e}")
                self.db.rollback()
                raise

        logger.info(f"120 日均线突破股票池导入完成，共 {total} 条记录")
        return total

    def normalize_existing_data(self) -> None:
        """
        修正历史数据：
        1) 三张表 ts_code 统一为 6 位
        2) stock_basic 的 symbol 同步为 6 位
        3) stock_pool_ma120 / stock_ai_analysis 的 name,industry 以 stock_basic 回填
        """
        conn = self.db.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE stock_basic
                    SET ts_code = LPAD(SUBSTRING_INDEX(ts_code, '.', 1), 6, '0'),
                        symbol = LPAD(SUBSTRING_INDEX(COALESCE(symbol, ts_code), '.', 1), 6, '0')
                """)
                cursor.execute("""
                    UPDATE stock_pool_ma120
                    SET ts_code = LPAD(SUBSTRING_INDEX(ts_code, '.', 1), 6, '0')
                """)
                cursor.execute("""
                    UPDATE stock_ai_analysis
                    SET ts_code = LPAD(SUBSTRING_INDEX(ts_code, '.', 1), 6, '0')
                """)
                cursor.execute("""
                    UPDATE stock_pool_ma120 p
                    LEFT JOIN stock_basic b ON p.ts_code = b.ts_code
                    SET p.name = COALESCE(b.name, p.name),
                        p.industry = COALESCE(b.industry, p.industry)
                """)
                cursor.execute("""
                    UPDATE stock_ai_analysis a
                    LEFT JOIN stock_basic b ON a.ts_code = b.ts_code
                    SET a.name = COALESCE(b.name, a.name),
                        a.industry = COALESCE(b.industry, a.industry)
                """)
            self.db.commit()
            logger.info("历史数据规范化完成（ts_code/name/industry）")
        except Exception:
            self.db.rollback()
            raise

    def get_pool_stocks(self) -> List[dict]:
        """
        获取股票池中的所有股票

        :return: 股票列表
        """
        sql = """
            SELECT p.ts_code, p.name, p.industry, p.break_date,
                   a.id as analysis_id, a.analyzed_at
            FROM stock_pool_ma120 p
            LEFT JOIN stock_ai_analysis a ON p.ts_code = a.ts_code AND a.is_valid = 1
            ORDER BY p.created_at DESC
        """
        return self.db.query_all(sql)

    def get_pending_stocks(self) -> List[dict]:
        """
        获取待分析的股票（尚未进行 AI 分析的）

        :return: 待分析股票列表
        """
        sql = """
            SELECT p.ts_code, p.name, p.industry, p.break_date
            FROM stock_pool_ma120 p
            LEFT JOIN stock_ai_analysis a ON p.ts_code = a.ts_code AND a.is_valid = 1
            WHERE a.id IS NULL
            ORDER BY p.break_date DESC
        """
        return self.db.query_all(sql)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    from .db import Database, init_tables

    db = Database()

    # 初始化表
    init_tables(db)

    # 测试导入
    importer = CSVImporter(db)

    # 示例：导入股票基础信息
    # stock_basic_csv = "/path/to/stock_basic.csv"
    # if os.path.exists(stock_basic_csv):
    #     importer.import_stock_basic(stock_basic_csv)

    # 示例：导入 120 日均线突破股票池
    # ma120_csv = "/path/to/ma120_breakthrough.csv"
    # if os.path.exists(ma120_csv):
    #     importer.import_ma120_pool(ma120_csv)

    db.close()
