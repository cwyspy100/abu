"""A股/港股/美股 Excel 快照导入共用：周五归属日、数值清洗、读表、批量 upsert。"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

import pandas as pd

if TYPE_CHECKING:
    from cy_ai.db import Database

def asof_nearest_friday(ref: Optional[date] = None) -> date:
    """相对 ref 最近的周五（含 ref 为周五则当天）。"""
    ref = ref or date.today()
    wd = ref.weekday()
    offset = (wd - 4) % 7
    return ref - timedelta(days=offset)


def is_blank_excel_token(x: Any) -> bool:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return True
    if isinstance(x, str):
        t = x.strip()
        return t == "" or t == "--" or t == "-"
    return False


def to_float(x: Any) -> Optional[float]:
    if is_blank_excel_token(x):
        return None
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        if isinstance(x, float) and pd.isna(x):
            return None
        return float(x)
    s = str(x).strip().replace(",", "")
    if s in ("", "--", "-"):
        return None
    s = re.sub(r"[↑↓%]", "", s)
    try:
        return float(s)
    except ValueError:
        return None


def to_int(x: Any) -> Optional[int]:
    f = to_float(x)
    if f is None:
        return None
    try:
        return int(round(f))
    except (ValueError, OverflowError):
        return None


def to_str(x: Any) -> Optional[str]:
    if is_blank_excel_token(x):
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


def parse_list_date(x: Any) -> Optional[date]:
    if is_blank_excel_token(x):
        return None
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        if isinstance(x, float) and pd.isna(x):
            return None
        d = int(x)
        if d > 1000000:
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


def load_excel_sheet(path: Path, sheet_candidates: list[str]) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(path)
    xl = pd.ExcelFile(path, engine="openpyxl")
    sheet = next((s for s in sheet_candidates if s in xl.sheet_names), xl.sheet_names[0])
    df = pd.read_excel(path, sheet_name=sheet, engine="openpyxl")
    df.columns = [str(c).strip() for c in df.columns]
    return df


def upsert_screen_rows(
    db: "Database",
    table: str,
    insert_cols: tuple[str, ...],
    rows: list[tuple],
    batch_size: int = 300,
) -> int:
    """INSERT ... ON DUPLICATE KEY UPDATE，表须有 uk_asof_ts (asof_date, ts_code)。"""
    if not rows:
        return 0
    upd = ", ".join(f"`{c}` = VALUES(`{c}`)" for c in insert_cols if c not in ("asof_date", "ts_code"))
    cols_sql = ", ".join(f"`{c}`" for c in insert_cols)
    ph = ", ".join(["%s"] * len(insert_cols))
    sql = f"""
        INSERT INTO `{table}` ({cols_sql})
        VALUES ({ph})
        ON DUPLICATE KEY UPDATE
        {upd},
        `updated_at` = CURRENT_TIMESTAMP
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
    return n
