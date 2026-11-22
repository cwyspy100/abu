#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate narrow 'non-crowded strong-trend pullback' hypotheses.

This follow-up turns the winner-profile insight into practical filters on top of
the current best MA120 monthly ranking line, and compares them with the
baseline ranking.
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
    VALID_END,
    VALID_START,
    build_ranked_panel,
    latest_file_map,
    load_kline,
    simulate_top10,
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


def apply_variant_filters(df: pd.DataFrame, name: str) -> pd.DataFrame:
    x = df.copy()
    if name == "baseline":
        return x
    if name == "moderate_non_crowded":
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
    if name == "tight_non_crowded":
        mask = (
            (x["bull_ma_stack"] >= 1.0)
            & (x["above_days"].between(45, 90))
            & (x["ma120_slope20"] > 0.03)
            & (x["price_vs_ma120_pct_in_month"] <= 0.45)
            & (x["dist_to_high60_pct_in_month"] <= 0.35)
            & (x["volume_ratio20_pct_in_month"] <= 0.40)
            & (x["up_ratio20_pct_in_month"] <= 0.35)
        )
        return x[mask].copy()
    if name == "pullback_sniper":
        mask = (
            (x["bull_ma_stack"] >= 1.0)
            & (x["above_days"].between(50, 90))
            & (x["ma120_slope20"] > 0.03)
            & (x["price_vs_ma120_pct_in_month"].between(0.20, 0.50))
            & (x["dist_to_high60_pct_in_month"] <= 0.35)
            & (x["drawdown20_pct_in_month"] <= 0.35)
            & (x["volume_ratio20_pct_in_month"] <= 0.35)
            & (x["up_ratio20_pct_in_month"] <= 0.35)
        )
        return x[mask].copy()
    raise ValueError(f"unknown variant: {name}")


def candidate_month_summary(df: pd.DataFrame, top_n: int) -> Dict[str, float]:
    if df.empty:
        return {"avg_candidates_per_month": 0.0, "min_candidates_per_month": 0.0, "months_with_enough_picks": 0.0}
    per_month = df.groupby("eval_month")["symbol"].nunique()
    return {
        "avg_candidates_per_month": float(per_month.mean()),
        "min_candidates_per_month": float(per_month.min()),
        "months_with_enough_picks": int((per_month >= top_n).sum()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate narrow MA120 trend-sniper filters.")
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
    ranked = add_month_percentiles(
        ranked,
        ["price_vs_ma120", "dist_to_high60", "volume_ratio20", "up_ratio20", "drawdown20"],
    )

    variants = ["baseline", "moderate_non_crowded", "tight_non_crowded", "pullback_sniper"]
    cost_oneway = args.cost_bps / 10000.0
    symbols = ranked["symbol"].astype(str).unique().tolist()
    price_cache = price_cache_for(args.csv_dir, symbols)

    rows: List[Dict[str, object]] = []
    month_rows: List[Dict[str, object]] = []
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.output_dir, f"ma120_monthly_trend_sniper_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    for variant in variants:
        sub = apply_variant_filters(ranked, variant)
        daily, trades, perf = simulate_top10(
            sub, args.csv_dir, VALID_START, VALID_END, args.top_n, args.stop_pct, cost_oneway, price_cache
        )
        meta = candidate_month_summary(sub[(sub["eval_date"] >= VALID_START) & (sub["eval_date"] <= VALID_END)].copy(), args.top_n)
        rows.append({"variant": variant, **meta, **perf})

        by_month = (
            sub[(sub["eval_date"] >= VALID_START) & (sub["eval_date"] <= VALID_END)]
            .groupby("eval_month", as_index=False)
            .agg(candidate_n=("symbol", "nunique"))
        )
        by_month["variant"] = variant
        month_rows.append(by_month)

        daily.to_csv(os.path.join(out_dir, f"daily_{variant}.csv"), index=False, encoding="utf-8-sig")
        trades.to_csv(os.path.join(out_dir, f"trades_{variant}.csv"), index=False, encoding="utf-8-sig")
        sub.to_csv(os.path.join(out_dir, f"panel_{variant}.csv"), index=False, encoding="utf-8-sig")

    summary = pd.DataFrame(rows)
    candidate_by_month = pd.concat(month_rows, ignore_index=True) if month_rows else pd.DataFrame()
    summary.to_csv(os.path.join(out_dir, "variant_summary.csv"), index=False, encoding="utf-8-sig")
    candidate_by_month.to_csv(os.path.join(out_dir, "candidate_count_by_month.csv"), index=False, encoding="utf-8-sig")

    report = [
        "# MA120 Monthly Trend Sniper Validation",
        "",
        "## Fixed Base",
        "",
        "- obs_days = 30",
        "- score = ret60 + price_vs_ma120 + volatility20 + ret20 + atr20_vs_atr60",
        "- Top10 monthly",
        "- 10% hard stop",
        "- no mid-month refill",
        "- 10 bps one-way cost",
        "",
        "## Variants",
        "",
        "- baseline: no extra filter",
        "- moderate_non_crowded: moderate non-crowded pullback filter",
        "- tight_non_crowded: narrower non-crowded pullback filter",
        "- pullback_sniper: strongest narrow hypothesis from winner profile",
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
