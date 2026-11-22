"""Load local abupy K-line CSV files for the MA120 MVP."""

from __future__ import annotations

import glob
import os
from dataclasses import dataclass
from typing import Iterable, List, Optional

import pandas as pd


@dataclass(frozen=True)
class KlineFile:
    ts_code: str
    path: str


def filename_to_ts_code(path: str) -> Optional[str]:
    """Convert abupy file names such as sh600000_... to 600000.SH."""
    name = os.path.basename(path)
    if name.endswith(".csv"):
        name = name[:-4]
    code_part = name.split("_", 1)[0]
    if len(code_part) < 3:
        return None
    prefix = code_part[:2].lower()
    symbol = code_part[2:]
    exchange = {"sh": "SH", "sz": "SZ"}.get(prefix)
    if not exchange or not symbol:
        return None
    if not is_a_share_symbol(symbol, exchange):
        return None
    return f"{symbol}.{exchange}"


def is_a_share_symbol(symbol: str, exchange: str) -> bool:
    """Filter stock symbols and skip broad indices such as sh000001."""
    code = str(symbol).zfill(6)
    exchange = exchange.upper()
    if exchange == "SH":
        return code.startswith(("600", "601", "603", "605", "688", "689", "900"))
    if exchange == "SZ":
        return code.startswith(("000", "001", "002", "003", "300", "301", "200"))
    return False


def normalize_ts_code(value: object) -> str:
    """Normalize common A-share code forms to 000001.SZ / 600000.SH."""
    raw = str(value).strip()
    if not raw:
        return ""
    upper = raw.upper()
    if "." in upper:
        symbol, exchange = upper.split(".", 1)
        return f"{symbol.zfill(6)}.{exchange}"
    digits = "".join(ch for ch in upper if ch.isdigit())
    if len(digits) <= 6:
        symbol = digits.zfill(6)
        exchange = "SH" if symbol.startswith(("6", "9")) else "SZ"
        return f"{symbol}.{exchange}"
    return upper


def ts_code_to_prefix(ts_code: str) -> str:
    """Convert 600000.SH to sh600000 for file lookup."""
    norm = normalize_ts_code(ts_code)
    if "." not in norm:
        return norm.lower()
    symbol, exchange = norm.split(".", 1)
    prefix = {"SH": "sh", "SZ": "sz"}.get(exchange.upper(), exchange.lower())
    return f"{prefix}{symbol}"


class KlineLoader:
    """Find and read local K-line CSV files."""

    def __init__(self, data_roots: Optional[Iterable[str]] = None):
        roots = data_roots or [
            "~/abu/data/csv/astock",
            "~/abu/data/csv",
        ]
        self.data_roots = [os.path.expanduser(root) for root in roots]

    def iter_a_share_files(self, prefixes: Iterable[str] = ("sh", "sz")) -> List[KlineFile]:
        files = {}
        for root in self.data_roots:
            if not os.path.isdir(root):
                continue
            for prefix in prefixes:
                for path in glob.glob(os.path.join(root, f"{prefix}*")):
                    ts_code = filename_to_ts_code(path)
                    if ts_code:
                        files[ts_code] = path
        return [KlineFile(ts_code=code, path=path) for code, path in sorted(files.items())]

    def find_file(self, ts_code: str) -> Optional[str]:
        prefix = ts_code_to_prefix(ts_code)
        matches = []
        for root in self.data_roots:
            if not os.path.isdir(root):
                continue
            matches.extend(glob.glob(os.path.join(root, f"{prefix}_*")))
            matches.extend(glob.glob(os.path.join(root, f"{prefix}_*.csv")))
        if not matches:
            return None
        return sorted(set(matches), key=os.path.getmtime)[-1]

    def load(self, path_or_ts_code: str) -> Optional[pd.DataFrame]:
        path = path_or_ts_code
        if not os.path.exists(path):
            found = self.find_file(path_or_ts_code)
            if not found:
                return None
            path = found

        for encoding in ("utf-8-sig", "utf-8", "gbk"):
            try:
                df = pd.read_csv(path, encoding=encoding)
                break
            except Exception:
                df = None
        if df is None or df.empty:
            return None

        if "trade_date" not in df.columns and "date" in df.columns:
            df = df.rename(columns={"date": "trade_date"})
        if "trade_date" not in df.columns or "close" not in df.columns:
            return None

        df = df.copy()
        df["trade_date"] = df["trade_date"].astype(str).str.replace(r"[\s\-:]", "", regex=True).str.slice(0, 8)
        for col in ("open", "close", "high", "low", "volume"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["trade_date", "close"]).sort_values("trade_date").reset_index(drop=True)
        return df


def read_pool_codes(pool_csv: str) -> List[str]:
    """Read ts_code/symbol/code from a simple pool CSV."""
    df = pd.read_csv(pool_csv, dtype=str, encoding="utf-8-sig")
    for col in ("ts_code", "symbol", "code"):
        if col in df.columns:
            return [normalize_ts_code(v) for v in df[col].dropna().tolist() if str(v).strip()]
    raise ValueError(f"Pool CSV must contain one of: ts_code, symbol, code: {pool_csv}")
