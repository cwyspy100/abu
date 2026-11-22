#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Event-level MA120 hold10 stop/take-profit backtest.

Workflow:
- Input clean_hold10_events.csv from ma120_hold10_feature_study.py.
- Buy on the first trading day after the 10-day observation window.
- Only open trades when the benchmark close is above its MA200.
- Exit on fixed stop loss, fixed take profit, or mark-to-market at data end.
"""

from __future__ import annotations

import argparse
import glob
import os
from datetime import datetime
from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd


def symbol_from_path(path: str) -> str:
    return os.path.basename(path).split("_", 1)[0]


def parse_date(raw: pd.Series) -> pd.Series:
    s = raw.astype(str)
    if s.str.fullmatch(r"\d{8}").mean() > 0.8:
        return pd.to_datetime(s, format="%Y%m%d", errors="coerce")
    return pd.to_datetime(s, errors="coerce")


def scan_symbol_files(csv_dir: str, symbols: Iterable[str]) -> Dict[str, List[str]]:
    need = set(symbols)
    grouped: Dict[str, List[str]] = {s: [] for s in need}
    for fp in glob.glob(os.path.join(csv_dir, "**", "*"), recursive=True):
        if not os.path.isfile(fp):
            continue
        sym = symbol_from_path(fp)
        if sym in need:
            grouped[sym].append(fp)
    return {k: v for k, v in grouped.items() if v}


def load_kline(paths: Iterable[str]) -> pd.DataFrame:
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
        keep = [c for c in [dcol, "open", "high", "low", "close", "volume"] if c in df.columns]
        tmp = df[keep].copy()
        tmp["dt"] = parse_date(tmp[dcol])
        for c in ["open", "high", "low", "close", "volume"]:
            if c in tmp.columns:
                tmp[c] = pd.to_numeric(tmp[c], errors="coerce")
        cols = [c for c in ["dt", "open", "high", "low", "close", "volume"] if c in tmp.columns]
        frames.append(tmp[cols])
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out = out.dropna(subset=["dt", "close"]).sort_values("dt")
    out = out.drop_duplicates(subset=["dt"], keep="last").reset_index(drop=True)
    out["ma200"] = out["close"].rolling(200, min_periods=200).mean()
    return out


def row_idx_on_or_after(k: pd.DataFrame, dt: pd.Timestamp) -> Optional[int]:
    idx = k.index[k["dt"] >= dt]
    return int(idx[0]) if len(idx) else None


def row_on_or_before(k: pd.DataFrame, dt: pd.Timestamp) -> Optional[pd.Series]:
    rows = k[k["dt"] <= dt]
    if rows.empty:
        return None
    return rows.iloc[-1]


def benchmark_ok(bench: pd.DataFrame, dt: pd.Timestamp) -> bool:
    row = row_on_or_before(bench, dt)
    if row is None:
        return False
    return bool(pd.notna(row["ma200"]) and float(row["close"]) > float(row["ma200"]))


def simulate_trade(
    symbol: str,
    k: pd.DataFrame,
    buy_dt: pd.Timestamp,
    stop_loss: float,
    take_profit: float,
    max_hold_days: int,
) -> Optional[Dict[str, object]]:
    buy_i = row_idx_on_or_after(k, buy_dt)
    if buy_i is None:
        return None
    buy_price = float(k.at[buy_i, "close"])
    if buy_price <= 0:
        return None

    end_i = len(k) - 1
    if max_hold_days > 0:
        end_i = min(end_i, buy_i + max_hold_days)

    future = k.iloc[buy_i + 1 : end_i + 1]
    exit_i = end_i
    exit_reason = "mtm_end"
    if not future.empty:
        close_ret = future["close"].to_numpy(dtype=float) / buy_price - 1.0
        if "low" in future.columns:
            low_ret = future["low"].to_numpy(dtype=float) / buy_price - 1.0
            low_ret = np.where(np.isfinite(low_ret), low_ret, close_ret)
        else:
            low_ret = close_ret
        if "high" in future.columns:
            high_ret = future["high"].to_numpy(dtype=float) / buy_price - 1.0
            high_ret = np.where(np.isfinite(high_ret), high_ret, close_ret)
        else:
            high_ret = close_ret

        stop_hits = np.flatnonzero((low_ret <= -stop_loss) | (close_ret <= -stop_loss))
        take_hits = np.flatnonzero((high_ret >= take_profit) | (close_ret >= take_profit))
        stop_pos = int(stop_hits[0]) if len(stop_hits) else None
        take_pos = int(take_hits[0]) if len(take_hits) else None
        if stop_pos is not None and (take_pos is None or stop_pos <= take_pos):
            exit_i = buy_i + 1 + stop_pos
            exit_reason = "stop_loss"
        elif take_pos is not None:
            exit_i = buy_i + 1 + take_pos
            exit_reason = "take_profit"

    if exit_reason == "stop_loss":
        exit_price = buy_price * (1.0 - stop_loss)
    elif exit_reason == "take_profit":
        exit_price = buy_price * (1.0 + take_profit)
    else:
        exit_price = float(k.at[exit_i, "close"])
    ret = exit_price / buy_price - 1.0
    holding_days = int(exit_i - buy_i)
    peak_ret = 0.0
    trough_ret = 0.0
    if holding_days > 0:
        path = k.iloc[buy_i : exit_i + 1]
        peak_ret = float(path["close"].max() / buy_price - 1.0)
        trough_ret = float((path["close"] / buy_price - 1.0).min())
    return {
        "symbol": symbol,
        "buy_date": k.at[buy_i, "dt"],
        "buy_price": buy_price,
        "exit_date": k.at[exit_i, "dt"],
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "holding_days": holding_days,
        "ret": ret,
        "max_ret": peak_ret,
        "max_drawdown_from_entry": trough_ret,
    }


def summary_table(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame([{"trades": 0}])
    rows = []
    for name, sub in [("all", trades), *list(trades.groupby("exit_reason"))]:
        if isinstance(name, tuple):
            name = str(name[0])
        rows.append(
            {
                "group": str(name),
                "trades": int(len(sub)),
                "symbols": int(sub["symbol"].nunique()),
                "avg_ret": float(sub["ret"].mean()),
                "median_ret": float(sub["ret"].median()),
                "win_rate": float((sub["ret"] > 0).mean()),
                "take_profit_rate": float((sub["exit_reason"] == "take_profit").mean()),
                "stop_loss_rate": float((sub["exit_reason"] == "stop_loss").mean()),
                "avg_holding_days": float(sub["holding_days"].mean()),
                "median_holding_days": float(sub["holding_days"].median()),
                "tail_gt20": float((sub["ret"] >= 0.20).mean()),
                "loss_lt8": float((sub["ret"] <= -0.08).mean()),
                "avg_max_drawdown": float(sub["max_drawdown_from_entry"].mean()),
            }
        )
    return pd.DataFrame(rows)


def period_summary(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    t = trades.copy()
    year = pd.to_datetime(t["buy_date"]).dt.year
    t["period"] = np.select(
        [year <= 2013, (year >= 2014) & (year <= 2015), year >= 2016],
        ["2011-2013", "2014-2015", "2016-2017"],
        default="other",
    )
    rows = []
    for period, sub in t.groupby("period"):
        row = summary_table(sub).iloc[0].to_dict()
        row["period"] = period
        rows.append(row)
    return pd.DataFrame(rows)


def monthly_equal_weight_curve(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    t = trades.copy()
    t["month"] = pd.to_datetime(t["buy_date"]).dt.to_period("M").dt.to_timestamp("M")
    monthly = (
        t.groupby("month")
        .agg(trades=("ret", "size"), avg_ret=("ret", "mean"), median_ret=("ret", "median"), win_rate=("ret", lambda s: (s > 0).mean()))
        .reset_index()
    )
    monthly["equity"] = (1.0 + monthly["avg_ret"]).cumprod()
    monthly["drawdown"] = monthly["equity"] / monthly["equity"].cummax() - 1.0
    years = len(monthly) / 12.0
    total = float(monthly["equity"].iloc[-1] - 1.0)
    cagr = float(monthly["equity"].iloc[-1] ** (1.0 / years) - 1.0) if years > 0 and monthly["equity"].iloc[-1] > 0 else np.nan
    monthly.attrs["total_return"] = total
    monthly.attrs["cagr"] = cagr
    monthly.attrs["max_drawdown"] = float(monthly["drawdown"].min())
    return monthly


def run(
    events_csv: str,
    csv_dir: str,
    output_dir: str,
    benchmark_symbol: str,
    stop_loss: float,
    take_profit: float,
    max_hold_days: int,
    require_benchmark_ma200: bool,
) -> str:
    events = pd.read_csv(events_csv)
    for c in ["break_date", "obs_end_date", "buy_date", "future_end_date"]:
        if c in events.columns:
            events[c] = pd.to_datetime(events[c], errors="coerce")
    events = events.dropna(subset=["symbol", "buy_date"]).copy()

    symbols = set(events["symbol"].astype(str).unique())
    symbols.add(benchmark_symbol)
    grouped = scan_symbol_files(csv_dir, symbols)
    if benchmark_symbol not in grouped:
        raise ValueError(f"benchmark not found in csv_dir: {benchmark_symbol}")
    bench = load_kline(grouped[benchmark_symbol])
    if bench.empty:
        raise ValueError(f"benchmark has no usable data: {benchmark_symbol}")

    rows: List[Dict[str, object]] = []
    skipped_by_market = 0
    skipped_no_kline = 0
    for sym, sub in events.groupby("symbol"):
        sym = str(sym)
        paths = grouped.get(sym)
        if not paths:
            skipped_no_kline += len(sub)
            continue
        k = load_kline(paths)
        if k.empty:
            skipped_no_kline += len(sub)
            continue
        for _, ev in sub.iterrows():
            buy_dt = pd.Timestamp(ev["buy_date"])
            if require_benchmark_ma200 and not benchmark_ok(bench, buy_dt):
                skipped_by_market += 1
                continue
            trade = simulate_trade(sym, k, buy_dt, stop_loss, take_profit, max_hold_days)
            if trade is None:
                skipped_no_kline += 1
                continue
            for c in [
                "break_date",
                "obs_end_date",
                "close_above_p0_days",
                "ret_obs_10d",
                "max_drawdown_from_p0",
                "up_days",
                "down_days",
                "up_down_diff",
                "ma120_distance_end",
                "ma120_distance_min",
                "new_high_120_count",
            ]:
                if c in ev.index:
                    trade[c] = ev[c]
            rows.append(trade)

    trades = pd.DataFrame(rows)
    summary = summary_table(trades)
    by_period = period_summary(trades)
    monthly = monthly_equal_weight_curve(trades)
    monthly_summary = pd.DataFrame(
        [
            {
                "months": int(len(monthly)),
                "total_return": monthly.attrs.get("total_return", np.nan),
                "cagr": monthly.attrs.get("cagr", np.nan),
                "max_drawdown": monthly.attrs.get("max_drawdown", np.nan),
                "avg_monthly_ret": float(monthly["avg_ret"].mean()) if len(monthly) else np.nan,
                "median_monthly_ret": float(monthly["avg_ret"].median()) if len(monthly) else np.nan,
            }
        ]
    )
    meta = pd.DataFrame(
        [
            {
                "events_input": int(len(events)),
                "trades": int(len(trades)),
                "skipped_by_market": int(skipped_by_market),
                "skipped_no_kline": int(skipped_no_kline),
                "benchmark_symbol": benchmark_symbol,
                "require_benchmark_ma200": bool(require_benchmark_ma200),
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "max_hold_days": max_hold_days,
            }
        ]
    )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(output_dir, f"ma120_hold10_stop_take_us_{stamp}")
    os.makedirs(out_dir, exist_ok=True)
    meta.to_csv(os.path.join(out_dir, "meta.csv"), index=False, encoding="utf-8-sig")
    trades.to_csv(os.path.join(out_dir, "trades.csv"), index=False, encoding="utf-8-sig")
    summary.to_csv(os.path.join(out_dir, "summary.csv"), index=False, encoding="utf-8-sig")
    by_period.to_csv(os.path.join(out_dir, "period_summary.csv"), index=False, encoding="utf-8-sig")
    monthly.to_csv(os.path.join(out_dir, "monthly_equal_weight_curve.csv"), index=False, encoding="utf-8-sig")
    monthly_summary.to_csv(os.path.join(out_dir, "monthly_equal_weight_summary.csv"), index=False, encoding="utf-8-sig")

    print(out_dir)
    print("\nMeta:")
    print(meta.to_string(index=False))
    print("\nTrade summary:")
    print(summary.to_string(index=False))
    print("\nMonthly equal-weight summary:")
    print(monthly_summary.to_string(index=False))
    return out_dir


def main() -> None:
    p = argparse.ArgumentParser(description="MA120 hold10 fixed stop/take backtest.")
    p.add_argument("--events-csv", required=True)
    p.add_argument("--csv-dir", default="/Users/water/abu/csv_his")
    p.add_argument("--output-dir", default="/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output")
    p.add_argument("--benchmark-symbol", default="usQQQ")
    p.add_argument("--stop-loss", type=float, default=0.08)
    p.add_argument("--take-profit", type=float, default=0.40)
    p.add_argument("--max-hold-days", type=int, default=0, help="0 means hold until stop/take/data end.")
    p.add_argument("--no-benchmark-ma200", action="store_true")
    args = p.parse_args()
    run(
        events_csv=args.events_csv,
        csv_dir=args.csv_dir,
        output_dir=args.output_dir,
        benchmark_symbol=args.benchmark_symbol,
        stop_loss=args.stop_loss,
        take_profit=args.take_profit,
        max_hold_days=args.max_hold_days,
        require_benchmark_ma200=(not args.no_benchmark_ma200),
    )


if __name__ == "__main__":
    main()
