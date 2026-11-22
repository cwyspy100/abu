#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A-share trend backtest with MA, fixed-stop and trailing-stop exits.

Entry: close crosses from at/below MA to above MA; buy next trading day open.
Exit signals are confirmed at the close and executed next trading day open:
  - close falls below the same MA;
  - close reaches the fixed loss from entry (5% for MA60, 10% for MA120);
  - close reaches the trailing loss from the highest intraday high since entry
    (10% for MA60, 20% for MA120).

The script deliberately excludes an open trade at the end from the primary
win-rate denominator and reports it separately.
"""

from __future__ import annotations

import argparse
import glob
import os
from datetime import datetime
from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd


def load_kline(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    dcol = "date" if "date" in df.columns else ("Unnamed: 0" if "Unnamed: 0" in df.columns else None)
    if dcol is None or "close" not in df.columns:
        return pd.DataFrame()
    raw_dates = df[dcol].astype(str).str.strip()
    dt_yyyymmdd = pd.to_datetime(raw_dates.where(raw_dates.str.fullmatch(r"\d{8}")), format="%Y%m%d", errors="coerce")
    dt_generic = pd.to_datetime(raw_dates.where(~raw_dates.str.fullmatch(r"\d{8}")), errors="coerce")
    out = pd.DataFrame({"dt": dt_yyyymmdd.fillna(dt_generic)})
    for col in ("open", "high", "close"):
        out[col] = pd.to_numeric(df[col], errors="coerce") if col in df.columns else np.nan
    out["open"] = out["open"].fillna(out["close"])
    out["high"] = out["high"].fillna(out["close"])
    out = out.dropna(subset=["dt", "close", "open", "high"])
    out = out[out["close"] > 0].sort_values("dt").drop_duplicates("dt").reset_index(drop=True)
    out["ma60"] = out["close"].rolling(60, min_periods=60).mean()
    out["ma120"] = out["close"].rolling(120, min_periods=120).mean()
    return out


def simulate(symbol: str, market: str, k: pd.DataFrame, window: int, fixed_stop: float, trail_stop: float) -> List[Dict[str, object]]:
    ma_col = f"ma{window}"
    if len(k) < window + 2:
        return []
    dates = k["dt"].to_numpy()
    opens = k["open"].to_numpy(dtype=float)
    highs = k["high"].to_numpy(dtype=float)
    closes = k["close"].to_numpy(dtype=float)
    mas = k[ma_col].to_numpy(dtype=float)
    trades: List[Dict[str, object]] = []
    i = window
    while i < len(k) - 1:
        if not (np.isfinite(mas[i]) and np.isfinite(mas[i - 1])):
            i += 1
            continue
        if not (closes[i - 1] <= mas[i - 1] and closes[i] > mas[i]):
            i += 1
            continue

        buy_i = i + 1
        buy_price = opens[buy_i]
        if buy_price <= 0:
            i += 1
            continue
        peak_high = buy_price
        exit_i: Optional[int] = None
        reasons: List[str] = []
        for j in range(buy_i, len(k) - 1):
            peak_high = max(peak_high, highs[j])
            fixed_line = buy_price * (1.0 - fixed_stop)
            trail_line = peak_high * (1.0 - trail_stop)
            if closes[j] < mas[j]:
                reasons.append("below_ma")
            if closes[j] <= fixed_line:
                reasons.append("fixed_stop")
            if closes[j] <= trail_line:
                reasons.append("trailing_stop")
            if reasons:
                exit_i = j + 1
                break
        if exit_i is None:
            trades.append({
                "symbol": symbol, "market": market, "window": window,
                "entry_date": dates[buy_i], "entry_price": buy_price,
                "exit_date": pd.NaT, "exit_price": np.nan, "exit_reason": "open_end",
                "ret": np.nan, "holding_days": int(len(k) - 1 - buy_i),
            })
            break

        exit_price = opens[exit_i]
        trades.append({
            "symbol": symbol, "market": market, "window": window,
            "entry_date": dates[buy_i], "entry_price": buy_price,
            "exit_date": dates[exit_i], "exit_price": exit_price,
            "exit_reason": "+".join(reasons), "ret": exit_price / buy_price - 1.0,
            "holding_days": int(exit_i - buy_i),
        })
        i = exit_i
    return trades


def summary(trades: pd.DataFrame) -> pd.DataFrame:
    rows: List[Dict[str, object]] = []
    for market, window in sorted(trades[["market", "window"]].drop_duplicates().itertuples(index=False, name=None)):
        sub = trades[(trades["market"] == market) & (trades["window"] == window)]
        closed = sub[sub["exit_reason"] != "open_end"].copy()
        rows.append({
            "market": market, "window": int(window), "symbols": int(sub["symbol"].nunique()),
            "all_trades": int(len(sub)), "closed_trades": int(len(closed)), "open_end": int((sub["exit_reason"] == "open_end").sum()),
            "win_rate": float((closed["ret"] > 0).mean()) if len(closed) else np.nan,
            "avg_ret": float(closed["ret"].mean()) if len(closed) else np.nan,
            "median_ret": float(closed["ret"].median()) if len(closed) else np.nan,
            "profit_factor": float(closed.loc[closed["ret"] > 0, "ret"].sum() / abs(closed.loc[closed["ret"] < 0, "ret"].sum())) if (closed["ret"] < 0).any() else np.inf,
            "below_ma_rate": float(closed["exit_reason"].str.contains("below_ma").mean()) if len(closed) else np.nan,
            "fixed_stop_rate": float(closed["exit_reason"].str.contains("fixed_stop").mean()) if len(closed) else np.nan,
            "trailing_stop_rate": float(closed["exit_reason"].str.contains("trailing_stop").mean()) if len(closed) else np.nan,
            "median_holding_days": float(closed["holding_days"].median()) if len(closed) else np.nan,
        })
    return pd.DataFrame(rows)


def market_from_name(name: str) -> Optional[str]:
    prefix = name[:2].lower()
    return {"sh": "A", "sz": "A"}.get(prefix)


def run(csv_dir: str, output_dir: str) -> str:
    rows: List[Dict[str, object]] = []
    paths = sorted(glob.glob(os.path.join(csv_dir, "*")))
    for path in paths:
        if not os.path.isfile(path):
            continue
        name = os.path.basename(path)
        market = market_from_name(name)
        if market is None:
            continue
        symbol = name.split("_", 1)[0]
        k = load_kline(path)
        for window, fixed_stop, trail_stop in ((60, 0.05, 0.10), (120, 0.10, 0.20)):
            rows.extend(simulate(symbol, market, k, window, fixed_stop, trail_stop))
    trades = pd.DataFrame(rows)
    os.makedirs(output_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(output_dir, f"ma_trend_exit_rule_a_{stamp}")
    os.makedirs(out_dir, exist_ok=True)
    if not trades.empty:
        trades.to_csv(os.path.join(out_dir, "trades.csv"), index=False)
        summary(trades).to_csv(os.path.join(out_dir, "summary.csv"), index=False)
        trades[trades["exit_reason"] != "open_end"].groupby(["window", "exit_reason"], as_index=False).size().to_csv(os.path.join(out_dir, "exit_reason_counts.csv"), index=False)
    else:
        pd.DataFrame().to_csv(os.path.join(out_dir, "trades.csv"), index=False)
        pd.DataFrame().to_csv(os.path.join(out_dir, "summary.csv"), index=False)
    return out_dir


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv-dir", default="/Users/water/abu/csv_his")
    parser.add_argument("--output-dir", default="cy_quant/output")
    args = parser.parse_args()
    print(run(args.csv_dir, args.output_dir))
