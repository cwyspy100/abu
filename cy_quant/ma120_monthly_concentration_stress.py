#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Concentration stress tests for the best MA120 monthly ranking line.

Stress dimensions:
  1) leave-one-winner-out / leave-topN-winners-out
  2) leave-one-entry-month-out

Re-run the baseline portfolio after excluding symbols or entry months from the
monthly candidate pool, instead of just editing realized trade PnL afterward.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Set, Tuple

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from cy_quant.ma120_monthly_factor_reverse_2025_2026 import (  # noqa: E402
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
        "start": str(pd.Timestamp(daily["date"].iloc[0]).date()) if len(daily) else "",
        "end": str(pd.Timestamp(daily["date"].iloc[-1]).date()) if len(daily) else "",
        "total_return": total,
        "cagr": cagr,
        "max_drawdown": float(dd.min()) if len(dd) else 0.0,
        "sharpe": sharpe,
        "trades": int(len(trades)),
        "win_rate": float((trades["ret"] > 0).mean()) if len(trades) else 0.0,
        "avg_trade_ret": float(trades["ret"].mean()) if len(trades) else 0.0,
        "avg_active": float(daily["active_n"].mean()) if len(daily) else 0.0,
        "avg_exposure": float(daily["exposure"].mean()) if len(daily) else 0.0,
        "stop_count": int((trades["reason"] == "stop10").sum()) if len(trades) else 0,
        "rebalance_count": int((trades["reason"] == "rebalance").sum()) if len(trades) else 0,
        "mark_to_end_count": int((trades["reason"] == "mark_to_end").sum()) if len(trades) else 0,
    }


def next_trade_map(calendar: Sequence[pd.Timestamp]) -> Dict[pd.Timestamp, pd.Timestamp]:
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


def simulate_baseline(
    ranked: pd.DataFrame,
    csv_dir: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    top_n: int,
    stop_pct: float,
    cost_oneway: float,
    exclude_symbols: Optional[Set[str]] = None,
    exclude_entry_months: Optional[Set[str]] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, object]]:
    exclude_symbols = exclude_symbols or set()
    exclude_entry_months = exclude_entry_months or set()

    calendar = [d for d in load_calendar(csv_dir) if start <= d <= end]
    next_map = next_trade_map(calendar)

    panel = ranked[(pd.to_datetime(ranked["eval_date"]) >= start) & (pd.to_datetime(ranked["eval_date"]) <= end)].copy()
    panel["eval_date"] = pd.to_datetime(panel["eval_date"])
    panel["eval_month"] = panel["eval_month"].astype(str)
    if exclude_symbols:
        panel = panel[~panel["symbol"].astype(str).isin(exclude_symbols)].copy()
    if exclude_entry_months:
        panel = panel[~panel["eval_month"].isin(exclude_entry_months)].copy()

    by_eval = {d: g.sort_values("rank_in_month") for d, g in panel.groupby("eval_date")}
    rebalance_dates = [next_map[d] for d in sorted(by_eval.keys()) if d in next_map and next_map[d] <= end]
    picks_by_rebalance = {
        next_map[d]: by_eval[d].head(top_n).copy()
        for d in sorted(by_eval.keys())
        if d in next_map and next_map[d] <= end
    }

    all_symbols = ranked["symbol"].astype(str).unique().tolist()
    prices = price_cache_for(csv_dir, all_symbols)

    positions: Dict[str, Dict[str, object]] = {}
    closed: List[Dict[str, object]] = []
    daily_rows: List[Dict[str, object]] = []
    equity = 1.0

    for date in calendar:
        day_ret = 0.0
        forced_closes: List[Tuple[str, float, str]] = []

        for code, pos in list(positions.items()):
            if code not in prices or date not in prices[code].index:
                continue
            row = prices[code].loc[date]
            last_price = float(pos["last_price"])
            close_px = float(row["close"])
            day_ret += float(pos["weight"]) * (close_px / last_price - 1.0)
            stop_line = float(pos["entry_price"]) * (1.0 - stop_pct)
            if float(row["low"]) <= stop_line:
                forced_closes.append((code, stop_line, "stop10"))
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
                        "weight": float(pos["weight"]),
                        "pnl_contrib": float(pos["weight"]) * (open_px / float(pos["entry_price"]) - 1.0),
                    }
                )
                positions.pop(code, None)

            picks = picks_by_rebalance.get(date)
            if picks is not None and len(picks):
                month = str(picks["eval_month"].iloc[0])
                actual_picks = picks.head(top_n)
                pick_count = len(actual_picks)
                if pick_count > 0:
                    weight = 1.0 / float(top_n)
                    for _, r in actual_picks.iterrows():
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
                        }
                        day_ret -= cost_oneway * weight

        for code, exit_px, reason in forced_closes:
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
                    "month": pos["month"],
                    "weight": float(pos["weight"]),
                    "pnl_contrib": float(pos["weight"]) * trade_ret,
                }
            )

        equity *= 1.0 + day_ret
        daily_rows.append(
            {
                "date": date,
                "equity": equity,
                "active_n": len(positions),
                "exposure": sum(float(p["weight"]) for p in positions.values()),
            }
        )

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
                    "weight": float(pos["weight"]),
                    "pnl_contrib": float(pos["weight"]) * trade_ret,
                }
            )

    daily = pd.DataFrame(daily_rows)
    trades = pd.DataFrame(closed)
    return daily, trades, perf_summary(daily, trades)


def main() -> None:
    parser = argparse.ArgumentParser(description="MA120 monthly concentration stress tests.")
    parser.add_argument("--panel-csv", required=True)
    parser.add_argument("--baseline-trades-csv", required=True)
    parser.add_argument("--csv-dir", default=os.path.expanduser("~/abu/data/csv"))
    parser.add_argument("--output-dir", default="cy_quant/output")
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--stop-pct", type=float, default=0.10)
    parser.add_argument("--cost-bps", type=float, default=10.0)
    parser.add_argument("--top-winners", type=int, default=3)
    args = parser.parse_args()

    panel = pd.read_csv(args.panel_csv)
    panel["eval_date"] = pd.to_datetime(panel["eval_date"])
    ranked = build_ranked_panel(panel, 30, BEST_SPEC)
    cost_oneway = args.cost_bps / 10000.0

    base_daily, base_trades, base_perf = simulate_baseline(
        ranked, args.csv_dir, VALID_START, VALID_END, args.top_n, args.stop_pct, cost_oneway
    )

    base_attr = pd.read_csv(args.baseline_trades_csv)
    top_symbols = (
        base_attr.groupby("symbol", as_index=False)["pnl_contrib"]
        .sum()
        .sort_values("pnl_contrib", ascending=False)["symbol"]
        .astype(str)
        .tolist()
    )
    top_symbols = top_symbols[: max(args.top_winners, 0)]
    entry_months = (
        base_attr.assign(entry_month=pd.to_datetime(base_attr["entry_date"]).dt.to_period("M").astype(str))
        .groupby("entry_month", as_index=False)["pnl_contrib"]
        .sum()
        .sort_values("pnl_contrib", ascending=False)["entry_month"]
        .astype(str)
        .tolist()
    )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.output_dir, f"ma120_monthly_concentration_stress_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    rows: List[Dict[str, object]] = [{"variant": "baseline", "excluded": "", **base_perf}]
    base_daily.to_csv(os.path.join(out_dir, "daily_baseline.csv"), index=False, encoding="utf-8-sig")
    base_trades.to_csv(os.path.join(out_dir, "trades_baseline.csv"), index=False, encoding="utf-8-sig")

    for sym in top_symbols:
        daily, trades, perf = simulate_baseline(
            ranked, args.csv_dir, VALID_START, VALID_END, args.top_n, args.stop_pct, cost_oneway, exclude_symbols={sym}
        )
        rows.append({"variant": "leave_one_winner_out", "excluded": sym, **perf})
        daily.to_csv(os.path.join(out_dir, f"daily_ex_symbol_{sym}.csv"), index=False, encoding="utf-8-sig")
        trades.to_csv(os.path.join(out_dir, f"trades_ex_symbol_{sym}.csv"), index=False, encoding="utf-8-sig")

    for n in range(2, len(top_symbols) + 1):
        excluded = top_symbols[:n]
        daily, trades, perf = simulate_baseline(
            ranked, args.csv_dir, VALID_START, VALID_END, args.top_n, args.stop_pct, cost_oneway, exclude_symbols=set(excluded)
        )
        rows.append({"variant": f"leave_top{n}_winners_out", "excluded": ",".join(excluded), **perf})
        daily.to_csv(os.path.join(out_dir, f"daily_ex_top{n}_winners.csv"), index=False, encoding="utf-8-sig")
        trades.to_csv(os.path.join(out_dir, f"trades_ex_top{n}_winners.csv"), index=False, encoding="utf-8-sig")

    for month in entry_months:
        daily, trades, perf = simulate_baseline(
            ranked, args.csv_dir, VALID_START, VALID_END, args.top_n, args.stop_pct, cost_oneway, exclude_entry_months={month}
        )
        rows.append({"variant": "leave_one_month_out", "excluded": month, **perf})
        daily.to_csv(os.path.join(out_dir, f"daily_ex_month_{month}.csv"), index=False, encoding="utf-8-sig")
        trades.to_csv(os.path.join(out_dir, f"trades_ex_month_{month}.csv"), index=False, encoding="utf-8-sig")

    summary = pd.DataFrame(rows)
    summary.to_csv(os.path.join(out_dir, "variant_summary.csv"), index=False, encoding="utf-8-sig")

    winner_tbl = summary[summary["variant"].str.contains("winner", na=False) | (summary["variant"] == "baseline")].copy()
    month_tbl = summary[summary["variant"].str.contains("month", na=False) | (summary["variant"] == "baseline")].copy()

    report = [
        "# MA120 Monthly Concentration Stress",
        "",
        "## Fixed Base",
        "",
        "- obs_days = 30",
        "- Top10 monthly",
        "- factors = ret60 + price_vs_ma120 + volatility20 + ret20 + atr20_vs_atr60",
        "- 10% hard stop",
        "- no mid-month refill",
        "- 10 bps one-way cost",
        "",
        "## Top Positive Contributors Used For Stress Tests",
        "",
        f"- Top winners: {', '.join(top_symbols) if top_symbols else '(none)'}",
        f"- Entry months by positive contribution: {', '.join(entry_months) if entry_months else '(none)'}",
        "",
        "## Winner Stress",
        "",
        winner_tbl.to_markdown(index=False, floatfmt=".4f"),
        "",
        "## Month Stress",
        "",
        month_tbl.to_markdown(index=False, floatfmt=".4f"),
    ]
    with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(report))

    print(out_dir)
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
