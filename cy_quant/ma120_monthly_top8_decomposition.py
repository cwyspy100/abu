#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Decompose moderate_non_crowded + Top8 holdings and month structure."""

from __future__ import annotations

import argparse
import os
from datetime import datetime
from typing import Dict, List

import pandas as pd


def month_trade_summary(trades: pd.DataFrame) -> pd.DataFrame:
    t = trades.copy()
    t["entry_month"] = pd.to_datetime(t["entry_date"]).dt.to_period("M").astype(str)
    return (
        t.groupby("entry_month", as_index=False)
        .agg(
            trades=("symbol", "count"),
            winners=("ret", lambda s: int((pd.to_numeric(s, errors="coerce") > 0).sum())),
            stop_count=("reason", lambda s: int((s == "stop10").sum())),
            rebalance_count=("reason", lambda s: int((s == "rebalance").sum())),
            avg_ret=("ret", "mean"),
            pnl_contrib=("pnl_contrib", "sum"),
        )
        .sort_values("entry_month")
        .reset_index(drop=True)
    )


def symbol_summary(trades: pd.DataFrame) -> pd.DataFrame:
    t = trades.copy()
    return (
        t.groupby("symbol", as_index=False)
        .agg(
            trades=("symbol", "count"),
            avg_ret=("ret", "mean"),
            pnl_contrib=("pnl_contrib", "sum"),
            stop_count=("reason", lambda s: int((s == "stop10").sum())),
            rebalance_count=("reason", lambda s: int((s == "rebalance").sum())),
        )
        .sort_values("pnl_contrib", ascending=False)
        .reset_index(drop=True)
    )


def selected_panel_summary(panel: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    p = panel.copy()
    p["eval_month"] = p["eval_month"].astype(str)
    t = trades.copy()
    t["entry_month"] = pd.to_datetime(t["entry_date"]).dt.to_period("M").astype(str)
    merged = p.merge(t[["symbol", "entry_month", "ret", "reason", "pnl_contrib"]], left_on=["symbol", "eval_month"], right_on=["symbol", "entry_month"], how="inner")
    rows: List[Dict[str, object]] = []
    feat_cols = ["price_vs_ma120", "dist_to_high60", "volume_ratio20", "up_ratio20", "above_days", "ma120_slope20", "score"]
    for month, grp in merged.groupby("eval_month"):
        row: Dict[str, object] = {"eval_month": month, "selected_n": int(len(grp)), "avg_ret": float(grp["ret"].mean()), "pnl_contrib": float(grp["pnl_contrib"].sum())}
        for col in feat_cols:
            row[f"{col}_median"] = float(pd.to_numeric(grp[col], errors="coerce").median())
        rows.append(row)
    return pd.DataFrame(rows).sort_values("eval_month").reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Decompose moderate_non_crowded + Top8 structure.")
    parser.add_argument("--trades-csv", required=True)
    parser.add_argument("--panel-csv", required=True)
    parser.add_argument("--output-dir", default="cy_quant/output")
    args = parser.parse_args()

    trades = pd.read_csv(args.trades_csv)
    panel = pd.read_csv(args.panel_csv)

    by_month = month_trade_summary(trades)
    by_symbol = symbol_summary(trades)
    by_selected_month = selected_panel_summary(panel, trades)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.output_dir, f"ma120_monthly_top8_decomp_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    by_month.to_csv(os.path.join(out_dir, "entry_month_summary.csv"), index=False, encoding="utf-8-sig")
    by_symbol.to_csv(os.path.join(out_dir, "symbol_summary.csv"), index=False, encoding="utf-8-sig")
    by_selected_month.to_csv(os.path.join(out_dir, "selected_month_profile.csv"), index=False, encoding="utf-8-sig")

    report = [
        "# MA120 Monthly Top8 Decomposition",
        "",
        "## Entry Month Summary",
        "",
        by_month.to_markdown(index=False, floatfmt=".4f"),
        "",
        "## Top Symbol Contributors",
        "",
        by_symbol.head(12).to_markdown(index=False, floatfmt=".4f"),
        "",
        "## Selected Month Feature Profile",
        "",
        by_selected_month.to_markdown(index=False, floatfmt=".4f"),
    ]
    with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(report))

    print(out_dir)
    print("Entry month summary:")
    print(by_month.to_string(index=False))
    print("\nTop symbol contributors:")
    print(by_symbol.head(12).to_string(index=False))


if __name__ == "__main__":
    main()
