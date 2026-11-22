#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Best-line stop-structure follow-up for A-share MA120 monthly ranking.

Base line:
  obs_days = 30
  features = ret60 + price_vs_ma120 + volatility20 + ret20 + atr20_vs_atr60
  Top10 monthly
  no mid-month refill

This script compares whether the current line is being stopped out too early:
  1) single hard stop: 10% / 12% / 15%
  2) staged stop / trend core:
     - 50% at 10%, 50% at 15%
     - 50% at 10%, 50% at 20%
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from typing import Dict, List, Sequence, Tuple

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

STOP_VARIANTS: Dict[str, List[Tuple[str, float, float]]] = {
    "stop10_full": [("full", 1.0, 0.10)],
    "stop12_full": [("full", 1.0, 0.12)],
    "stop15_full": [("full", 1.0, 0.15)],
    "stop10_15_half": [("satellite", 0.50, 0.10), ("core", 0.50, 0.15)],
    "stop10_20_half": [("satellite", 0.50, 0.10), ("core", 0.50, 0.20)],
}


def perf_summary(daily: pd.DataFrame, trades: pd.DataFrame) -> Dict[str, object]:
    eq = daily["equity"].astype(float)
    total = float(eq.iloc[-1] - 1.0) if len(eq) else 0.0
    years = max((pd.Timestamp(daily["date"].iloc[-1]) - pd.Timestamp(daily["date"].iloc[0])).days / 365.25, 1e-9)
    cagr = float(eq.iloc[-1] ** (1.0 / years) - 1.0) if len(eq) and eq.iloc[-1] > 0 else 0.0
    dd = eq / eq.cummax() - 1.0
    dret = eq.pct_change().fillna(0.0)
    sharpe = float(dret.mean() / dret.std() * (252 ** 0.5)) if dret.std() > 0 else 0.0
    stop_trades = trades[trades["reason"].str.startswith("stop")] if len(trades) else trades
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
        "median_trade_ret": float(trades["ret"].median()) if len(trades) else 0.0,
        "avg_active": float(daily["active_n"].mean()) if len(daily) else 0.0,
        "avg_exposure": float(daily["exposure"].mean()) if len(daily) else 0.0,
        "stop_count": int(len(stop_trades)) if len(trades) else 0,
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


def simulate_variant(
    ranked: pd.DataFrame,
    csv_dir: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    top_n: int,
    cost_oneway: float,
    legs_spec: List[Tuple[str, float, float]],
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, object]]:
    calendar = [d for d in load_calendar(csv_dir) if start <= d <= end]
    next_map = next_trade_map(calendar)

    panel = ranked[(pd.to_datetime(ranked["eval_date"]) >= start) & (pd.to_datetime(ranked["eval_date"]) <= end)].copy()
    panel["eval_date"] = pd.to_datetime(panel["eval_date"])
    by_eval = {d: g.sort_values("rank_in_month") for d, g in panel.groupby("eval_date")}
    rebalance_dates = [next_map[d] for d in sorted(by_eval.keys()) if d in next_map and next_map[d] <= end]
    picks_by_rebalance = {
        next_map[d]: by_eval[d].head(top_n).copy()
        for d in sorted(by_eval.keys())
        if d in next_map and next_map[d] <= end
    }
    all_symbols = panel["symbol"].astype(str).unique().tolist()
    prices = price_cache_for(csv_dir, all_symbols)

    positions: Dict[str, Dict[str, object]] = {}
    closed: List[Dict[str, object]] = []
    daily_rows: List[Dict[str, object]] = []
    equity = 1.0

    for date in calendar:
        day_ret = 0.0
        forced_closes: List[Tuple[str, str, float, str]] = []

        for pos_id, pos in list(positions.items()):
            code = str(pos["symbol"])
            if code not in prices or date not in prices[code].index:
                continue
            row = prices[code].loc[date]
            last_price = float(pos["last_price"])
            close_px = float(row["close"])
            day_ret += float(pos["weight"]) * (close_px / last_price - 1.0)
            stop_line = float(pos["entry_price"]) * (1.0 - float(pos["stop_pct"]))
            if float(row["low"]) <= stop_line:
                forced_closes.append((pos_id, code, stop_line, f"stop{int(round(float(pos['stop_pct']) * 100))}"))
            pos["last_price"] = close_px

        if date in rebalance_dates:
            for pos_id, pos in list(positions.items()):
                code = str(pos["symbol"])
                if code not in prices or date not in prices[code].index:
                    continue
                row = prices[code].loc[date]
                open_px = float(row["open"])
                day_ret += float(pos["weight"]) * (open_px / float(pos["last_price"]) - 1.0)
                day_ret -= cost_oneway * float(pos["weight"])
                closed.append(
                    {
                        "symbol": code,
                        "leg_tag": pos["leg_tag"],
                        "stop_pct": float(pos["stop_pct"]),
                        "entry_date": pos["entry_date"],
                        "exit_date": date,
                        "entry_price": pos["entry_price"],
                        "exit_price": open_px,
                        "ret": open_px / float(pos["entry_price"]) - 1.0,
                        "reason": "rebalance",
                        "weight": float(pos["weight"]),
                        "pnl_contrib": float(pos["weight"]) * (open_px / float(pos["entry_price"]) - 1.0),
                    }
                )
                positions.pop(pos_id, None)

            picks = picks_by_rebalance.get(date)
            if picks is not None and len(picks):
                symbol_weight = 1.0 / float(top_n)
                for _, r in picks.iterrows():
                    code = str(r["symbol"])
                    if code not in prices or date not in prices[code].index:
                        continue
                    row = prices[code].loc[date]
                    open_px = float(row["open"])
                    for leg_tag, leg_frac, stop_pct in legs_spec:
                        leg_weight = symbol_weight * float(leg_frac)
                        pos_id = f"{code}|{leg_tag}|{stop_pct:.4f}"
                        positions[pos_id] = {
                            "symbol": code,
                            "leg_tag": leg_tag,
                            "entry_date": date,
                            "entry_price": open_px,
                            "last_price": open_px,
                            "weight": leg_weight,
                            "stop_pct": float(stop_pct),
                        }
                        day_ret -= cost_oneway * leg_weight

        for pos_id, code, exit_px, reason in forced_closes:
            pos = positions.pop(pos_id, None)
            if pos is None:
                continue
            current_close = float(pos["last_price"])
            day_ret += float(pos["weight"]) * (exit_px / current_close - 1.0)
            day_ret -= cost_oneway * float(pos["weight"])
            trade_ret = exit_px / float(pos["entry_price"]) - 1.0
            closed.append(
                {
                    "symbol": code,
                    "leg_tag": pos["leg_tag"],
                    "stop_pct": float(pos["stop_pct"]),
                    "entry_date": pos["entry_date"],
                    "exit_date": date,
                    "entry_price": pos["entry_price"],
                    "exit_price": exit_px,
                    "ret": trade_ret,
                    "reason": reason,
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
        for pos_id, pos in list(positions.items()):
            code = str(pos["symbol"])
            if code not in prices or final_date not in prices[code].index:
                continue
            row = prices[code].loc[final_date]
            close_px = float(row["close"])
            trade_ret = close_px / float(pos["entry_price"]) - 1.0
            closed.append(
                {
                    "symbol": code,
                    "leg_tag": pos["leg_tag"],
                    "stop_pct": float(pos["stop_pct"]),
                    "entry_date": pos["entry_date"],
                    "exit_date": final_date,
                    "entry_price": pos["entry_price"],
                    "exit_price": close_px,
                    "ret": trade_ret,
                    "reason": "mark_to_end",
                    "weight": float(pos["weight"]),
                    "pnl_contrib": float(pos["weight"]) * trade_ret,
                }
            )

    daily = pd.DataFrame(daily_rows)
    trades = pd.DataFrame(closed)
    return daily, trades, perf_summary(daily, trades)


def main() -> None:
    parser = argparse.ArgumentParser(description="MA120 monthly stop-structure follow-up.")
    parser.add_argument("--panel-csv", required=True)
    parser.add_argument("--csv-dir", default=os.path.expanduser("~/abu/data/csv"))
    parser.add_argument("--output-dir", default="cy_quant/output")
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--cost-bps", type=float, default=10.0)
    args = parser.parse_args()

    panel = pd.read_csv(args.panel_csv)
    panel["eval_date"] = pd.to_datetime(panel["eval_date"])
    ranked = build_ranked_panel(panel, 30, BEST_SPEC)
    cost_oneway = args.cost_bps / 10000.0

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.output_dir, f"ma120_monthly_stop_structure_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    rows: List[Dict[str, object]] = []
    for variant, legs_spec in STOP_VARIANTS.items():
        daily, trades, perf = simulate_variant(
            ranked, args.csv_dir, VALID_START, VALID_END, args.top_n, cost_oneway, legs_spec
        )
        rows.append({"variant": variant, **perf})
        daily.to_csv(os.path.join(out_dir, f"daily_{variant}.csv"), index=False, encoding="utf-8-sig")
        trades.to_csv(os.path.join(out_dir, f"trades_{variant}.csv"), index=False, encoding="utf-8-sig")

    summary = pd.DataFrame(rows).sort_values(["total_return", "sharpe"], ascending=[False, False]).reset_index(drop=True)
    summary.to_csv(os.path.join(out_dir, "variant_summary.csv"), index=False, encoding="utf-8-sig")

    report = [
        "# MA120 Monthly Stop Structure Follow-up",
        "",
        "## Fixed Base",
        "",
        "- obs_days = 30",
        "- Top10 monthly",
        "- factors = ret60 + price_vs_ma120 + volatility20 + ret20 + atr20_vs_atr60",
        "- no mid-month refill",
        "- 10 bps one-way cost",
        "",
        "## Variants",
        "",
        "- stop10_full: single 10% hard stop",
        "- stop12_full: single 12% hard stop",
        "- stop15_full: single 15% hard stop",
        "- stop10_15_half: sell 50% at 10%, keep 50% until 15%",
        "- stop10_20_half: sell 50% at 10%, keep 50% until 20%",
        "",
        "## Summary",
        "",
        summary.to_markdown(index=False, floatfmt=".4f"),
    ]
    with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(report))

    print(out_dir)
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
