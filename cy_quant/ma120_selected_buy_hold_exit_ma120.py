#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Backtest: pick selected events, buy on buy_date, sell when close < MA120.

流程：
1) 从 event_panel_with_345_features.csv 中按月+分数选股（可加二级门槛）
2) buy_date 买入
3) 持有到首次 close < ma120 的交易日收盘卖出；若未触发则持有到数据最后一天（按市值计入）
4) 输出交易级与组合级统计
"""

from __future__ import annotations

import argparse
import glob
import os
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


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
        if market is None:
            continue
        mp[f"{num}.{market}"] = p
    return mp


def _load_kline(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, usecols=lambda c: c in {"date", "close"})
    if "date" not in df.columns or "close" not in df.columns:
        return pd.DataFrame()
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"].astype(str), format="%Y%m%d", errors="coerce")
    out["close"] = pd.to_numeric(out["close"], errors="coerce")
    out = out.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
    out["ma120"] = out["close"].rolling(120, min_periods=120).mean()
    return out


def _pick_events(panel: pd.DataFrame, top_n: int, min_close_above: int, min_ret30: float) -> pd.DataFrame:
    df = panel.copy()
    if "ts_code" not in df.columns and "symbol" in df.columns:
        s = df["symbol"].astype(str)
        prefix = s.str[:2].str.lower()
        num = s.str[2:]
        market = prefix.map({"sh": "SH", "sz": "SZ", "bj": "BJ", "hk": "HK", "us": "US"}).fillna("")
        df["ts_code"] = np.where(market != "", num + "." + market, np.nan)

    if "ret_30d_from_p0" not in df.columns:
        if "ret_obs_10d" in df.columns:
            df["ret_30d_from_p0"] = df["ret_obs_10d"]
        else:
            df["ret_30d_from_p0"] = df.get("ret_30d", np.nan)
    df["eval_date"] = pd.to_datetime(df["eval_date"], errors="coerce")
    df["buy_date"] = pd.to_datetime(df["buy_date"], errors="coerce")
    df = df.dropna(subset=["ts_code", "eval_date", "buy_date", "total_score"]).copy()
    df = df[(df["close_above_p0_days"] >= min_close_above) & (df["ret_30d_from_p0"] > min_ret30)].copy()
    df["eval_month"] = df["eval_date"].dt.to_period("M").dt.to_timestamp("M")
    df = (
        df.sort_values(["eval_month", "total_score"], ascending=[True, False])
        .groupby("eval_month", as_index=False)
        .head(top_n)
        .copy()
    )
    return df


def _simulate_trade(k: pd.DataFrame, buy_date: pd.Timestamp, cost_oneway: float) -> Optional[Dict[str, object]]:
    sidx = k.index[k["date"] >= buy_date]
    if len(sidx) == 0:
        return None
    i0 = int(sidx[0])
    seg = k.iloc[i0:].copy()
    if len(seg) < 2:
        return None
    buy_px = float(seg.iloc[0]["close"])
    buy_dt = pd.Timestamp(seg.iloc[0]["date"])

    sell_i = None
    for j in range(1, len(seg)):
        row = seg.iloc[j]
        if pd.notna(row["ma120"]) and float(row["close"]) < float(row["ma120"]):
            sell_i = j
            break
    if sell_i is None:
        sell_i = len(seg) - 1
        exit_reason = "mtm_end"
    else:
        exit_reason = "below_ma120"

    sell_px = float(seg.iloc[sell_i]["close"])
    sell_dt = pd.Timestamp(seg.iloc[sell_i]["date"])
    gross = sell_px / buy_px - 1.0
    # open-ended mtm_end only charge buy side to更贴近当前持仓估值
    cost = cost_oneway + (cost_oneway if exit_reason == "below_ma120" else 0.0)
    net = gross - cost

    # build daily contribution (equal weight handled at portfolio aggregation)
    rows = []
    path = seg.iloc[: sell_i + 1][["date", "close"]].copy().reset_index(drop=True)
    rows.append({"date": path.iloc[0]["date"], "day_ret": -cost_oneway})
    for t in range(1, len(path)):
        r = float(path.iloc[t]["close"] / path.iloc[t - 1]["close"] - 1.0)
        rows.append({"date": path.iloc[t]["date"], "day_ret": r})
    if exit_reason == "below_ma120":
        rows[-1]["day_ret"] = float(rows[-1]["day_ret"]) - cost_oneway

    return {
        "buy_date": buy_dt,
        "sell_date": sell_dt,
        "buy_close": buy_px,
        "sell_close": sell_px,
        "hold_days": int((sell_dt - buy_dt).days),
        "gross_ret": gross,
        "net_ret": net,
        "exit_reason": exit_reason,
        "daily_path": pd.DataFrame(rows),
    }


def _max_dd(eq: pd.Series) -> float:
    peak = eq.cummax()
    dd = eq / peak - 1.0
    return float(dd.min()) if len(dd) else 0.0


def run(
    panel_csv: str,
    csv_dir: str,
    output_dir: str,
    top_n: int,
    min_close_above: int,
    min_ret30: float,
    cost_oneway: float,
    markets: str,
) -> str:
    panel = pd.read_csv(panel_csv)
    if "ts_code" not in panel.columns and "symbol" in panel.columns:
        s = panel["symbol"].astype(str)
        prefix = s.str[:2].str.lower()
        num = s.str[2:]
        market = prefix.map({"sh": "SH", "sz": "SZ", "bj": "BJ", "hk": "HK", "us": "US"}).fillna("")
        panel["ts_code"] = np.where(market != "", num + "." + market, np.nan)
    if markets:
        allow = {m.strip().upper() for m in markets.split(",") if m.strip()}
        panel = panel[panel["ts_code"].astype(str).str.split(".").str[-1].isin(allow)].copy()

    picks = _pick_events(panel, top_n=top_n, min_close_above=min_close_above, min_ret30=min_ret30)
    mp = _scan_csv_map(csv_dir)
    kcache: Dict[str, pd.DataFrame] = {}
    trade_rows: List[Dict[str, object]] = []
    daily_rows: List[pd.DataFrame] = []

    for _, r in picks.iterrows():
        ts = str(r["ts_code"])
        path = mp.get(ts)
        if path is None:
            continue
        if path not in kcache:
            kcache[path] = _load_kline(path)
        k = kcache[path]
        tr = _simulate_trade(k, pd.Timestamp(r["buy_date"]), cost_oneway=cost_oneway)
        if tr is None:
            continue
        trade_id = f"{ts}_{pd.Timestamp(r['buy_date']).date()}"
        tr_row = {
            "trade_id": trade_id,
            "ts_code": ts,
            "eval_date": pd.Timestamp(r["eval_date"]),
            "buy_date": tr["buy_date"],
            "sell_date": tr["sell_date"],
            "hold_days": tr["hold_days"],
            "gross_ret": tr["gross_ret"],
            "net_ret": tr["net_ret"],
            "exit_reason": tr["exit_reason"],
        }
        trade_rows.append(tr_row)
        d = tr["daily_path"].copy()
        d["trade_id"] = trade_id
        daily_rows.append(d)

    trades = pd.DataFrame(trade_rows)
    if trades.empty:
        raise ValueError("no trades generated")
    daily_all = pd.concat(daily_rows, ignore_index=True)
    daily = daily_all.groupby("date", as_index=False).agg(day_ret=("day_ret", "mean"), active_n=("trade_id", "nunique"))
    daily = daily.sort_values("date").reset_index(drop=True)
    daily["equity"] = (1.0 + daily["day_ret"]).cumprod()
    daily["drawdown"] = daily["equity"] / daily["equity"].cummax() - 1.0

    years = len(daily) / 252.0
    total = float(daily["equity"].iloc[-1] - 1.0)
    cagr = float(daily["equity"].iloc[-1] ** (1.0 / years) - 1.0) if years > 0 and daily["equity"].iloc[-1] > 0 else np.nan
    vol = float(daily["day_ret"].std(ddof=0) * np.sqrt(252)) if len(daily) > 1 else 0.0
    summary = pd.DataFrame(
        [
            {
                "trades": int(len(trades)),
                "start_date": str(pd.to_datetime(daily["date"].min()).date()),
                "end_date": str(pd.to_datetime(daily["date"].max()).date()),
                "years": float(years),
                "total_return": total,
                "cagr": cagr,
                "annual_vol": vol,
                "sharpe_0rf": float((daily["day_ret"].mean() * 252) / vol) if vol > 0 else np.nan,
                "max_drawdown": _max_dd(daily["equity"]),
                "trade_win_rate": float((trades["net_ret"] > 0).mean()),
                "avg_trade_ret": float(trades["net_ret"].mean()),
                "avg_hold_days": float(trades["hold_days"].mean()),
                "exit_below_ma120_ratio": float((trades["exit_reason"] == "below_ma120").mean()),
                "open_mtm_ratio": float((trades["exit_reason"] == "mtm_end").mean()),
            }
        ]
    )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(output_dir, f"ma120_selected_exit_ma120_{ts}")
    os.makedirs(out_dir, exist_ok=True)
    picks.to_csv(os.path.join(out_dir, "selected_events.csv"), index=False, encoding="utf-8-sig")
    trades.to_csv(os.path.join(out_dir, "trade_results.csv"), index=False, encoding="utf-8-sig")
    daily.to_csv(os.path.join(out_dir, "portfolio_daily_curve.csv"), index=False, encoding="utf-8-sig")
    summary.to_csv(os.path.join(out_dir, "summary.csv"), index=False, encoding="utf-8-sig")
    return out_dir


def main() -> None:
    p = argparse.ArgumentParser(description="Selected MA120 buy + exit below MA120 backtest")
    p.add_argument("--panel-csv", required=True)
    p.add_argument("--csv-dir", required=True)
    p.add_argument("--output-dir", default="/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output")
    p.add_argument("--top-n", type=int, default=30)
    p.add_argument("--min-close-above-p0-days", type=int, default=15)
    p.add_argument("--min-ret-30d-from-p0", type=float, default=0.0)
    p.add_argument("--cost-oneway", type=float, default=0.0015)
    p.add_argument("--markets", default="SH,SZ")
    args = p.parse_args()
    out = run(
        panel_csv=args.panel_csv,
        csv_dir=args.csv_dir,
        output_dir=args.output_dir,
        top_n=args.top_n,
        min_close_above=args.min_close_above_p0_days,
        min_ret30=args.min_ret_30d_from_p0,
        cost_oneway=args.cost_oneway,
        markets=args.markets,
    )
    print(out)


if __name__ == "__main__":
    main()
