#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Industry filter rolling segment validation for MA120 obs10 pipeline."""

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
    select_candidates,
)


def _split_three_segments(months: List[str]) -> List[List[str]]:
    n = len(months)
    if n < 6:
        return []
    k = n // 3
    if k == 0:
        return []
    seg1 = months[:k]
    seg2 = months[k : 2 * k]
    seg3 = months[2 * k :]
    return [seg1, seg2, seg3]


def _seg_perf(picks: pd.DataFrame) -> Dict[str, float]:
    if picks.empty:
        return {"months": 0, "avg_ret120": np.nan, "win_rate120": np.nan, "pick_count": 0}
    return {
        "months": int(picks["pick_month"].nunique()),
        "avg_ret120": float(picks["ret_120d"].mean()),
        "win_rate120": float((picks["ret_120d"] > 0).mean()),
        "pick_count": int(len(picks)),
    }


def run_roll(
    csv_dir: str,
    a_basic_csv: str,
    max_files: int,
    top_pcts: List[float],
) -> Dict[str, pd.DataFrame]:
    panel = build_events(csv_dir, "sh", obs_days=10, max_files=max_files)
    panel_sz = build_events(csv_dir, "sz", obs_days=10, max_files=max_files)
    panel = pd.concat([panel, panel_sz], ignore_index=True)
    if panel.empty:
        return {"segment": pd.DataFrame(), "overall": pd.DataFrame()}

    industry_map = load_a_industry_map(a_basic_csv)
    panel = add_industry_strength_for_a(panel, industry_map)
    months = sorted(panel["pick_month"].unique().tolist())
    segs = _split_three_segments(months)
    if not segs:
        return {"segment": pd.DataFrame(), "overall": pd.DataFrame()}

    baseline = select_candidates(panel, obs_days=10, use_industry_filter=False, industry_top_pct=0.2)
    rows = []
    overall_rows = []
    for pct in top_pcts:
        filt = select_candidates(panel, obs_days=10, use_industry_filter=True, industry_top_pct=float(pct))
        eff = 0
        for i, seg_m in enumerate(segs, start=1):
            b_seg = baseline[baseline["pick_month"].isin(seg_m)].copy()
            f_seg = filt[filt["pick_month"].isin(seg_m)].copy()
            pb = _seg_perf(b_seg)
            pf = _seg_perf(f_seg)
            alpha = (pf["avg_ret120"] - pb["avg_ret120"]) if (pd.notna(pf["avg_ret120"]) and pd.notna(pb["avg_ret120"])) else np.nan
            valid = bool(pd.notna(alpha) and alpha > 0 and pf["pick_count"] >= 10)
            if valid:
                eff += 1
            rows.append(
                {
                    "industry_top_pct": pct,
                    "segment": f"S{i}",
                    "months": ",".join(seg_m),
                    "base_avg_ret120": pb["avg_ret120"],
                    "filt_avg_ret120": pf["avg_ret120"],
                    "alpha_ret120": alpha,
                    "base_win_rate120": pb["win_rate120"],
                    "filt_win_rate120": pf["win_rate120"],
                    "base_pick_count": pb["pick_count"],
                    "filt_pick_count": pf["pick_count"],
                    "valid_flag": valid,
                }
            )

        stable = eff >= 2
        overall_rows.append(
            {
                "industry_top_pct": pct,
                "effective_segments": eff,
                "stable_flag": stable,
                "total_segments": len(segs),
            }
        )

    return {
        "segment": pd.DataFrame(rows),
        "overall": pd.DataFrame(overall_rows).sort_values("industry_top_pct"),
    }


def main() -> None:
    p = argparse.ArgumentParser(description="A股行业过滤滚动三段稳定性验证")
    p.add_argument("--csv-dir", default="/Users/water/abu/data/csv")
    p.add_argument("--a-basic-csv", default="/Users/water/mylearn/PycharmProjects/abu-master/todolist/stock_A_basic_list.csv")
    p.add_argument("--output-dir", default="/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output")
    p.add_argument("--max-files", type=int, default=2500)
    p.add_argument("--top-pcts", nargs="+", type=float, default=[0.2, 0.3, 0.4])
    args = p.parse_args()

    res = run_roll(
        csv_dir=args.csv_dir,
        a_basic_csv=args.a_basic_csv,
        max_files=args.max_files,
        top_pcts=args.top_pcts,
    )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.output_dir, f"industry_filter_roll_validation_{ts}")
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
