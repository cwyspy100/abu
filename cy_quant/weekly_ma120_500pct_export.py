#!/usr/bin/env python3
"""Export A-share first weekly MA120 breakout runs whose gain exceeds 500%."""

from __future__ import annotations

import argparse
from functools import partial
from multiprocessing import Pool
from pathlib import Path
from typing import Optional

import pandas as pd


MA_WEEKS = 120
LOOKBACK_TRADING_DAYS = 120
MIN_GAIN_PCT = 500.0
DEFAULT_STOCK_BASIC_CSV = "todolist/stock_A_basic_list.csv"


def _parse_dates(values: pd.Series) -> pd.Series:
    text = values.astype(str).str.strip()
    compact = pd.to_datetime(text.where(text.str.fullmatch(r"\d{8}")), format="%Y%m%d", errors="coerce")
    other = pd.to_datetime(text.where(~text.str.fullmatch(r"\d{8}")), errors="coerce")
    return compact.fillna(other)


def normalize_daily(daily: pd.DataFrame) -> pd.DataFrame:
    """Validate and normalize the price columns needed by the scanner."""
    date_col = "date" if "date" in daily.columns else "trade_date"
    required = {date_col, "high", "low", "close"}
    if not required.issubset(daily.columns):
        return pd.DataFrame(columns=["date", "high", "low", "close"])
    result = pd.DataFrame({
        "date": _parse_dates(daily[date_col]),
        "high": pd.to_numeric(daily["high"], errors="coerce"),
        "low": pd.to_numeric(daily["low"], errors="coerce"),
        "close": pd.to_numeric(daily["close"], errors="coerce"),
    }).dropna().sort_values("date").drop_duplicates("date")
    return result[(result.high > 0) & (result.low > 0) & (result.close > 0)].reset_index(drop=True)


def _weekly_close(daily: pd.DataFrame, drop_incomplete_final_week: bool = False) -> pd.DataFrame:
    weekly = daily.assign(week=daily["date"].dt.to_period("W-FRI")).groupby("week", sort=True).agg(
        week_end=("date", "last"), close=("close", "last")
    ).reset_index(drop=True)
    # Calendar-free data cannot distinguish a cutoff Tuesday from a holiday
    # Thursday. Keep the last available week by default; callers that know
    # their file is truncated mid-week can opt into excluding it.
    if drop_incomplete_final_week and not weekly.empty and weekly.iloc[-1]["week_end"].dayofweek < 4:
        weekly = weekly.iloc[:-1].reset_index(drop=True)
    weekly["ma120w"] = weekly["close"].rolling(MA_WEEKS, min_periods=MA_WEEKS).mean()
    return weekly


def find_first_cross_run(code: str, daily: pd.DataFrame, drop_incomplete_final_week: bool = False) -> Optional[dict]:
    """Return the first qualifying first-cross run, or None.

    A cross is evaluated at a completed weekly close. The run includes every
    complete week from that cross through the final weekly close strictly above
    MA120W. The price high/low measurements themselves use daily OHLC data.
    """
    prices = normalize_daily(daily)
    if prices.empty:
        return None
    weekly = _weekly_close(prices, drop_incomplete_final_week)
    if len(weekly) <= MA_WEEKS:
        return None

    crossed = (weekly["close"] > weekly["ma120w"]) & (
        weekly["close"].shift(1) <= weekly["ma120w"].shift(1)
    )
    cross_indices = weekly.index[crossed.fillna(False)].tolist()
    if not cross_indices:
        return None
    cross_idx = cross_indices[0]
    cross_date = weekly.at[cross_idx, "week_end"]
    pre_cross = prices[prices["date"] < cross_date].tail(LOOKBACK_TRADING_DAYS)
    if len(pre_cross) < LOOKBACK_TRADING_DAYS:
        return None
    low_row = pre_cross.loc[pre_cross["low"].idxmin()]

    run_end_idx = cross_idx
    while run_end_idx + 1 < len(weekly):
        next_idx = run_end_idx + 1
        if not (weekly.at[next_idx, "close"] > weekly.at[next_idx, "ma120w"]):
            break
        run_end_idx = next_idx
    run_end_date = weekly.at[run_end_idx, "week_end"]
    run_prices = prices[(prices["date"] >= cross_date) & (prices["date"] <= run_end_date)]
    high_row = run_prices.loc[run_prices["high"].idxmax()]
    gain_pct = (high_row["high"] / low_row["low"] - 1.0) * 100.0
    if gain_pct <= MIN_GAIN_PCT:
        return None

    return {
        "code": code,
        "cross_date": cross_date.date(),
        "lowest_price": float(low_row["low"]),
        "start_date": low_row["date"].date(),
        "highest_price": float(high_row["high"]),
        "end_date": high_row["date"].date(),
        "gain_pct": round(float(gain_pct), 2),
        "duration_days": int((high_row["date"] - low_row["date"]).days),
        "duration_weeks": round((high_row["date"] - low_row["date"]).days / 7.0, 2),
        "run_end_date": run_end_date.date(),
        "qualifies_over_500pct": True,
    }


def _load_names(stock_basic_csv: Optional[str]) -> dict[str, str]:
    if not stock_basic_csv:
        return {}
    path = Path(stock_basic_csv)
    if not path.is_file():
        raise FileNotFoundError(f"stock basic file not found: {path}")
    basic = pd.read_csv(path)
    if not {"ts_code", "name"}.issubset(basic.columns):
        raise ValueError("stock basic CSV must include ts_code and name columns")
    names: dict[str, str] = {}
    for row in basic[["ts_code", "name"]].dropna().itertuples(index=False):
        ts_code = str(row.ts_code)
        if ts_code.endswith(".SH"):
            names[f"sh{ts_code[:6]}"] = str(row.name)
        elif ts_code.endswith(".SZ"):
            names[f"sz{ts_code[:6]}"] = str(row.name)
    return names


def _scan_one_path(path_text: str, drop_incomplete_final_week: bool = False) -> Optional[dict]:
    path = Path(path_text)
    code = path.name.split("_", 1)[0]
    try:
        return find_first_cross_run(code, pd.read_csv(path), drop_incomplete_final_week)
    except (OSError, ValueError, pd.errors.EmptyDataError, pd.errors.ParserError, UnicodeDecodeError):
        return None


def scan_csv_dir(csv_dir: str, stock_basic_csv: Optional[str] = None, workers: int = 1, drop_incomplete_final_week: bool = False) -> pd.DataFrame:
    names = _load_names(stock_basic_csv)
    paths = [
        path for path in sorted(Path(csv_dir).iterdir())
        if path.is_file()
        and path.name.startswith(("sh", "sz"))
        and (not names or path.name.split("_", 1)[0] in names)
    ]
    scan_one = partial(_scan_one_path, drop_incomplete_final_week=drop_incomplete_final_week)
    if workers == 1:
        raw_records = map(scan_one, map(str, paths))
    else:
        with Pool(processes=workers) as pool:
            raw_records = list(pool.imap_unordered(scan_one, map(str, paths), chunksize=20))
    records = []
    for record in raw_records:
        if record is not None:
            record["stock_name"] = names.get(record["code"], "")
            records.append(record)
    columns = ["code", "stock_name", "cross_date", "lowest_price", "start_date", "highest_price", "end_date", "gain_pct", "duration_days", "duration_weeks", "run_end_date"]
    return pd.DataFrame(records, columns=columns).sort_values("gain_pct", ascending=False, ignore_index=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export first weekly MA120 breakout runs exceeding 500% gain")
    parser.add_argument("--csv-dir", default="/Users/water/abu/csv_his")
    parser.add_argument("--output", default="cy_quant/output/weekly_ma120_first_cross_over500pct.csv")
    parser.add_argument(
        "--stock-basic-csv",
        default=DEFAULT_STOCK_BASIC_CSV,
        help="CSV with ts_code,name for stock-name enrichment (default: todolist/stock_A_basic_list.csv)",
    )
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--drop-incomplete-final-week", action="store_true", help="exclude a final Mon–Thu week when the data cutoff is known to be incomplete")
    args = parser.parse_args()
    result = scan_csv_dir(args.csv_dir, args.stock_basic_csv, args.workers, args.drop_incomplete_final_week)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output, index=False, encoding="utf-8-sig")
    print(f"exported {len(result)} records to {output}")


if __name__ == "__main__":
    main()
