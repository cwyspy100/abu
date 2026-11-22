#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compare round-level characteristics for moderate_non_crowded + Top8.

Focus on entry rounds 2026-01 / 2026-02 / 2026-03 that map to portfolio entry
on 2026-02 / 2026-03 / 2026-04.
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime
from typing import Dict, List

import pandas as pd


BASE_FEATURES = [
    "score",
    "price_vs_ma120",
    "dist_to_high60",
    "volume_ratio20",
    "up_ratio20",
    "above_days",
    "ma120_slope20",
    "ret20",
    "ret60",
    "drawdown20",
    "ret_fwd_20d",
    "ret_fwd_40d",
    "ret_fwd_60d",
]


def summarize_pool(df: pd.DataFrame, label: str) -> Dict[str, object]:
    row: Dict[str, object] = {
        "label": label,
        "count": int(len(df)),
    }
    if len(df) == 0:
        for col in BASE_FEATURES:
            row[f"{col}_median"] = None
        row["ret_fwd20_pos_rate"] = None
        row["ret_fwd40_pos_rate"] = None
        row["ret_fwd60_pos_rate"] = None
        return row
    for col in BASE_FEATURES:
        row[f"{col}_median"] = float(pd.to_numeric(df[col], errors="coerce").median()) if col in df.columns else None
    row["ret_fwd20_pos_rate"] = float((pd.to_numeric(df["ret_fwd_20d"], errors="coerce") > 0).mean()) if "ret_fwd_20d" in df.columns else None
    row["ret_fwd40_pos_rate"] = float((pd.to_numeric(df["ret_fwd_40d"], errors="coerce") > 0).mean()) if "ret_fwd_40d" in df.columns else None
    row["ret_fwd60_pos_rate"] = float((pd.to_numeric(df["ret_fwd_60d"], errors="coerce") > 0).mean()) if "ret_fwd_60d" in df.columns else None
    return row


def selected_trade_summary(trades: pd.DataFrame) -> Dict[str, object]:
    row: Dict[str, object] = {"selected_trade_n": int(len(trades))}
    if len(trades) == 0:
        row.update(
            {
                "selected_win_rate": None,
                "selected_avg_ret": None,
                "selected_pnl_contrib": None,
                "selected_stop_rate": None,
            }
        )
        return row
    row["selected_win_rate"] = float((pd.to_numeric(trades["ret"], errors="coerce") > 0).mean())
    row["selected_avg_ret"] = float(pd.to_numeric(trades["ret"], errors="coerce").mean())
    row["selected_pnl_contrib"] = float(pd.to_numeric(trades["pnl_contrib"], errors="coerce").sum())
    row["selected_stop_rate"] = float((trades["reason"].astype(str) == "stop10").mean())
    return row


def main() -> None:
    parser = argparse.ArgumentParser(description="Round-level comparison for moderate_non_crowded + Top8.")
    parser.add_argument("--full-panel-csv", required=True)
    parser.add_argument("--moderate-panel-csv", required=True)
    parser.add_argument("--top8-trades-csv", required=True)
    parser.add_argument("--output-dir", default="cy_quant/output")
    args = parser.parse_args()

    full_panel = pd.read_csv(args.full_panel_csv)
    moderate_panel = pd.read_csv(args.moderate_panel_csv)
    top8_trades = pd.read_csv(args.top8_trades_csv)

    full_panel["eval_month"] = full_panel["eval_month"].astype(str)
    moderate_panel["eval_month"] = moderate_panel["eval_month"].astype(str)
    top8_trades["entry_month"] = pd.to_datetime(top8_trades["entry_date"]).dt.to_period("M").astype(str)

    round_months = ["2026-01", "2026-02", "2026-03"]
    rows: List[Dict[str, object]] = []

    for month in round_months:
        full_month = full_panel[(full_panel["eval_month"] == month) & (pd.to_numeric(full_panel["above_days"], errors="coerce") >= 30)].copy()
        moderate_month = moderate_panel[moderate_panel["eval_month"] == month].copy()
        selected_month = top8_trades[top8_trades["entry_month"] == str((pd.Period(month) + 1).strftime("%Y-%m"))].copy()

        row: Dict[str, object] = {
            "eval_month": month,
            "entry_month": str((pd.Period(month) + 1).strftime("%Y-%m")),
            "full_pool_n": int(len(full_month)),
            "moderate_pool_n": int(len(moderate_month)),
            "moderate_pass_ratio": float(len(moderate_month) / len(full_month)) if len(full_month) else None,
        }
        row.update({f"full_{k}": v for k, v in summarize_pool(full_month, "full").items() if k not in {"label", "count"}})
        row.update({f"moderate_{k}": v for k, v in summarize_pool(moderate_month, "moderate").items() if k not in {"label", "count"}})
        row.update(selected_trade_summary(selected_month))
        rows.append(row)

    summary = pd.DataFrame(rows)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.output_dir, f"ma120_monthly_round_filter_compare_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    summary.to_csv(os.path.join(out_dir, "round_summary.csv"), index=False, encoding="utf-8-sig")

    keep_cols = [
        "eval_month",
        "entry_month",
        "full_pool_n",
        "moderate_pool_n",
        "moderate_pass_ratio",
        "full_ret_fwd20_pos_rate",
        "moderate_ret_fwd20_pos_rate",
        "full_ret_fwd40_pos_rate",
        "moderate_ret_fwd40_pos_rate",
        "full_ret_fwd60_pos_rate",
        "moderate_ret_fwd60_pos_rate",
        "full_score_median",
        "moderate_score_median",
        "full_ret20_median",
        "moderate_ret20_median",
        "full_ret60_median",
        "moderate_ret60_median",
        "full_price_vs_ma120_median",
        "moderate_price_vs_ma120_median",
        "full_dist_to_high60_median",
        "moderate_dist_to_high60_median",
        "full_volume_ratio20_median",
        "moderate_volume_ratio20_median",
        "full_up_ratio20_median",
        "moderate_up_ratio20_median",
        "selected_trade_n",
        "selected_win_rate",
        "selected_avg_ret",
        "selected_pnl_contrib",
        "selected_stop_rate",
    ]
    report = [
        "# MA120 Monthly Round Filter Compare",
        "",
        "## Round Summary",
        "",
        summary[keep_cols].to_markdown(index=False, floatfmt=".4f"),
    ]
    with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(report))

    print(out_dir)
    print(summary[keep_cols].to_string(index=False))


if __name__ == "__main__":
    main()
