#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Best-line refill vs cash, plus month/symbol attribution.

Base line:
  obs_days = 30
  features = ret60 + price_vs_ma120 + volatility20 + ret20 + atr20_vs_atr60
  Top10 monthly
  10% stop

Compare:
  A) stop then stay in cash until next rebalance
  B) stop then refill next trading day using next-ranked unused stock of same eval_month
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from typing import Dict, List, Tuple

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from cy_quant.ma120_monthly_factor_reverse_2025_2026 import (
    TRAIN_END,
    TRAIN_START,
    VALID_END,
    VALID_START,
    build_ranked_panel,
    latest_file_map,
    load_calendar,
    load_kline,
)


BEST_SPEC: List[Tuple[str, float]] = [
    ("ret60", -1.0),
    ("price_vs_ma120", -1.0),
    ("volatility20", -1.0),
    ("ret20", -1.0),
    ("atr20_vs_atr60", -1.0),
]


def perf_summary(daily: pd.DataFrame, trades: pd.DataFrame) -> Dict[str, object]:
    eq = daily["equity"].astype(float)
    total = float(eq.iloc[-1] - 1.0) if len(eq) else 0.0
    years = max((pd.Timestamp(daily["date"].iloc[-1]) - pd.Timestamp(daily["date"].iloc[0])).days / 365.25, 1e-9)
    cagr = float(eq.iloc[-1] ** (1.0 / years) - 1.0) if len(eq) and eq.iloc[-1] > 0 else 0.0
    dd = eq / eq.cummax() - 1.0
    dret = eq.pct_change().fillna(0.0)
    sharpe = float(dret.mean() / dret.std() * (252 ** 0.5)) if dret.std() > 0 else 0.0
    return {
        "total_return": total,
        "cagr": cagr,
        "max_drawdown": float(dd.min()) if len(dd) else 0.0,
        "sharpe": sharpe,
        "trades": int(len(trades)),
        "win_rate": float((trades["ret"] > 0).mean()) if len(trades) else 0.0,
        "avg_trade_ret": float(trades["ret"].mean()) if len(trades) else 0.0,
        "avg_active": float(daily["active_n"].mean()) if len(daily) else 0.0,
        "avg_exposure": float(daily["exposure"].mean()) if len(daily) else 0.0,
    }


def next_trade_map(calendar: List[pd.Timestamp]) -> Dict[pd.Timestamp, pd.Timestamp]:
    return {pd.Timestamp(calendar[i]): pd.Timestamp(calendar[i + 1]) for i in range(len(calendar) - 1)}


def price_cache_for(csv_dir: str, symbols: List[str]) -> Dict[str, pd.DataFrame]:
    files = latest_file_map(csv_dir)
    out: Dict[str, pd.DataFrame] = {}
    for code in symbols:
        path = files.get(code)
        if not path:
            continue
        base = load_kline(path)[["dt", "open", "low", "close"]].dropna().drop_duplicates(subset=["dt"], keep="last")
        out[code] = base.set_index("dt").sort_index()
    return out


def simulate(
    ranked: pd.DataFrame,
    csv_dir: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    top_n: int,
    stop_pct: float,
    cost_oneway: float,
    refill: bool,
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, object]]:
    calendar = [d for d in load_calendar(csv_dir) if start <= d <= end]
    next_map = next_trade_map(calendar)

    panel = ranked[(pd.to_datetime(ranked["eval_date"]) >= start) & (pd.to_datetime(ranked["eval_date"]) <= end)].copy()
    panel["eval_date"] = pd.to_datetime(panel["eval_date"])
    by_eval = {d: g.sort_values("rank_in_month") for d, g in panel.groupby("eval_date")}
    rebalance_dates = [next_map[d] for d in sorted(by_eval.keys()) if d in next_map and next_map[d] <= end]
    picks_by_rebalance = {
        next_map[d]: by_eval[d].copy()
        for d in sorted(by_eval.keys())
        if d in next_map and next_map[d] <= end
    }
    all_symbols = panel["symbol"].astype(str).unique().tolist()
    prices = price_cache_for(csv_dir, all_symbols)

    positions: Dict[str, Dict[str, object]] = {}
    closed: List[Dict[str, object]] = []
    daily_rows: List[Dict[str, object]] = []
    refill_queue: List[Tuple[pd.Timestamp, str, str, float]] = []
    used_by_month: Dict[str, set] = {}
    month_rank_map: Dict[str, List[str]] = {
        month: grp.sort_values("rank_in_month")["symbol"].astype(str).tolist()
        for month, grp in panel.groupby("eval_month")
    }
    month_eval_date: Dict[str, pd.Timestamp] = {
        month: pd.Timestamp(grp["eval_date"].iloc[0]) for month, grp in panel.groupby("eval_month")
    }

    equity = 1.0
    for date in calendar:
        day_ret = 0.0
        forced_closes: List[Tuple[str, float, str, str]] = []

        # scheduled refill entries happen before close mark-to-market for simplicity at next open
        due = [x for x in refill_queue if x[0] == date]
        refill_queue = [x for x in refill_queue if x[0] != date]
        for entry_date, month, symbol, weight in due:
            if symbol in positions or symbol not in prices or date not in prices[symbol].index:
                continue
            row = prices[symbol].loc[date]
            open_px = float(row["open"])
            positions[symbol] = {
                "entry_date": date,
                "entry_price": open_px,
                "last_price": open_px,
                "weight": weight,
                "month": month,
                "refill": True,
            }
            day_ret -= cost_oneway * weight

        for code, pos in list(positions.items()):
            if code not in prices or date not in prices[code].index:
                continue
            row = prices[code].loc[date]
            last_price = float(pos["last_price"])
            close_px = float(row["close"])
            day_ret += float(pos["weight"]) * (close_px / last_price - 1.0)
            stop_line = float(pos["entry_price"]) * (1.0 - stop_pct)
            if float(row["low"]) <= stop_line:
                forced_closes.append((code, stop_line, "stop10", str(pos["month"])))
            pos["last_price"] = close_px

        if date in rebalance_dates:
            for code, pos in list(positions.items()):
                if code not in prices or date not in prices[code].index:
                    continue
                row = prices[code].loc[date]
                open_px = float(row["open"])
                day_ret += float(pos["weight"]) * (open_px / float(pos["last_price"]) - 1.0)
                day_ret -= cost_oneway * float(pos["weight"])
                closed.append(
                    {
                        "symbol": code,
                        "entry_date": pos["entry_date"],
                        "exit_date": date,
                        "entry_price": pos["entry_price"],
                        "exit_price": open_px,
                        "ret": open_px / float(pos["entry_price"]) - 1.0,
                        "reason": "rebalance",
                        "month": pos["month"],
                        "refill": bool(pos.get("refill", False)),
                        "weight": float(pos["weight"]),
                        "pnl_contrib": float(pos["weight"]) * (open_px / float(pos["entry_price"]) - 1.0),
                    }
                )
                positions.pop(code, None)

            picks = picks_by_rebalance.get(date)
            if picks is not None and len(picks):
                month = str(picks["eval_month"].iloc[0])
                used_by_month[month] = set()
                weight = 1.0 / float(top_n)
                for _, r in picks.head(top_n).iterrows():
                    code = str(r["symbol"])
                    if code not in prices or date not in prices[code].index:
                        continue
                    row = prices[code].loc[date]
                    open_px = float(row["open"])
                    positions[code] = {
                        "entry_date": date,
                        "entry_price": open_px,
                        "last_price": open_px,
                        "weight": weight,
                        "month": month,
                        "refill": False,
                    }
                    used_by_month[month].add(code)
                    day_ret -= cost_oneway * weight

        for code, exit_px, reason, month in forced_closes:
            pos = positions.pop(code, None)
            if pos is None:
                continue
            current_close = float(pos["last_price"])
            day_ret += float(pos["weight"]) * (exit_px / current_close - 1.0)
            day_ret -= cost_oneway * float(pos["weight"])
            trade_ret = exit_px / float(pos["entry_price"]) - 1.0
            closed.append(
                {
                    "symbol": code,
                    "entry_date": pos["entry_date"],
                    "exit_date": date,
                    "entry_price": pos["entry_price"],
                    "exit_price": exit_px,
                    "ret": trade_ret,
                    "reason": reason,
                    "month": month,
                    "refill": bool(pos.get("refill", False)),
                    "weight": float(pos["weight"]),
                    "pnl_contrib": float(pos["weight"]) * trade_ret,
                }
            )
            if refill and date in next_map:
                candidates = month_rank_map.get(month, [])
                used = used_by_month.setdefault(month, set())
                next_symbol = next((s for s in candidates if s not in used and s not in positions), None)
                if next_symbol is not None:
                    used.add(next_symbol)
                    refill_queue.append((next_map[date], month, next_symbol, float(pos["weight"])))

        equity *= 1.0 + day_ret
        daily_rows.append(
            {
                "date": date,
                "equity": equity,
                "active_n": len(positions),
                "exposure": sum(float(p["weight"]) for p in positions.values()),
            }
        )

    # Add a terminal mark for still-open positions so attribution includes
    # unrealized winners/losers carried to the sample end.
    final_date = pd.Timestamp(calendar[-1]) if calendar else None
    if final_date is not None:
        for code, pos in list(positions.items()):
            if code not in prices or final_date not in prices[code].index:
                continue
            row = prices[code].loc[final_date]
            close_px = float(row["close"])
            trade_ret = close_px / float(pos["entry_price"]) - 1.0
            closed.append(
                {
                    "symbol": code,
                    "entry_date": pos["entry_date"],
                    "exit_date": final_date,
                    "entry_price": pos["entry_price"],
                    "exit_price": close_px,
                    "ret": trade_ret,
                    "reason": "mark_to_end",
                    "month": pos["month"],
                    "refill": bool(pos.get("refill", False)),
                    "weight": float(pos["weight"]),
                    "pnl_contrib": float(pos["weight"]) * trade_ret,
                }
            )

    daily = pd.DataFrame(daily_rows)
    trades = pd.DataFrame(closed)
    return daily, trades, perf_summary(daily, trades)


def attribution_tables(trades: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    t = trades.copy()
    t["entry_month"] = pd.to_datetime(t["entry_date"]).dt.to_period("M").astype(str)
    by_month = (
        t.groupby("entry_month", as_index=False)
        .agg(
            trades=("symbol", "count"),
            winners=("ret", lambda s: int((s > 0).sum())),
            avg_ret=("ret", "mean"),
            pnl_contrib=("pnl_contrib", "sum"),
        )
        .sort_values("pnl_contrib", ascending=False)
    )
    by_symbol = (
        t.groupby("symbol", as_index=False)
        .agg(
            trades=("symbol", "count"),
            avg_ret=("ret", "mean"),
            pnl_contrib=("pnl_contrib", "sum"),
            max_ret=("ret", "max"),
            min_ret=("ret", "min"),
        )
        .sort_values("pnl_contrib", ascending=False)
    )
    return by_month, by_symbol


def main() -> None:
    parser = argparse.ArgumentParser(description="Best-line refill vs cash and attribution study.")
    parser.add_argument("--panel-csv", required=True)
    parser.add_argument("--csv-dir", default=os.path.expanduser("~/abu/data/csv"))
    parser.add_argument("--output-dir", default="cy_quant/output")
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--stop-pct", type=float, default=0.10)
    parser.add_argument("--cost-bps", type=float, default=10.0)
    args = parser.parse_args()

    panel = pd.read_csv(args.panel_csv)
    panel["eval_date"] = pd.to_datetime(panel["eval_date"])
    ranked = build_ranked_panel(panel, 30, BEST_SPEC)
    cost_oneway = args.cost_bps / 10000.0

    daily_cash, trades_cash, perf_cash = simulate(
        ranked, args.csv_dir, VALID_START, VALID_END, args.top_n, args.stop_pct, cost_oneway, refill=False
    )
    daily_refill, trades_refill, perf_refill = simulate(
        ranked, args.csv_dir, VALID_START, VALID_END, args.top_n, args.stop_pct, cost_oneway, refill=True
    )
    month_attr, symbol_attr = attribution_tables(trades_cash)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.output_dir, f"ma120_monthly_refill_attr_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    pd.DataFrame([{"variant": "cash_until_rebalance", **perf_cash}, {"variant": "refill_next_day", **perf_refill}]).to_csv(
        os.path.join(out_dir, "variant_summary.csv"), index=False, encoding="utf-8-sig"
    )
    daily_cash.to_csv(os.path.join(out_dir, "daily_cash_until_rebalance.csv"), index=False, encoding="utf-8-sig")
    daily_refill.to_csv(os.path.join(out_dir, "daily_refill_next_day.csv"), index=False, encoding="utf-8-sig")
    trades_cash.to_csv(os.path.join(out_dir, "trades_cash_until_rebalance.csv"), index=False, encoding="utf-8-sig")
    trades_refill.to_csv(os.path.join(out_dir, "trades_refill_next_day.csv"), index=False, encoding="utf-8-sig")
    month_attr.to_csv(os.path.join(out_dir, "month_attribution_cash.csv"), index=False, encoding="utf-8-sig")
    symbol_attr.to_csv(os.path.join(out_dir, "symbol_attribution_cash.csv"), index=False, encoding="utf-8-sig")

    report = [
        "# MA120 Monthly Refill vs Cash",
        "",
        "## Summary",
        "",
        pd.DataFrame([{"variant": "cash_until_rebalance", **perf_cash}, {"variant": "refill_next_day", **perf_refill}]).to_markdown(index=False, floatfmt=".4f"),
        "",
        "## Top Month Contributors",
        "",
        month_attr.head(10).to_markdown(index=False, floatfmt=".4f"),
        "",
        "## Top Symbol Contributors",
        "",
        symbol_attr.head(10).to_markdown(index=False, floatfmt=".4f"),
    ]
    with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(report))

    print(out_dir)
    print(pd.DataFrame([{"variant": "cash_until_rebalance", **perf_cash}, {"variant": "refill_next_day", **perf_refill}]).to_string(index=False))
    print("\nTop month attribution:")
    print(month_attr.head(10).to_string(index=False))
    print("\nTop symbol attribution:")
    print(symbol_attr.head(10).to_string(index=False))


if __name__ == "__main__":
    main()
