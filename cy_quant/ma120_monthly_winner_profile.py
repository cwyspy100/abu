#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Profile top winners at selection time for the MA120 monthly ranking line."""

from __future__ import annotations

import argparse
import os
from datetime import datetime
from typing import Dict, List, Tuple

import pandas as pd

FEATURES = [
    "above_days",
    "price_vs_ma120",
    "ma120_slope20",
    "ret5",
    "ret20",
    "ret60",
    "dist_to_high60",
    "dist_to_high120",
    "volume_ratio20",
    "volume_ratio5_20",
    "atr20_vs_atr60",
    "up_down_diff20",
    "up_ratio20",
    "drawdown20",
    "volatility20",
    "nh20_count20",
    "bull_ma_stack",
]


def build_pick_panel(panel: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    p = panel.copy()
    p["eval_date"] = pd.to_datetime(p["eval_date"])
    p["eval_month"] = p["eval_month"].astype(str)

    t = trades.copy()
    t["month"] = t["month"].astype(str)
    t["symbol"] = t["symbol"].astype(str)

    # collapse repeated trades for same symbol/month if any; keep best realized contribution record
    t = t.sort_values(["symbol", "month", "pnl_contrib"], ascending=[True, True, False]).drop_duplicates(["symbol", "month"])
    merged = p.merge(t[["symbol", "month", "ret", "reason", "pnl_contrib"]], left_on=["symbol", "eval_month"], right_on=["symbol", "month"], how="inner")
    merged = merged.drop(columns=["month"])

    for feat in FEATURES:
        merged[f"{feat}_pct_in_month"] = merged.groupby("eval_month")[feat].rank(pct=True, method="average")
    return merged


def summarize_group(df: pd.DataFrame, label: str) -> pd.DataFrame:
    rows: List[Dict[str, object]] = []
    for feat in FEATURES:
        rows.append(
            {
                "group": label,
                "feature": feat,
                "mean": pd.to_numeric(df[feat], errors="coerce").mean(),
                "median": pd.to_numeric(df[feat], errors="coerce").median(),
                "mean_pct_in_month": pd.to_numeric(df[f"{feat}_pct_in_month"], errors="coerce").mean(),
                "median_pct_in_month": pd.to_numeric(df[f"{feat}_pct_in_month"], errors="coerce").median(),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Winner profile analysis for MA120 monthly strategy.")
    parser.add_argument("--panel-csv", required=True)
    parser.add_argument("--trades-csv", required=True)
    parser.add_argument("--output-dir", default="cy_quant/output")
    parser.add_argument("--top-winners", type=int, default=3)
    args = parser.parse_args()

    panel = pd.read_csv(args.panel_csv)
    trades = pd.read_csv(args.trades_csv)
    picks = build_pick_panel(panel, trades)

    top_winners = (
        picks.groupby("symbol", as_index=False)["pnl_contrib"]
        .sum()
        .sort_values("pnl_contrib", ascending=False)
        .head(args.top_winners)["symbol"]
        .astype(str)
        .tolist()
    )

    winners = picks[picks["symbol"].isin(top_winners)].copy()
    positive_non_winners = picks[(~picks["symbol"].isin(top_winners)) & (picks["pnl_contrib"] > 0)].copy()
    stopped = picks[picks["reason"] == "stop10"].copy()
    full_sample = picks.copy()

    summary = pd.concat(
        [
            summarize_group(winners, "top_winners"),
            summarize_group(positive_non_winners, "other_positive_picks"),
            summarize_group(stopped, "stop10_picks"),
            summarize_group(full_sample, "all_picks"),
        ],
        ignore_index=True,
    )

    pivot_abs = summary.pivot(index="feature", columns="group", values="median")
    pivot_pct = summary.pivot(index="feature", columns="group", values="median_pct_in_month")
    comp = summary[summary["group"] == "top_winners"][["feature", "median", "median_pct_in_month"]].rename(
        columns={"median": "top_winners_median", "median_pct_in_month": "top_winners_median_pct"}
    )
    comp = comp.merge(
        summary[summary["group"] == "all_picks"][["feature", "median", "median_pct_in_month"]].rename(
            columns={"median": "all_picks_median", "median_pct_in_month": "all_picks_median_pct"}
        ),
        on="feature",
        how="left",
    )
    comp["median_diff"] = comp["top_winners_median"] - comp["all_picks_median"]
    comp["month_pct_diff"] = comp["top_winners_median_pct"] - comp["all_picks_median_pct"]
    comp = comp.sort_values("month_pct_diff", ascending=False).reset_index(drop=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.output_dir, f"ma120_monthly_winner_profile_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    picks.to_csv(os.path.join(out_dir, "pick_panel_with_profiles.csv"), index=False, encoding="utf-8-sig")
    summary.to_csv(os.path.join(out_dir, "group_feature_summary.csv"), index=False, encoding="utf-8-sig")
    pivot_abs.to_csv(os.path.join(out_dir, "median_absolute_comparison.csv"), encoding="utf-8-sig")
    pivot_pct.to_csv(os.path.join(out_dir, "median_month_percentile_comparison.csv"), encoding="utf-8-sig")
    comp.to_csv(os.path.join(out_dir, "top_winner_vs_all_feature_diff.csv"), index=False, encoding="utf-8-sig")

    report = [
        "# MA120 Monthly Winner Profile",
        "",
        f"- Top winners: {', '.join(top_winners)}",
        "",
        "## Top Winner Snapshot Rows",
        "",
        winners[["symbol", "eval_month", "ret", "pnl_contrib"] + FEATURES].to_markdown(index=False, floatfmt=".4f"),
        "",
        "## Feature Median Comparison",
        "",
        comp.to_markdown(index=False, floatfmt=".4f"),
        "",
        "## Absolute Medians By Group",
        "",
        pivot_abs.to_markdown(floatfmt=".4f"),
        "",
        "## Within-Month Median Percentiles By Group",
        "",
        pivot_pct.to_markdown(floatfmt=".4f"),
    ]
    with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(report))

    print(out_dir)
    print("Top winners:", ", ".join(top_winners))
    print(comp.to_string(index=False))


if __name__ == "__main__":
    main()
