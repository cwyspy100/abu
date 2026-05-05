"""
导入「4-25港股.xlsx」类表到 MySQL stock_hk_screen（asof_date = 参考日最近周五）。

用法（项目根目录）:
  python3 cy_ai/stock/import_hk_xlsx.py
  python3 cy_ai/stock/import_hk_xlsx.py --file cy_ai/stock/4-25港股.xlsx --init-tables
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd

from cy_ai.db import Database, init_tables
from cy_ai.stock.xlsx_screen_common import (
    asof_nearest_friday,
    load_excel_sheet,
    to_float,
    to_int,
    to_str,
    upsert_screen_rows,
)

logger = logging.getLogger(__name__)

TABLE = "stock_hk_screen"

INSERT_COLS = (
    "asof_date",
    "ts_code",
    "name",
    "screen_rank",
    "pct_chg",
    "last_price",
    "change_amt",
    "volume_total",
    "amount",
    "volume_ratio",
    "turnover_rate",
    "total_mv",
    "float_mv",
    "net_profit_raw",
    "pe_ttm",
    "pb",
    "hk_connect_shares",
    "pct_h_share",
    "industry",
    "open_price",
    "high",
    "low",
    "speed_1m",
    "speed_5m",
    "pre_close",
    "source_file",
)


def normalize_hk_ts_code(cell: Any) -> Optional[str]:
    """499 / 00499.HK -> 00499.HK（5 位 + .HK）"""
    if cell is None or (isinstance(cell, float) and pd.isna(cell)):
        return None
    s = str(cell).strip().upper()
    if not s or s == "NAN":
        return None
    if s.endswith(".HK"):
        left = s[:-3]
    else:
        left = s
    digits = "".join(c for c in left if c.isdigit())
    if not digits:
        return None
    if len(digits) > 5:
        digits = digits[-5:]
    return f"{digits.zfill(5)}.HK"


def load_hk_excel(path: Path) -> pd.DataFrame:
    df = load_excel_sheet(path, ["港股"])
    if "代码" not in df.columns:
        raise ValueError(f"缺少「代码」列: {list(df.columns)}")
    return df


def dataframe_to_rows(df: pd.DataFrame, asof: date, source_file: str) -> list[tuple]:
    rows: list[tuple] = []
    for _, r in df.iterrows():
        code = normalize_hk_ts_code(r.get("代码"))
        if not code:
            continue
        row = (
            asof,
            code,
            to_str(r.get("名称")),
            to_str(r.get(".")),
            to_float(r.get("涨幅")),
            to_float(r.get("现价")),
            to_float(r.get("涨跌")),
            to_int(r.get("总量")),
            to_float(r.get("总金额")),
            to_float(r.get("量比")),
            to_float(r.get("换手")),
            to_float(r.get("总市值")),
            to_float(r.get("流通市值")),
            to_str(r.get("净利润")),
            to_float(r.get("TTM市盈率")),
            to_float(r.get("市净率")),
            to_int(r.get("港股通持股量")),
            to_float(r.get("占H股%")),
            to_str(r.get("所属行业")),
            to_float(r.get("开盘")),
            to_float(r.get("最高")),
            to_float(r.get("最低")),
            to_float(r.get("1分钟涨速")),
            to_float(r.get("5分钟涨速")),
            to_float(r.get("昨收")),
            source_file,
        )
        rows.append(row)
    return rows


def import_hk_xlsx(
    db: Database,
    xlsx_path: Path,
    ref_date: Optional[date] = None,
    batch_size: int = 300,
) -> tuple[date, int]:
    asof = asof_nearest_friday(ref_date)
    df = load_hk_excel(xlsx_path)
    source = str(xlsx_path.resolve())
    rows = dataframe_to_rows(df, asof, source)
    n = upsert_screen_rows(db, TABLE, INSERT_COLS, rows, batch_size=batch_size)
    logger.info("asof_date=%s 导入 %s 行 -> %s", asof, n, TABLE)
    return asof, n


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    default_file = Path(__file__).resolve().parent / "4-25港股.xlsx"
    p = argparse.ArgumentParser(description="导入港股 xlsx 到 MySQL")
    p.add_argument("--file", type=Path, default=default_file)
    p.add_argument("--ref-date", type=str, default="", help="参考日 YYYY-MM-DD")
    p.add_argument("--init-tables", action="store_true")
    args = p.parse_args()

    ref: Optional[date] = None
    if args.ref_date:
        ref = datetime.strptime(args.ref_date.strip(), "%Y-%m-%d").date()

    db = Database()
    try:
        if args.init_tables:
            init_tables(db)
        import_hk_xlsx(db, args.file.expanduser().resolve(), ref_date=ref)
    finally:
        db.close()


if __name__ == "__main__":
    main()
