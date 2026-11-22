#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
扫描本地 K 线，筛选「当前收盘价在 120 日均线之上」的标的，
统计 2026 年涨幅、本月涨幅、本周涨幅、最近一周（5 个交易日）涨幅。

数据源：~/abu/data/csv/（与 Analyze120MA.py 相同命名约定）

命令行::

  python cy_quant/Analyze120MAAboveReturns.py              # A股+港股+美股
  python cy_quant/Analyze120MAAboveReturns.py cn           # 仅 A 股 sh+sz
  python cy_quant/Analyze120MAAboveReturns.py hk           # 仅港股
  python cy_quant/Analyze120MAAboveReturns.py us           # 仅美股
  python cy_quant/Analyze120MAAboveReturns.py all --year 2026
"""

from __future__ import annotations

import argparse
import glob
import logging
import os
import time
import warnings
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd

warnings.filterwarnings("ignore")

logger = logging.getLogger(__name__)

_PREFIX_TO_EXCHANGE = {"sh": "SH", "sz": "SZ", "hk": "HK", "us": "US"}
_PREFIX_TO_MARKET = {"sh": "A股", "sz": "A股", "hk": "港股", "us": "美股"}
_DEFAULT_PREFIXES = ["sh", "sz", "hk", "us"]
_DEFAULT_OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "output"
)


def _setup_logging() -> None:
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
        )
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)


class Analyze120MAAboveReturns:
    """筛选站上 MA120 的标的，并计算多周期涨幅。"""

    def __init__(
        self,
        prefixes: Optional[List[str]] = None,
        csv_dir: Optional[str] = None,
        stat_year: int = 2026,
    ):
        self.csv_dir = os.path.expanduser(csv_dir or "~/abu/data/csv")
        self._csv_roots = [self.csv_dir, os.path.join(self.csv_dir, "astock")]
        self.prefixes = list(prefixes) if prefixes else list(_DEFAULT_PREFIXES)
        self.prefixes = [str(p).strip().lower() for p in self.prefixes if str(p).strip()]
        for p in self.prefixes:
            if p not in _PREFIX_TO_EXCHANGE:
                raise ValueError("不支持的前缀: %r（仅 sh/sz/hk/us）" % p)
        self.stat_year = int(stat_year)

    # ------------------------------------------------------------------ #
    # 文件扫描与解析
    # ------------------------------------------------------------------ #
    def get_stock_files(self) -> List[str]:
        valid: List[str] = []
        seen: set = set()
        for prefix in self.prefixes:
            for root in self._csv_roots:
                if not os.path.isdir(root):
                    continue
                for pat in (
                    os.path.join(root, f"{prefix}*"),
                    os.path.join(root, f"{prefix}*.csv"),
                ):
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
        stem = name[:-4] if name.lower().endswith(".csv") else name
        if not stem.lower().startswith(prefix):
            return False
        parts = stem.split("_")
        if len(parts) < 3:
            return False
        return (
            parts[1].isdigit()
            and len(parts[1]) == 8
            and parts[2].isdigit()
            and len(parts[2]) == 8
        )

    @staticmethod
    def parse_filename(filepath: str) -> Optional[Tuple[str, str, str, str]]:
        """返回 (ts_code, market, start_date, end_date)。"""
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
        market = _PREFIX_TO_MARKET[head2]
        symbol = code_part[2:]
        if not symbol:
            return None

        if market == "A股":
            ts_code = symbol.zfill(6) if symbol.isdigit() else symbol
        elif market == "港股":
            digits = "".join(ch for ch in symbol if ch.isdigit())
            ts_code = digits[-5:].zfill(5) if digits else symbol
        else:
            ts_code = symbol.upper()
        return ts_code, market, parts[1], parts[2]

    @staticmethod
    def _should_skip_symbol(ts_code: str, market: str) -> bool:
        """跳过常见指数代码。"""
        if market != "A股":
            return False
        code = str(ts_code)
        if code.startswith("399"):
            return True
        if code.startswith("000") and len(code) == 6 and code.endswith("000"):
            return True
        return False

    # ------------------------------------------------------------------ #
    # K 线读取与指标
    # ------------------------------------------------------------------ #
    @staticmethod
    def _read_kline(filepath: str) -> Optional[pd.DataFrame]:
        for enc in ("utf-8-sig", "utf-8", "gbk", "gb2312"):
            try:
                df = pd.read_csv(filepath, encoding=enc)
            except Exception:
                continue
            if df is None or df.empty:
                continue
            if "Unnamed: 0" in df.columns and "date" not in df.columns:
                df = df.rename(columns={"Unnamed: 0": "date"})
            if "trade_date" in df.columns and "date" not in df.columns:
                df = df.rename(columns={"trade_date": "date"})
            if "date" not in df.columns or "close" not in df.columns:
                continue
            out = df.copy()
            out["date"] = (
                out["date"].astype(str).str.replace(r"[^\d]", "", regex=True).str[:8]
            )
            out = out[out["date"].str.len() == 8]
            out["close"] = pd.to_numeric(out["close"], errors="coerce")
            out = out.dropna(subset=["close"])
            if out.empty:
                continue
            return out.sort_values("date").reset_index(drop=True)
        return None

    @staticmethod
    def _calc_ma120(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        out["ma120"] = out["close"].rolling(window=120, min_periods=120).mean()
        return out

    @staticmethod
    def _is_above_ma120(df: pd.DataFrame) -> bool:
        if df is None or len(df) < 120:
            return False
        last = df.iloc[-1]
        ma = last.get("ma120")
        if pd.isna(ma):
            return False
        return float(last["close"]) > float(ma)

    @staticmethod
    def _period_growth(
        df: pd.DataFrame, start_key: str, end_idx: int = -1
    ) -> Optional[Dict[str, float]]:
        """从首个 date >= start_key 的交易日到 end_idx 收盘的涨幅。"""
        if df is None or df.empty:
            return None
        sub = df[df["date"] >= start_key]
        if sub.empty:
            return None
        start_price = float(sub.iloc[0]["close"])
        end_price = float(df.iloc[end_idx]["close"])
        if start_price <= 0:
            return None
        growth = round((end_price / start_price - 1.0) * 100.0, 2)
        return {
            "start_date": sub.iloc[0]["date"],
            "start_price": round(start_price, 4),
            "end_price": round(end_price, 4),
            "growth_pct": growth,
        }

    @staticmethod
    def _recent_trading_days_growth(
        df: pd.DataFrame, n_days: int = 5
    ) -> Optional[float]:
        """最近 n 个交易日的涨跌幅（含首尾共 n 根 K 线）。"""
        if df is None or len(df) < n_days:
            return None
        start_price = float(df.iloc[-n_days]["close"])
        end_price = float(df.iloc[-1]["close"])
        if start_price <= 0:
            return None
        return round((end_price / start_price - 1.0) * 100.0, 2)

    @staticmethod
    def _week_start_key(ref: datetime) -> str:
        """本周一（ISO 周）对应的 YYYYMMDD。"""
        monday = ref.date().fromordinal(ref.toordinal() - ref.weekday())
        return monday.strftime("%Y%m%d")

    @staticmethod
    def _month_start_key(ref: datetime) -> str:
        return ref.strftime("%Y%m") + "01"

    @staticmethod
    def _year_start_key(year: int) -> str:
        return f"{year}0101"

    # ------------------------------------------------------------------ #
    # 单股分析
    # ------------------------------------------------------------------ #
    def _analyze_one(self, filepath: str, ref_dt: datetime) -> Optional[dict]:
        parsed = self.parse_filename(filepath)
        if parsed is None:
            return None
        ts_code, market, _, _ = parsed
        if self._should_skip_symbol(ts_code, market):
            return None

        df = self._read_kline(filepath)
        if df is None or df.empty:
            return None

        df = self._calc_ma120(df)
        if not self._is_above_ma120(df):
            return None

        last_row = df.iloc[-1]
        year_info = self._period_growth(df, self._year_start_key(self.stat_year))
        month_info = self._period_growth(df, self._month_start_key(ref_dt))
        week_info = self._period_growth(df, self._week_start_key(ref_dt))
        recent_week = self._recent_trading_days_growth(df, n_days=5)

        if year_info is None:
            return None

        result = {
            "ts_code": ts_code,
            "market": market,
            "last_trade_date": last_row["date"],
            "current_price": round(float(last_row["close"]), 4),
            "ma120": round(float(last_row["ma120"]), 4),
            "year_growth_pct": year_info["growth_pct"],
            "year_start_date": year_info["start_date"],
            "year_start_price": year_info["start_price"],
            "month_growth_pct": month_info["growth_pct"] if month_info else None,
            "month_start_date": month_info["start_date"] if month_info else None,
            "week_growth_pct": week_info["growth_pct"] if week_info else None,
            "week_start_date": week_info["start_date"] if week_info else None,
            "recent_week_growth_pct": recent_week,
        }
        return result

    # ------------------------------------------------------------------ #
    # 主流程
    # ------------------------------------------------------------------ #
    def analyze_all(self, ref_dt: Optional[datetime] = None) -> pd.DataFrame:
        ref_dt = ref_dt or datetime.now()
        files = self.get_stock_files()
        if not files:
            return pd.DataFrame()

        logger.info("=" * 60)
        logger.info(
            "筛选 MA120 之上标的 | 年=%s | 参考日=%s | 市场=%s",
            self.stat_year,
            ref_dt.strftime("%Y-%m-%d"),
            ",".join(self.prefixes),
        )
        logger.info("=" * 60)

        rows: List[dict] = []
        total = len(files)
        for i, fp in enumerate(files, 1):
            row = self._analyze_one(fp, ref_dt)
            if row is not None:
                rows.append(row)
            if i % 200 == 0:
                logger.info("已处理 %d/%d，命中 %d 只", i, total, len(rows))

        if not rows:
            logger.info("未找到任何站上 MA120 且满足统计条件的标的")
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        df = df.sort_values(
            ["market", "year_growth_pct"], ascending=[True, False], na_position="last"
        )
        df = df.drop_duplicates(subset=["ts_code", "market"], keep="first").reset_index(
            drop=True
        )
        logger.info("扫描完成：共 %d 只站上 MA120", len(df))
        return df

    @staticmethod
    def _normalize_export(df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return df
        out = df.copy()
        for col in ("last_trade_date", "year_start_date", "month_start_date", "week_start_date"):
            if col in out.columns:
                s = out[col].astype(str).str.replace(r"[^\d]", "", regex=True).str[:8]
                out[col] = pd.to_numeric(s, errors="coerce").astype("Int64")
        numeric_cols = [
            "current_price",
            "ma120",
            "year_growth_pct",
            "year_start_price",
            "month_growth_pct",
            "week_growth_pct",
            "recent_week_growth_pct",
        ]
        for col in numeric_cols:
            if col in out.columns:
                out[col] = pd.to_numeric(out[col], errors="coerce")
        return out

    def save_results(
        self, df: pd.DataFrame, output_dir: Optional[str] = None, filename: Optional[str] = None
    ) -> str:
        if df is None or df.empty:
            raise ValueError("没有数据可保存")

        out_df = self._normalize_export(df)
        out_dir = output_dir or _DEFAULT_OUTPUT_DIR
        os.makedirs(out_dir, exist_ok=True)

        if filename is None:
            today = datetime.now().strftime("%Y%m%d")
            markets = "_".join(self.prefixes)
            filename = f"ma120_above_returns_{self.stat_year}_{markets}_{today}.csv"

        out_path = os.path.join(out_dir, filename)
        out_df.to_csv(out_path, index=False, encoding="utf-8-sig")
        logger.info("结果已保存至: %s（共 %d 条）", out_path, len(out_df))
        return out_path


def _parse_market_arg(market: str) -> List[str]:
    raw_parts = [p.strip().lower() for p in market.split(",") if p.strip()]
    prefixes: List[str] = []
    for p in raw_parts:
        if p in ("cn", "a", "a股"):
            prefixes.extend(["sh", "sz"])
        elif p == "all":
            prefixes.extend(list(_DEFAULT_PREFIXES))
        elif p in _PREFIX_TO_EXCHANGE:
            prefixes.append(p)
        elif p == "港股":
            prefixes.append("hk")
        elif p == "美股":
            prefixes.append("us")
        else:
            raise ValueError("不支持的市场标识: %r" % p)
    seen: set = set()
    return [x for x in prefixes if not (x in seen or seen.add(x))]


def main(
    market: str = "all",
    stat_year: int = 2026,
    output_dir: Optional[str] = None,
    output_file: Optional[str] = None,
) -> pd.DataFrame:
    _setup_logging()
    prefixes = _parse_market_arg(market)
    analyzer = Analyze120MAAboveReturns(prefixes=prefixes, stat_year=stat_year)
    result_df = analyzer.analyze_all()
    if not result_df.empty:
        analyzer.save_results(result_df, output_dir=output_dir, filename=output_file)
    return result_df


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="筛选 MA120 之上标的，统计 2026 年/本月/本周/近一周涨幅（A股+港股+美股）"
    )
    ap.add_argument(
        "market",
        nargs="?",
        default="all",
        help="市场：cn=A股, hk=港股, us=美股, all=全部（默认 all）",
    )
    ap.add_argument(
        "--year",
        type=int,
        default=2026,
        dest="stat_year",
        help="年涨幅统计起始年份（默认 2026）",
    )
    ap.add_argument(
        "--output-dir",
        default=_DEFAULT_OUTPUT_DIR,
        help="输出目录（默认 cy_quant/output）",
    )
    ap.add_argument(
        "--output-file",
        default=None,
        help="输出文件名（默认自动生成）",
    )
    args = ap.parse_args()

    start = time.time()
    df = main(
        market=args.market,
        stat_year=args.stat_year,
        output_dir=args.output_dir,
        output_file=args.output_file,
    )
    logger.info("处理完成，耗时 %.2f 秒", time.time() - start)
    if not df.empty:
        preview_cols = [
            "ts_code",
            "market",
            "current_price",
            "ma120",
            "year_growth_pct",
            "month_growth_pct",
            "week_growth_pct",
            "recent_week_growth_pct",
        ]
        cols = [c for c in preview_cols if c in df.columns]
        logger.info("前 10 条预览:\n%s", df[cols].head(10).to_string(index=False))
