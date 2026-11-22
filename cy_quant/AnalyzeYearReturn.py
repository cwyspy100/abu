#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统计 A股 / 港股 / 美股 K 线文件中从年初到当前的涨幅，写入 stock_pool_year。

表结构（来自用户 SQL）：
    CREATE TABLE `stock_pool_year` (
      `id` int(11) NOT NULL AUTO_INCREMENT,
      `ts_code` varchar(20) NOT NULL,
      `name` varchar(30) DEFAULT NULL,
      `industry` varchar(50) DEFAULT NULL,
      `up_percent` float DEFAULT '0' COMMENT '今年以来的涨幅',
      `up_percent_week` float DEFAULT '0' COMMENT '本周涨幅',
      `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
      `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
      `remark` text,
      `market` varchar(10) DEFAULT 'A股',
      PRIMARY KEY (`id`),
      UNIQUE KEY `uk_ts_code_market` (`ts_code`,`market`),
      KEY `idx_market` (`market`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='年度股票池';

写入方式参考 cy_ai.main --import-pool：
- 数据源：~/abu/data/csv/ 下的 K 线文件（按 sh/sz/hk/us 前缀分组）。
- 扫描三个市场所有符合命名约定的文件（shxxxxxx_yyyymmdd_yyyymmdd 等）。
- name / industry 优先从 stock_basic 表回填。
- 写入策略（无 status 字段）：仅对本次涉及的 market 做写入（INSERT … ON DUPLICATE KEY UPDATE）；
  上次 up_percent 与本次计算结果求差，写入 up_percent_week（首次为 0）。

使用示例：
    python cy_quant/AnalyzeYearReturn.py            # 扫描 A股+港股+美股 全部
    python cy_quant/AnalyzeYearReturn.py cn         # 仅 A股
    python cy_quant/AnalyzeYearReturn.py hk         # 仅 港股
    python cy_quant/AnalyzeYearReturn.py us         # 仅 美股
    python cy_quant/AnalyzeYearReturn.py all --min-last-date 20260101
"""

import glob
import logging
import os
import sys
import warnings
from datetime import datetime
from typing import List, Optional, Tuple

import pandas as pd

warnings.filterwarnings("ignore")

# 让脚本既可被 import，也可作为入口运行
_PKG_PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PKG_PARENT not in sys.path:
    sys.path.insert(0, _PKG_PARENT)

logger = logging.getLogger(__name__)

# 文件名解析：与 Analyze120MA 保持一致
#   sh600452_20240703_20251217
#   usZZZ_20240126_20260418
_PREFIX_TO_EXCHANGE = {"sh": "SH", "sz": "SZ", "hk": "HK", "us": "US"}
_PREFIX_TO_MARKET = {"sh": "A股", "sz": "A股", "hk": "港股", "us": "美股"}


def _setup_logging():
    if not logger.handlers:
        h = logging.StreamHandler()
        h.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
        )
        logger.addHandler(h)
    logger.setLevel(logging.INFO)


class AnalyzeYearReturn:
    """统计各市场 K 线文件的「年初至今」涨幅，写入 stock_pool_year。"""

    # 默认扫描的三个市场；可通过 prefixes 参数覆盖
    DEFAULT_PREFIXES = ["sh", "sz", "hk", "us"]

    def __init__(self, prefixes: Optional[List[str]] = None):
        """
        :param prefixes: 要扫描的文件前缀列表，None 表示 A股+港股+美股全扫
        """
        self.csv_dir = os.path.expanduser("~/abu/data/csv")
        # 兼容 astock 子目录（与 csv_importer 的搜索顺序保持一致）
        self._csv_roots = [self.csv_dir, os.path.join(self.csv_dir, "astock")]
        self.prefixes = (
            list(prefixes) if prefixes else list(self.DEFAULT_PREFIXES)
        )
        # 标准化
        self.prefixes = [str(p).strip().lower() for p in self.prefixes if str(p).strip()]
        for p in self.prefixes:
            if p not in _PREFIX_TO_EXCHANGE:
                raise ValueError(
                    "不支持的前缀: %r（仅支持 sh/sz/hk/us）" % p
                )
        self.results: List[dict] = []

    # ------------------------------------------------------------------ #
    # 文件扫描
    # ------------------------------------------------------------------ #
    def get_stock_files(self) -> List[str]:
        """获取所有指定前缀下、符合命名约定的 K 线文件路径。"""
        valid: List[str] = []
        seen: set = set()
        for prefix in self.prefixes:
            for root in self._csv_roots:
                if not os.path.exists(root):
                    continue
                patterns = [
                    os.path.join(root, f"{prefix}*"),
                    os.path.join(root, f"{prefix}*.csv"),
                ]
                for pat in patterns:
                    for f in glob.glob(pat):
                        if f in seen:
                            continue
                        if self._is_valid_filename(os.path.basename(f), prefix):
                            valid.append(f)
                            seen.add(f)
        valid.sort()
        logger.info("找到 %s 个有效 K 线文件（前缀=%s）", len(valid), ",".join(self.prefixes))
        return valid

    @staticmethod
    def _is_valid_filename(name: str, prefix: str) -> bool:
        """
        校验文件名是否形如 sh600452_20240703_20251217（可带 .csv）。
        """
        stem = name[:-4] if name.lower().endswith(".csv") else name
        if not stem.lower().startswith(prefix):
            return False
        parts = stem.split("_")
        if len(parts) < 3:
            return False
        # 中间两段应为 8 位日期
        if not (parts[1].isdigit() and len(parts[1]) == 8):
            return False
        if not (parts[2].isdigit() and len(parts[2]) == 8):
            return False
        return True

    @staticmethod
    def parse_filename(filepath: str) -> Optional[Tuple[str, str, str, str]]:
        """
        解析文件名，返回 (ts_code, market_label, start_date, end_date)。
        ts_code 不带交易所后缀（与 stock_basic.ts_code 的新规则保持一致）：
            A股 -> 600452
            港股 -> 00700
            美股 -> AAPL
        """
        name = os.path.basename(filepath)
        stem = name[:-4] if name.lower().endswith(".csv") else name
        parts = stem.split("_")
        if len(parts) < 3:
            return None
        code_part = parts[0]
        if len(code_part) < 3:
            return None
        head2 = code_part[:2].lower()
        if head2 not in _PREFIX_TO_EXCHANGE:
            return None
        exchange = _PREFIX_TO_EXCHANGE[head2]
        market = _PREFIX_TO_MARKET[head2]
        symbol = code_part[2:]
        if not symbol:
            return None

        if market == "A股":
            ts_code = symbol.zfill(6) if symbol.isdigit() else symbol
        elif market == "港股":
            digits = "".join(ch for ch in symbol if ch.isdigit())
            if digits:
                ts_code = digits[-5:].zfill(5)
            else:
                ts_code = symbol
        else:  # 美股
            ts_code = symbol.upper()
        return ts_code, market, parts[1], parts[2]

    # ------------------------------------------------------------------ #
    # 单股分析
    # ------------------------------------------------------------------ #
    def _read_kline(self, filepath: str) -> Optional[pd.DataFrame]:
        """
        读取 K 线文件，自动尝试多种编码。
        约定列：date(YYYYMMDD 或 YYYY-MM-DD), open, close, high, low, volume …
        """
        for enc in ("utf-8-sig", "utf-8", "gbk", "gb2312"):
            try:
                df = pd.read_csv(filepath, encoding=enc)
            except Exception:
                continue
            if df is None or df.empty:
                continue

            # 兼容 "Unnamed: 0" 作为日期列
            if "Unnamed: 0" in df.columns and "date" not in df.columns:
                df = df.rename(columns={"Unnamed: 0": "date"})

            if "date" not in df.columns or "close" not in df.columns:
                continue
            df = df.copy()
            # 把 date 规范为字符串 8 位
            df["date"] = df["date"].astype(str).str.replace(r"[^\d]", "", regex=True).str[:8]
            df = df[df["date"].str.len() == 8]
            if df.empty:
                continue
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            df = df.dropna(subset=["close"])
            if df.empty:
                continue
            df = df.sort_values("date").reset_index(drop=True)
            return df
        return None

    @staticmethod
    def _ytd_growth(df: pd.DataFrame, year: int) -> Optional[dict]:
        """
        计算年内首行到最后一行的涨幅。
        缺失或不足两行时返回 None。
        """
        if df is None or df.empty:
            return None
        df_year = df[df["date"].str.startswith(f"{year}")]
        if len(df_year) < 2:
            return None
        start_close = float(df_year.iloc[0]["close"])
        end_close = float(df_year.iloc[-1]["close"])
        if start_close <= 0:
            return None
        growth = round((end_close / start_close - 1.0) * 100.0, 4)
        return {
            "year_start_date": df_year.iloc[0]["date"],
            "year_end_date": df_year.iloc[-1]["date"],
            "year_start_price": round(start_close, 4),
            "year_end_price": round(end_close, 4),
            "ytd_growth": growth,
        }

    def _analyze_one(self, filepath: str, year: int) -> Optional[dict]:
        parsed = self.parse_filename(filepath)
        if parsed is None:
            return None
        ts_code, market, _, end_date_in_name = parsed
        df = self._read_kline(filepath)
        if df is None or df.empty:
            return None
        info = self._ytd_growth(df, year)
        if info is None:
            return None
        info.update(
            {
                "ts_code": ts_code,
                "market": market,
                "file_end_date": end_date_in_name,
            }
        )
        return info

    # ------------------------------------------------------------------ #
    # 主流程
    # ------------------------------------------------------------------ #
    def analyze_all(self, year: Optional[int] = None) -> pd.DataFrame:
        """
        扫描所有 K 线文件，计算年内涨幅，返回 DataFrame。
        """
        if year is None:
            year = datetime.now().year

        files = self.get_stock_files()
        if not files:
            return pd.DataFrame()

        logger.info("=" * 60)
        logger.info("开始统计 %s 年度涨幅（市场：%s）", year, ",".join(self.prefixes))
        logger.info("=" * 60)

        rows: List[dict] = []
        total = len(files)
        for i, fp in enumerate(files, 1):
            r = self._analyze_one(fp, year)
            if r is not None:
                rows.append(r)
            if i % 200 == 0:
                logger.info("已处理 %d/%d 个文件，命中 %d 只", i, total, len(rows))

        df = pd.DataFrame(rows)
        if df.empty:
            logger.info("未找到任何 %d 年内有效 K 线数据", year)
            return df

        # 去重：(ts_code, market) 保留年内最新 end_date
        df = df.sort_values(["ts_code", "market", "year_end_date"], ascending=[True, True, False])
        df = df.drop_duplicates(subset=["ts_code", "market"], keep="first")
        logger.info("扫描完成：%d 只标的年内有数据", len(df))
        return df

    # ------------------------------------------------------------------ #
    # 写入 stock_pool_year（参考 cy_ai.main --import-pool）
    # ------------------------------------------------------------------ #
    def write_to_db(self, df: pd.DataFrame, db=None) -> int:
        """
        把结果写入 stock_pool_year。返回受影响行数（新增+更新合计）。
        :param df: analyze_all 返回的 DataFrame
        :param db: Database 实例（None 时按需 import 并新建）
        """
        if df is None or df.empty:
            logger.info("无数据可写入 stock_pool_year")
            return 0

        # 延迟 import cy_ai.db，避免在不需要写入时引入依赖
        from cy_ai.db import Database
        from cy_ai.csv_importer import CSVImporter

        own_db = False
        if db is None:
            db = Database()
            own_db = True
        try:
            importer = CSVImporter(db)

            # 1) 准备写入表
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS stock_pool_year (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    ts_code VARCHAR(20) NOT NULL,
                    name VARCHAR(30) DEFAULT NULL,
                    industry VARCHAR(50) DEFAULT NULL,
                    up_percent FLOAT DEFAULT 0 COMMENT '今年以来的涨幅',
                    up_percent_week FLOAT DEFAULT 0 COMMENT '本周涨幅',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    remark TEXT,
                    market VARCHAR(10) DEFAULT 'A股' COMMENT '市场：A股/港股/美股',
                    UNIQUE KEY uk_ts_code_market (ts_code, market),
                    KEY idx_market (market)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='年度股票池'
                """
            )
            db.commit()

            # 2) 准备行情数据：market, ts_code, up_percent
            #    market 在文件解析时已确定；ts_code 已在 parse_filename 中规范化。
            df["market"] = df["market"].apply(lambda m: m if m in ("A股", "港股", "美股") else "A股")
            df["up_percent"] = pd.to_numeric(df["ytd_growth"], errors="coerce").fillna(0.0)

            # 3) name/industry 从 stock_basic 批量回填
            meta_map = importer._get_basic_meta_map(df["ts_code"].astype(str).tolist())

            def _fill_name(row) -> str:
                key = str(row["ts_code"]).strip().upper()
                if key in meta_map and meta_map[key].get("name"):
                    return meta_map[key]["name"]
                norm = CSVImporter.normalize_ts_code(key)
                if norm in meta_map and meta_map[norm].get("name"):
                    return meta_map[norm]["name"]
                return ""

            def _fill_industry(row) -> str:
                key = str(row["ts_code"]).strip().upper()
                if key in meta_map and meta_map[key].get("industry"):
                    return meta_map[key]["industry"]
                norm = CSVImporter.normalize_ts_code(key)
                if norm in meta_map and meta_map[norm].get("industry"):
                    return meta_map[norm]["industry"]
                return ""

            df["name"] = df.apply(_fill_name, axis=1)
            df["industry"] = df.apply(_fill_industry, axis=1)

            # 4) 本次涉及的市场：从 df 取
            target_markets = sorted({m for m in df["market"].tolist() if m})
            if not target_markets:
                logger.info("无可写入的市场，结束")
                return 0

            # 5) 读取旧 up_percent，用于算 up_percent_week
            placeholders = ", ".join(["%s"] * len(target_markets))
            old_rows = db.query_all(
                f"SELECT ts_code, market, up_percent FROM stock_pool_year "
                f"WHERE market IN ({placeholders})",
                tuple(target_markets),
            )
            old_map = {
                (str(r.get("ts_code", "")), str(r.get("market", ""))): r.get("up_percent")
                for r in old_rows
            }

            # 6) 批量 UPSERT
            insert_params = []
            seen_keys: set = set()
            for _, row in df.iterrows():
                ts_code = str(row["ts_code"]).strip()
                market = str(row["market"]).strip()
                if not ts_code or not market:
                    continue
                key = (ts_code, market)
                if key in seen_keys:
                    continue
                seen_keys.add(key)

                new_up = float(row["up_percent"]) if pd.notnull(row["up_percent"]) else 0.0
                old_up = old_map.get(key)
                if old_up is not None and pd.notnull(old_up):
                    try:
                        up_week = round(float(new_up) - float(old_up), 4)
                    except (TypeError, ValueError):
                        up_week = 0.0
                else:
                    up_week = 0.0

                name = str(row.get("name", "") or "").strip() or None
                industry = str(row.get("industry", "") or "").strip() or None
                remark = "YTD scan"  # 写一个简短的 remark 标记，便于追溯

                # 用 INSERT … ON DUPLICATE KEY UPDATE 一并处理新增与更新
                insert_params.append(
                    (ts_code, name, industry, new_up, up_week, market, remark)
                )

            if not insert_params:
                logger.info("无有效记录可写入")
                return 0

            sql = """
                INSERT INTO stock_pool_year
                    (ts_code, name, industry, up_percent, up_percent_week, market, remark)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    name = COALESCE(VALUES(name), name),
                    industry = COALESCE(VALUES(industry), industry),
                    up_percent = VALUES(up_percent),
                    up_percent_week = VALUES(up_percent_week),
                    market = VALUES(market),
                    remark = VALUES(remark),
                    updated_at = NOW()
            """
            try:
                conn = db.connect()
                with conn.cursor() as cursor:
                    cursor.executemany(sql, insert_params)
                db.commit()
                affected = len(insert_params)
                logger.info(
                    "stock_pool_year 写入完成：本次涉及市场=%s，待 upsert=%s（实际生效可能因冲突而更少）",
                    ",".join(target_markets),
                    affected,
                )
                return affected
            except Exception as e:
                db.rollback()
                logger.error("写入 stock_pool_year 失败: %s", e)
                raise
        finally:
            if own_db:
                db.close()


# ---------------------------------------------------------------------- #
# 命令行入口
# ---------------------------------------------------------------------- #
def main(market: str = "all", year: Optional[int] = None) -> int:
    """
    :param market: 'cn' | 'hk' | 'us' | 'all' | 'cn,us' … 多个用英文逗号分隔
    :param year:   统计年份；None 表示当前年
    """
    _setup_logging()
    if not market:
        market = "all"
    raw_parts = [p.strip().lower() for p in market.split(",") if p.strip()]
    prefixes: List[str] = []
    for p in raw_parts:
        if p in ("cn", "a", "sh,sz"):
            prefixes.extend(["sh", "sz"])
        elif p == "all":
            prefixes.extend(["sh", "sz", "hk", "us"])
        elif p in ("sh", "sz", "hk", "us"):
            prefixes.append(p)
        elif p in ("a股", "cn"):
            prefixes.extend(["sh", "sz"])
        elif p == "港股":
            prefixes.append("hk")
        elif p == "美股":
            prefixes.append("us")
        else:
            raise ValueError("不支持的市场标识: %r" % p)
    # 去重保持顺序
    seen = set()
    prefixes = [x for x in prefixes if not (x in seen or seen.add(x))]

    analyzer = AnalyzeYearReturn(prefixes=prefixes)
    df = analyzer.analyze_all(year=year)
    if df.empty:
        return 0
    analyzer.write_to_db(df)
    # 也保存一份 CSV 便于核查
    out_name = f"year_return_{year or datetime.now().year}_{'_'.join(prefixes)}.csv"
    out_path = os.path.join(os.getcwd(), out_name)
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    logger.info("结果 CSV 已保存至: %s", out_path)
    return len(df)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(
        description="统计 A股/港股/美股年初至今涨幅并写入 stock_pool_year"
    )
    ap.add_argument(
        "market",
        nargs="?",
        default="all",
        help="市场：cn=A股 sh+sz, hk=港股, us=美股, all=全部, 多个用英文逗号分隔，如 cn,us",
    )
    ap.add_argument(
        "--year",
        type=int,
        default=None,
        help="统计年份（默认当前年）",
    )
    args = ap.parse_args()
    main(market=args.market, year=args.year)
