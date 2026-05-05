"""
将「4-25A股.xlsx」类行情/筛选表导入 MySQL 表 stock_cn_a_screen。

依赖: pandas, openpyxl, pymysql（与 cy_ai 一致）
  python3 -m pip install pandas openpyxl pymysql

用法（在项目根目录）:
  python3 cy_ai/stock/import_cn_a_xlsx.py
  python3 cy_ai/stock/import_cn_a_xlsx.py --file cy_ai/stock/4-25A股.xlsx --init-tables

asof_date: 相对「参考日」最近的周五（含当天若为周五）。默认参考日为今天。
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

# 项目根加入 path，便于直接运行脚本
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd

from cy_ai.db import Database, init_tables

logger = logging.getLogger(__name__)

# Excel 表头(去空格后) -> 数据库列名（除 代码 单独处理为 ts_code）
_EXCEL_TO_DB: list[tuple[str, str]] = [
    (".", "screen_rank"),
    ("名称", "name"),
    ("涨幅", "pct_chg"),
    ("现价", "last_price"),
    ("涨跌", "change_amt"),
    ("买价", "bid_price"),
    ("卖价", "ask_price"),
    ("总手", "volume_hands"),
    ("总金额", "amount"),
    ("现手", "last_vol"),
    ("1分钟涨速", "speed_1m"),
    ("实体涨幅", "body_pct_chg"),
    ("现均差%", "vs_avg_pct"),
    ("换手", "turnover_rate"),
    ("委比%", "bid_ask_ratio_pct"),
    ("总市值", "total_mv"),
    ("流通市值", "float_mv"),
    ("流通比例", "float_ratio"),
    ("4分钟涨速", "speed_4m"),
    ("当日偏离值", "deviate_day"),
    ("异动偏离值", "deviate_abnormal"),
    ("10日内偏离值", "deviate_10d"),
    ("30日内偏离值", "deviate_30d"),
    ("10日异动次数", "abnormal_count_10d"),
    ("内盘", "inner_vol"),
    ("外盘", "outer_vol"),
    ("内外比", "inner_outer_ratio"),
    ("备注", "remark"),
    ("利空", "bad_news"),
    ("利好", "good_news"),
    ("主力净量", "main_net_ratio"),
    ("量比", "volume_ratio"),
    ("TTM市盈率", "pe_ttm"),
    ("净利润", "net_profit_raw"),
    ("市净率", "pb"),
    ("每股盈利", "eps"),
    ("细分行业", "sub_industry"),
    ("所属行业", "industry"),
    ("昨收", "pre_close"),
    ("开盘", "open_price"),
    ("开盘涨幅", "open_pct_chg"),
    ("竞价换手", "call_auction_turnover"),
    ("最高", "high"),
    ("最低", "low"),
    ("5日涨幅", "pct_chg_5d"),
    ("10日涨幅", "pct_chg_10d"),
    ("20日涨幅", "pct_chg_20d"),
    ("年初至今", "ytd_pct_chg"),
    ("振幅", "amplitude"),
    ("买量", "bid_vol"),
    ("卖量", "ask_vol"),
    ("笔数", "trade_count"),
    ("贡献度", "contribution"),
    ("机构动向", "inst_flow"),
    ("异动类型", "abnormal_type"),
    ("总股本", "total_shares"),
    ("流通股本", "float_shares"),
    ("利润总额", "total_profit_raw"),
    ("净利润增长率", "net_profit_yoy"),
    ("每股净资产", "bps"),
    ("金叉个数", "golden_cross_cnt"),
    ("散户数量", "retail_count_raw"),
]

_FLOAT_COLS = frozenset(
    {
        "screen_rank",
        "pct_chg",
        "last_price",
        "change_amt",
        "bid_price",
        "ask_price",
        "amount",
        "speed_1m",
        "body_pct_chg",
        "vs_avg_pct",
        "turnover_rate",
        "bid_ask_ratio_pct",
        "total_mv",
        "float_mv",
        "float_ratio",
        "speed_4m",
        "inner_outer_ratio",
        "main_net_ratio",
        "volume_ratio",
        "pe_ttm",
        "pb",
        "eps",
        "pre_close",
        "open_price",
        "open_pct_chg",
        "call_auction_turnover",
        "high",
        "low",
        "ytd_pct_chg",
        "amplitude",
    }
)
_INT_COLS = frozenset(
    {
        "volume_hands",
        "inner_vol",
        "outer_vol",
        "bid_vol",
        "ask_vol",
        "trade_count",
        "total_shares",
        "float_shares",
        "golden_cross_cnt",
    }
)
_STR_COLS = frozenset(
    {
        "last_vol",
        "deviate_day",
        "deviate_abnormal",
        "deviate_10d",
        "deviate_30d",
        "abnormal_count_10d",
        "remark",
        "bad_news",
        "good_news",
        "net_profit_raw",
        "sub_industry",
        "industry",
        "pct_chg_5d",
        "pct_chg_10d",
        "pct_chg_20d",
        "contribution",
        "inst_flow",
        "abnormal_type",
        "total_profit_raw",
        "net_profit_yoy",
        "retail_count_raw",
        "name",
    }
)


def asof_nearest_friday(ref: Optional[date] = None) -> date:
    """相对 ref 最近的周五（含 ref 为周五则当天）。"""
    ref = ref or date.today()
    wd = ref.weekday()  # Mon=0 ... Fri=4 Sat=5 Sun=6
    offset = (wd - 4) % 7
    return ref - timedelta(days=offset)


def normalize_ts_code(cell: Any) -> Optional[str]:
    """SH688808 -> 688808.SH；SZ300422 -> 300422.SZ；BJxxxxxx -> xxxxxx.BJ"""
    if cell is None or (isinstance(cell, float) and pd.isna(cell)):
        return None
    s = str(cell).strip().upper()
    if not s or s == "NAN":
        return None
    m = re.match(r"^(\d{6})\.(SH|SZ|BJ)$", s)
    if m:
        return f"{m.group(1)}.{m.group(2)}"
    if re.match(r"^SH\d{6}$", s):
        return f"{s[2:]}.SH"
    if re.match(r"^SZ\d{6}$", s):
        return f"{s[2:]}.SZ"
    if re.match(r"^BJ\d{6}$", s):
        return f"{s[2:]}.BJ"
    digits = "".join(c for c in s if c.isdigit())
    if len(digits) == 6:
        return f"{digits}.SH"
    return None


def _is_blank_excel_token(x: Any) -> bool:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return True
    if isinstance(x, str):
        t = x.strip()
        return t == "" or t == "--" or t == "-"
    return False


def _to_float(x: Any) -> Optional[float]:
    if _is_blank_excel_token(x):
        return None
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        try:
            if isinstance(x, float) and pd.isna(x):
                return None
        except Exception:
            pass
        return float(x)
    s = str(x).strip().replace(",", "")
    if s in ("", "--", "-"):
        return None
    s = re.sub(r"[↑↓%]", "", s)
    try:
        return float(s)
    except ValueError:
        return None


def _to_int(x: Any) -> Optional[int]:
    f = _to_float(x)
    if f is None:
        return None
    try:
        return int(round(f))
    except (ValueError, OverflowError):
        return None


def _to_str(x: Any) -> Optional[str]:
    if _is_blank_excel_token(x):
        return None
    if isinstance(x, str):
        t = x.strip()
        return t if t else None
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        if isinstance(x, float) and pd.isna(x):
            return None
        if float(x).is_integer():
            return str(int(x))
        return str(x)
    return str(x)


def _parse_list_date(x: Any) -> Optional[date]:
    if _is_blank_excel_token(x):
        return None
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        if isinstance(x, float) and pd.isna(x):
            return None
        d = int(x)
        if d > 30000000 or (d > 1000000 and d < 30000000):
            y, m, day = d // 10000, (d // 100) % 100, d % 100
            if 1 <= m <= 12 and 1 <= day <= 31:
                try:
                    return date(y, m, day)
                except ValueError:
                    return None
    s = str(x).strip().replace("-", "")
    if len(s) == 8 and s.isdigit():
        y, m, day = int(s[:4]), int(s[4:6]), int(s[6:8])
        try:
            return date(y, m, day)
        except ValueError:
            return None
    return None


def _coerce(db_col: str, value: Any) -> Any:
    if db_col == "list_date":
        return _parse_list_date(value)
    if db_col in _INT_COLS:
        return _to_int(value)
    if db_col in _FLOAT_COLS:
        return _to_float(value)
    if db_col in _STR_COLS:
        return _to_str(value)
    return _to_str(value)


def load_cn_a_excel(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(path)
    xl = pd.ExcelFile(path, engine="openpyxl")
    sheet = "A股" if "A股" in xl.sheet_names else xl.sheet_names[0]
    df = pd.read_excel(path, sheet_name=sheet, engine="openpyxl")
    df.columns = [str(c).strip() for c in df.columns]
    if "代码" not in df.columns:
        raise ValueError(f"缺少「代码」列，当前列: {list(df.columns)}")
    return df


def dataframe_to_rows(df: pd.DataFrame, asof: date, source_file: str) -> list[tuple]:
    rows: list[tuple] = []

    for _, r in df.iterrows():
        code = normalize_ts_code(r.get("代码"))
        if not code:
            continue

        data: dict[str, Any] = {"ts_code": code}
        for cn, db in _EXCEL_TO_DB:
            if cn not in df.columns:
                data[db] = None
            else:
                data[db] = _coerce(db, r.get(cn))

        data["list_date"] = _parse_list_date(r.get("上市日期"))

        # 列顺序与 INSERT 一致
        row_tuple = (
            asof,
            data["ts_code"],
            data.get("screen_rank"),
            data.get("name"),
            data.get("pct_chg"),
            data.get("last_price"),
            data.get("change_amt"),
            data.get("bid_price"),
            data.get("ask_price"),
            data.get("volume_hands"),
            data.get("amount"),
            data.get("last_vol"),
            data.get("speed_1m"),
            data.get("body_pct_chg"),
            data.get("vs_avg_pct"),
            data.get("turnover_rate"),
            data.get("bid_ask_ratio_pct"),
            data.get("total_mv"),
            data.get("float_mv"),
            data.get("float_ratio"),
            data.get("speed_4m"),
            data.get("deviate_day"),
            data.get("deviate_abnormal"),
            data.get("deviate_10d"),
            data.get("deviate_30d"),
            data.get("abnormal_count_10d"),
            data.get("inner_vol"),
            data.get("outer_vol"),
            data.get("inner_outer_ratio"),
            data.get("remark"),
            data.get("bad_news"),
            data.get("good_news"),
            data.get("main_net_ratio"),
            data.get("volume_ratio"),
            data.get("pe_ttm"),
            data.get("net_profit_raw"),
            data.get("pb"),
            data.get("eps"),
            data.get("sub_industry"),
            data.get("industry"),
            data.get("pre_close"),
            data.get("open_price"),
            data.get("open_pct_chg"),
            data.get("call_auction_turnover"),
            data.get("high"),
            data.get("low"),
            data.get("pct_chg_5d"),
            data.get("pct_chg_10d"),
            data.get("pct_chg_20d"),
            data.get("ytd_pct_chg"),
            data.get("amplitude"),
            data.get("bid_vol"),
            data.get("ask_vol"),
            data.get("trade_count"),
            data.get("contribution"),
            data.get("inst_flow"),
            data.get("abnormal_type"),
            data.get("total_shares"),
            data.get("float_shares"),
            data.get("total_profit_raw"),
            data.get("net_profit_yoy"),
            data.get("bps"),
            data.get("golden_cross_cnt"),
            data.get("retail_count_raw"),
            data.get("list_date"),
            source_file,
        )
        rows.append(row_tuple)
    return rows


INSERT_COLS = (
    "asof_date",
    "ts_code",
    "screen_rank",
    "name",
    "pct_chg",
    "last_price",
    "change_amt",
    "bid_price",
    "ask_price",
    "volume_hands",
    "amount",
    "last_vol",
    "speed_1m",
    "body_pct_chg",
    "vs_avg_pct",
    "turnover_rate",
    "bid_ask_ratio_pct",
    "total_mv",
    "float_mv",
    "float_ratio",
    "speed_4m",
    "deviate_day",
    "deviate_abnormal",
    "deviate_10d",
    "deviate_30d",
    "abnormal_count_10d",
    "inner_vol",
    "outer_vol",
    "inner_outer_ratio",
    "remark",
    "bad_news",
    "good_news",
    "main_net_ratio",
    "volume_ratio",
    "pe_ttm",
    "net_profit_raw",
    "pb",
    "eps",
    "sub_industry",
    "industry",
    "pre_close",
    "open_price",
    "open_pct_chg",
    "call_auction_turnover",
    "high",
    "low",
    "pct_chg_5d",
    "pct_chg_10d",
    "pct_chg_20d",
    "ytd_pct_chg",
    "amplitude",
    "bid_vol",
    "ask_vol",
    "trade_count",
    "contribution",
    "inst_flow",
    "abnormal_type",
    "total_shares",
    "float_shares",
    "total_profit_raw",
    "net_profit_yoy",
    "bps",
    "golden_cross_cnt",
    "retail_count_raw",
    "list_date",
    "source_file",
)

UPDATE_SET = ", ".join(f"{c} = VALUES({c})" for c in INSERT_COLS if c not in ("asof_date", "ts_code"))


def import_cn_a_xlsx(
    db: Database,
    xlsx_path: Path,
    ref_date: Optional[date] = None,
    batch_size: int = 300,
) -> tuple[date, int]:
    """
    导入单个 xlsx，返回 (asof_date, 写入行数)。
    """
    asof = asof_nearest_friday(ref_date)
    df = load_cn_a_excel(xlsx_path)
    source_file = str(xlsx_path.resolve())
    rows = dataframe_to_rows(df, asof, source_file)
    if not rows:
        logger.warning("没有有效行（代码均无法解析）")
        return asof, 0

    cols_sql = ", ".join(INSERT_COLS)
    placeholders = ", ".join(["%s"] * len(INSERT_COLS))
    sql = f"""
        INSERT INTO stock_cn_a_screen ({cols_sql})
        VALUES ({placeholders})
        ON DUPLICATE KEY UPDATE
        {UPDATE_SET},
        updated_at = CURRENT_TIMESTAMP
    """

    n = 0
    conn = db.connect()
    try:
        with conn.cursor() as cur:
            for i in range(0, len(rows), batch_size):
                chunk = rows[i : i + batch_size]
                cur.executemany(sql, chunk)
                n += len(chunk)
        db.commit()
    except Exception:
        db.rollback()
        raise

    logger.info("asof_date=%s 导入 %s 行 -> stock_cn_a_screen", asof, n)
    return asof, n


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    default_file = Path(__file__).resolve().parent / "4-25A股.xlsx"
    p = argparse.ArgumentParser(description="导入 A 股筛选 xlsx 到 MySQL")
    p.add_argument("--file", type=Path, default=default_file, help="xlsx 路径")
    p.add_argument("--ref-date", type=str, default="", help="参考日 YYYY-MM-DD，默认今天")
    p.add_argument("--init-tables", action="store_true", help="先执行 cy_ai 全量建表")
    args = p.parse_args()

    ref: Optional[date] = None
    if args.ref_date:
        ref = datetime.strptime(args.ref_date.strip(), "%Y-%m-%d").date()

    db = Database()
    try:
        if args.init_tables:
            init_tables(db)
        import_cn_a_xlsx(db, args.file.expanduser().resolve(), ref_date=ref)
    finally:
        db.close()


if __name__ == "__main__":
    main()
