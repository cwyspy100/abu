#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Monthly cross-section split validation for industry filter on A-share MA120 events."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from typing import Dict, List

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from cy_quant.datacsv_obs10_latest_candidates import (
    add_industry_strength_for_a,
    build_events,
    load_a_industry_map,
)


def _split_three(months: List[str]) -> List[List[str]]:
    n = len(months)
    if n < 9:
        return []
    k = n // 3
    return [months[:k], months[k : 2 * k], months[2 * k :]]


def _pick_monthly_top30(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    return (
        df.sort_values(["pick_month", "total_score"], ascending=[True, False])
        .groupby("pick_month", as_index=False)
        .head(30)
        .copy()
    )


def _seg_stats(df: pd.DataFrame) -> Dict[str, float]:
    if df.empty:
        return {"ret120": np.nan, "win120": np.nan, "n": 0}
    return {
        "ret120": float(df["ret_120d"].mean()),
        "win120": float((df["ret_120d"] > 0).mean()),
        "n": int(len(df)),
    }


def run(csv_dir: str, a_basic_csv: str, max_files: int, top_pcts: List[float]) -> Dict[str, pd.DataFrame]:
    panel = pd.concat(
        [
            build_events(csv_dir, "sh", obs_days=10, max_files=max_files),
            build_events(csv_dir, "sz", obs_days=10, max_files=max_files),
        ],
        ignore_index=True,
    )
    if panel.empty:
        return {"segment": pd.DataFrame(), "overall": pd.DataFrame()}

    panel = add_industry_strength_for_a(panel, load_a_industry_map(a_basic_csv))
    months = sorted(panel["pick_month"].unique().tolist())
    segs = _split_three(months)
    if not segs:
        return {"segment": pd.DataFrame(), "overall": pd.DataFrame()}

    base_picks = _pick_monthly_top30(panel)
    seg_rows = []
    ov_rows = []
    for pct in top_pcts:
        filt = panel[panel["industry_strength_score"] >= (1.0 - float(pct))].copy()
        filt_picks = _pick_monthly_top30(filt)
        eff = 0
        for i, seg_m in enumerate(segs, start=1):
            b = base_picks[base_picks["pick_month"].isin(seg_m)]
            f = filt_picks[filt_picks["pick_month"].isin(seg_m)]
            sb = _seg_stats(b)
            sf = _seg_stats(f)
            alpha = (sf["ret120"] - sb["ret120"]) if (pd.notna(sf["ret120"]) and pd.notna(sb["ret120"])) else np.nan
            valid = bool(pd.notna(alpha) and alpha > 0 and sf["n"] >= 30)
            if valid:
                eff += 1
            seg_rows.append(
                {
                    "industry_top_pct": pct,
                    "segment": f"S{i}",
                    "months": ",".join(seg_m),
                    "base_ret120": sb["ret120"],
                    "filt_ret120": sf["ret120"],
                    "alpha_ret120": alpha,
                    "base_win120": sb["win120"],
                    "filt_win120": sf["win120"],
                    "base_n": sb["n"],
                    "filt_n": sf["n"],
                    "valid_flag": valid,
                }
            )
        ov_rows.append(
            {
                "industry_top_pct": pct,
                "effective_segments": eff,
                "stable_flag": eff >= 2,
                "total_segments": len(segs),
            }
        )
    return {"segment": pd.DataFrame(seg_rows), "overall": pd.DataFrame(ov_rows).sort_values("industry_top_pct")}


def main() -> None:
    p = argparse.ArgumentParser(description="行业过滤月截面三段验证")
    p.add_argument("--csv-dir", default="/Users/water/abu/data/csv")
    p.add_argument("--a-basic-csv", default="/Users/water/mylearn/PycharmProjects/abu-master/todolist/stock_A_basic_list.csv")
    p.add_argument("--output-dir", default="/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output")
    p.add_argument("--max-files", type=int, default=2500)
    p.add_argument("--top-pcts", nargs="+", type=float, default=[0.2, 0.3, 0.4])
    args = p.parse_args()

    res = run(args.csv_dir, args.a_basic_csv, args.max_files, args.top_pcts)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.output_dir, f"industry_filter_roll_monthly_{ts}")
    os.makedirs(out_dir, exist_ok=True)
    seg_csv = os.path.join(out_dir, "segment_validation.csv")
    ov_csv = os.path.join(out_dir, "overall_stability.csv")
    res["segment"].to_csv(seg_csv, index=False, encoding="utf-8-sig")
    res["overall"].to_csv(ov_csv, index=False, encoding="utf-8-sig")
    print("done")
    print(f"segment_validation: {seg_csv}")
    print(f"overall_stability: {ov_csv}")


if __name__ == "__main__":
    main()
