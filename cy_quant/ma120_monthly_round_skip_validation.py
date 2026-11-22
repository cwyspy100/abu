#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate a simple round-level skip rule for moderate_non_crowded + Top8.

Rule:
  If the monthly pass ratio of moderate_non_crowded candidates versus the
  full MA120-above pool is below a threshold, skip that whole next-entry round.
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


def add_month_percentiles(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    out = df.copy()
    for col in cols:
        out[f"{col}_pct_in_month"] = out.groupby("eval_month")[col].rank(pct=True, method="average")
    return out


def apply_moderate_filter(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    mask = (
        (x["bull_ma_stack"] >= 1.0)
        & (x["above_days"] >= 45)
        & (x["ma120_slope20"] > 0.02)
        & (x["price_vs_ma120_pct_in_month"] <= 0.45)
        & (x["dist_to_high60_pct_in_month"] <= 0.45)
        & (x["volume_ratio20_pct_in_month"] <= 0.45)
        & (x["up_ratio20_pct_in_month"] <= 0.45)
    )
    return x[mask].copy()


def next_trade_map(calendar: Sequence[pd.Timestamp]) -> Dict[pd.Timestamp, pd.Timestamp]:
    return {pd.Timestamp(calendar[i]): pd.Timestamp(calendar[i + 1]) for i in range(len(calendar) - 1)}


def simulate_with_skipped_eval_months(
    ranked: pd.DataFrame,
    csv_dir: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    top_n: int,
    stop_pct: float,
    cost_oneway: float,
    price_cache: Dict[str, pd.DataFrame],
    skipped_eval_months: Optional[Set[str]] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, object]]:
    skipped_eval_months = skipped_eval_months or set()
    calendar = [d for d in load_calendar(csv_dir) if start <= d <= end]
    next_map = next_trade_map(calendar)

    panel = ranked[(pd.to_datetime(ranked["eval_date"]) >= start) & (pd.to_datetime(ranked["eval_date"]) <= end)].copy()
    panel["eval_date"] = pd.to_datetime(panel["eval_date"])
    panel["eval_month"] = panel["eval_month"].astype(str)
    if skipped_eval_months:
        panel = panel[~panel["eval_month"].isin(skipped_eval_months)].copy()

    by_eval = {d: g.sort_values("rank_in_month") for d, g in panel.groupby("eval_date")}
    rebalance_dates = [next_map[d] for d in sorted(by_eval.keys()) if d in next_map and next_map[d] <= end]
    picks_by_rebalance = {
        next_map[d]: by_eval[d].head(top_n).copy()
        for d in sorted(by_eval.keys())
        if d in next_map and next_map[d] <= end
    }

    positions: Dict[str, Dict[str, object]] = {}
    closed: List[Dict[str, object]] = []
    daily_rows: List[Dict[str, object]] = []
    equity = 1.0

    for date in calendar:
        day_ret = 0.0
        forced_closes: List[Tuple[str, float, str]] = []

        for code, pos in list(positions.items()):
            if code not in price_cache or date not in price_cache[code].index:
                continue
            row = price_cache[code].loc[date]
            last_price = float(pos["last_price"])
            close_px = float(row["close"])
            day_ret += float(pos["weight"]) * (close_px / last_price - 1.0)
            stop_line = float(pos["entry_price"]) * (1.0 - stop_pct)
            if float(row["low"]) <= stop_line:
                forced_closes.append((code, stop_line, "stop10"))
            pos["last_price"] = close_px

        if date in rebalance_dates:
            for code, pos in list(positions.items()):
                if code not in price_cache or date not in price_cache[code].index:
                    continue
                row = price_cache[code].loc[date]
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
                weight = 1.0 / float(top_n)
                for _, r in picks.head(top_n).iterrows():
                    code = str(r["symbol"])
                    if code not in price_cache or date not in price_cache[code].index:
                        continue
                    row = price_cache[code].loc[date]
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
            {"date": date, "equity": equity, "active_n": len(positions), "exposure": sum(float(p["weight"]) for p in positions.values())}
        )

    final_date = pd.Timestamp(calendar[-1]) if calendar else None
    if final_date is not None:
        for code, pos in list(positions.items()):
            if code not in price_cache or final_date not in price_cache[code].index:
                continue
            row = price_cache[code].loc[final_date]
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
    eq = daily["equity"].astype(float)
    dd = eq / eq.cummax() - 1.0
    dret = eq.pct_change().fillna(0.0)
    years = max((pd.Timestamp(daily["date"].iloc[-1]) - pd.Timestamp(daily["date"].iloc[0])).days / 365.25, 1e-9) if len(daily) else 1e-9
    perf = {
        "days": int(len(daily)),
        "start": str(pd.Timestamp(daily["date"].iloc[0]).date()) if len(daily) else "",
        "end": str(pd.Timestamp(daily["date"].iloc[-1]).date()) if len(daily) else "",
        "total_return": float(eq.iloc[-1] - 1.0) if len(eq) else 0.0,
        "cagr": float(eq.iloc[-1] ** (1.0 / years) - 1.0) if len(eq) and eq.iloc[-1] > 0 else 0.0,
        "max_drawdown": float(dd.min()) if len(dd) else 0.0,
        "sharpe": float(dret.mean() / dret.std() * (252 ** 0.5)) if len(dret) and dret.std() > 0 else 0.0,
        "trades": int(len(trades)),
        "win_rate": float((trades["ret"] > 0).mean()) if len(trades) else 0.0,
        "avg_trade_ret": float(trades["ret"].mean()) if len(trades) else 0.0,
        "median_trade_ret": float(trades["ret"].median()) if len(trades) else 0.0,
        "avg_active": float(daily["active_n"].mean()) if len(daily) else 0.0,
        "avg_exposure": float(daily["exposure"].mean()) if len(daily) else 0.0,
    }
    return daily, trades, perf


def round_pass_ratio_table(full_ranked: pd.DataFrame, moderate: pd.DataFrame) -> pd.DataFrame:
    full_valid = full_ranked[(full_ranked["eval_date"] >= VALID_START) & (full_ranked["eval_date"] <= VALID_END)].copy()
    moderate_valid = moderate[(moderate["eval_date"] >= VALID_START) & (moderate["eval_date"] <= VALID_END)].copy()
    full_counts = full_valid.groupby("eval_month")["symbol"].nunique().rename("full_n")
    moderate_counts = moderate_valid.groupby("eval_month")["symbol"].nunique().rename("moderate_n")
    tab = pd.concat([full_counts, moderate_counts], axis=1).fillna(0.0).reset_index()
    tab["pass_ratio"] = tab["moderate_n"] / tab["full_n"]
    return tab


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate simple round skip thresholds.")
    parser.add_argument("--panel-csv", required=True)
    parser.add_argument("--csv-dir", default=os.path.expanduser("~/abu/data/csv"))
    parser.add_argument("--output-dir", default="cy_quant/output")
    parser.add_argument("--top-n", type=int, default=8)
    parser.add_argument("--stop-pct", type=float, default=0.10)
    parser.add_argument("--cost-bps", type=float, default=10.0)
    args = parser.parse_args()

    panel = pd.read_csv(args.panel_csv)
    panel["eval_date"] = pd.to_datetime(panel["eval_date"])
    full_ranked = build_ranked_panel(panel, 30, BEST_SPEC)
    full_ranked = add_month_percentiles(full_ranked, ["price_vs_ma120", "dist_to_high60", "volume_ratio20", "up_ratio20"])
    moderate = apply_moderate_filter(full_ranked)

    price_cache = price_cache_for(args.csv_dir, full_ranked["symbol"].astype(str).unique().tolist())
    cost_oneway = args.cost_bps / 10000.0
    round_tab = round_pass_ratio_table(full_ranked, moderate)

    thresholds = [0.0, 0.045, 0.05, 0.06, 0.07]
    rows: List[Dict[str, object]] = []
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.output_dir, f"ma120_monthly_round_skip_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    for th in thresholds:
        skipped = set(round_tab.loc[round_tab["pass_ratio"] < th, "eval_month"].astype(str).tolist())
        daily, trades, perf = simulate_with_skipped_eval_months(
            moderate, args.csv_dir, VALID_START, VALID_END, args.top_n, args.stop_pct, cost_oneway, price_cache, skipped_eval_months=skipped
        )
        rows.append(
            {
                "pass_ratio_threshold": th,
                "skipped_eval_months": ",".join(sorted(skipped)),
                **perf,
            }
        )
        suffix = str(th).replace(".", "p")
        daily.to_csv(os.path.join(out_dir, f"daily_th_{suffix}.csv"), index=False, encoding="utf-8-sig")
        trades.to_csv(os.path.join(out_dir, f"trades_th_{suffix}.csv"), index=False, encoding="utf-8-sig")

    summary = pd.DataFrame(rows)
    round_tab.to_csv(os.path.join(out_dir, "round_pass_ratio_table.csv"), index=False, encoding="utf-8-sig")
    summary.to_csv(os.path.join(out_dir, "threshold_summary.csv"), index=False, encoding="utf-8-sig")

    report = [
        "# MA120 Monthly Round Skip Validation",
        "",
        "## Round Pass Ratio Table",
        "",
        round_tab.to_markdown(index=False, floatfmt=".4f"),
        "",
        "## Threshold Summary",
        "",
        summary.to_markdown(index=False, floatfmt=".4f"),
    ]
    with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(report))

    print(out_dir)
    print("Round pass ratio table:")
    print(round_tab.to_string(index=False))
    print("\nThreshold summary:")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
