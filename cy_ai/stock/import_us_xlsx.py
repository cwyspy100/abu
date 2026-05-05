"""
导入「4-25美股数据.xlsx」类表到 MySQL stock_us_screen（asof_date = 参考日最近周五）。

用法（项目根目录）:
  python3 cy_ai/stock/import_us_xlsx.py
  python3 cy_ai/stock/import_us_xlsx.py --file cy_ai/stock/4-25美股数据.xlsx --init-tables
"""

from __future__ import annotations

import argparse
import logging
import re
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

TABLE = "stock_us_screen"

INSERT_COLS = (
    "asof_date",
    "ts_code",
    "name",
    "pct_chg",
    "last_price",
    "change_amt",
    "pre_market_price",
    "pre_market_pct_chg",
    "pre_market_change",
    "post_market_price",
    "post_market_pct_chg",
    "post_market_change",
    "turnover_rate",
    "amplitude",
    "volume_total",
    "amount_usd",
    "total_mv_usd",
    "eps",
    "pe_ttm",
    "pb",
    "net_profit_raw",
    "bps",
    "inst_hold_pct",
    "open_price",
    "pre_close",
    "high",
    "low",
    "high_52w",
    "low_52w",
    "industry",
    "source_file",
)


def normalize_us_ts_code(cell: Any) -> Optional[str]:
    """MXL -> MXL.US；已带 .US 则规范化大写。"""
    if cell is None or (isinstance(cell, float) and pd.isna(cell)):
        return None
    if isinstance(cell, (int, float)) and not isinstance(cell, bool):
        if isinstance(cell, float) and pd.isna(cell):
            return None
        if isinstance(cell, float) and float(cell).is_integer():
            s = str(int(cell))
        else:
            s = str(cell).strip().upper()
    else:
        s = str(cell).strip().upper()
    s = re.sub(r"\s+", "", s)
    if not s or s == "NAN":
        return None
    if s.endswith(".US"):
        base = s[:-3]
        if not base:
            return None
        return f"{base}.US"
    if not re.match(r"^[A-Z0-9][A-Z0-9.\-]{0,14}$", s):
        return None
    return f"{s}.US"


def load_us_excel(path: Path) -> pd.DataFrame:
    df = load_excel_sheet(path, ["Table", "美股", "Sheet1"])
    if "代码" not in df.columns:
        raise ValueError(f"缺少「代码」列: {list(df.columns)}")
    return df


def dataframe_to_rows(df: pd.DataFrame, asof: date, source_file: str) -> list[tuple]:
    rows: list[tuple] = []
    for _, r in df.iterrows():
        code = normalize_us_ts_code(r.get("代码"))
        if not code:
            continue
        row = (
            asof,
            code,
            to_str(r.get("名称")),
            to_float(r.get("涨幅")),
            to_float(r.get("现价")),
            to_float(r.get("涨跌")),
            to_float(r.get("盘前价")),
            to_float(r.get("盘前涨幅")),
            to_float(r.get("盘前涨跌")),
            to_float(r.get("盘后价")),
            to_float(r.get("盘后涨幅")),
            to_float(r.get("盘后涨跌")),
            to_float(r.get("换手")),
            to_float(r.get("振幅")),
            to_int(r.get("总量")),
            to_float(r.get("金额(＄)")),
            to_float(r.get("总市值(＄)")),
            to_float(r.get("每股收益")),
            to_float(r.get("TTM市盈率")),
            to_float(r.get("市净率")),
            to_str(r.get("净利润")),
            to_float(r.get("每股净资产")),
            to_float(r.get("机构持仓%")),
            to_float(r.get("开盘")),
            to_float(r.get("昨收")),
            to_float(r.get("最高")),
            to_float(r.get("最低")),
            to_float(r.get("52周最高")),
            to_float(r.get("52周最低")),
            to_str(r.get("所属行业")),
            source_file,
        )
        rows.append(row)
    return rows


def import_us_xlsx(
    db: Database,
    xlsx_path: Path,
    ref_date: Optional[date] = None,
    batch_size: int = 300,
) -> tuple[date, int]:
    asof = asof_nearest_friday(ref_date)
    df = load_us_excel(xlsx_path)
    source = str(xlsx_path.resolve())
    rows = dataframe_to_rows(df, asof, source)
    n = upsert_screen_rows(db, TABLE, INSERT_COLS, rows, batch_size=batch_size)
    logger.info("asof_date=%s 导入 %s 行 -> %s", asof, n, TABLE)
    return asof, n


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    default_file = Path(__file__).resolve().parent / "4-25美股数据.xlsx"
    p = argparse.ArgumentParser(description="导入美股 xlsx 到 MySQL")
    p.add_argument("--file", type=Path, default=default_file)
    p.add_argument("--ref-date", type=str, default="")
    p.add_argument("--init-tables", action="store_true")
    args = p.parse_args()

    ref: Optional[date] = None
    if args.ref_date:
        ref = datetime.strptime(args.ref_date.strip(), "%Y-%m-%d").date()

    db = Database()
    try:
        if args.init_tables:
            init_tables(db)
        import_us_xlsx(db, args.file.expanduser().resolve(), ref_date=ref)
    finally:
        db.close()


if __name__ == "__main__":
    main()
