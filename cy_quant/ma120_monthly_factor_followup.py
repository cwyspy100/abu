#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Follow-up tests for the best MA120 monthly factor line.

Use the best current factor set:
  obs_days = 30
  features = ret60, price_vs_ma120, volatility20, ret20, atr20_vs_atr60

Then compare:
1) Top10 / Top15 / Top20
2) Industry top-30% filter
3) 70/30 stock-industry blended score
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from typing import Dict, List, Tuple

import numpy as np
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
    simulate_top10,
)


BEST_SPEC: List[Tuple[str, float]] = [
    ("ret60", -1.0),
    ("price_vs_ma120", -1.0),
    ("volatility20", -1.0),
    ("ret20", -1.0),
    ("atr20_vs_atr60", -1.0),
]


def load_industry_map(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, usecols=["ts_code", "industry"])
    df["ts_code"] = df["ts_code"].astype(str).str.upper()
    return df.dropna(subset=["ts_code", "industry"]).drop_duplicates(subset=["ts_code"], keep="last")


def symbol_to_ts_code(symbol: str) -> str:
    s = str(symbol)
    prefix = s[:2].lower()
    code = s[2:]
    market = {"sh": "SH", "sz": "SZ", "bj": "BJ"}.get(prefix, "")
    return f"{code}.{market}" if market else s.upper()


def attach_industry(panel: pd.DataFrame, industry_map: pd.DataFrame) -> pd.DataFrame:
    out = panel.copy()
    out["ts_code"] = out["symbol"].map(symbol_to_ts_code)
    return out.merge(industry_map, on="ts_code", how="left")


def zscore(s: pd.Series) -> pd.Series:
    std = s.std(ddof=0)
    if std == 0 or np.isnan(std):
        return pd.Series(0.0, index=s.index)
    return (s - s.mean()) / std


def prepare_ranked_variants(panel: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    base = build_ranked_panel(panel, 30, BEST_SPEC).copy()
    out: Dict[str, pd.DataFrame] = {"base": base}

    # Industry strength from same-month average base score.
    ind = (
        base.dropna(subset=["industry"])
        .groupby(["eval_month", "industry"], as_index=False)
        .agg(industry_score=("score", "mean"), industry_count=("symbol", "count"))
    )
    ind["industry_rank"] = ind.groupby("eval_month")["industry_score"].rank(method="average", pct=True)

    merged = base.merge(ind, on=["eval_month", "industry"], how="left")

    filt = merged[(merged["industry_rank"] >= 0.70) & merged["industry"].notna()].copy()
    filt["rank_in_month"] = filt.groupby("eval_month")["score"].rank(method="first", ascending=False)
    out["industry_top30_filter"] = filt.sort_values(["eval_date", "rank_in_month", "symbol"]).reset_index(drop=True)

    mix = merged.copy()
    mix["stock_z"] = mix.groupby("eval_month")["score"].transform(zscore)
    mix["industry_z"] = mix.groupby("eval_month")["industry_rank"].transform(zscore)
    mix["mix_score"] = 0.7 * mix["stock_z"].fillna(0.0) + 0.3 * mix["industry_z"].fillna(0.0)
    mix["rank_in_month"] = mix.groupby("eval_month")["mix_score"].rank(method="first", ascending=False)
    mix["score"] = mix["mix_score"]
    out["industry_mix_70_30"] = mix.sort_values(["eval_date", "rank_in_month", "symbol"]).reset_index(drop=True)

    return out


def run_followup(panel_csv: str, industry_csv: str, csv_dir: str, output_dir: str, cost_bps: float, stop_pct: float) -> str:
    panel = pd.read_csv(panel_csv)
    panel["eval_date"] = pd.to_datetime(panel["eval_date"])
    industry_map = load_industry_map(industry_csv)
    panel = attach_industry(panel, industry_map)
    ranked_variants = prepare_ranked_variants(panel)
    price_cache: Dict[str, pd.DataFrame] = {}
    cost_oneway = cost_bps / 10000.0

    rows = []
    daily_exports = []
    trade_exports = []
    for variant_name, ranked in ranked_variants.items():
        for top_n in [10, 15, 20]:
            daily_2025, trades_2025, perf_2025 = simulate_top10(
                ranked, csv_dir, TRAIN_START, TRAIN_END, top_n, stop_pct, cost_oneway, price_cache
            )
            daily_2026, trades_2026, perf_2026 = simulate_top10(
                ranked, csv_dir, VALID_START, VALID_END, top_n, stop_pct, cost_oneway, price_cache
            )
            rows.append(
                {
                    "variant": variant_name,
                    "top_n": top_n,
                    "train_total_return": perf_2025["total_return"],
                    "train_cagr": perf_2025["cagr"],
                    "train_max_drawdown": perf_2025["max_drawdown"],
                    "valid_total_return": perf_2026["total_return"],
                    "valid_cagr": perf_2026["cagr"],
                    "valid_max_drawdown": perf_2026["max_drawdown"],
                    "valid_sharpe": perf_2026["sharpe"],
                    "valid_trades": perf_2026["trades"],
                    "valid_win_rate": perf_2026["win_rate"],
                    "valid_avg_trade_ret": perf_2026["avg_trade_ret"],
                    "valid_avg_active": perf_2026["avg_active"],
                    "valid_avg_exposure": perf_2026["avg_exposure"],
                }
            )
            label = f"{variant_name}_top{top_n}"
            daily_exports.append((f"{label}_daily_2026.csv", daily_2026))
            trade_exports.append((f"{label}_trades_2026.csv", trades_2026))

    summary = pd.DataFrame(rows).sort_values(
        ["valid_cagr", "valid_max_drawdown", "valid_sharpe"], ascending=[False, False, False]
    ).reset_index(drop=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(output_dir, f"ma120_monthly_factor_followup_{stamp}")
    os.makedirs(out_dir, exist_ok=True)
    summary.to_csv(os.path.join(out_dir, "followup_summary.csv"), index=False, encoding="utf-8-sig")
    for name, df in daily_exports:
        df.to_csv(os.path.join(out_dir, name), index=False, encoding="utf-8-sig")
    for name, df in trade_exports:
        df.to_csv(os.path.join(out_dir, name), index=False, encoding="utf-8-sig")

    report = [
        "# MA120 Monthly Factor Follow-up",
        "",
        "Best fixed factor set:",
        "",
        "- `obs_days = 30`",
        "- `ret60 + price_vs_ma120 + volatility20 + ret20 + atr20_vs_atr60`",
        "",
        "## Validation Summary",
        "",
        summary[
            [
                "variant",
                "top_n",
                "valid_total_return",
                "valid_cagr",
                "valid_max_drawdown",
                "valid_sharpe",
                "valid_trades",
                "valid_avg_exposure",
            ]
        ].to_markdown(index=False, floatfmt=".4f"),
    ]
    with open(os.path.join(out_dir, "followup_report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(report))

    print(out_dir)
    print(summary.to_string(index=False))
    return out_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Follow-up tests for the best MA120 monthly factor line.")
    parser.add_argument("--panel-csv", required=True)
    parser.add_argument("--industry-csv", default="todolist/stock_A_basic_list.csv")
    parser.add_argument("--csv-dir", default=os.path.expanduser("~/abu/data/csv"))
    parser.add_argument("--output-dir", default="cy_quant/output")
    parser.add_argument("--cost-bps", type=float, default=10.0)
    parser.add_argument("--stop-pct", type=float, default=0.10)
    args = parser.parse_args()
    run_followup(args.panel_csv, args.industry_csv, args.csv_dir, args.output_dir, args.cost_bps, args.stop_pct)


if __name__ == "__main__":
    main()
