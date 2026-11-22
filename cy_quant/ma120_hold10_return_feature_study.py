#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Return-feature study after a clean 10-day hold above MA120.

Input events should come from ma120_hold10_feature_study.py. This script adds
fixed-horizon returns from the day after the 10-day observation window and then
summarizes which observation-window features correspond to better 30/60/120 day
returns.
"""

from __future__ import annotations

import argparse
import glob
import os
from datetime import datetime
from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd


FEATURES = [
    "close_above_p0_days",
    "ret_obs_10d",
    "max_drawdown_from_p0",
    "up_days",
    "down_days",
    "up_down_diff",
    "ma120_distance_end",
    "ma120_distance_min",
    "ma120_distance_avg",
    "volume_ratio_10_60",
    "atr10_vs_atr60",
    "new_high_120_count",
    "future_above_ma120_days",
]


def symbol_from_path(path: str) -> str:
    return os.path.basename(path).split("_", 1)[0]


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
        frames.append(tmp[["dt", "close"]])
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out = out.dropna(subset=["dt", "close"]).sort_values("dt")
    out = out.drop_duplicates(subset=["dt"], keep="last").reset_index(drop=True)
    out["ma120"] = out["close"].rolling(120, min_periods=120).mean()
    return out


def row_idx_on_or_after(k: pd.DataFrame, dt: pd.Timestamp) -> Optional[int]:
    idx = k.index[k["dt"] >= dt]
    return int(idx[0]) if len(idx) else None


def add_fixed_returns(events: pd.DataFrame, csv_dir: str, horizons: List[int]) -> pd.DataFrame:
    grouped = scan_symbol_files(csv_dir, events["symbol"].unique())
    rows: List[Dict[str, object]] = []
    for sym, sub in events.groupby("symbol"):
        paths = grouped.get(str(sym), [])
        if not paths:
            continue
        k = load_symbol(paths)
        if k.empty:
            continue
        for _, ev in sub.iterrows():
            buy_i = row_idx_on_or_after(k, pd.Timestamp(ev["buy_date"]))
            if buy_i is None:
                continue
            buy_close = float(k.at[buy_i, "close"])
            if buy_close <= 0:
                continue
            row = ev.to_dict()
            row["buy_close"] = buy_close
            for h in horizons:
                hi = buy_i + h
                if hi < len(k):
                    row[f"ret_{h}d"] = float(k.at[hi, "close"] / buy_close - 1.0)
                    row[f"date_{h}d"] = k.at[hi, "dt"]
                    path = k.iloc[buy_i : hi + 1]
                    row[f"max_ret_{h}d"] = float(path["close"].max() / buy_close - 1.0)
                    row[f"max_drawdown_{h}d"] = float((path["close"] / buy_close - 1.0).min())
                    row[f"above_ma120_days_{h}d"] = int((path["close"] > path["ma120"]).sum())
                else:
                    row[f"ret_{h}d"] = np.nan
                    row[f"date_{h}d"] = pd.NaT
                    row[f"max_ret_{h}d"] = np.nan
                    row[f"max_drawdown_{h}d"] = np.nan
                    row[f"above_ma120_days_{h}d"] = np.nan
            rows.append(row)
    return pd.DataFrame(rows)


def horizon_overview(panel: pd.DataFrame, horizons: List[int]) -> pd.DataFrame:
    rows = []
    for h in horizons:
        r = pd.to_numeric(panel[f"ret_{h}d"], errors="coerce").dropna()
        rows.append(
            {
                "horizon": h,
                "events": int(len(r)),
                "avg_ret": float(r.mean()) if len(r) else np.nan,
                "median_ret": float(r.median()) if len(r) else np.nan,
                "win_rate": float((r > 0).mean()) if len(r) else np.nan,
                "tail_gt10": float((r >= 0.10).mean()) if len(r) else np.nan,
                "tail_gt20": float((r >= 0.20).mean()) if len(r) else np.nan,
                "loss_lt10": float((r <= -0.10).mean()) if len(r) else np.nan,
            }
        )
    return pd.DataFrame(rows)


def return_group_feature_summary(panel: pd.DataFrame, horizons: List[int]) -> pd.DataFrame:
    rows = []
    bins = [-10, -0.10, 0, 0.10, 0.20, 10]
    labels = ["<-10%", "-10~0%", "0~10%", "10~20%", ">20%"]
    for h in horizons:
        p = panel.dropna(subset=[f"ret_{h}d"]).copy()
        p["ret_group"] = pd.cut(p[f"ret_{h}d"], bins=bins, labels=labels, right=False)
        for g, sub in p.groupby("ret_group", observed=False):
            row = {
                "horizon": h,
                "ret_group": str(g),
                "events": int(len(sub)),
                "symbols": int(sub["symbol"].nunique()),
                "avg_ret": float(sub[f"ret_{h}d"].mean()) if len(sub) else np.nan,
                "median_ret": float(sub[f"ret_{h}d"].median()) if len(sub) else np.nan,
            }
            for f in FEATURES:
                row[f"{f}_mean"] = float(sub[f].mean()) if f in sub.columns else np.nan
                row[f"{f}_median"] = float(sub[f].median()) if f in sub.columns else np.nan
            rows.append(row)
    return pd.DataFrame(rows)


def top_bottom_feature_diff(panel: pd.DataFrame, horizons: List[int]) -> pd.DataFrame:
    rows = []
    for h in horizons:
        p = panel.dropna(subset=[f"ret_{h}d"]).copy()
        if p.empty:
            continue
        q80 = p[f"ret_{h}d"].quantile(0.80)
        q20 = p[f"ret_{h}d"].quantile(0.20)
        top = p[p[f"ret_{h}d"] >= q80]
        bottom = p[p[f"ret_{h}d"] <= q20]
        for f in FEATURES:
            rows.append(
                {
                    "horizon": h,
                    "feature": f,
                    "top20_mean": float(top[f].mean()) if f in top.columns else np.nan,
                    "bottom20_mean": float(bottom[f].mean()) if f in bottom.columns else np.nan,
                    "diff": float(top[f].mean() - bottom[f].mean()) if f in top.columns else np.nan,
                    "top20_median": float(top[f].median()) if f in top.columns else np.nan,
                    "bottom20_median": float(bottom[f].median()) if f in bottom.columns else np.nan,
                }
            )
    return pd.DataFrame(rows)


def feature_bin_summary(panel: pd.DataFrame, horizons: List[int]) -> pd.DataFrame:
    specs = [
        ("close_above_p0_days", [-1, 3, 6, 8, 10], ["0-3", "4-6", "7-8", "9-10"]),
        ("ret_obs_10d", [-10, 0, 0.03, 0.08, 10], ["<0", "0-3%", "3-8%", ">8%"]),
        ("ma120_distance_min", [-10, 0.01, 0.03, 0.05, 10], ["0-1%", "1-3%", "3-5%", ">5%"]),
        ("new_high_120_count", [-1, 0, 2, 10], ["0", "1-2", "3+"]),
        ("up_down_diff", [-10, 0, 2, 4, 10], ["<=0", "1-2", "3-4", "5+"]),
    ]
    rows = []
    for feature, bins, labels in specs:
        p = panel.copy()
        p["bin"] = pd.cut(p[feature], bins=bins, labels=labels, include_lowest=True)
        for h in horizons:
            for b, sub in p.dropna(subset=[f"ret_{h}d"]).groupby("bin", observed=False):
                r = sub[f"ret_{h}d"]
                rows.append(
                    {
                        "feature": feature,
                        "bin": str(b),
                        "horizon": h,
                        "events": int(len(sub)),
                        "avg_ret": float(r.mean()) if len(r) else np.nan,
                        "median_ret": float(r.median()) if len(r) else np.nan,
                        "win_rate": float((r > 0).mean()) if len(r) else np.nan,
                        "tail_gt20": float((r >= 0.20).mean()) if len(r) else np.nan,
                        "loss_lt10": float((r <= -0.10).mean()) if len(r) else np.nan,
                    }
                )
    return pd.DataFrame(rows)


def run(events_csv: str, csv_dir: str, output_dir: str, horizons: List[int], max_events: int) -> str:
    events = pd.read_csv(events_csv)
    for c in ["break_date", "obs_end_date", "buy_date", "future_end_date"]:
        if c in events.columns:
            events[c] = pd.to_datetime(events[c], errors="coerce")
    events = events.dropna(subset=["symbol", "buy_date"]).copy()
    if max_events > 0:
        events = events.head(max_events).copy()
    panel = add_fixed_returns(events, csv_dir, horizons)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(output_dir, f"ma120_hold10_return_feature_study_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    outputs = {
        "return_panel.csv": panel,
        "horizon_overview.csv": horizon_overview(panel, horizons),
        "return_group_feature_summary.csv": return_group_feature_summary(panel, horizons),
        "top_bottom_feature_diff.csv": top_bottom_feature_diff(panel, horizons),
        "feature_bin_return_summary.csv": feature_bin_summary(panel, horizons),
    }
    for name, df in outputs.items():
        df.to_csv(os.path.join(out_dir, name), index=False, encoding="utf-8-sig")
    print(out_dir)
    print(outputs["horizon_overview.csv"].to_string(index=False))
    print("\nTop-bottom feature diff:")
    print(outputs["top_bottom_feature_diff.csv"].sort_values(["horizon", "diff"], ascending=[True, False]).to_string(index=False))
    return out_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Fixed-horizon return feature study for clean MA120 hold10 events.")
    parser.add_argument("--events-csv", required=True)
    parser.add_argument("--csv-dir", default="/Users/water/abu/data/csv")
    parser.add_argument("--output-dir", default="/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output")
    parser.add_argument("--horizons", type=int, nargs="+", default=[30, 60, 120])
    parser.add_argument("--max-events", type=int, default=0)
    args = parser.parse_args()
    run(args.events_csv, args.csv_dir, args.output_dir, args.horizons, args.max_events)


if __name__ == "__main__":
    main()
