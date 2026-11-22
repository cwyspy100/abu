#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Attribution test for MA120 buy rule: stop loss vs add-on.

Goal:
1) Keep buy rule fixed: MA120 candidate pool + observation window + TopN.
2) Vary only stop/add-on logic.
3) Measure whether returns mainly come from a few winners and whether add-on
   is the key to the payoff shape.
"""

from __future__ import annotations

import argparse
import glob
import math
import os
import warnings
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=RuntimeWarning)


@dataclass(frozen=True)
class Config:
    name: str
    top_n: int
    stop_mode: str  # pct | atr
    stop_value: float
    fail_days: Optional[int]
    fail_min_ret: float
    add_trigger: Optional[float]
    add_scale1: float
    add_trigger2: Optional[float]
    add_scale2: float


CONFIGS = [
    Config("stop5_noadd", 5, "pct", 0.05, None, 0.0, None, 0.0, None, 0.0),
    Config("stop5_add6_0.5", 5, "pct", 0.05, None, 0.0, 0.06, 0.5, None, 0.0),
    Config("stop5_add8_0.5", 5, "pct", 0.05, None, 0.0, 0.08, 0.5, None, 0.0),
    Config("stop5_add8_0.5_add15_0.3", 5, "pct", 0.05, None, 0.0, 0.08, 0.5, 0.15, 0.3),
    Config("stop6_add8_0.5", 5, "pct", 0.06, None, 0.0, 0.08, 0.5, None, 0.0),
    Config("atr2_noadd", 5, "atr", 2.0, None, 0.0, None, 0.0, None, 0.0),
    Config("atr2_add8_0.5", 5, "atr", 2.0, None, 0.0, 0.08, 0.5, None, 0.0),
    Config("stop5_fail10_add8_0.5", 5, "pct", 0.05, 10, 0.0, 0.08, 0.5, None, 0.0),
    Config("stop5_fail10_add8_0.5_add15_0.3", 5, "pct", 0.05, 10, 0.0, 0.08, 0.5, 0.15, 0.3),
]


def _scan_csv_map(csv_dir: str) -> Dict[str, str]:
    mp: Dict[str, str] = {}
    for p in glob.glob(os.path.join(csv_dir, "*")):
        if os.path.isdir(p):
            continue
        stem = os.path.basename(p)
        if stem.endswith(".csv"):
            stem = stem[:-4]
        if "_" not in stem:
            continue
        code_part = stem.split("_", 1)[0]
        if len(code_part) < 3:
            continue
        prefix = code_part[:2].lower()
        num = code_part[2:]
        market = {"sh": "SH", "sz": "SZ", "bj": "BJ", "hk": "HK", "us": "US"}.get(prefix)
        if market is not None:
            mp[f"{num}.{market}"] = p
    return mp


def _symbol_to_ts_code(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "ts_code" in out.columns or "symbol" not in out.columns:
        return out
    s = out["symbol"].astype(str)
    prefix = s.str[:2].str.lower()
    num = s.str[2:]
    market = prefix.map({"sh": "SH", "sz": "SZ", "bj": "BJ", "hk": "HK", "us": "US"}).fillna("")
    out["ts_code"] = np.where(market != "", num + "." + market, np.nan)
    return out


def _load_kline(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, usecols=lambda c: c in {"date", "close", "high", "low"})
    if "date" not in df.columns or "close" not in df.columns:
        return pd.DataFrame()
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"].astype(str), format="%Y%m%d", errors="coerce")
    for c in ["close", "high", "low"]:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    out = out.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
    out["ma20"] = out["close"].rolling(20, min_periods=20).mean()
    out["ma120"] = out["close"].rolling(120, min_periods=120).mean()
    out["ma120_slope20"] = out["ma120"] - out["ma120"].shift(20)
    prev_close = out["close"].shift(1)
    tr1 = out["high"] - out["low"]
    tr2 = (out["high"] - prev_close).abs()
    tr3 = (out["low"] - prev_close).abs()
    out["tr"] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    out["atr14"] = out["tr"].rolling(14, min_periods=14).mean()
    return out


def _load_market(csv_map: Dict[str, str], index_code: str) -> pd.DataFrame:
    path = csv_map.get(index_code)
    if path is None:
        raise ValueError(f"index data not found: {index_code}")
    return _load_kline(path)


def _market_ok(market: pd.DataFrame, date: pd.Timestamp) -> bool:
    rows = market[market["date"] <= date]
    if rows.empty:
        return False
    r = rows.iloc[-1]
    return bool(pd.notna(r["ma120"]) and pd.notna(r["ma120_slope20"]) and r["close"] > r["ma120"] and r["ma120_slope20"] > 0)


def _pick_events(panel_csv: str, markets: str, top_n: int, min_close_above: int, min_ret_obs: float) -> pd.DataFrame:
    df = pd.read_csv(panel_csv)
    df = _symbol_to_ts_code(df)
    if markets:
        allow = {m.strip().upper() for m in markets.split(",") if m.strip()}
        df = df[df["ts_code"].astype(str).str.split(".").str[-1].isin(allow)].copy()
    if "ret_30d_from_p0" not in df.columns:
        df["ret_30d_from_p0"] = df["ret_obs_10d"] if "ret_obs_10d" in df.columns else df.get("ret_30d", np.nan)
    df["eval_date"] = pd.to_datetime(df["eval_date"], errors="coerce")
    df["buy_date"] = pd.to_datetime(df["buy_date"], errors="coerce")
    df = df.dropna(subset=["ts_code", "eval_date", "buy_date", "total_score"]).copy()
    df = df[(df["close_above_p0_days"] >= min_close_above) & (df["ret_30d_from_p0"] > min_ret_obs)].copy()
    df["eval_month"] = df["eval_date"].dt.to_period("M").dt.to_timestamp("M")
    return (
        df.sort_values(["eval_month", "total_score"], ascending=[True, False])
        .groupby("eval_month", as_index=False)
        .head(top_n)
        .sort_values(["buy_date", "total_score"], ascending=[True, False])
        .copy()
    )


def _simulate_trade(k: pd.DataFrame, buy_date: pd.Timestamp, cfg: Config, cost_oneway: float) -> Optional[Dict[str, object]]:
    start = k.index[k["date"] >= buy_date]
    if len(start) == 0:
        return None
    seg = k.iloc[int(start[0]) :].copy().reset_index(drop=True)
    if len(seg) < 2:
        return None
    buy_px = float(seg.iloc[0]["close"])
    atr0 = float(seg.iloc[0]["atr14"]) if pd.notna(seg.iloc[0].get("atr14")) else np.nan
    stop_px = None
    if cfg.stop_mode == "pct":
        stop_px = buy_px * (1.0 - cfg.stop_value)
    elif cfg.stop_mode == "atr" and pd.notna(atr0):
        stop_px = buy_px - cfg.stop_value * atr0
    else:
        stop_px = buy_px * 0.95

    pos = 1.0
    added1 = False
    added2 = False
    rows: List[Dict[str, object]] = [{"date": seg.iloc[0]["date"], "day_ret": -cost_oneway * pos, "position": pos}]
    add_events = 0
    exit_reason = "mtm_end"
    exit_i = len(seg) - 1

    for i in range(1, len(seg)):
        row = seg.iloc[i]
        prev = seg.iloc[i - 1]
        ret_d = float(row["close"] / prev["close"] - 1.0)
        rows.append({"date": row["date"], "day_ret": pos * ret_d, "position": pos})
        ret_from_buy = float(row["close"] / buy_px - 1.0)

        if stop_px is not None and float(row["close"]) <= stop_px:
            exit_reason = "stop_loss"
            exit_i = i
            rows[-1]["day_ret"] = float(rows[-1]["day_ret"]) - cost_oneway * pos
            break

        if pd.notna(row.get("ma20")) and float(row["close"]) < float(row["ma20"]):
            exit_reason = "below_ma20"
            exit_i = i
            rows[-1]["day_ret"] = float(rows[-1]["day_ret"]) - cost_oneway * pos
            break

        if cfg.fail_days is not None and i >= cfg.fail_days and ret_from_buy <= cfg.fail_min_ret:
            exit_reason = f"fail{cfg.fail_days}"
            exit_i = i
            rows[-1]["day_ret"] = float(rows[-1]["day_ret"]) - cost_oneway * pos
            break

        if cfg.add_trigger is not None and (not added1) and ret_from_buy >= cfg.add_trigger:
            pos += cfg.add_scale1
            added1 = True
            add_events += 1
            rows[-1]["day_ret"] = float(rows[-1]["day_ret"]) - cost_oneway * cfg.add_scale1
            rows[-1]["position"] = pos

        if cfg.add_trigger2 is not None and added1 and (not added2) and ret_from_buy >= cfg.add_trigger2:
            pos += cfg.add_scale2
            added2 = True
            add_events += 1
            rows[-1]["day_ret"] = float(rows[-1]["day_ret"]) - cost_oneway * cfg.add_scale2
            rows[-1]["position"] = pos

    if exit_reason == "mtm_end":
        rows[-1]["day_ret"] = float(rows[-1]["day_ret"]) - cost_oneway * pos

    path = pd.DataFrame(rows[: exit_i + 1])
    net_ret = float((1.0 + path["day_ret"]).prod() - 1.0)
    return {
        "buy_date": pd.Timestamp(seg.iloc[0]["date"]),
        "sell_date": pd.Timestamp(seg.iloc[exit_i]["date"]),
        "hold_days": int((pd.Timestamp(seg.iloc[exit_i]["date"]) - pd.Timestamp(seg.iloc[0]["date"])).days),
        "net_ret": net_ret,
        "exit_reason": exit_reason,
        "add_events": add_events,
        "max_position": float(path["position"].max()),
        "daily_path": path,
    }


def _max_dd(eq: pd.Series) -> float:
    peak = eq.cummax()
    return float((eq / peak - 1.0).min()) if len(eq) else 0.0


def _build_portfolio(trades_df: pd.DataFrame, daily_paths: List[pd.DataFrame]) -> pd.DataFrame:
    if trades_df.empty:
        return pd.DataFrame()
    all_daily = pd.concat(daily_paths, ignore_index=True)
    daily = all_daily.groupby("date", as_index=False).agg(day_ret=("day_ret", "mean"), active_n=("trade_id", "nunique"))
    daily = daily.sort_values("date").reset_index(drop=True)
    daily["equity"] = (1.0 + daily["day_ret"]).cumprod()
    daily["drawdown"] = daily["equity"] / daily["equity"].cummax() - 1.0
    return daily


def _winner_concentration(trades: pd.DataFrame) -> tuple[float, float]:
    pos = trades[trades["net_ret"] > 0].sort_values("net_ret", ascending=False).copy()
    total_profit = float(pos["net_ret"].sum())
    if total_profit <= 0 or pos.empty:
        return np.nan, np.nan
    n_top10 = max(1, math.ceil(len(pos) * 0.1))
    top10_share = float(pos.head(n_top10)["net_ret"].sum() / total_profit)
    n_top20 = max(1, math.ceil(len(pos) * 0.2))
    top20_share = float(pos.head(n_top20)["net_ret"].sum() / total_profit)
    return top10_share, top20_share


def _summarize(name: str, trades: pd.DataFrame, daily: pd.DataFrame) -> Dict[str, object]:
    years = len(daily) / 252.0 if not daily.empty else 0.0
    eq = daily["equity"] if not daily.empty else pd.Series(dtype=float)
    top10_share, top20_share = _winner_concentration(trades)
    return {
        "config": name,
        "trades": int(len(trades)),
        "years": float(years),
        "total_return": float(eq.iloc[-1] - 1.0) if len(eq) else np.nan,
        "cagr": float(eq.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 and len(eq) and eq.iloc[-1] > 0 else np.nan,
        "max_drawdown": _max_dd(eq) if len(eq) else np.nan,
        "trade_win_rate": float((trades["net_ret"] > 0).mean()) if len(trades) else np.nan,
        "avg_trade_ret": float(trades["net_ret"].mean()) if len(trades) else np.nan,
        "median_trade_ret": float(trades["net_ret"].median()) if len(trades) else np.nan,
        "avg_hold_days": float(trades["hold_days"].mean()) if len(trades) else np.nan,
        "avg_add_events": float(trades["add_events"].mean()) if len(trades) else np.nan,
        "add_usage_rate": float((trades["add_events"] > 0).mean()) if len(trades) else np.nan,
        "avg_max_position": float(trades["max_position"].mean()) if len(trades) else np.nan,
        "winner_top10_share": top10_share,
        "winner_top20_share": top20_share,
        "avg_active_n": float(daily["active_n"].mean()) if len(daily) else np.nan,
        "max_active_n": int(daily["active_n"].max()) if len(daily) else np.nan,
    }


def run_dataset(
    label: str,
    panel_csv: str,
    csv_dir: str,
    output_dir: str,
    markets: str,
    index_code: str,
    min_close_above: int,
    min_ret_obs: float,
    cost_oneway: float,
) -> str:
    csv_map = _scan_csv_map(csv_dir)
    market = _load_market(csv_map, index_code)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(output_dir, f"ma120_stop_addon_attr_{label}_{ts}")
    os.makedirs(out_dir, exist_ok=True)

    summaries: List[Dict[str, object]] = []
    for cfg in CONFIGS:
        picks = _pick_events(panel_csv, markets=markets, top_n=cfg.top_n, min_close_above=min_close_above, min_ret_obs=min_ret_obs)
        kcache: Dict[str, pd.DataFrame] = {}
        open_until: Dict[str, pd.Timestamp] = {}
        trades: List[Dict[str, object]] = []
        daily_paths: List[pd.DataFrame] = []
        for _, r in picks.iterrows():
            ts_code = str(r["ts_code"])
            buy_date = pd.Timestamp(r["buy_date"])
            if not _market_ok(market, buy_date):
                continue
            if ts_code in open_until and buy_date <= open_until[ts_code]:
                continue
            path = csv_map.get(ts_code)
            if path is None:
                continue
            if path not in kcache:
                kcache[path] = _load_kline(path)
            tr = _simulate_trade(kcache[path], buy_date, cfg=cfg, cost_oneway=cost_oneway)
            if tr is None:
                continue
            open_until[ts_code] = tr["sell_date"]
            trade_id = f"{cfg.name}_{ts_code}_{buy_date.date()}"
            trades.append(
                {
                    "trade_id": trade_id,
                    "ts_code": ts_code,
                    "buy_date": tr["buy_date"],
                    "sell_date": tr["sell_date"],
                    "hold_days": tr["hold_days"],
                    "net_ret": tr["net_ret"],
                    "exit_reason": tr["exit_reason"],
                    "add_events": tr["add_events"],
                    "max_position": tr["max_position"],
                }
            )
            d = tr["daily_path"].copy()
            d["trade_id"] = trade_id
            daily_paths.append(d)

        trades_df = pd.DataFrame(trades)
        daily = _build_portfolio(trades_df, daily_paths) if len(trades_df) else pd.DataFrame()
        if len(trades_df):
            trades_df.to_csv(os.path.join(out_dir, f"trades_{cfg.name}.csv"), index=False, encoding="utf-8-sig")
        if len(daily):
            daily.to_csv(os.path.join(out_dir, f"daily_{cfg.name}.csv"), index=False, encoding="utf-8-sig")
        summaries.append(_summarize(cfg.name, trades_df, daily))

    summary = pd.DataFrame(summaries).sort_values(["max_drawdown", "cagr"], ascending=[False, False])
    summary.to_csv(os.path.join(out_dir, "summary.csv"), index=False, encoding="utf-8-sig")
    return out_dir


def main() -> None:
    p = argparse.ArgumentParser(description="MA120 stop/add-on attribution")
    p.add_argument("--label", required=True)
    p.add_argument("--panel-csv", required=True)
    p.add_argument("--csv-dir", required=True)
    p.add_argument("--output-dir", default="/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output")
    p.add_argument("--markets", default="SH,SZ")
    p.add_argument("--index-code", default="000001.SH")
    p.add_argument("--min-close-above-p0-days", type=int, default=15)
    p.add_argument("--min-ret-obs", type=float, default=0.0)
    p.add_argument("--cost-oneway", type=float, default=0.0015)
    args = p.parse_args()
    out = run_dataset(
        label=args.label,
        panel_csv=args.panel_csv,
        csv_dir=args.csv_dir,
        output_dir=args.output_dir,
        markets=args.markets,
        index_code=args.index_code,
        min_close_above=args.min_close_above_p0_days,
        min_ret_obs=args.min_ret_obs,
        cost_oneway=args.cost_oneway,
    )
    print(out)


if __name__ == "__main__":
    main()
