"""真实强赎事件过滤 vs 价格代理过滤 对照回测。"""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timedelta
from typing import Dict, List

import numpy as np
import pandas as pd

from cy_quant.cb.cb_factor_decile_research import build_panel
from cy_quant.cb.cb_factor_combo_research import build_combo_factors
from cy_quant.cb.cb_combo_monthly_backtest import run_backtest, summarize


def _parse_ymd(v: object) -> pd.Timestamp:
    if pd.isna(v):
        return pd.NaT
    s = str(v).split(".")[0]
    if not s or s.lower() == "nan":
        return pd.NaT
    return pd.to_datetime(s, format="%Y%m%d", errors="coerce")


def build_real_call_intervals(cb_call_path: str, default_days: int = 30) -> pd.DataFrame:
    d = pd.read_csv(cb_call_path, dtype={"ts_code": str})
    if d.empty:
        return pd.DataFrame(columns=["ts_code", "start", "end"])

    for c in ["call_type", "is_call", "ann_date", "call_date"]:
        if c not in d.columns:
            d[c] = ""

    d["ann_date"] = d["ann_date"].apply(_parse_ymd)
    d["call_date"] = d["call_date"].apply(_parse_ymd)

    # 真实强赎风险：强赎类，且不是“不强赎”公告
    mask = d["call_type"].astype(str).str.contains("强赎", na=False) & (~d["is_call"].astype(str).str.contains("不强赎", na=False))
    d = d[mask].copy()
    if d.empty:
        return pd.DataFrame(columns=["ts_code", "start", "end"])

    d["start"] = d["ann_date"]
    d["end"] = d["call_date"]
    miss = d["end"].isna()
    d.loc[miss, "end"] = d.loc[miss, "start"] + timedelta(days=default_days)

    out = d[["ts_code", "start", "end"]].dropna()
    out = out[out["end"] >= out["start"]].copy()
    return out.reset_index(drop=True)


def apply_real_call_filter(panel: pd.DataFrame, intervals: pd.DataFrame) -> pd.DataFrame:
    if panel.empty or intervals.empty:
        return panel.copy()

    out = panel.copy()
    out["_drop"] = False

    intervals_by_code: Dict[str, List[tuple[pd.Timestamp, pd.Timestamp]]] = {}
    for r in intervals.itertuples(index=False):
        intervals_by_code.setdefault(str(r.ts_code), []).append((r.start, r.end))

    for code, sub_idx in out.groupby("ts_code").groups.items():
        ivs = intervals_by_code.get(str(code))
        if not ivs:
            continue
        idx = list(sub_idx)
        td = out.loc[idx, "trade_date"]
        drop_mask = pd.Series(False, index=td.index)
        for st, ed in ivs:
            drop_mask = drop_mask | ((td >= st) & (td <= ed))
        out.loc[idx, "_drop"] = drop_mask.values

    out = out[~out["_drop"]].drop(columns=["_drop"]).reset_index(drop=True)
    return out


def main() -> None:
    p = argparse.ArgumentParser(description="真实强赎过滤对照回测")
    p.add_argument("--cb-daily", default="/Users/water/abu/data/cb/cb_daily_20240527_20260527.csv")
    p.add_argument("--cb-basic", default="/Users/water/abu/data/cb/cb_basic.csv")
    p.add_argument("--cb-call", default="/Users/water/abu/data/cb/cb_call_20240527_20260527.csv")
    p.add_argument("--out-dir", default="cy_quant/output")
    p.add_argument("--top-n", type=int, default=20)
    p.add_argument("--min-amount-wan", type=float, default=3000.0)
    p.add_argument("--roundtrip-cost-bps", type=float, default=40.0)
    p.add_argument("--proxy-max-price", type=float, default=140.0)
    args = p.parse_args()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.out_dir, f"cb_real_call_compare_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    panel = build_combo_factors(build_panel(args.cb_daily, args.cb_basic))
    intervals = build_real_call_intervals(args.cb_call)
    panel_real = apply_real_call_filter(panel, intervals)

    strategies = ["combo_dl_trend", "combo_dl_trend_call", "combo_lp_trend"]

    rows = []
    for mode, pnl, max_price in [
        ("proxy_price_filter", panel, args.proxy_max_price),
        ("real_call_filter", panel_real, 9999.0),
    ]:
        for st in strategies:
            perf, _ = run_backtest(
                pnl,
                st,
                top_n=args.top_n,
                min_amount_wan=args.min_amount_wan,
                max_price_for_call_risk=max_price,
                roundtrip_cost_bps=args.roundtrip_cost_bps,
            )
            s = summarize(perf)
            s["mode"] = mode
            s["strategy"] = st
            rows.append(s)
            perf.to_csv(os.path.join(out_dir, f"perf_{mode}_{st}.csv"), index=False, encoding="utf-8-sig")

    summary = pd.DataFrame(rows)
    summary = summary[["mode", "strategy", "periods", "ann_return", "max_drawdown", "win_rate", "avg_period_ret", "avg_turnover", "avg_cost"]]
    summary.to_csv(os.path.join(out_dir, "real_call_compare_summary.csv"), index=False, encoding="utf-8-sig")

    meta = pd.DataFrame(
        [
            {
                "panel_rows": len(panel),
                "panel_real_rows": len(panel_real),
                "real_call_intervals": len(intervals),
                "unique_bonds_real_call": intervals["ts_code"].nunique() if not intervals.empty else 0,
            }
        ]
    )
    meta.to_csv(os.path.join(out_dir, "real_call_compare_meta.csv"), index=False, encoding="utf-8-sig")

    print(f"对照回测完成 -> {out_dir}")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
