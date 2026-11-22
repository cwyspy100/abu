#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A-share MA trend backtest with five-day confirmation and market filters."""

from __future__ import annotations

import argparse
import glob
import os
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


def parse_dates(s: pd.Series) -> pd.Series:
    raw = s.astype(str).str.strip()
    a = pd.to_datetime(raw.where(raw.str.fullmatch(r"\d{8}")), format="%Y%m%d", errors="coerce")
    b = pd.to_datetime(raw.where(~raw.str.fullmatch(r"\d{8}")), errors="coerce")
    return a.fillna(b)


def load(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    dcol = "date" if "date" in df.columns else "Unnamed: 0"
    if "close" not in df.columns or dcol not in df.columns:
        return pd.DataFrame()
    out = pd.DataFrame({"dt": parse_dates(df[dcol])})
    for c in ("open", "high", "low", "close", "volume"):
        out[c] = pd.to_numeric(df[c], errors="coerce") if c in df.columns else np.nan
    out["open"] = out["open"].fillna(out["close"])
    out["high"] = out["high"].fillna(out["close"])
    out["low"] = out["low"].fillna(out["close"])
    out = out.dropna(subset=["dt", "open", "high", "low", "close"]).sort_values("dt").drop_duplicates("dt").reset_index(drop=True)
    out = out[out.close > 0].reset_index(drop=True)
    for window in (5, 10, 20, 30, 60, 120):
        out[f"ma{window}"] = out.close.rolling(window, min_periods=window).mean()
    out["vol20_median"] = out.volume.rolling(20, min_periods=20).median()
    prev_close = out.close.shift(1)
    tr = pd.concat([out.high - out.low, (out.high - prev_close).abs(), (out.low - prev_close).abs()], axis=1).max(axis=1)
    out["atr20"] = tr.rolling(20, min_periods=20).mean()
    out["close_ret"] = out.close / prev_close - 1.0
    out["open_gap"] = out.open / prev_close - 1.0
    return out


def simulate(symbol: str, k: pd.DataFrame, bench: pd.DataFrame, window: int, fixed_stop: float, trail_stop: float) -> tuple[List[Dict[str, object]], Dict[str, int]]:
    ma = f"ma{window}"
    stats = {"breakout": 0, "confirmed": 0, "market_pass": 0, "quality_pass": 0, "low_volume_reject": 0, "jump_reject": 0}
    if len(k) < window + 10:
        return [], stats
    dates = k.dt.to_numpy(); opens = k.open.to_numpy(float); highs = k.high.to_numpy(float); closes = k.close.to_numpy(float)
    mas = k[ma].to_numpy(float); vols = k.volume.to_numpy(float); vmed = k.vol20_median.to_numpy(float)
    atr = k.atr20.to_numpy(float); cret = k.close_ret.to_numpy(float); gap = k.open_gap.to_numpy(float)
    bd = bench.dt.to_numpy(); bc = bench.close.to_numpy(float); bm = bench.ma120.to_numpy(float)
    bench_ok = np.array([bool(np.isfinite(bm[x]) and bc[x] > bm[x]) if x >= 0 else False for x in range(len(bench))])
    bench_pos = {d: i for i, d in enumerate(bd)}
    trades: List[Dict[str, object]] = []
    i = window
    while i + 6 < len(k) - 1:
        if not (np.isfinite(mas[i]) and np.isfinite(mas[i - 1]) and closes[i - 1] <= mas[i - 1] and closes[i] > mas[i]):
            i += 1; continue
        stats["breakout"] += 1
        conf = i + 5
        if not (np.isfinite(mas[conf]) and closes[conf] > mas[conf] and closes[conf] >= closes[i] * 1.05 and mas[conf] > mas[i]):
            i += 1; continue
        stats["confirmed"] += 1
        bi = bench_pos.get(dates[conf], -1)
        if bi < 0 or not bench_ok[bi]:
            i += 1; continue
        stats["market_pass"] += 1
        if not (np.isfinite(vmed[conf]) and vols[conf] >= 0.5 * vmed[conf]):
            stats["low_volume_reject"] += 1; i += 1; continue
        entry = conf + 1
        if entry >= len(k) - 1:
            break
        # At next-open entry, only the overnight gap is observable without lookahead.
        if abs(gap[entry]) > 0.08 or (np.isfinite(cret[conf]) and abs(cret[conf]) > 0.10) or (np.isfinite(atr[conf]) and highs[conf] - lowsafe(k, conf) > 3 * atr[conf]):
            stats["jump_reject"] += 1; i += 1; continue
        stats["quality_pass"] += 1
        buy = opens[entry]
        if buy <= 0: i += 1; continue
        peak = buy; below = 0; exit_i: Optional[int] = None; reasons: List[str] = []
        for j in range(entry, len(k) - 1):
            peak = max(peak, highs[j])
            below = below + 1 if closes[j] < mas[j] else 0
            if below >= 2: reasons.append("below_ma_2d")
            if closes[j] <= buy * (1 - fixed_stop): reasons.append("fixed_stop")
            if closes[j] <= peak * (1 - trail_stop): reasons.append("trailing_stop")
            if reasons:
                exit_i = j + 1; break
        if exit_i is None:
            trades.append({"symbol": symbol, "window": window, "entry_date": dates[entry], "entry_price": buy, "exit_date": pd.NaT, "exit_price": np.nan, "exit_reason": "open_end", "ret": np.nan, "holding_days": len(k)-1-entry})
            break
        sell = opens[exit_i]
        trades.append({"symbol": symbol, "window": window, "entry_date": dates[entry], "entry_price": buy, "exit_date": dates[exit_i], "exit_price": sell, "exit_reason": "+".join(reasons), "ret": sell/buy-1, "holding_days": exit_i-entry})
        i = exit_i
    return trades, stats


def lowsafe(k: pd.DataFrame, i: int) -> float:
    return float(k.iloc[i]["low"])


def main(csv_dir: str, output_root: str) -> str:
    bench_files = glob.glob(os.path.join(csv_dir, "sh000001_*"))
    if not bench_files:
        raise FileNotFoundError("sh000001 benchmark not found")
    bench = load(bench_files[0])
    all_trades: List[Dict[str, object]] = []; stat_rows: List[Dict[str, object]] = []
    for path in sorted(glob.glob(os.path.join(csv_dir, "*"))):
        name = os.path.basename(path)
        if not os.path.isfile(path) or not name.startswith(("sh", "sz")):
            continue
        k = load(path)
        symbol = name.split("_", 1)[0]
        for w, fs, ts in ((60, .05, .10), (120, .10, .20)):
            trades, stats = simulate(symbol, k, bench, w, fs, ts)
            all_trades.extend(trades); stat_rows.append({"symbol": symbol, "window": w, **stats})
    t = pd.DataFrame(all_trades); q = pd.DataFrame(stat_rows)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S"); out = os.path.join(output_root, f"ma_trend_filtered_confirmation_a_{stamp}"); os.makedirs(out, exist_ok=True)
    t.to_csv(os.path.join(out, "trades.csv"), index=False); q.to_csv(os.path.join(out, "filter_stats_by_symbol.csv"), index=False)
    rows = []
    for w, s in t.groupby("window"):
        c = s[s.exit_reason != "open_end"]
        rows.append({"window": int(w), "all_trades": len(s), "closed_trades": len(c), "open_end": int((s.exit_reason=="open_end").sum()), "win_rate": (c.ret>0).mean() if len(c) else np.nan, "avg_ret": c.ret.mean() if len(c) else np.nan, "median_ret": c.ret.median() if len(c) else np.nan, "profit_factor": c.loc[c.ret>0,"ret"].sum()/abs(c.loc[c.ret<0,"ret"].sum()) if (c.ret<0).any() else np.inf, "median_holding_days": c.holding_days.median() if len(c) else np.nan})
    pd.DataFrame(rows).to_csv(os.path.join(out, "summary.csv"), index=False)
    qsum = q.groupby("window")[['breakout','confirmed','market_pass','quality_pass','low_volume_reject','jump_reject']].sum().reset_index(); qsum.to_csv(os.path.join(out, "filter_summary.csv"), index=False)
    print(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--csv-dir", default="/Users/water/abu/csv_his"); ap.add_argument("--output-root", default="cy_quant/output"); a = ap.parse_args(); main(a.csv_dir, a.output_root)
