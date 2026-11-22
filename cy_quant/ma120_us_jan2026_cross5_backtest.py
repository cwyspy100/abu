#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MA120 first-cross backtest for US or A-share universes.

Rules:
- First cross above MA120 on/after start date
- N trading days later still close > MA120
- MA120 slope upward at confirmation day
- Buy next trading day close (equal weight per trade)
- Exit when close < MA120 and/or pct stop if enabled
"""

from __future__ import annotations

import argparse
import glob
import os
import re
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

A_EQUITY_RE = re.compile(r"^(sh(?:60|68)\d{4}|sz(?:00|30)\d{4})$")


def symbol_from_path(path: str) -> str:
    return os.path.basename(path).split("_", 1)[0]


def scan_us_files(csv_dir: str, max_stocks: int = 5000) -> Dict[str, str]:
    files = sorted(f for f in glob.glob(os.path.join(csv_dir, "us*")) if os.path.isfile(f))
    skip = {"us.DJI", "us.INX", "us.IXIC", "usQQQ", "usTQQQ", "usSPY", "usVOO"}
    out: Dict[str, str] = {}
    for fp in files:
        sym = symbol_from_path(fp)
        if sym in skip or "." in sym:
            continue
        out[sym] = fp
        if len(out) >= max_stocks:
            break
    return out


def scan_a_files(csv_dir: str, max_stocks: int = 10000) -> Dict[str, str]:
    files = sorted(
        f
        for prefix in ("sh", "sz")
        for f in glob.glob(os.path.join(csv_dir, f"{prefix}*"))
        if os.path.isfile(f)
    )
    out: Dict[str, str] = {}
    for fp in files:
        sym = symbol_from_path(fp)
        if not A_EQUITY_RE.match(sym):
            continue
        out[sym] = fp
        if len(out) >= max_stocks:
            break
    return out


def scan_market_files(market: str, csv_dir: str, max_stocks: int) -> Dict[str, str]:
    if market == "us":
        return scan_us_files(csv_dir, max_stocks=max_stocks)
    if market == "a":
        return scan_a_files(csv_dir, max_stocks=max_stocks)
    raise ValueError(f"unsupported market: {market}")


def load_kline(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "close" not in df.columns:
        return pd.DataFrame()
    dcol = "date" if "date" in df.columns else None
    if dcol is None:
        return pd.DataFrame()
    out = df.copy()
    raw = out[dcol].astype(str)
    if raw.str.fullmatch(r"\d{8}").mean() > 0.8:
        out["dt"] = pd.to_datetime(raw, format="%Y%m%d", errors="coerce")
    else:
        out["dt"] = pd.to_datetime(raw, errors="coerce")
    out["close"] = pd.to_numeric(out["close"], errors="coerce")
    out = out.dropna(subset=["dt", "close"]).sort_values("dt").reset_index(drop=True)
    out["ma120"] = out["close"].rolling(120, min_periods=120).mean()
    out["ret1"] = out["close"].pct_change()
    return out


def find_events(
    k: pd.DataFrame,
    start_date: pd.Timestamp,
    obs_days: int,
    slope_lookback: int,
    end_date: Optional[pd.Timestamp] = None,
) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    above = (k["close"] > k["ma120"]).fillna(False)
    cross = above & (~above.shift(1, fill_value=False).astype(bool))
    idxs = np.where(cross.fillna(False).values)[0]
    last_i = -999
    for i in idxs:
        if i < 120:
            continue
        cross_dt = pd.Timestamp(k.at[i, "dt"])
        if cross_dt < start_date:
            continue
        if end_date is not None and cross_dt > end_date:
            continue
        if i - last_i < 30:
            continue
        ev = i + obs_days
        buy = ev + 1
        if buy >= len(k):
            continue
        confirm = k.iloc[ev]
        if pd.isna(confirm["ma120"]) or float(confirm["close"]) <= float(confirm["ma120"]):
            continue
        ma_now = float(confirm["ma120"])
        ma_prev_idx = ev - slope_lookback
        if ma_prev_idx < 0 or pd.isna(k.at[ma_prev_idx, "ma120"]):
            continue
        ma_prev = float(k.at[ma_prev_idx, "ma120"])
        if ma_now <= ma_prev:
            continue
        buy_px = float(k.at[buy, "close"])
        if buy_px <= 0:
            continue
        rows.append(
            {
                "cross_date": cross_dt,
                "confirm_date": pd.Timestamp(k.at[ev, "dt"]),
                "buy_date": pd.Timestamp(k.at[buy, "dt"]),
                "buy_idx": buy,
                "buy_price": buy_px,
                "cross_idx": i,
            }
        )
        last_i = i
    return rows


def simulate_trade(
    k: pd.DataFrame,
    buy_idx: int,
    buy_price: float,
    stop_pct: Optional[float],
    eval_date: Optional[pd.Timestamp],
) -> Dict[str, object]:
    seg = k.iloc[buy_idx:].copy().reset_index(drop=True)
    entry = buy_price
    exit_date = None
    exit_price = None
    exit_reason = None
    for j in range(len(seg)):
        dt = pd.Timestamp(seg.at[j, "dt"])
        close = float(seg.at[j, "close"])
        ma120 = seg.at[j, "ma120"]
        dd = close / entry - 1.0
        below_ma = pd.notna(ma120) and close < float(ma120)
        stop_hit = stop_pct is not None and dd <= -stop_pct
        if below_ma or stop_hit:
            exit_date = dt
            exit_price = close
            if below_ma and stop_hit:
                exit_reason = "below_ma120_and_stop"
            elif below_ma:
                exit_reason = "below_ma120"
            else:
                exit_reason = "stop_pct"
            break
        if eval_date is not None and dt >= eval_date:
            exit_date = dt
            exit_price = close
            exit_reason = "held_to_eval"
            break
    if exit_date is None:
        exit_date = pd.Timestamp(seg.iloc[-1]["dt"])
        exit_price = float(seg.iloc[-1]["close"])
        exit_reason = "data_end"
    ret = exit_price / entry - 1.0
    still_open = exit_reason in {"held_to_eval", "data_end"}
    hold_days = int((exit_date - pd.Timestamp(seg.at[0, "dt"])).days)
    return {
        "exit_date": exit_date,
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "ret": ret,
        "still_open_at_eval": still_open,
        "hold_days": hold_days,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="MA120 first-cross backtest for US or A-share.")
    parser.add_argument("--market", choices=["us", "a"], default="us")
    parser.add_argument("--csv-dir", default="/Users/water/abu/data/csv")
    parser.add_argument("--output-dir", default="cy_quant/output")
    parser.add_argument("--start-date", default="2026-01-02")
    parser.add_argument("--end-date", default="", help="Optional last cross date in study window.")
    parser.add_argument("--eval-date", default="2026-04-01", help="Use 'none' to hold until MA120 exit only.")
    parser.add_argument("--obs-days", type=int, default=5)
    parser.add_argument("--slope-lookback", type=int, default=20)
    parser.add_argument("--stop-pct", type=float, default=0.05, help="Use 0 to disable pct stop.")
    parser.add_argument("--label", default="")
    parser.add_argument("--max-daily-jump", type=float, default=0.35)
    parser.add_argument("--max-stocks", type=int, default=5000)
    args = parser.parse_args()

    start_date = pd.Timestamp(args.start_date)
    end_date = pd.Timestamp(args.end_date) if args.end_date else None
    eval_date = None if str(args.eval_date).lower() == "none" else pd.Timestamp(args.eval_date)
    stop_pct = None if args.stop_pct <= 0 else args.stop_pct
    files = scan_market_files(args.market, args.csv_dir, max_stocks=args.max_stocks)

    events: List[Dict[str, object]] = []
    trades: List[Dict[str, object]] = []
    skipped_jump = 0
    skipped_short = 0

    for sym, fp in files.items():
        k = load_kline(fp)
        if len(k) < 260:
            skipped_short += 1
            continue
        if float(k["ret1"].abs().max(skipna=True) or 0.0) > args.max_daily_jump:
            skipped_jump += 1
            continue
        evs = find_events(k, start_date, args.obs_days, args.slope_lookback, end_date=end_date)
        for ev in evs:
            buy_date = pd.Timestamp(ev["buy_date"])
            if end_date is not None and buy_date > end_date:
                continue
            if eval_date is not None and buy_date > eval_date:
                continue
            sim = simulate_trade(k, int(ev["buy_idx"]), float(ev["buy_price"]), stop_pct, eval_date)
            row = {
                "symbol": sym,
                "cross_date": ev["cross_date"],
                "confirm_date": ev["confirm_date"],
                "buy_date": buy_date,
                "buy_price": ev["buy_price"],
                **sim,
            }
            events.append(ev)
            trades.append(row)

    trades_df = pd.DataFrame(trades)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    tag = args.label or f"cross{args.obs_days}"
    out_dir = os.path.join(args.output_dir, f"ma120_{args.market}_{tag}_{ts}")
    os.makedirs(out_dir, exist_ok=True)

    if trades_df.empty:
        print("No qualifying trades found.")
        return

    trades_df.to_csv(os.path.join(out_dir, "trades.csv"), index=False)
    still = trades_df[trades_df["still_open_at_eval"]].copy()
    still.to_csv(os.path.join(out_dir, "still_open_at_eval.csv"), index=False)

    def summarize(df: pd.DataFrame, label: str) -> Dict[str, object]:
        r = pd.to_numeric(df["ret"], errors="coerce")
        return {
            "group": label,
            "n": len(df),
            "mean_ret": r.mean(),
            "median_ret": r.median(),
            "win_rate": (r > 0).mean(),
            "gt20": (r > 0.20).mean(),
            "gt30": (r > 0.30).mean(),
            "lt10": (r < -0.10).mean(),
        }

    summary = pd.DataFrame(
        [
            summarize(trades_df, "all_trades"),
            summarize(still, "still_open_at_eval"),
            summarize(trades_df[~trades_df["still_open_at_eval"]], "closed_before_eval_or_end"),
        ]
    )
    hold_stats = trades_df["hold_days"].describe()
    summary.to_csv(os.path.join(out_dir, "summary.csv"), index=False)

    reason_counts = trades_df["exit_reason"].value_counts().rename_axis("exit_reason").reset_index(name="count")
    reason_counts.to_csv(os.path.join(out_dir, "exit_reason_counts.csv"), index=False)

    eq = trades_df.copy()
    eq["weight"] = 1.0 / len(eq)
    port_ret = float((eq["ret"] * eq["weight"]).sum())
    still_eq = still.copy()
    still_port = float(still_eq["ret"].mean()) if len(still_eq) else np.nan

    report_lines = [
        f"{args.market.upper()} MA120 cross+{args.obs_days}d backtest",
        f"csv_dir={args.csv_dir}",
        f"start_date={start_date.date()} end_date={'none' if end_date is None else end_date.date()} eval_date={'none' if eval_date is None else eval_date.date()}",
        f"stop_pct={'disabled' if stop_pct is None else stop_pct}",
        f"universe_files={len(files)} skipped_short={skipped_short} skipped_jump={skipped_jump}",
        f"qualifying_trades={len(trades_df)}",
        f"still_open_at_eval={len(still)}",
        f"equal_weight_all_trades_ret={port_ret:.4f}",
        f"equal_weight_still_open_mean_ret={still_port:.4f}" if len(still_eq) else "equal_weight_still_open_mean_ret=NA",
        "",
        "summary:",
        summary.to_string(index=False),
        "",
        "exit_reason:",
        reason_counts.to_string(index=False),
        "",
        "hold_days:",
        hold_stats.to_string(),
    ]
    if len(still):
        top = still.sort_values("ret", ascending=False).head(20)[
            ["symbol", "buy_date", "buy_price", "exit_price", "ret", "exit_reason"]
        ]
        report_lines.extend(["", "top20 still open:", top.to_string(index=False)])

    report = "\n".join(report_lines)
    with open(os.path.join(out_dir, "report.txt"), "w", encoding="utf-8") as f:
        f.write(report)
    print(report)
    print(f"\noutput_dir={out_dir}")


if __name__ == "__main__":
    main()
