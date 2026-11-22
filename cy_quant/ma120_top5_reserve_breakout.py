#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Top5 initial buy + Top6-20 reserve breakout + one add-on.

Rules:
- Fixed buy universe: MA120 candidate panel after observation window.
- Top5 of each month: buy on buy_date.
- Rank 6-20: enter later only after price breaks observation-window high.
- Market filter: index close > MA120 and MA120 slope20 > 0.
- Risk exit: stop loss at -5% or close < MA20.
- Add-on once: if trade return reaches +8%, add 0.5x initial position.
"""

from __future__ import annotations

import argparse
import glob
import os
import warnings
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=RuntimeWarning)


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


def _load_panel(panel_csv: str, markets: str, min_close_above: int, min_ret_obs: float, top_reserve: int) -> pd.DataFrame:
    df = pd.read_csv(panel_csv)
    df = _symbol_to_ts_code(df)
    if markets:
        allow = {m.strip().upper() for m in markets.split(",") if m.strip()}
        df = df[df["ts_code"].astype(str).str.split(".").str[-1].isin(allow)].copy()
    if "ret_30d_from_p0" not in df.columns:
        df["ret_30d_from_p0"] = df["ret_obs_10d"] if "ret_obs_10d" in df.columns else df.get("ret_30d", np.nan)
    df["p0_date"] = pd.to_datetime(df["p0_date"], errors="coerce")
    df["eval_date"] = pd.to_datetime(df["eval_date"], errors="coerce")
    df["buy_date"] = pd.to_datetime(df["buy_date"], errors="coerce")
    df = df.dropna(subset=["ts_code", "p0_date", "eval_date", "buy_date", "total_score"]).copy()
    df = df[(df["close_above_p0_days"] >= min_close_above) & (df["ret_30d_from_p0"] > min_ret_obs)].copy()
    df["eval_month"] = df["eval_date"].dt.to_period("M").dt.to_timestamp("M")
    df["rank_in_month"] = (
        df.sort_values(["eval_month", "total_score"], ascending=[True, False])
        .groupby("eval_month")["total_score"]
        .rank(method="first", ascending=False)
    )
    df = df[df["rank_in_month"] <= top_reserve].copy()
    df["bucket"] = np.where(df["rank_in_month"] <= 5, "top5", "reserve")
    return df.sort_values(["buy_date", "rank_in_month"]).reset_index(drop=True)


def _obs_high(k: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> Optional[float]:
    seg = k[(k["date"] >= start) & (k["date"] <= end)]
    if seg.empty:
        return None
    return float(seg["close"].max())


def _find_reserve_entry(
    k: pd.DataFrame,
    buy_date: pd.Timestamp,
    obs_high: float,
    breakout_buffer: float,
) -> Optional[pd.Timestamp]:
    seg = k[k["date"] >= buy_date]
    if seg.empty:
        return None
    trigger = obs_high * (1.0 + breakout_buffer)
    hit = seg[seg["close"] > trigger]
    if hit.empty:
        return None
    return pd.Timestamp(hit.iloc[0]["date"])


def _simulate_trade(k: pd.DataFrame, entry_date: pd.Timestamp, stop_pct: float, add_trigger: float, add_scale: float, cost_oneway: float) -> Optional[Dict[str, object]]:
    start = k.index[k["date"] >= entry_date]
    if len(start) == 0:
        return None
    seg = k.iloc[int(start[0]) :].copy().reset_index(drop=True)
    if len(seg) < 2:
        return None

    buy_px = float(seg.iloc[0]["close"])
    stop_px = buy_px * (1.0 - stop_pct)
    pos = 1.0
    added = False
    rows: List[Dict[str, object]] = [{"date": seg.iloc[0]["date"], "day_ret": -cost_oneway * pos, "position": pos}]
    exit_reason = "mtm_end"
    exit_i = len(seg) - 1

    for i in range(1, len(seg)):
        row = seg.iloc[i]
        prev = seg.iloc[i - 1]
        ret_d = float(row["close"] / prev["close"] - 1.0)
        rows.append({"date": row["date"], "day_ret": pos * ret_d, "position": pos})
        ret_from_buy = float(row["close"] / buy_px - 1.0)

        if float(row["close"]) <= stop_px:
            exit_reason = "stop5"
            exit_i = i
            rows[-1]["day_ret"] = float(rows[-1]["day_ret"]) - cost_oneway * pos
            break

        if pd.notna(row.get("ma20")) and float(row["close"]) < float(row["ma20"]):
            exit_reason = "below_ma20"
            exit_i = i
            rows[-1]["day_ret"] = float(rows[-1]["day_ret"]) - cost_oneway * pos
            break

        if (not added) and ret_from_buy >= add_trigger:
            pos += add_scale
            added = True
            rows[-1]["day_ret"] = float(rows[-1]["day_ret"]) - cost_oneway * add_scale
            rows[-1]["position"] = pos

    if exit_reason == "mtm_end":
        rows[-1]["day_ret"] = float(rows[-1]["day_ret"]) - cost_oneway * pos

    path = pd.DataFrame(rows[: exit_i + 1])
    return {
        "entry_date": pd.Timestamp(seg.iloc[0]["date"]),
        "exit_date": pd.Timestamp(seg.iloc[exit_i]["date"]),
        "hold_days": int((pd.Timestamp(seg.iloc[exit_i]["date"]) - pd.Timestamp(seg.iloc[0]["date"])).days),
        "net_ret": float((1.0 + path["day_ret"]).prod() - 1.0),
        "exit_reason": exit_reason,
        "added": int(added),
        "max_position": float(path["position"].max()),
        "daily_path": path,
    }


def _max_dd(eq: pd.Series) -> float:
    peak = eq.cummax()
    return float((eq / peak - 1.0).min()) if len(eq) else 0.0


def _winner_share(trades: pd.DataFrame) -> float:
    pos = trades[trades["net_ret"] > 0].sort_values("net_ret", ascending=False)
    if pos.empty:
        return np.nan
    total = float(pos["net_ret"].sum())
    if total <= 0:
        return np.nan
    n = max(1, int(np.ceil(len(pos) * 0.1)))
    return float(pos.head(n)["net_ret"].sum() / total)


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
    top_reserve: int,
    max_positions: int,
    stop_pct: float,
    add_trigger: float,
    add_scale: float,
    breakout_buffer: float,
) -> str:
    csv_map = _scan_csv_map(csv_dir)
    market = _load_market(csv_map, index_code)
    panel = _load_panel(panel_csv, markets, min_close_above, min_ret_obs, top_reserve=top_reserve)
    kcache: Dict[str, pd.DataFrame] = {}

    trade_rows: List[Dict[str, object]] = []
    daily_paths: List[pd.DataFrame] = []
    open_until: Dict[str, pd.Timestamp] = {}
    active_trades: List[Dict[str, object]] = []

    for _, r in panel.iterrows():
        ts_code = str(r["ts_code"])
        path = csv_map.get(ts_code)
        if path is None:
            continue
        if path not in kcache:
            kcache[path] = _load_kline(path)
        k = kcache[path]

        obs_high = _obs_high(k, pd.Timestamp(r["p0_date"]), pd.Timestamp(r["eval_date"]))
        if obs_high is None:
            continue

        if r["bucket"] == "top5":
            entry_date = pd.Timestamp(r["buy_date"])
        else:
            entry_date = _find_reserve_entry(
                k,
                pd.Timestamp(r["buy_date"]),
                obs_high,
                breakout_buffer=breakout_buffer,
            )
            if entry_date is None:
                continue

        if not _market_ok(market, entry_date):
            continue
        if ts_code in open_until and entry_date <= open_until[ts_code]:
            continue

        active_trades = [x for x in active_trades if x["exit_date"] >= entry_date]
        if len(active_trades) >= max_positions:
            continue

        tr = _simulate_trade(k, entry_date, stop_pct=stop_pct, add_trigger=add_trigger, add_scale=add_scale, cost_oneway=cost_oneway)
        if tr is None:
            continue

        open_until[ts_code] = tr["exit_date"]
        active_trades.append({"ts_code": ts_code, "exit_date": tr["exit_date"]})
        trade_id = f"{label}_{ts_code}_{entry_date.date()}"
        trade_rows.append(
            {
                "trade_id": trade_id,
                "ts_code": ts_code,
                "bucket": r["bucket"],
                "rank_in_month": int(r["rank_in_month"]),
                "obs_high": obs_high,
                "entry_date": tr["entry_date"],
                "exit_date": tr["exit_date"],
                "hold_days": tr["hold_days"],
                "net_ret": tr["net_ret"],
                "exit_reason": tr["exit_reason"],
                "added": tr["added"],
                "max_position": tr["max_position"],
            }
        )
        d = tr["daily_path"].copy()
        d["trade_id"] = trade_id
        daily_paths.append(d)

    trades = pd.DataFrame(trade_rows)
    daily = pd.DataFrame()
    if not trades.empty:
        all_daily = pd.concat(daily_paths, ignore_index=True)
        daily = all_daily.groupby("date", as_index=False).agg(day_ret=("day_ret", "mean"), active_n=("trade_id", "nunique"))
        daily = daily.sort_values("date").reset_index(drop=True)
        daily["equity"] = (1.0 + daily["day_ret"]).cumprod()
        daily["drawdown"] = daily["equity"] / daily["equity"].cummax() - 1.0

    years = len(daily) / 252.0 if not daily.empty else 0.0
    summary = pd.DataFrame(
        [
            {
                "label": label,
                "breakout_buffer": breakout_buffer,
                "trades": int(len(trades)),
                "reserve_trade_ratio": float((trades["bucket"] == "reserve").mean()) if len(trades) else np.nan,
                "add_usage_rate": float((trades["added"] > 0).mean()) if len(trades) else np.nan,
                "winner_top10_share": _winner_share(trades) if len(trades) else np.nan,
                "total_return": float(daily["equity"].iloc[-1] - 1.0) if not daily.empty else np.nan,
                "cagr": float(daily["equity"].iloc[-1] ** (1.0 / years) - 1.0) if years > 0 and not daily.empty and daily["equity"].iloc[-1] > 0 else np.nan,
                "max_drawdown": _max_dd(daily["equity"]) if not daily.empty else np.nan,
                "trade_win_rate": float((trades["net_ret"] > 0).mean()) if len(trades) else np.nan,
                "avg_trade_ret": float(trades["net_ret"].mean()) if len(trades) else np.nan,
                "median_trade_ret": float(trades["net_ret"].median()) if len(trades) else np.nan,
                "avg_hold_days": float(trades["hold_days"].mean()) if len(trades) else np.nan,
                "avg_active_n": float(daily["active_n"].mean()) if not daily.empty else np.nan,
                "max_active_n": int(daily["active_n"].max()) if not daily.empty else np.nan,
            }
        ]
    )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(output_dir, f"ma120_top5_reserve_breakout_{label}_{ts}")
    os.makedirs(out_dir, exist_ok=True)
    trades.to_csv(os.path.join(out_dir, "trades.csv"), index=False, encoding="utf-8-sig")
    daily.to_csv(os.path.join(out_dir, "daily.csv"), index=False, encoding="utf-8-sig")
    summary.to_csv(os.path.join(out_dir, "summary.csv"), index=False, encoding="utf-8-sig")
    return out_dir


def main() -> None:
    p = argparse.ArgumentParser(description="Top5 initial + reserve breakout backtest")
    p.add_argument("--label", required=True)
    p.add_argument("--panel-csv", required=True)
    p.add_argument("--csv-dir", required=True)
    p.add_argument("--output-dir", default="/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output")
    p.add_argument("--markets", default="SH,SZ")
    p.add_argument("--index-code", default="000001.SH")
    p.add_argument("--min-close-above-p0-days", type=int, default=15)
    p.add_argument("--min-ret-obs", type=float, default=0.0)
    p.add_argument("--cost-oneway", type=float, default=0.0015)
    p.add_argument("--top-reserve", type=int, default=20)
    p.add_argument("--max-positions", type=int, default=10)
    p.add_argument("--stop-pct", type=float, default=0.05)
    p.add_argument("--add-trigger", type=float, default=0.08)
    p.add_argument("--add-scale", type=float, default=0.5)
    p.add_argument("--breakout-buffer", type=float, default=0.0)
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
        top_reserve=args.top_reserve,
        max_positions=args.max_positions,
        stop_pct=args.stop_pct,
        add_trigger=args.add_trigger,
        add_scale=args.add_scale,
        breakout_buffer=args.breakout_buffer,
    )
    print(out)


if __name__ == "__main__":
    main()
