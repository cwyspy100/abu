#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A-share trend system v1: confirmation, pullback re-entry and R-based exits."""

from __future__ import annotations

import argparse
import glob
import os
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from ma_trend_filtered_confirmation_backtest import load


def simulate(symbol: str, k: pd.DataFrame, bench: pd.DataFrame, window: int, trail_stop: float) -> List[Dict[str, object]]:
    ma = f"ma{window}"
    if len(k) < window + 30:
        return []
    dates = k.dt.to_numpy(); opens = k.open.to_numpy(float); highs = k.high.to_numpy(float); lows = k.low.to_numpy(float); closes = k.close.to_numpy(float)
    mas = k[ma].to_numpy(float); atr = k.atr20.to_numpy(float); vols = k.volume.to_numpy(float); vmed = k.vol20_median.to_numpy(float); cret = k.close_ret.to_numpy(float); gaps = k.open_gap.to_numpy(float)
    bench_pos = {d: i for i, d in enumerate(bench.dt.to_numpy())}
    bc = bench.close.to_numpy(float); bm = bench.ma120.to_numpy(float)
    trades: List[Dict[str, object]] = []
    i = window
    while i + 6 < len(k) - 1:
        if not (np.isfinite(mas[i]) and np.isfinite(mas[i-1]) and closes[i-1] <= mas[i-1] and closes[i] > mas[i]):
            i += 1; continue
        conf = i + 5
        if not (np.isfinite(mas[conf]) and closes[conf] > mas[conf] and closes[conf] >= closes[i]*1.05 and mas[conf] > mas[i]):
            i += 1; continue
        bi = bench_pos.get(dates[conf], -1)
        if bi < 0 or not (np.isfinite(bm[bi]) and bc[bi] > bm[bi]):
            i += 1; continue
        if not (np.isfinite(vmed[conf]) and vols[conf] >= .5*vmed[conf]):
            i += 1; continue
        # Reject abnormal confirmation-day movement and next-open gaps.
        if (np.isfinite(cret[conf]) and abs(cret[conf]) > .10) or (np.isfinite(atr[conf]) and highs[conf]-lows[conf] > 3*atr[conf]):
            i += 1; continue
        entry: Optional[int] = None
        # Pullback: touch within 3% of MA, close remains above MA, then next day re-strengthens.
        for p in range(conf + 1, min(conf + 21, len(k) - 1)):
            if not (np.isfinite(mas[p]) and lows[p] <= mas[p]*1.03 and closes[p] >= mas[p]):
                continue
            if closes[p+1] > closes[p] and closes[p+1] > mas[p+1] and abs(gaps[p+1]) <= .08:
                entry = p + 2 if p + 2 < len(k) else None
                break
        if entry is None or entry >= len(k) - 1:
            i += 1; continue
        buy = opens[entry]
        if buy <= 0:
            i += 1; continue
        atr_stop = (2*atr[entry]/buy) if np.isfinite(atr[entry]) else .10
        stop_dist = min(max(.10, atr_stop), .15)
        r_value = buy * stop_dist
        peak = buy; below = 0; trail_active = False; partial = False; exit_i: Optional[int] = None; reasons: List[str] = []
        for j in range(entry, len(k) - 1):
            peak = max(peak, highs[j])
            if closes[j] >= buy + r_value:
                trail_active = True
            below = below + 1 if closes[j] < mas[j] else 0
            if below >= 2: reasons.append("below_ma_2d")
            if closes[j] <= buy * (1-stop_dist): reasons.append("atr_or_fixed_stop")
            if trail_active and closes[j] <= peak * (1-trail_stop): reasons.append("trailing_stop")
            if not partial and closes[j] >= buy + 2*r_value:
                partial = True
            if reasons:
                exit_i = j + 1; break
        if exit_i is None:
            trades.append({"symbol": symbol, "window": window, "entry_date": dates[entry], "entry_price": buy, "exit_date": pd.NaT, "exit_price": np.nan, "exit_reason": "open_end", "ret": np.nan, "holding_days": len(k)-1-entry, "partial_2r": partial, "stop_pct": stop_dist})
            break
        sell = opens[exit_i]
        if partial:
            ret = (1/3) * (2*stop_dist) + (2/3) * (sell/buy - 1)
        else:
            ret = sell/buy - 1
        trades.append({"symbol": symbol, "window": window, "entry_date": dates[entry], "entry_price": buy, "exit_date": dates[exit_i], "exit_price": sell, "exit_reason": "+".join(reasons), "ret": ret, "holding_days": exit_i-entry, "partial_2r": partial, "stop_pct": stop_dist})
        i = exit_i
    return trades


def main(csv_dir: str, output_root: str) -> str:
    bench_path = glob.glob(os.path.join(csv_dir, "sh000001_*"))[0]
    bench = load(bench_path); rows: List[Dict[str, object]] = []
    for path in sorted(glob.glob(os.path.join(csv_dir, "*"))):
        name = os.path.basename(path)
        if not os.path.isfile(path) or not name.startswith(("sh", "sz")):
            continue
        k = load(path); symbol = name.split("_", 1)[0]
        rows.extend(simulate(symbol, k, bench, 60, .15))
        rows.extend(simulate(symbol, k, bench, 120, .20))
    t = pd.DataFrame(rows); stamp = datetime.now().strftime("%Y%m%d_%H%M%S"); out = os.path.join(output_root, f"ma_trend_system_v1_a_{stamp}"); os.makedirs(out, exist_ok=True)
    t.to_csv(os.path.join(out, "trades.csv"), index=False)
    summary = []
    for w, s in t.groupby("window"):
        c = s[s.exit_reason != "open_end"]
        summary.append({"window": int(w), "all_trades": len(s), "closed_trades": len(c), "open_end": int((s.exit_reason=="open_end").sum()), "win_rate": (c.ret>0).mean() if len(c) else np.nan, "avg_ret": c.ret.mean() if len(c) else np.nan, "median_ret": c.ret.median() if len(c) else np.nan, "profit_factor": c.loc[c.ret>0,"ret"].sum()/abs(c.loc[c.ret<0,"ret"].sum()) if (c.ret<0).any() else np.inf, "partial_2r_rate": c.partial_2r.mean() if len(c) else np.nan, "median_holding_days": c.holding_days.median() if len(c) else np.nan, "avg_stop_pct": c.stop_pct.mean() if len(c) else np.nan})
    pd.DataFrame(summary).to_csv(os.path.join(out, "summary.csv"), index=False)
    t[t.exit_reason!="open_end"].groupby(["window", "exit_reason"], as_index=False).size().to_csv(os.path.join(out, "exit_reason_counts.csv"), index=False)
    print(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--csv-dir", default="/Users/water/abu/csv_his"); ap.add_argument("--output-root", default="cy_quant/output"); a = ap.parse_args(); main(a.csv_dir, a.output_root)
