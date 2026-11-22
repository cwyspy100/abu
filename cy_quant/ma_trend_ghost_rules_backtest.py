#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compare the previous A-share MA system with Ghost-style position rules."""

from __future__ import annotations

import argparse
import glob
import os
import re
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from ma_trend_filtered_confirmation_backtest import load


def signal_entry(k: pd.DataFrame, bench: pd.DataFrame, window: int, symbol: str) -> List[int]:
    ma = f"ma{window}"
    dates = k.dt.to_numpy(); closes = k.close.to_numpy(float); highs = k.high.to_numpy(float); lows = k.low.to_numpy(float)
    mas = k[ma].to_numpy(float); vols = k.volume.to_numpy(float); vmed = k.vol20_median.to_numpy(float); atr = k.atr20.to_numpy(float); cret = k.close_ret.to_numpy(float); gaps = k.open_gap.to_numpy(float)
    bpos = {d: i for i, d in enumerate(bench.dt.to_numpy())}; bc = bench.close.to_numpy(float); bm = bench.ma120.to_numpy(float)
    entries: List[int] = []; i = window
    while i + 6 < len(k) - 1:
        if not (np.isfinite(mas[i]) and np.isfinite(mas[i-1]) and closes[i-1] <= mas[i-1] and closes[i] > mas[i]):
            i += 1; continue
        conf = i + 5; bi = bpos.get(dates[conf], -1)
        valid = (np.isfinite(mas[conf]) and closes[conf] > mas[conf] and closes[conf] >= closes[i]*1.05 and mas[conf] > mas[i] and bi >= 0 and np.isfinite(bm[bi]) and bc[bi] > bm[bi] and np.isfinite(vmed[conf]) and vols[conf] >= .5*vmed[conf])
        if valid and ((np.isfinite(cret[conf]) and abs(cret[conf]) > .10) or (np.isfinite(atr[conf]) and highs[conf]-lows[conf] > 3*atr[conf])):
            valid = False
        entry = conf + 1
        if valid and entry < len(k)-1 and abs(gaps[entry]) <= .08:
            entries.append(entry)
        i += 1
    return entries


def simulate_one(k: pd.DataFrame, entry: int, window: int, ghost: bool) -> Optional[Dict[str, object]]:
    fs = .05 if window == 60 else .10
    trail = .10 if window == 60 else .20
    dates = k.dt.to_numpy(); opens = k.open.to_numpy(float); highs = k.high.to_numpy(float); closes = k.close.to_numpy(float); mas = k[f"ma{window}"].to_numpy(float)
    vols = k.volume.to_numpy(float); vmed = k.vol20_median.to_numpy(float)
    buy = opens[entry]
    if buy <= 0: return None
    peak = buy; below = 0; highvol = 0; vol_exit_schedule: Optional[int] = None; frozen_add = False
    tranches = [(1/3, buy)] if ghost else [(1.0, buy)]
    next_add = 1; add_count = 0; realized = 0.0; volume_stage = 0; exit_i: Optional[int] = None; reasons: List[str] = []

    def sell_fraction(fraction: float, price: float) -> None:
        nonlocal realized, tranches
        new_tranches = []
        for weight, px in tranches:
            sold = weight * fraction
            realized += sold * (price / px - 1.0)
            remain = weight - sold
            if remain > 1e-12:
                new_tranches.append((remain, px))
        tranches = new_tranches
    for j in range(entry, len(k)-1):
        peak = max(peak, highs[j])
        if np.isfinite(vmed[j]) and vols[j] >= 2*vmed[j]: highvol += 1
        else: highvol = 0
        if ghost and highvol >= 3 and vol_exit_schedule is None:
            vol_exit_schedule = j + 1; frozen_add = True
        if ghost and vol_exit_schedule is not None and j >= vol_exit_schedule and volume_stage < 3:
            reasons.append("extreme_volume")
            if volume_stage < 2:
                sell_fraction(.5, opens[j]); volume_stage += 1
            else:
                sell_fraction(1.0, opens[j]); volume_stage = 3; exit_i = j; break
        # Add only after the close has proved the position correct; execute next open.
        if ghost and not frozen_add and next_add <= 2 and closes[j] >= buy * (1 + next_add*fs) and j+1 < len(k)-1:
            add_price = opens[j+1]; tranches.append((1/3, add_price)); add_count += 1; next_add += 1
        below = below + 1 if closes[j] < mas[j] else 0
        trigger = None
        if below >= 2: reasons.append("below_ma_2d"); trigger = "signal"
        if closes[j] <= buy*(1-fs): reasons.append("fixed_stop"); trigger = "signal"
        if closes[j] <= peak*(1-trail): reasons.append("trailing_stop"); trigger = "signal"
        if trigger:
            exit_i = j+1; sell_fraction(1.0, opens[exit_i]); break
    if exit_i is None:
        return {"window":window,"entry_date":dates[entry],"entry_price":buy,"exit_date":pd.NaT,"exit_price":np.nan,"exit_reason":"open_end","ret":np.nan,"holding_days":len(k)-1-entry,"add_count":add_count,"entered_weight":sum(w for w,_ in tranches),"exit_index":len(k)-1}
    sell = opens[exit_i]
    ret = realized + sum(w*(sell/px-1) for w,px in tranches)
    return {"window":window,"entry_date":dates[entry],"entry_price":buy,"exit_date":dates[exit_i],"exit_price":sell,"exit_reason":"+".join(dict.fromkeys(reasons)),"ret":ret,"holding_days":exit_i-entry,"add_count":add_count,"entered_weight":sum(w for w,_ in tranches),"exit_index":exit_i}


def eligible_symbol(name: str, market: str) -> bool:
    if market == "a":
        return bool(re.match(r"^(sh|sz)\d{6}_", name))
    if market == "hk":
        return bool(re.match(r"^hk\d{5}_", name))
    if market == "us":
        return bool(re.match(r"^us[^._]+_", name))
    return False


def main(csv_dir: str, output_root: str, market: str, benchmark_symbol: Optional[str], windows: str, symbols_file: Optional[str]) -> str:
    benchmark_symbol = benchmark_symbol or {"a": "sh000001", "hk": "hkHSI", "us": "us.INX"}[market]
    benchmark_files = glob.glob(os.path.join(csv_dir, f"{benchmark_symbol}_*"))
    if not benchmark_files:
        raise FileNotFoundError(f"benchmark not found: {benchmark_symbol}")
    bench = load(benchmark_files[0]); rows: List[Dict[str, object]] = []
    allowed_symbols = None
    if symbols_file:
        with open(symbols_file, "r", encoding="utf-8") as fh:
            allowed_symbols = {line.strip().upper() for line in fh if line.strip() and not line.lstrip().startswith("#")}
    for path in sorted(glob.glob(os.path.join(csv_dir, "*"))):
        name = os.path.basename(path)
        if not os.path.isfile(path) or not eligible_symbol(name, market): continue
        ticker = name.split("_", 1)[0][2:].upper()
        if allowed_symbols is not None and ticker not in allowed_symbols: continue
        k = load(path); symbol = name.split("_",1)[0]
        for w in tuple(int(x.strip()) for x in windows.split(",") if x.strip()):
            entries = signal_entry(k, bench, w, symbol)
            for mode, ghost in (("baseline",False),("ghost",True)):
                next_allowed = -1
                for entry in entries:
                    if entry <= next_allowed:
                        continue
                    tr = simulate_one(k, entry, w, ghost)
                    if tr:
                        tr.update({"symbol":symbol,"mode":mode}); rows.append(tr); next_allowed = int(tr["exit_index"])
    t = pd.DataFrame(rows); stamp = datetime.now().strftime("%Y%m%d_%H%M%S"); universe_tag = "_filtered" if allowed_symbols is not None else ""; out = os.path.join(output_root,f"ma_trend_ghost_rules_{market}{universe_tag}_{stamp}"); os.makedirs(out,exist_ok=True); t.to_csv(os.path.join(out,"trades.csv"),index=False)
    summary=[]
    for (mode,w),s in t.groupby(["mode","window"]):
        c=s[s.exit_reason!="open_end"]; wins=c[c.ret>0].ret; losses=c[c.ret<0].ret
        trimmed=c[c.ret < c.ret.quantile(.99)]
        summary.append({"mode":mode,"window":int(w),"all_trades":len(s),"closed_trades":len(c),"open_end":int((s.exit_reason=="open_end").sum()),"win_rate":(c.ret>0).mean(),"avg_ret":c.ret.mean(),"median_ret":c.ret.median(),"avg_win":wins.mean() if len(wins) else np.nan,"avg_loss":losses.mean() if len(losses) else np.nan,"profit_factor":wins.sum()/abs(losses.sum()) if len(losses) else np.nan,"trimmed_avg_ret_ex_top1pct":trimmed.ret.mean(),"avg_add_count":c.add_count.mean(),"extreme_volume_exit_rate":c.exit_reason.str.contains("extreme_volume").mean()})
    pd.DataFrame(summary).to_csv(os.path.join(out,"summary.csv"),index=False)
    print(out)


if __name__ == "__main__":
    ap=argparse.ArgumentParser(); ap.add_argument("--csv-dir",default="/Users/water/abu/csv_his"); ap.add_argument("--output-root",default="cy_quant/output"); ap.add_argument("--market",choices=["a","hk","us"],default="a"); ap.add_argument("--benchmark-symbol"); ap.add_argument("--windows",default="60,120"); ap.add_argument("--symbols-file"); a=ap.parse_args(); main(a.csv_dir,a.output_root,a.market,a.benchmark_symbol,a.windows,a.symbols_file)
