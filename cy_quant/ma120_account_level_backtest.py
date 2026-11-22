#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Account-level backtest for MA120 observation-pool strategy.

This is deliberately not a parameter optimizer. It keeps the buy universe fixed
and tests whether simple position sizing, stop loss, and one add-on can form a
usable live-trading prototype.
"""

from __future__ import annotations

import argparse
import glob
import os
import warnings
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=RuntimeWarning)


@dataclass
class Position:
    ts_code: str
    entry_date: pd.Timestamp
    entry_price: float
    weight: float
    added: bool = False
    last_price: Optional[float] = None


def _scan_csv_map(csv_dir: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
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
            out[f"{num}.{market}"] = p
    return out


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
    df = pd.read_csv(path, usecols=lambda c: c in {"date", "close"})
    if "date" not in df.columns or "close" not in df.columns:
        return pd.DataFrame()
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"].astype(str), format="%Y%m%d", errors="coerce")
    out["close"] = pd.to_numeric(out["close"], errors="coerce")
    out = out.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
    out["ma20"] = out["close"].rolling(20, min_periods=20).mean()
    out["ma120"] = out["close"].rolling(120, min_periods=120).mean()
    out["ma120_slope20"] = out["ma120"] - out["ma120"].shift(20)
    return out


def _row_on_or_before(k: pd.DataFrame, date: pd.Timestamp) -> Optional[pd.Series]:
    rows = k[k["date"] <= date]
    if rows.empty:
        return None
    return rows.iloc[-1]


def _row_on_or_after(k: pd.DataFrame, date: pd.Timestamp) -> Optional[pd.Series]:
    rows = k[k["date"] >= date]
    if rows.empty:
        return None
    return rows.iloc[0]


def _market_ok(market: pd.DataFrame, date: pd.Timestamp, mode: str) -> bool:
    if mode == "off":
        return True
    r = _row_on_or_before(market, date)
    if r is None:
        return False
    if mode == "price":
        return bool(pd.notna(r["ma120"]) and r["close"] > r["ma120"])
    return bool(pd.notna(r["ma120"]) and pd.notna(r["ma120_slope20"]) and r["close"] > r["ma120"] and r["ma120_slope20"] > 0)


def _load_candidates(
    panel_csv: str,
    markets: str,
    top_n: int,
    min_close_above: int,
    min_ret_obs: float,
) -> pd.DataFrame:
    df = pd.read_csv(panel_csv)
    df = _symbol_to_ts_code(df)
    if markets:
        allow = {m.strip().upper() for m in markets.split(",") if m.strip()}
        df = df[df["ts_code"].astype(str).str.split(".").str[-1].isin(allow)].copy()
    # Avoid treating generated index rows as tradeable stocks.
    df = df[~df["ts_code"].astype(str).str.match(r"^000\d{3}\.SH$")].copy()
    if "ret_30d_from_p0" not in df.columns:
        df["ret_30d_from_p0"] = df["ret_obs_10d"] if "ret_obs_10d" in df.columns else df.get("ret_30d", np.nan)
    df["eval_date"] = pd.to_datetime(df["eval_date"], errors="coerce")
    df["buy_date"] = pd.to_datetime(df["buy_date"], errors="coerce")
    df = df.dropna(subset=["ts_code", "eval_date", "buy_date", "total_score"]).copy()
    df = df[(df["close_above_p0_days"] >= min_close_above) & (df["ret_30d_from_p0"] > min_ret_obs)].copy()
    df["eval_month"] = df["eval_date"].dt.to_period("M").dt.to_timestamp("M")
    df["rank_in_month"] = (
        df.sort_values(["eval_month", "total_score"], ascending=[True, False])
        .groupby("eval_month")["total_score"]
        .rank(method="first", ascending=False)
    )
    df = df[df["rank_in_month"] <= top_n].copy()
    return df.sort_values(["buy_date", "rank_in_month"]).reset_index(drop=True)


def _max_dd(eq: pd.Series) -> float:
    peak = eq.cummax()
    return float((eq / peak - 1.0).min()) if len(eq) else 0.0


def _summarize(daily: pd.DataFrame, trades: pd.DataFrame) -> Dict[str, object]:
    eq = daily["equity"]
    years = len(daily) / 252.0 if len(daily) else 0.0
    total = float(eq.iloc[-1] - 1.0) if len(eq) else np.nan
    cagr = float(eq.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 and len(eq) and eq.iloc[-1] > 0 else np.nan
    return {
        "days": int(len(daily)),
        "start_date": str(pd.to_datetime(daily["date"].min()).date()) if len(daily) else "",
        "end_date": str(pd.to_datetime(daily["date"].max()).date()) if len(daily) else "",
        "total_return": total,
        "cagr": cagr,
        "max_drawdown": _max_dd(eq),
        "trades": int(len(trades)),
        "win_rate": float((trades["ret"] > 0).mean()) if len(trades) else np.nan,
        "avg_trade_ret": float(trades["ret"].mean()) if len(trades) else np.nan,
        "median_trade_ret": float(trades["ret"].median()) if len(trades) else np.nan,
        "add_usage_rate": float((trades["added"] > 0).mean()) if len(trades) else np.nan,
        "avg_active_n": float(daily["active_n"].mean()) if len(daily) else np.nan,
        "max_active_n": int(daily["active_n"].max()) if len(daily) else 0,
        "avg_exposure": float(daily["exposure"].mean()) if len(daily) else np.nan,
        "max_exposure": float(daily["exposure"].max()) if len(daily) else np.nan,
    }


def run_one(
    label: str,
    panel_csv: str,
    csv_dir: str,
    output_dir: str,
    markets: str,
    index_code: str,
    top_n: int,
    min_close_above: int,
    min_ret_obs: float,
    initial_weight: float,
    total_cap: float,
    max_positions: int,
    stop_pct: float,
    add_trigger: float,
    add_scale: float,
    cost_oneway: float,
    market_filter: str,
) -> str:
    csv_map = _scan_csv_map(csv_dir)
    market_path = csv_map.get(index_code)
    if market_path is None:
        raise ValueError(f"index data not found: {index_code}")
    market = _load_kline(market_path)
    candidates = _load_candidates(panel_csv, markets, top_n, min_close_above, min_ret_obs)

    cache: Dict[str, pd.DataFrame] = {}
    for code, path in csv_map.items():
        if code == index_code:
            continue
        # Lazy load later; this keeps startup tolerable for large csv folders.
        cache[path] = pd.DataFrame()

    entry_by_date: Dict[pd.Timestamp, List[pd.Series]] = {}
    for _, row in candidates.iterrows():
        entry_by_date.setdefault(pd.Timestamp(row["buy_date"]), []).append(row)

    if candidates.empty:
        raise ValueError("no candidates after filters")
    start = pd.Timestamp(candidates["buy_date"].min())
    end = pd.Timestamp(market["date"].max())
    calendar = market[(market["date"] >= start) & (market["date"] <= end)]["date"].tolist()

    positions: Dict[str, Position] = {}
    closed: List[Dict[str, object]] = []
    daily_rows: List[Dict[str, object]] = []
    equity = 1.0

    for date in calendar:
        day_ret = 0.0
        to_close: List[tuple[str, str, float]] = []

        for code, pos in list(positions.items()):
            path = csv_map.get(code)
            if path is None:
                continue
            if cache[path].empty:
                cache[path] = _load_kline(path)
            k = cache[path]
            row = _row_on_or_before(k, date)
            if row is None:
                continue
            price = float(row["close"])
            if pos.last_price is not None and pos.last_price > 0:
                day_ret += pos.weight * (price / pos.last_price - 1.0)

            ret_from_entry = price / pos.entry_price - 1.0
            if ret_from_entry <= -stop_pct:
                to_close.append((code, "stop", price))
            elif pd.notna(row.get("ma20")) and price < float(row["ma20"]):
                to_close.append((code, "below_ma20", price))
            else:
                exposure = sum(p.weight for p in positions.values())
                add_weight = initial_weight * add_scale
                if (not pos.added) and ret_from_entry >= add_trigger and exposure + add_weight <= total_cap + 1e-12:
                    pos.weight += add_weight
                    pos.added = True
                    day_ret -= cost_oneway * add_weight
            pos.last_price = price

        for code, reason, price in to_close:
            pos = positions.pop(code, None)
            if pos is None:
                continue
            day_ret -= cost_oneway * pos.weight
            closed.append(
                {
                    "ts_code": code,
                    "entry_date": pos.entry_date,
                    "exit_date": date,
                    "entry_price": pos.entry_price,
                    "exit_price": price,
                    "ret": price / pos.entry_price - 1.0,
                    "exit_reason": reason,
                    "added": int(pos.added),
                    "final_weight": pos.weight,
                }
            )

        # Open new positions after exit checks.
        if _market_ok(market, date, market_filter):
            for row in entry_by_date.get(pd.Timestamp(date), []):
                code = str(row["ts_code"])
                if code in positions or len(positions) >= max_positions:
                    continue
                exposure = sum(p.weight for p in positions.values())
                if exposure + initial_weight > total_cap + 1e-12:
                    continue
                path = csv_map.get(code)
                if path is None:
                    continue
                if cache[path].empty:
                    cache[path] = _load_kline(path)
                k = cache[path]
                entry_row = _row_on_or_after(k, date)
                if entry_row is None:
                    continue
                price = float(entry_row["close"])
                positions[code] = Position(
                    ts_code=code,
                    entry_date=pd.Timestamp(entry_row["date"]),
                    entry_price=price,
                    weight=initial_weight,
                    last_price=price,
                )
                day_ret -= cost_oneway * initial_weight

        equity *= 1.0 + day_ret
        daily_rows.append(
            {
                "date": date,
                "day_ret": day_ret,
                "equity": equity,
                "active_n": len(positions),
                "exposure": sum(p.weight for p in positions.values()),
            }
        )

    # Mark remaining open positions to the last available price.
    for code, pos in positions.items():
        path = csv_map.get(code)
        if path is None:
            continue
        k = cache[path] if not cache[path].empty else _load_kline(path)
        row = _row_on_or_before(k, pd.Timestamp(calendar[-1]))
        if row is None:
            continue
        price = float(row["close"])
        closed.append(
            {
                "ts_code": code,
                "entry_date": pos.entry_date,
                "exit_date": pd.Timestamp(calendar[-1]),
                "entry_price": pos.entry_price,
                "exit_price": price,
                "ret": price / pos.entry_price - 1.0,
                "exit_reason": "mtm_end",
                "added": int(pos.added),
                "final_weight": pos.weight,
            }
        )

    daily = pd.DataFrame(daily_rows)
    daily["drawdown"] = daily["equity"] / daily["equity"].cummax() - 1.0
    trades = pd.DataFrame(closed)
    summary = pd.DataFrame([_summarize(daily, trades)])
    summary["label"] = label
    summary["top_n"] = top_n
    summary["total_cap"] = total_cap
    summary["max_positions"] = max_positions
    summary["initial_weight"] = initial_weight
    summary["add_trigger"] = add_trigger
    summary["add_scale"] = add_scale
    summary["market_filter"] = market_filter

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(output_dir, f"ma120_account_bt_{label}_{ts}")
    os.makedirs(out_dir, exist_ok=True)
    daily.to_csv(os.path.join(out_dir, "daily.csv"), index=False, encoding="utf-8-sig")
    trades.to_csv(os.path.join(out_dir, "trades.csv"), index=False, encoding="utf-8-sig")
    summary.to_csv(os.path.join(out_dir, "summary.csv"), index=False, encoding="utf-8-sig")
    return out_dir


def main() -> None:
    p = argparse.ArgumentParser(description="MA120 account-level backtest")
    p.add_argument("--label", required=True)
    p.add_argument("--panel-csv", required=True)
    p.add_argument("--csv-dir", required=True)
    p.add_argument("--output-dir", default="/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output")
    p.add_argument("--markets", default="SH,SZ")
    p.add_argument("--index-code", default="000001.SH")
    p.add_argument("--top-n", type=int, default=5)
    p.add_argument("--min-close-above-p0-days", type=int, default=15)
    p.add_argument("--min-ret-obs", type=float, default=0.0)
    p.add_argument("--initial-weight", type=float, default=0.05)
    p.add_argument("--total-cap", type=float, default=0.30)
    p.add_argument("--max-positions", type=int, default=5)
    p.add_argument("--stop-pct", type=float, default=0.05)
    p.add_argument("--add-trigger", type=float, default=0.08)
    p.add_argument("--add-scale", type=float, default=0.5)
    p.add_argument("--cost-oneway", type=float, default=0.0015)
    p.add_argument("--market-filter", choices=["strict", "price", "off"], default="strict")
    args = p.parse_args()

    out = run_one(
        label=args.label,
        panel_csv=args.panel_csv,
        csv_dir=args.csv_dir,
        output_dir=args.output_dir,
        markets=args.markets,
        index_code=args.index_code,
        top_n=args.top_n,
        min_close_above=args.min_close_above_p0_days,
        min_ret_obs=args.min_ret_obs,
        initial_weight=args.initial_weight,
        total_cap=args.total_cap,
        max_positions=args.max_positions,
        stop_pct=args.stop_pct,
        add_trigger=args.add_trigger,
        add_scale=args.add_scale,
        cost_oneway=args.cost_oneway,
        market_filter=args.market_filter,
    )
    print(out)


if __name__ == "__main__":
    main()
