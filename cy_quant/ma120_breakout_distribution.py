#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Distribution after price breaks above MA120.

For each symbol, merge all matching csv files under a directory, detect close
crossing above MA120, then measure the continuous period above MA120 and return
from breakout close to the last close before falling below MA120.
"""

from __future__ import annotations

import argparse
import glob
import os
from datetime import datetime
from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd


A_PREFIXES = ("sh60", "sh68", "sz00", "sz30", "sz001", "bj")


def symbol_from_path(path: str) -> str:
    return os.path.basename(path).split("_", 1)[0]


def market_of_symbol(symbol: str) -> Optional[str]:
    s = symbol.lower()
    if s.startswith("hk"):
        return "hk"
    if s.startswith("us") and not s.startswith("us."):
        return "us"
    if s.startswith(A_PREFIXES):
        return "a"
    return None


def scan_files(csv_dir: str, market: str) -> Dict[str, List[str]]:
    files = [p for p in glob.glob(os.path.join(csv_dir, "**", "*"), recursive=True) if os.path.isfile(p)]
    grouped: Dict[str, List[str]] = {}
    for fp in files:
        sym = symbol_from_path(fp)
        if market_of_symbol(sym) != market:
            continue
        grouped.setdefault(sym, []).append(fp)
    return grouped


def parse_date(raw: pd.Series) -> pd.Series:
    s = raw.astype(str)
    if s.str.fullmatch(r"\d{8}").mean() > 0.8:
        return pd.to_datetime(s, format="%Y%m%d", errors="coerce")
    return pd.to_datetime(s, errors="coerce")


def load_symbol(paths: Iterable[str]) -> pd.DataFrame:
    frames: List[pd.DataFrame] = []
    for fp in paths:
        try:
            df = pd.read_csv(fp)
        except Exception:
            continue
        if "close" not in df.columns:
            continue
        dcol = "date" if "date" in df.columns else ("Unnamed: 0" if "Unnamed: 0" in df.columns else None)
        if dcol is None:
            continue
        tmp = df.copy()
        tmp["dt"] = parse_date(tmp[dcol])
        tmp["close"] = pd.to_numeric(tmp["close"], errors="coerce")
        keep_cols = ["dt", "close"]
        for c in ["open", "high", "low", "volume"]:
            if c in tmp.columns:
                tmp[c] = pd.to_numeric(tmp[c], errors="coerce")
                keep_cols.append(c)
        frames.append(tmp[keep_cols])
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out = out.dropna(subset=["dt", "close"]).sort_values("dt")
    out = out.drop_duplicates(subset=["dt"], keep="last").reset_index(drop=True)
    out["ma120"] = out["close"].rolling(120, min_periods=120).mean()
    return out


def breakout_segments(symbol: str, k: pd.DataFrame) -> List[Dict[str, object]]:
    if len(k) < 121:
        return []
    above = (k["close"] > k["ma120"]).fillna(False).astype(bool)
    prev_above = above.shift(1, fill_value=False).astype(bool)
    cross = above & (~prev_above)
    rows: List[Dict[str, object]] = []
    idxs = np.where(cross.values)[0]
    for i in idxs:
        if i < 119:
            continue
        j = i
        while j < len(k) and bool(above.iloc[j]):
            j += 1
        end_i = j - 1
        is_open = j >= len(k)
        entry = float(k.at[i, "close"])
        exit_close = float(k.at[end_i, "close"])
        if entry <= 0:
            continue
        seg = k.iloc[i : end_i + 1]
        rows.append(
            {
                "symbol": symbol,
                "break_date": k.at[i, "dt"],
                "end_date": k.at[end_i, "dt"],
                "is_open": bool(is_open),
                "above_ma120_days": int(end_i - i + 1),
                "entry_close": entry,
                "end_close": exit_close,
                "ret": exit_close / entry - 1.0,
                "max_ret_in_segment": float(seg["close"].max() / entry - 1.0),
                "max_drawdown_from_entry": float((seg["close"] / entry - 1.0).min()),
            }
        )
    return rows


def add_bins(events: pd.DataFrame) -> pd.DataFrame:
    out = events.copy()
    day_bins = [0, 5, 10, 20, 40, 60, 120, 240, 10_000]
    day_labels = ["1-5", "6-10", "11-20", "21-40", "41-60", "61-120", "121-240", "240+"]
    ret_bins = [-10, -0.30, -0.20, -0.10, 0, 0.10, 0.20, 0.30, 0.50, 10]
    ret_labels = ["<-30%", "-30~-20%", "-20~-10%", "-10~0%", "0~10%", "10~20%", "20~30%", "30~50%", ">50%"]
    out["day_bin"] = pd.cut(out["above_ma120_days"], bins=day_bins, labels=day_labels, right=True)
    out["ret_bin"] = pd.cut(out["ret"], bins=ret_bins, labels=ret_labels, right=False)
    return out


def dist_table(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    total = len(df)
    g = (
        df.groupby(group_col, observed=False)
        .agg(
            events=("symbol", "count"),
            symbols=("symbol", "nunique"),
            avg_days=("above_ma120_days", "mean"),
            avg_ret=("ret", "mean"),
            median_ret=("ret", "median"),
            win_rate=("ret", lambda s: float((s > 0).mean()) if len(s) else np.nan),
        )
        .reset_index()
    )
    g["event_ratio"] = g["events"] / total if total else np.nan
    return g


def run(csv_dir: str, market: str, output_dir: str) -> str:
    grouped = scan_files(csv_dir, market)
    rows: List[Dict[str, object]] = []
    symbol_count = 0
    for sym, paths in sorted(grouped.items()):
        k = load_symbol(paths)
        if k.empty:
            continue
        symbol_count += 1
        rows.extend(breakout_segments(sym, k))
    events = add_bins(pd.DataFrame(rows)) if rows else pd.DataFrame()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(output_dir, f"ma120_breakout_distribution_{market}_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    events.to_csv(os.path.join(out_dir, "breakout_events.csv"), index=False, encoding="utf-8-sig")
    day_summary = dist_table(events, "day_bin") if not events.empty else pd.DataFrame()
    ret_summary = dist_table(events, "ret_bin") if not events.empty else pd.DataFrame()
    matrix = (
        pd.crosstab(events["day_bin"], events["ret_bin"], normalize="index")
        if not events.empty
        else pd.DataFrame()
    )
    day_summary.to_csv(os.path.join(out_dir, "day_distribution.csv"), index=False, encoding="utf-8-sig")
    ret_summary.to_csv(os.path.join(out_dir, "return_distribution.csv"), index=False, encoding="utf-8-sig")
    matrix.to_csv(os.path.join(out_dir, "day_return_ratio_matrix.csv"), encoding="utf-8-sig")

    overview = pd.DataFrame(
        [
            {
                "market": market,
                "symbols_loaded": symbol_count,
                "events": int(len(events)),
                "open_events": int(events["is_open"].sum()) if not events.empty else 0,
                "closed_events": int((~events["is_open"]).sum()) if not events.empty else 0,
                "avg_days": float(events["above_ma120_days"].mean()) if not events.empty else np.nan,
                "median_days": float(events["above_ma120_days"].median()) if not events.empty else np.nan,
                "avg_ret": float(events["ret"].mean()) if not events.empty else np.nan,
                "median_ret": float(events["ret"].median()) if not events.empty else np.nan,
                "win_rate": float((events["ret"] > 0).mean()) if not events.empty else np.nan,
                "tail_gt20": float((events["ret"] >= 0.20).mean()) if not events.empty else np.nan,
                "loss_lt10": float((events["ret"] <= -0.10).mean()) if not events.empty else np.nan,
            }
        ]
    )
    overview.to_csv(os.path.join(out_dir, "overview.csv"), index=False, encoding="utf-8-sig")
    print(out_dir)
    print(overview.to_string(index=False))
    print("\nDay distribution:")
    print(day_summary.to_string(index=False))
    print("\nReturn distribution:")
    print(ret_summary.to_string(index=False))
    return out_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="MA120 breakout distribution by market.")
    parser.add_argument("--csv-dir", default="/Users/water/abu/data/csv")
    parser.add_argument("--market", choices=["a", "hk", "us"], default="a")
    parser.add_argument("--output-dir", default="/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output")
    args = parser.parse_args()
    run(args.csv_dir, args.market, args.output_dir)


if __name__ == "__main__":
    main()
