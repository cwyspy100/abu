#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Small practical grid for MA120 selected stocks.

Research question:
- After MA120 candidate selection, can simple market/risk filters make the
  system closer to live trading?

This intentionally uses a small, plain set of rules instead of a wide optimizer.
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


@dataclass(frozen=True)
class Rule:
    name: str
    use_market_filter: bool
    exit_ma: int
    stop_loss: Optional[float] = None
    fail_days: Optional[int] = None
    fail_min_ret: float = 0.0


RULES = [
    Rule("base_exit_ma120", False, 120),
    Rule("market_exit_ma120", True, 120),
    Rule("market_stop8_exit_ma120", True, 120, stop_loss=-0.08),
    Rule("market_stop5_exit_ma20", True, 20, stop_loss=-0.05),
    Rule("market_stop6_exit_ma20", True, 20, stop_loss=-0.06),
    Rule("market_stop8_exit_ma20", True, 20, stop_loss=-0.08),
    Rule("market_stop5_fail5_exit_ma20", True, 20, stop_loss=-0.05, fail_days=5),
    Rule("market_stop6_fail10_exit_ma20", True, 20, stop_loss=-0.06, fail_days=10),
    Rule("market_stop8_fail10_exit_ma20", True, 20, stop_loss=-0.08, fail_days=10),
    Rule("market_stop10_fail20_exit_ma20", True, 20, stop_loss=-0.10, fail_days=20),
    Rule("market_stop5_exit_ma10", True, 10, stop_loss=-0.05),
    Rule("market_stop5_fail5_exit_ma10", True, 10, stop_loss=-0.05, fail_days=5),
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
        if market is None:
            continue
        mp[f"{num}.{market}"] = p
    return mp


def _symbol_to_ts_code(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "ts_code" in out.columns:
        return out
    if "symbol" not in out.columns:
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


def _pick_events(
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
    if "ret_30d_from_p0" not in df.columns:
        if "ret_obs_10d" in df.columns:
            df["ret_30d_from_p0"] = df["ret_obs_10d"]
        else:
            df["ret_30d_from_p0"] = df.get("ret_30d", np.nan)
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


def _simulate_trade(k: pd.DataFrame, buy_date: pd.Timestamp, rule: Rule, cost_oneway: float) -> Optional[Dict[str, object]]:
    start = k.index[k["date"] >= buy_date]
    if len(start) == 0:
        return None
    i0 = int(start[0])
    seg = k.iloc[i0:].copy().reset_index(drop=True)
    if len(seg) < 2:
        return None
    buy_px = float(seg.iloc[0]["close"])
    rows = [{"date": seg.iloc[0]["date"], "day_ret": -cost_oneway}]
    exit_i = len(seg) - 1
    reason = "mtm_end"

    for i in range(1, len(seg)):
        row = seg.iloc[i]
        prev = seg.iloc[i - 1]
        day_ret = float(row["close"] / prev["close"] - 1.0)
        rows.append({"date": row["date"], "day_ret": day_ret})
        ret_from_buy = float(row["close"] / buy_px - 1.0)

        if rule.stop_loss is not None and ret_from_buy <= rule.stop_loss:
            exit_i = i
            reason = "stop_loss"
            break

        ma_col = f"ma{rule.exit_ma}"
        if pd.notna(row.get(ma_col)) and float(row["close"]) < float(row[ma_col]):
            exit_i = i
            reason = f"below_ma{rule.exit_ma}"
            break

        if rule.fail_days is not None and i >= rule.fail_days and ret_from_buy <= rule.fail_min_ret:
            exit_i = i
            reason = f"fail{rule.fail_days}"
            break

    path = pd.DataFrame(rows[: exit_i + 1])
    if reason != "mtm_end":
        path.loc[path.index[-1], "day_ret"] = float(path.iloc[-1]["day_ret"]) - cost_oneway
    sell_px = float(seg.iloc[exit_i]["close"])
    gross = sell_px / buy_px - 1.0
    net = float((1.0 + path["day_ret"]).prod() - 1.0)
    return {
        "buy_date": pd.Timestamp(seg.iloc[0]["date"]),
        "sell_date": pd.Timestamp(seg.iloc[exit_i]["date"]),
        "hold_days": int((pd.Timestamp(seg.iloc[exit_i]["date"]) - pd.Timestamp(seg.iloc[0]["date"])).days),
        "gross_ret": gross,
        "net_ret": net,
        "exit_reason": reason,
        "daily_path": path,
    }


def _max_dd(eq: pd.Series) -> float:
    peak = eq.cummax()
    dd = eq / peak - 1.0
    return float(dd.min()) if len(dd) else 0.0


def _summarize(trades: pd.DataFrame, daily: pd.DataFrame) -> Dict[str, object]:
    years = len(daily) / 252.0
    equity = daily["equity"]
    total = float(equity.iloc[-1] - 1.0)
    cagr = float(equity.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 and equity.iloc[-1] > 0 else np.nan
    vol = float(daily["day_ret"].std(ddof=0) * np.sqrt(252)) if len(daily) > 1 else 0.0
    return {
        "trades": int(len(trades)),
        "start_date": str(pd.to_datetime(daily["date"].min()).date()),
        "end_date": str(pd.to_datetime(daily["date"].max()).date()),
        "years": float(years),
        "total_return": total,
        "cagr": cagr,
        "annual_vol": vol,
        "sharpe_0rf": float((daily["day_ret"].mean() * 252) / vol) if vol > 0 else np.nan,
        "max_drawdown": _max_dd(equity),
        "trade_win_rate": float((trades["net_ret"] > 0).mean()),
        "avg_trade_ret": float(trades["net_ret"].mean()),
        "median_trade_ret": float(trades["net_ret"].median()),
        "avg_hold_days": float(trades["hold_days"].mean()),
        "avg_active_n": float(daily["active_n"].mean()),
        "max_active_n": int(daily["active_n"].max()),
    }


def _run_one_rule(
    picks: pd.DataFrame,
    csv_map: Dict[str, str],
    market: pd.DataFrame,
    rule: Rule,
    cost_oneway: float,
    no_overlap_symbol: bool,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    kcache: Dict[str, pd.DataFrame] = {}
    open_until: Dict[str, pd.Timestamp] = {}
    trades: List[Dict[str, object]] = []
    daily_rows: List[pd.DataFrame] = []

    for _, r in picks.iterrows():
        ts = str(r["ts_code"])
        buy_date = pd.Timestamp(r["buy_date"])
        if no_overlap_symbol and ts in open_until and buy_date <= open_until[ts]:
            continue
        if rule.use_market_filter and not _market_ok(market, buy_date):
            continue
        path = csv_map.get(ts)
        if path is None:
            continue
        if path not in kcache:
            kcache[path] = _load_kline(path)
        tr = _simulate_trade(kcache[path], buy_date, rule=rule, cost_oneway=cost_oneway)
        if tr is None:
            continue
        trade_id = f"{rule.name}_{ts}_{buy_date.date()}"
        open_until[ts] = tr["sell_date"]
        trades.append(
            {
                "trade_id": trade_id,
                "rule": rule.name,
                "ts_code": ts,
                "eval_date": r["eval_date"],
                "buy_date": tr["buy_date"],
                "sell_date": tr["sell_date"],
                "hold_days": tr["hold_days"],
                "gross_ret": tr["gross_ret"],
                "net_ret": tr["net_ret"],
                "exit_reason": tr["exit_reason"],
            }
        )
        d = tr["daily_path"].copy()
        d["trade_id"] = trade_id
        daily_rows.append(d)

    trades_df = pd.DataFrame(trades)
    if trades_df.empty:
        return trades_df, pd.DataFrame()
    all_daily = pd.concat(daily_rows, ignore_index=True)
    daily = all_daily.groupby("date", as_index=False).agg(day_ret=("day_ret", "mean"), active_n=("trade_id", "nunique"))
    daily = daily.sort_values("date").reset_index(drop=True)
    daily["equity"] = (1.0 + daily["day_ret"]).cumprod()
    daily["drawdown"] = daily["equity"] / daily["equity"].cummax() - 1.0
    return trades_df, daily


def run_dataset(
    label: str,
    panel_csv: str,
    csv_dir: str,
    output_root: str,
    top_ns: List[int],
    min_close_above: int,
    min_ret_obs: float,
    cost_oneway: float,
    markets: str,
    index_code: str,
    no_overlap_symbol: bool,
) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(output_root, f"ma120_practical_grid_{label}_{ts}")
    os.makedirs(out_dir, exist_ok=True)
    csv_map = _scan_csv_map(csv_dir)
    market = _load_market(csv_map, index_code)
    summary_rows: List[Dict[str, object]] = []

    for top_n in top_ns:
        picks = _pick_events(panel_csv, markets=markets, top_n=top_n, min_close_above=min_close_above, min_ret_obs=min_ret_obs)
        picks.to_csv(os.path.join(out_dir, f"selected_events_top{top_n}.csv"), index=False, encoding="utf-8-sig")
        for rule in RULES:
            trades, daily = _run_one_rule(
                picks=picks,
                csv_map=csv_map,
                market=market,
                rule=rule,
                cost_oneway=cost_oneway,
                no_overlap_symbol=no_overlap_symbol,
            )
            if trades.empty or daily.empty:
                continue
            trades.to_csv(os.path.join(out_dir, f"trades_top{top_n}_{rule.name}.csv"), index=False, encoding="utf-8-sig")
            daily.to_csv(os.path.join(out_dir, f"daily_top{top_n}_{rule.name}.csv"), index=False, encoding="utf-8-sig")
            row = _summarize(trades, daily)
            row.update(
                {
                    "dataset": label,
                    "top_n": top_n,
                    "rule": rule.name,
                    "use_market_filter": rule.use_market_filter,
                    "exit_ma": rule.exit_ma,
                    "stop_loss": rule.stop_loss,
                    "fail_days": rule.fail_days,
                }
            )
            summary_rows.append(row)

    summary = pd.DataFrame(summary_rows)
    if not summary.empty:
        summary = summary.sort_values(["max_drawdown", "cagr"], ascending=[False, False])
    summary.to_csv(os.path.join(out_dir, "summary_grid.csv"), index=False, encoding="utf-8-sig")
    return out_dir


def main() -> None:
    p = argparse.ArgumentParser(description="Small practical MA120 system grid")
    p.add_argument("--label", required=True)
    p.add_argument("--panel-csv", required=True)
    p.add_argument("--csv-dir", required=True)
    p.add_argument("--output-dir", default="/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output")
    p.add_argument("--top-ns", nargs="+", type=int, default=[5, 10, 30])
    p.add_argument("--min-close-above-p0-days", type=int, default=15)
    p.add_argument("--min-ret-obs", type=float, default=0.0)
    p.add_argument("--cost-oneway", type=float, default=0.0015)
    p.add_argument("--markets", default="SH,SZ")
    p.add_argument("--index-code", default="000001.SH")
    p.add_argument("--allow-overlap-symbol", action="store_true")
    args = p.parse_args()
    out = run_dataset(
        label=args.label,
        panel_csv=args.panel_csv,
        csv_dir=args.csv_dir,
        output_root=args.output_dir,
        top_ns=args.top_ns,
        min_close_above=args.min_close_above_p0_days,
        min_ret_obs=args.min_ret_obs,
        cost_oneway=args.cost_oneway,
        markets=args.markets,
        index_code=args.index_code,
        no_overlap_symbol=not args.allow_overlap_symbol,
    )
    print(out)


if __name__ == "__main__":
    main()
