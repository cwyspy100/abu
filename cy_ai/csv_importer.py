"""
CSV 文件导入模块
支持导入全量股票基础信息和 120 日均线突破股票池
"""

import os
import logging
from pathlib import Path
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
        "stock_type": "stock_type",
        "market": "stock_type",
        "area": "area",
        "list_date": "list_date",
    }

    # 120日均线突破股票池列映射
    MA120_POOL_COLUMNS = {
        "ts_code": "ts_code",
        "name": "name",
        "industry": "industry",
        "breakthrough_date": "break_date",
        "market": "market",
    }

    # 兼容不同来源字段名
    MA120_POOL_ALIAS = {
        "break_date": "breakthrough_date",
        "突破日期": "breakthrough_date",
        "market_type": "market",
        "exchange": "market",
        "市场": "market",
        "股票代码": "ts_code",
        "code": "ts_code",
    }

    def __init__(self, db: Database):
        """
        初始化导入器

        :param db: Database 实例
        """
        self.db = db
        self._rom_meta_cache = {}

    @staticmethod
    def normalize_ts_code(ts_code) -> str:
        """
        统一股票代码格式：去掉交易所后缀并补齐到 6 位。
        示例：2594 / 2594.SZ -> 002594
        """
        if pd.isnull(ts_code):
            return ""
        code = str(ts_code).strip()
        if not code:
            return ""

        # 字母代码（如 AAPL）直接保留，供美股场景使用
        if "." not in code and any(ch.isalpha() for ch in code):
            return code.upper()

        if "." in code:
            code = code.split(".", 1)[0]
        code = "".join(ch for ch in code if ch.isdigit())
        if not code:
            return ""
        if len(code) <= 6:
            return code.zfill(6)
        return code

    @classmethod
    def infer_market(cls, raw_ts_code: str, raw_market: str = "") -> str:
        """推断市场类型：A股 / 港股 / 美股。"""
        market = str(raw_market or "").strip().upper()
        if market in ("A", "A股", "CN", "SH", "SZ", "BJ"):
            return "A股"
        if market in ("HK", "港股"):
            return "港股"
        if market in ("US", "美股"):
            return "美股"

        code = str(raw_ts_code or "").strip().upper()
        if code.endswith((".SH", ".SZ", ".BJ")) or code.startswith(("SH", "SZ", "BJ")):
            return "A股"
        if code.endswith(".HK") or code.startswith("HK"):
            return "港股"
        if code.endswith(".US"):
            return "美股"
        if any(ch.isalpha() for ch in code) and not code.startswith(("SH", "SZ", "BJ", "HK")):
            return "美股"
        return "A股"

    @classmethod
    def normalize_pool_ts_code(cls, raw_ts_code: str, market: str) -> str:
        """
        按市场标准化池内代码，避免 A/HK/US 冲突：
        - A股: 000001
        - 港股: 00700（不带 .HK）
        - 美股: AAPL（不带 .US）
        """
        raw = str(raw_ts_code or "").strip()
        mkt = cls.infer_market(raw, market)
        code = cls.normalize_ts_code(raw)
        if not code:
            return ""
        up = code.upper()
        if mkt == "港股":
            base = up.split(".", 1)[0]
            digits = "".join(ch for ch in base if ch.isdigit())
            if digits:
                # 港股标准 5 位，若被误补到 6 位，取后 5 位
                digits = digits[-5:]
                base = digits.zfill(5)
            else:
                base = base
            return base
        if mkt == "美股":
            base = up.split(".", 1)[0]
            return base
        # A股保持 6 位数字
        if "." in up:
            up = up.split(".", 1)[0]
        digits = "".join(ch for ch in up if ch.isdigit())
        return digits.zfill(6) if digits else up

    @classmethod
    def normalize_symbol_no_suffix(cls, raw_symbol: str, market: str = "") -> str:
        """
        标准化 symbol 主体（去后缀 .HK/.US），用于 stock_basic.symbol 存储。
        """
        s = str(raw_symbol or "").strip().upper()
        if not s:
            return ""
        if "." in s:
            s = s.split(".", 1)[0]
        mkt = cls.infer_market(s, market)
        if mkt == "港股":
            digits = "".join(ch for ch in s if ch.isdigit())
            if not digits:
                return s
            return digits[-5:].zfill(5)
        return s

    @classmethod
    def normalize_stock_basic_ts_code(cls, raw_symbol: str, market: str) -> str:
        """
        stock_basic.ts_code 规则：
        - 港股：5位数字，不带 .HK
        - 美股：不带 .US
        - A股：6位数字
        """
        mkt = cls.infer_market(raw_symbol, market)
        s = str(raw_symbol or "").strip().upper()
        if not s:
            return ""

        if mkt == "港股":
            if "." in s:
                s = s.split(".", 1)[0]
            digits = "".join(ch for ch in s if ch.isdigit())
            return digits[-5:].zfill(5) if digits else ""
        if mkt == "美股":
            if "." in s:
                s = s.split(".", 1)[0]
            return s
        # A股
        return cls.normalize_ts_code(s)

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
        # 字段别名归一（仅对股票池导入）
        alias_map = {}
        for old, new in self.MA120_POOL_ALIAS.items():
            if old in df.columns and new not in df.columns:
                alias_map[old] = new
        if alias_map:
            df = df.rename(columns=alias_map)

        # 只保留映射中存在的列
        available_columns = [col for col in columns_mapping.keys() if col in df.columns]
        df = df[available_columns].copy()

        # 重命名列
        df = df.rename(columns=columns_mapping)

        # 统一 ts_code
        if "ts_code" in df.columns:
            if columns_mapping == self.MA120_POOL_COLUMNS:
                # 股票池导入保留原始形态（避免港股/美股在此阶段被A股规则改写）
                df["ts_code"] = df["ts_code"].astype(str).str.strip()
            else:
                # 基础表导入使用旧规则：去后缀并补齐 6 位
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
        """从 stock_basic 批量读取 name/industry 映射（优先完整 ts_code 命中）。"""
        raw_codes = [str(c or "").strip().upper() for c in ts_codes if str(c or "").strip()]
        if not raw_codes:
            return {}

        # 兼容 stock_basic.ts_code 新规则（港股无后缀）与历史格式（带 .HK）
        code_set = set()
        for c in raw_codes:
            code_set.add(c)
            norm = self.normalize_ts_code(c)
            if norm:
                code_set.add(norm)
                # A股历史库兼容：ts_code 可能是 600036.SH / 000001.SZ / 430047.BJ
                if norm.isdigit() and len(norm) == 6:
                    code_set.add(f"{norm}.SH")
                    code_set.add(f"{norm}.SZ")
                    code_set.add(f"{norm}.BJ")
            if c.endswith(".HK"):
                hk_base = c.split(".", 1)[0]
                digits = "".join(ch for ch in hk_base if ch.isdigit())
                if digits:
                    code_set.add(digits[-5:].zfill(5))
            if c.endswith(".US"):
                code_set.add(c.split(".", 1)[0])
            if c.isdigit() and len(c) <= 5:
                code_set.add(c.zfill(5))
                code_set.add(f"{c.zfill(5)}.HK")
        codes = list(code_set)

        placeholders = ", ".join(["%s"] * len(codes))
        sql = f"SELECT ts_code, name, industry FROM stock_basic WHERE ts_code IN ({placeholders})"
        rows = self.db.query_all(sql, tuple(codes))

        meta = {}
        for r in rows:
            db_code = str(r.get("ts_code", "") or "").strip().upper()
            if not db_code:
                continue
            payload = {
                "name": r.get("name") or "",
                "industry": r.get("industry") or "",
            }
            # 完整代码键（优先）
            meta[db_code] = payload
            # 港股兼容键：无后缀 <-> .HK
            if db_code.isdigit() and len(db_code) <= 5:
                hk5 = db_code.zfill(5)
                meta[hk5] = payload
                meta[f"{hk5}.HK"] = payload
            if db_code.endswith(".HK"):
                hk_base = db_code.split(".", 1)[0]
                digits = "".join(ch for ch in hk_base if ch.isdigit())
                if digits:
                    hk5 = digits[-5:].zfill(5)
                    meta[hk5] = payload
                    meta[f"{hk5}.HK"] = payload
            # 美股兼容键：带/不带 .US
            if db_code.endswith(".US"):
                meta[db_code.split(".", 1)[0]] = payload
            elif any(ch.isalpha() for ch in db_code) and "." not in db_code:
                meta[f"{db_code}.US"] = payload
            # 兼容键（不带后缀）
            norm = self.normalize_ts_code(db_code)
            if norm and norm not in meta:
                meta[norm] = payload
        return meta

    @staticmethod
    def _rom_csv_path(filename: str) -> Path:
        return Path(__file__).resolve().parents[1] / "abupy" / "RomDataBu" / filename

    def _load_rom_market_meta(self, market: str) -> dict:
        """
        从 RomDataBu 的 stock_code_US/HK.csv 读取名称与行业映射。
        返回 key 统一为规范 ts_code（如 AAPL.US / 00700.HK）。
        """
        market = str(market or "").strip()
        if market in self._rom_meta_cache:
            return self._rom_meta_cache[market]

        if market == "美股":
            csv_path = self._rom_csv_path("stock_code_US.csv")
            suffix = ".US"
        elif market == "港股":
            csv_path = self._rom_csv_path("stock_code_HK.csv")
            suffix = ".HK"
        else:
            self._rom_meta_cache[market] = {}
            return {}

        if not csv_path.exists():
            logger.warning("RomDataBu 文件不存在，跳过回填: %s", csv_path)
            self._rom_meta_cache[market] = {}
            return {}

        try:
            df = pd.read_csv(csv_path, dtype=str, encoding="utf-8-sig")
        except Exception:
            try:
                df = pd.read_csv(csv_path, dtype=str, encoding="utf-8")
            except Exception as e:
                logger.warning("读取 RomDataBu 文件失败，跳过回填: %s err=%s", csv_path, e)
                self._rom_meta_cache[market] = {}
                return {}

        if "symbol" not in df.columns:
            self._rom_meta_cache[market] = {}
            return {}

        if "co_name" not in df.columns:
            df["co_name"] = ""
        if "industry" not in df.columns:
            df["industry"] = ""

        meta = {}
        for _, row in df.iterrows():
            raw_symbol = str(row.get("symbol", "") or "").strip()
            if not raw_symbol:
                continue
            ts_code = self.normalize_pool_ts_code(f"{raw_symbol}{suffix}", market)
            if not ts_code:
                continue
            meta[ts_code] = {
                "name": str(row.get("co_name", "") or "").strip(),
                "industry": str(row.get("industry", "") or "").strip(),
            }

        self._rom_meta_cache[market] = meta
        logger.info("加载 RomDataBu %s 元数据 %s 条", market, len(meta))
        return meta

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

        if "stock_type" not in df.columns:
            df["stock_type"] = df["ts_code"].apply(lambda c: self.infer_market(str(c), ""))
        else:
            df["stock_type"] = df["stock_type"].apply(lambda x: self.infer_market("", str(x)))

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

    def import_stock_basic_from_rom(
        self,
        hk_csv_path: str,
        us_csv_path: str,
        cn_csv_path: Optional[str] = None,
        batch_size: int = 200,
    ) -> int:
        """
        从 RomDataBu 的港股/美股代码表导入 stock_basic。

        - 港股：stock_code_HK.csv 的 symbol -> 规范为 5位数字.HK
        - 美股：stock_code_US.csv 的 symbol -> 规范为 字母代码.US
        - name/industry 分别取 co_name/industry
        - area 字段写入 市场（港股/美股）
        """
        rows = []
        failed_symbols = []
        sources = [
            ("A股", cn_csv_path, "A股"),
            ("港股", hk_csv_path, "港股"),
            ("美股", us_csv_path, "美股"),
        ]

        for market, file_path, area in sources:
            if not file_path or not os.path.exists(file_path):
                logger.warning("%s 基础表不存在，跳过: %s", market, file_path)
                continue
            df = self._read_csv(file_path)
            if "symbol" not in df.columns:
                logger.warning("%s 基础表缺少 symbol 列，跳过: %s", market, file_path)
                continue
            if "co_name" not in df.columns:
                df["co_name"] = ""
            if "industry" not in df.columns:
                df["industry"] = ""

            for _, r in df.iterrows():
                sym = str(r.get("symbol", "") or "").strip()
                if not sym:
                    failed_symbols.append(
                        {"market": market, "symbol": sym, "reason": "symbol 为空"}
                    )
                    continue
                ts_code = self.normalize_stock_basic_ts_code(sym, market)
                if not ts_code:
                    failed_symbols.append(
                        {"market": market, "symbol": sym, "reason": "ts_code 规范化失败"}
                    )
                    continue
                base = self.normalize_symbol_no_suffix(sym, market)
                if not base:
                    failed_symbols.append(
                        {"market": market, "symbol": sym, "reason": "symbol 去后缀后为空"}
                    )
                    continue
                rows.append(
                    {
                        "ts_code": ts_code,
                        "symbol": base,
                        "name": str(r.get("co_name", "") or "").strip(),
                        "industry": str(r.get("industry", "") or "").strip(),
                        "stock_type": market,
                        "area": area,
                        "list_date": None,
                    }
                )

        if not rows:
            logger.warning("没有可导入的港股/美股基础数据")
            if failed_symbols:
                logger.warning("导入失败 symbol 共 %s 条（前50条）:", len(failed_symbols))
                for item in failed_symbols[:50]:
                    logger.warning(
                        "导入失败 symbol market=%s symbol=%s reason=%s",
                        item["market"], item["symbol"], item["reason"]
                    )
            return 0

        df_all = pd.DataFrame(rows).drop_duplicates(subset=["ts_code"], keep="first")
        total = 0
        columns = ["ts_code", "symbol", "name", "industry", "stock_type", "area", "list_date"]
        sql = """
            INSERT INTO stock_basic (ts_code, symbol, name, industry, stock_type, area, list_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                symbol = VALUES(symbol),
                name = VALUES(name),
                industry = VALUES(industry),
                stock_type = VALUES(stock_type),
                area = VALUES(area),
                updated_at = CURRENT_TIMESTAMP
        """

        for i in range(0, len(df_all), batch_size):
            batch = df_all.iloc[i : i + batch_size]
            params_list = []
            for _, row in batch.iterrows():
                params_list.append(tuple(row.get(c, None) for c in columns))
            try:
                conn = self.db.connect()
                with conn.cursor() as cursor:
                    cursor.executemany(sql, params_list)
                self.db.commit()
                total += len(params_list)
                logger.info("stock_basic(港/美) 已导入 %s/%s", total, len(df_all))
            except Exception as e:
                logger.error("导入 stock_basic(港/美) 失败: %s", e)
                self.db.rollback()
                raise

        logger.info("stock_basic 港股/美股导入完成，共 %s 条", total)
        if failed_symbols:
            logger.warning("导入失败 symbol 共 %s 条（前50条）:", len(failed_symbols))
            for item in failed_symbols[:50]:
                logger.warning(
                    "导入失败 symbol market=%s symbol=%s reason=%s",
                    item["market"], item["symbol"], item["reason"]
                )
        return total

    def import_ma120_pool(self, csv_path: str, batch_size: int = 100, market: Optional[str] = None) -> int:
        """
        导入 120 日均线突破股票池

        :param csv_path: CSV 文件路径
        :param batch_size: 批量插入大小
        :return: 导入的记录数
        """
        logger.info(f"开始导入 120 日均线突破股票池: {csv_path}")

        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"文件不存在: {csv_path}")

        df_raw = self._read_csv(csv_path)
        df = df_raw.copy()
        df = self._clean_dataframe(df, self.MA120_POOL_COLUMNS)

        if df.empty:
            logger.warning("CSV 文件为空或没有有效数据")
            return 0

        # market 推断：兼容 A股/港股/美股
        if "market" not in df.columns:
            df["market"] = ""
        forced_market = self.infer_market("", market) if market else None
        if forced_market:
            df["market"] = forced_market
        df["market"] = df.apply(
            lambda r: self.infer_market(raw_ts_code=r.get("ts_code", ""), raw_market=r.get("market", "")),
            axis=1,
        )
        df["ts_code"] = df.apply(
            lambda r: self.normalize_pool_ts_code(r.get("ts_code", ""), r.get("market", "")),
            axis=1,
        )
        df = df[df["ts_code"] != ""]

        # name/industry 统一以 stock_basic 为准（所有市场）
        meta_map = self._get_basic_meta_map(df["ts_code"].tolist())

        def _merged_meta(ts_code: str, mkt: str) -> dict:
            key = str(ts_code or "").strip().upper()
            if key in meta_map:
                return meta_map.get(key, {}) or {}
            # 兜底兼容：历史 stock_basic 可能存储不带后缀
            norm = self.normalize_ts_code(key)
            if norm in meta_map:
                return meta_map.get(norm, {}) or {}
            return {}

        if "name" in df.columns:
            df["name"] = df.apply(
                lambda r: (_merged_meta(r["ts_code"], r.get("market", "")).get("name") or r.get("name", "")),
                axis=1,
            )
        else:
            df["name"] = df.apply(
                lambda r: _merged_meta(r["ts_code"], r.get("market", "")).get("name", ""),
                axis=1,
            )

        if "industry" in df.columns:
            df["industry"] = df.apply(
                lambda r: (_merged_meta(r["ts_code"], r.get("market", "")).get("industry") or r.get("industry", "")),
                axis=1,
            )
        else:
            df["industry"] = df.apply(
                lambda r: _merged_meta(r["ts_code"], r.get("market", "")).get("industry", ""),
                axis=1,
            )

        # 导入前，仅将“本次导入涉及的市场”标记为失效，避免覆盖其他市场
        target_markets = sorted({str(m).strip() for m in df["market"].tolist() if str(m).strip()})
        if target_markets:
            placeholders = ", ".join(["%s"] * len(target_markets))
            self.db.execute(
                f"UPDATE stock_pool_ma120 SET status = 0, updated_at = NOW() WHERE market IN ({placeholders})",
                tuple(target_markets),
            )
            self.db.commit()
            logger.info("导入前已将以下市场置失效: %s", ",".join(target_markets))

        # 现有记录映射（按 ts_code + market）
        existing_rows = self.db.query_all("SELECT ts_code, market FROM stock_pool_ma120")
        existing_keys = {(str(r.get("ts_code", "")), str(r.get("market", ""))) for r in existing_rows}

        total = 0
        inserted = 0
        reactivated = 0

        for i in range(0, len(df), batch_size):
            batch = df.iloc[i : i + batch_size]
            insert_params_list = []
            reactivate_params_list = []
            for _, row in batch.iterrows():
                ts_code = row["ts_code"] if pd.notnull(row["ts_code"]) else ""
                market = row["market"] if pd.notnull(row["market"]) else ""
                key = (str(ts_code), str(market))
                if key in existing_keys:
                    reactivate_params_list.append((market, ts_code))
                    reactivated += 1
                    continue

                insert_params_list.append(
                    (
                        ts_code,
                        row.get("name", None) if pd.notnull(row.get("name", None)) else None,
                        row.get("industry", None) if pd.notnull(row.get("industry", None)) else None,
                        row.get("break_date", None) if pd.notnull(row.get("break_date", None)) else None,
                        market,
                        1,
                    )
                )
                inserted += 1
                existing_keys.add(key)

            try:
                conn = self.db.connect()
                with conn.cursor() as cursor:
                    if insert_params_list:
                        cursor.executemany(
                            """
                            INSERT INTO stock_pool_ma120
                                (ts_code, name, industry, break_date, market, status)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            """,
                            insert_params_list,
                        )
                    if reactivate_params_list:
                        cursor.executemany(
                            """
                            UPDATE stock_pool_ma120
                            SET status = 1, updated_at = NOW(), market = %s
                            WHERE ts_code = %s
                            """,
                            reactivate_params_list,
                        )
                self.db.commit()
                total += len(insert_params_list) + len(reactivate_params_list)
                logger.info(f"已导入 {total}/{len(df)} 条记录")
            except Exception as e:
                logger.error(f"批量导入失败: {e}")
                self.db.rollback()
                raise

        logger.info(
            f"120 日均线突破股票池导入完成，共处理 {total} 条（新增 {inserted}，激活 {reactivated}）"
        )
        return total

    def export_ma120_import_csv(self, source_csv: str, output_csv: str, market: Optional[str] = None) -> int:
        """
        将分析结果 CSV 转为可直接导入 stock_pool_ma120 的标准格式。
        输出列：ts_code,name,industry,breakthrough_date,market
        """
        if not os.path.exists(source_csv):
            raise FileNotFoundError(f"文件不存在: {source_csv}")

        df = self._read_csv(source_csv)
        if "ts_code" not in df.columns:
            raise ValueError("源 CSV 缺少 ts_code 列")
        if "breakthrough_date" not in df.columns and "break_date" not in df.columns:
            raise ValueError("源 CSV 缺少 breakthrough_date/break_date 列")

        if "breakthrough_date" not in df.columns and "break_date" in df.columns:
            df["breakthrough_date"] = df["break_date"]
        if "name" not in df.columns:
            df["name"] = ""
        if "industry" not in df.columns:
            df["industry"] = ""

        forced_market = None
        if market:
            forced_market = self.infer_market("", market)

        out = pd.DataFrame()
        out_market_series = pd.Series(forced_market, index=df.index) if forced_market else df["ts_code"].apply(
            lambda x: self.infer_market(x, "")
        )
        out["market"] = out_market_series
        out["ts_code"] = [
            self.normalize_pool_ts_code(code, mkt)
            for code, mkt in zip(df["ts_code"].tolist(), out["market"].tolist())
        ]
        out["name"] = df["name"]
        out["industry"] = df["industry"]
        out["breakthrough_date"] = df["breakthrough_date"]

        out = out[out["ts_code"] != ""].drop_duplicates(subset=["ts_code", "market"], keep="first")
        out.to_csv(output_csv, index=False, encoding="utf-8-sig")
        logger.info(f"已导出可导入文件: {output_csv}（{len(out)} 条）")
        return len(out)

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
            SELECT p.ts_code, p.name, p.industry, p.market, p.break_date,
                   a.id as analysis_id, a.analyzed_at
            FROM stock_pool_ma120 p
            LEFT JOIN stock_ai_analysis a ON p.ts_code = a.ts_code AND a.is_valid = 1
            WHERE p.status = 1
            ORDER BY p.created_at DESC
        """
        return self.db.query_all(sql)

    def get_pending_stocks(self) -> List[dict]:
        """
        获取待分析的股票（尚未进行 AI 分析的）

        :return: 待分析股票列表
        """
        sql = """
            SELECT p.ts_code, p.name, p.industry, p.market, p.break_date
            FROM stock_pool_ma120 p
            LEFT JOIN stock_ai_analysis a ON p.ts_code = a.ts_code AND a.is_valid = 1
            WHERE a.id IS NULL
              AND p.status = 1
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
