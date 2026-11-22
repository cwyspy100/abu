"""A-share metadata helpers for filtering and display."""

from __future__ import annotations

import os
from typing import Optional

import pandas as pd


DEFAULT_BASIC_CSV = os.path.join("todolist", "stock_A_basic_list.csv")


def _normalize_ts_code(value: object) -> str:
    raw = str(value).strip().upper()
    if not raw:
        return ""
    if "." in raw:
        symbol, exchange = raw.split(".", 1)
        return f"{symbol.zfill(6)}.{exchange}"
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return raw
    symbol = digits.zfill(6)
    exchange = "SH" if symbol.startswith(("6", "9")) else "SZ"
    return f"{symbol}.{exchange}"


class StockMeta:
    """Load stock names and ST status from a local A-share basic CSV."""

    def __init__(self, basic_csv: Optional[str] = None):
        self.basic_csv = basic_csv or DEFAULT_BASIC_CSV
        self._df = self._load()
        self._by_code = self._df.set_index("ts_code").to_dict("index") if not self._df.empty else {}

    def _load(self) -> pd.DataFrame:
        if not self.basic_csv or not os.path.exists(self.basic_csv):
            return pd.DataFrame(columns=["ts_code", "name", "industry"])
        df = pd.read_csv(self.basic_csv, dtype=str, encoding="utf-8-sig")
        if "ts_code" not in df.columns:
            return pd.DataFrame(columns=["ts_code", "name", "industry"])
        out = df.copy()
        out["ts_code"] = out["ts_code"].apply(_normalize_ts_code)
        for col in ("name", "industry"):
            if col not in out.columns:
                out[col] = ""
            out[col] = out[col].fillna("")
        return out[["ts_code", "name", "industry"]].drop_duplicates("ts_code")

    def get(self, ts_code: str) -> dict:
        return self._by_code.get(_normalize_ts_code(ts_code), {})

    def enrich(self, row: dict) -> dict:
        meta = self.get(str(row.get("ts_code", "")))
        if not meta:
            row.setdefault("name", "")
            row.setdefault("industry", "")
            row.setdefault("is_st", False)
            return row
        name = str(meta.get("name") or "")
        row["name"] = name
        row["industry"] = str(meta.get("industry") or "")
        row["is_st"] = is_st_name(name)
        return row

    def is_st(self, ts_code: str) -> bool:
        return bool(is_st_name(str(self.get(ts_code).get("name") or "")))


def is_st_name(name: str) -> bool:
    upper = str(name or "").upper().strip()
    return upper.startswith("ST") or upper.startswith("*ST") or "ST" in upper[:4]

