#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Study features after a clean 10-day hold above MA120.

Research object:
- close crosses above MA120
- from breakout day p0 through p0+9, every close stays above MA120
- features are computed only inside this clean 10-day window
- labels start at p0+10, the first day after observation
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
        for c in ["open", "high", "low", "close", "volume"]:
            if c in tmp.columns:
                tmp[c] = pd.to_numeric(tmp[c], errors="coerce")
        keep = [c for c in ["dt", "open", "high", "low", "close", "volume"] if c in tmp.columns]
        frames.append(tmp[keep])
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out = out.dropna(subset=["dt", "close"]).sort_values("dt")
    out = out.drop_duplicates(subset=["dt"], keep="last").reset_index(drop=True)
    out["ma120"] = out["close"].rolling(120, min_periods=120).mean()
    out["ret1"] = out["close"].pct_change()
    out["ma120_dist"] = out["close"] / out["ma120"] - 1.0
    if {"high", "low"}.issubset(out.columns):
        prev_close = out["close"].shift(1)
        tr = pd.concat(
            [
                out["high"] - out["low"],
                (out["high"] - prev_close).abs(),
                (out["low"] - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        out["atr10"] = tr.rolling(10, min_periods=10).mean()
        out["atr60"] = tr.rolling(60, min_periods=60).mean()
    else:
        out["atr10"] = np.nan
        out["atr60"] = np.nan
    if "volume" in out.columns:
        out["vol60"] = out["volume"].rolling(60, min_periods=20).mean()
    else:
        out["volume"] = np.nan
        out["vol60"] = np.nan
    return out


def build_events(symbol: str, k: pd.DataFrame, obs_days: int) -> tuple[List[Dict[str, object]], int, int]:
    if len(k) < 121 + obs_days:
        return [], 0, 0
    above = (k["close"] > k["ma120"]).fillna(False).astype(bool)
    cross = above & (~above.shift(1, fill_value=False).astype(bool))
    cross_idxs = np.where(cross.values)[0]
    total_cross = 0
    hold10_cross = 0
    rows: List[Dict[str, object]] = []
    for i in cross_idxs:
        if i < 120:
            continue
        total_cross += 1
        obs_end = i + obs_days - 1
        buy_i = i + obs_days
        if buy_i >= len(k):
            continue
        obs = k.iloc[i : obs_end + 1].copy()
        if len(obs) < obs_days:
            continue
        if not bool((obs["close"] > obs["ma120"]).all()):
            continue
        hold10_cross += 1

        p0 = float(k.at[i, "close"])
        buy = float(k.at[buy_i, "close"])
        if p0 <= 0 or buy <= 0:
            continue

        future_end = buy_i
        while future_end < len(k) and bool(above.iloc[future_end]):
            future_end += 1
        last_above_i = future_end - 1
        if last_above_i < buy_i:
            future_days = 0
            end_close = buy
            fut = k.iloc[buy_i : buy_i + 1]
        else:
            future_days = int(last_above_i - buy_i + 1)
            end_close = float(k.at[last_above_i, "close"])
            fut = k.iloc[buy_i : last_above_i + 1]

        ret = obs["close"].pct_change().fillna(0.0)
        down = int((ret < 0).sum())
        up = int((ret > 0).sum())
        pre120_high = float(k.iloc[max(0, i - 120) : i]["close"].max()) if i > 0 else np.nan
        rows.append(
            {
                "symbol": symbol,
                "break_date": k.at[i, "dt"],
                "obs_end_date": k.at[obs_end, "dt"],
                "buy_date": k.at[buy_i, "dt"],
                "future_end_date": k.at[last_above_i, "dt"] if last_above_i >= buy_i else k.at[buy_i, "dt"],
                "is_open": bool(future_end >= len(k)),
                "close_above_p0_days": int((obs["close"] > p0).sum()),
                "ret_obs_10d": float(obs.iloc[-1]["close"] / p0 - 1.0),
                "max_drawdown_from_p0": float((obs["close"] / p0 - 1.0).min()),
                "up_days": up,
                "down_days": down,
                "up_down_diff": up - down,
                "ma120_distance_end": float(k.at[obs_end, "ma120_dist"]),
                "ma120_distance_min": float(obs["ma120_dist"].min()),
                "ma120_distance_avg": float(obs["ma120_dist"].mean()),
                "volume_ratio_10_60": float(obs["volume"].mean() / k.at[i, "vol60"])
                if pd.notna(k.at[i, "vol60"]) and k.at[i, "vol60"] > 0
                else np.nan,
                "atr10_vs_atr60": float(k.at[obs_end, "atr10"] / k.at[obs_end, "atr60"])
                if pd.notna(k.at[obs_end, "atr60"]) and k.at[obs_end, "atr60"] > 0
                else np.nan,
                "new_high_120_count": int((obs["close"] > pre120_high).sum()) if pd.notna(pre120_high) else 0,
                "future_above_ma120_days": future_days,
                "future_true60": bool(future_days >= 60),
                "future_true120": bool(future_days >= 120),
                "future_ret_until_break": float(end_close / buy - 1.0),
                "future_max_ret": float(fut["close"].max() / buy - 1.0) if not fut.empty else 0.0,
                "future_max_drawdown": float((fut["close"] / buy - 1.0).min()) if not fut.empty else 0.0,
            }
        )
    return rows, total_cross, hold10_cross


def summarize(df: pd.DataFrame, name: str) -> Dict[str, object]:
    if df.empty:
        return {"group": name, "events": 0}
    return {
        "group": name,
        "events": int(len(df)),
        "symbols": int(df["symbol"].nunique()),
        "avg_future_days": float(df["future_above_ma120_days"].mean()),
        "median_future_days": float(df["future_above_ma120_days"].median()),
        "true60_rate": float(df["future_true60"].mean()),
        "true120_rate": float(df["future_true120"].mean()),
        "avg_future_ret": float(df["future_ret_until_break"].mean()),
        "median_future_ret": float(df["future_ret_until_break"].median()),
        "win_rate": float((df["future_ret_until_break"] > 0).mean()),
        "tail_gt20": float((df["future_ret_until_break"] >= 0.20).mean()),
        "loss_lt10": float((df["future_ret_until_break"] <= -0.10).mean()),
    }


def feature_group_summary(events: pd.DataFrame) -> pd.DataFrame:
    bins = [-1, 10, 60, 120, 100000]
    labels = ["weak_0_10", "normal_11_60", "strong_61_120", "trend_120p"]
    e = events.copy()
    e["future_group"] = pd.cut(e["future_above_ma120_days"], bins=bins, labels=labels, right=True)
    features = [
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
    ]
    rows: List[Dict[str, object]] = []
    for g, sub in e.groupby("future_group", observed=False):
        row = {"future_group": str(g), "events": int(len(sub)), "symbols": int(sub["symbol"].nunique())}
        for f in features:
            row[f"{f}_mean"] = float(sub[f].mean())
            row[f"{f}_median"] = float(sub[f].median())
        rows.append(row)
    return pd.DataFrame(rows)


def bin_summary(events: pd.DataFrame, feature: str, bins: List[float], labels: List[str]) -> pd.DataFrame:
    e = events.copy()
    e["bin"] = pd.cut(e[feature], bins=bins, labels=labels, include_lowest=True)
    rows = []
    for b, sub in e.groupby("bin", observed=False):
        row = summarize(sub, str(b))
        row["feature"] = feature
        rows.append(row)
    return pd.DataFrame(rows)


def all_bin_summaries(events: pd.DataFrame) -> pd.DataFrame:
    specs = [
        ("close_above_p0_days", [-1, 3, 6, 8, 10], ["0-3", "4-6", "7-8", "9-10"]),
        ("ret_obs_10d", [-10, 0, 0.03, 0.08, 10], ["<0", "0-3%", "3-8%", ">8%"]),
        ("max_drawdown_from_p0", [-10, -0.08, -0.05, -0.03, 10], ["<-8%", "-8~-5%", "-5~-3%", ">-3%"]),
        ("ma120_distance_min", [-10, 0.01, 0.03, 0.05, 10], ["0-1%", "1-3%", "3-5%", ">5%"]),
        ("new_high_120_count", [-1, 0, 2, 10], ["0", "1-2", "3+"]),
    ]
    return pd.concat([bin_summary(events, f, b, l) for f, b, l in specs], ignore_index=True)


def rule_table(events: pd.DataFrame) -> pd.DataFrame:
    rules = {
        "base_hold10": pd.Series(True, index=events.index),
        "A_close_above_p0_ge7": events["close_above_p0_days"] >= 7,
        "B_A_ret_obs_pos": (events["close_above_p0_days"] >= 7) & (events["ret_obs_10d"] > 0),
        "C_B_dd_ge_minus5": (
            (events["close_above_p0_days"] >= 7)
            & (events["ret_obs_10d"] > 0)
            & (events["max_drawdown_from_p0"] >= -0.05)
        ),
        "D_C_newhigh_ge1": (
            (events["close_above_p0_days"] >= 7)
            & (events["ret_obs_10d"] > 0)
            & (events["max_drawdown_from_p0"] >= -0.05)
            & (events["new_high_120_count"] >= 1)
        ),
        "E_dist_min1_end3": (
            (events["close_above_p0_days"] >= 7)
            & (events["ret_obs_10d"] > 0)
            & (events["ma120_distance_min"] > 0.01)
            & (events["ma120_distance_end"] > 0.03)
        ),
    }
    rows = []
    for name, mask in rules.items():
        rows.append(summarize(events[mask], name))
    return pd.DataFrame(rows)


def stability_table(events: pd.DataFrame) -> pd.DataFrame:
    e = events.copy()
    year = pd.to_datetime(e["buy_date"]).dt.year
    e["period"] = np.select(
        [year <= 2018, (year >= 2019) & (year <= 2022), year >= 2023],
        ["2014-2018", "2019-2022", "2023-2026"],
        default="other",
    )
    rows = []
    rules = rule_table(e)["group"].tolist()
    masks = {
        "base_hold10": pd.Series(True, index=e.index),
        "A_close_above_p0_ge7": e["close_above_p0_days"] >= 7,
        "B_A_ret_obs_pos": (e["close_above_p0_days"] >= 7) & (e["ret_obs_10d"] > 0),
        "C_B_dd_ge_minus5": (
            (e["close_above_p0_days"] >= 7)
            & (e["ret_obs_10d"] > 0)
            & (e["max_drawdown_from_p0"] >= -0.05)
        ),
        "D_C_newhigh_ge1": (
            (e["close_above_p0_days"] >= 7)
            & (e["ret_obs_10d"] > 0)
            & (e["max_drawdown_from_p0"] >= -0.05)
            & (e["new_high_120_count"] >= 1)
        ),
        "E_dist_min1_end3": (
            (e["close_above_p0_days"] >= 7)
            & (e["ret_obs_10d"] > 0)
            & (e["ma120_distance_min"] > 0.01)
            & (e["ma120_distance_end"] > 0.03)
        ),
    }
    for period, sub_idx in e.groupby("period").groups.items():
        if period == "other":
            continue
        base = e.loc[sub_idx]
        base_true60 = float(base["future_true60"].mean()) if len(base) else np.nan
        for name in rules:
            sub = e.loc[sub_idx][masks[name].loc[sub_idx]]
            row = summarize(sub, name)
            row["period"] = period
            row["base_true60_rate"] = base_true60
            row["true60_alpha"] = row.get("true60_rate", np.nan) - base_true60
            rows.append(row)
    return pd.DataFrame(rows)


def future_day_distribution(events: pd.DataFrame) -> pd.DataFrame:
    e = events.copy()
    bins = [-1, 10, 20, 40, 60, 120, 240, 100000]
    labels = ["0-10", "11-20", "21-40", "41-60", "61-120", "121-240", "240+"]
    e["future_day_bin"] = pd.cut(e["future_above_ma120_days"], bins=bins, labels=labels, right=True)
    rows = []
    for b, sub in e.groupby("future_day_bin", observed=False):
        row = summarize(sub, str(b))
        row["event_ratio"] = len(sub) / len(e) if len(e) else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def run(csv_dir: str, market: str, output_dir: str, obs_days: int) -> str:
    grouped = scan_files(csv_dir, market)
    all_rows: List[Dict[str, object]] = []
    overview_rows = []
    symbols_loaded = 0
    total_cross = 0
    total_hold = 0
    for sym, paths in sorted(grouped.items()):
        k = load_symbol(paths)
        if k.empty:
            continue
        symbols_loaded += 1
        rows, crosses, holds = build_events(sym, k, obs_days)
        total_cross += crosses
        total_hold += holds
        all_rows.extend(rows)

    events = pd.DataFrame(all_rows)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(output_dir, f"ma120_hold10_feature_study_{market}_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    if events.empty:
        raise RuntimeError("No clean hold10 events generated.")

    overview_rows.append(
        {
            "market": market,
            "symbols_loaded": symbols_loaded,
            "total_cross_events": total_cross,
            "clean_hold10_events": int(len(events)),
            "clean_hold10_ratio": int(len(events)) / total_cross if total_cross else np.nan,
        }
    )
    overview = pd.DataFrame(overview_rows)
    event_summary = pd.DataFrame([summarize(events, "clean_hold10")])
    overview = pd.concat([overview, event_summary.drop(columns=["group"])], axis=1)

    outputs = {
        "overview.csv": overview,
        "clean_hold10_events.csv": events,
        "future_day_distribution.csv": future_day_distribution(events),
        "feature_group_summary.csv": feature_group_summary(events),
        "feature_bin_summary.csv": all_bin_summaries(events),
        "rule_summary.csv": rule_table(events),
        "stability_summary.csv": stability_table(events),
    }
    for name, df in outputs.items():
        df.to_csv(os.path.join(out_dir, name), index=False, encoding="utf-8-sig")

    print(out_dir)
    print("\nOverview:")
    print(overview.to_string(index=False))
    print("\nFuture day distribution:")
    print(outputs["future_day_distribution.csv"].to_string(index=False))
    print("\nRule summary:")
    print(outputs["rule_summary.csv"].to_string(index=False))
    return out_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="MA120 clean hold10 feature study.")
    parser.add_argument("--csv-dir", default="/Users/water/abu/data/csv")
    parser.add_argument("--market", choices=["a", "hk", "us"], default="a")
    parser.add_argument("--output-dir", default="/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output")
    parser.add_argument("--obs-days", type=int, default=10)
    args = parser.parse_args()
    run(args.csv_dir, args.market, args.output_dir, args.obs_days)


if __name__ == "__main__":
    main()
