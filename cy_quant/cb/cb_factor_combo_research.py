"""可转债因子叠加分层研究（第二阶段）。"""

from __future__ import annotations

import argparse
import os
from datetime import datetime
from typing import Dict, List

import pandas as pd

from cy_quant.cb.cb_factor_decile_research import build_panel, run_decile_test, FactorSpec


def _rank_score(panel: pd.DataFrame, col: str, ascending_better: bool) -> pd.Series:
    """按日截面把单因子变成 0~1 rank 分数，统一到“越高越好”。"""
    grouped = panel.groupby("trade_date")[col]
    if ascending_better:
        # 原始因子越低越好 => rank 取反
        return grouped.rank(pct=True, ascending=False)
    return grouped.rank(pct=True, ascending=True)


def build_combo_factors(panel: pd.DataFrame) -> pd.DataFrame:
    out = panel.copy()
    out["s_low_premium"] = _rank_score(out, "bond_over_rate", ascending_better=True)
    out["s_double_low"] = _rank_score(out, "double_low", ascending_better=True)
    out["s_stock_trend"] = _rank_score(out, "stock_trend_120", ascending_better=False)
    out["s_call_risk"] = _rank_score(out, "call_risk_proxy", ascending_better=True)

    out["combo_dl_trend"] = out[["s_double_low", "s_stock_trend"]].mean(axis=1)
    out["combo_dl_trend_call"] = out[["s_double_low", "s_stock_trend", "s_call_risk"]].mean(axis=1)
    out["combo_lp_trend"] = out[["s_low_premium", "s_stock_trend"]].mean(axis=1)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="可转债因子叠加分层研究")
    parser.add_argument("--cb-daily", default="/Users/water/abu/data/cb/cb_daily_20240527_20260527.csv")
    parser.add_argument("--cb-basic", default="/Users/water/abu/data/cb/cb_basic.csv")
    parser.add_argument("--out-dir", default="cy_quant/output")
    parser.add_argument("--min-cross-section", type=int, default=50)
    args = parser.parse_args()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.out_dir, f"cb_combo_research_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    panel = build_panel(args.cb_daily, args.cb_basic)
    panel = build_combo_factors(panel)

    combos: List[FactorSpec] = [
        FactorSpec("combo_dl_trend", "combo_dl_trend", False, "双低 + 趋势 叠加分数（高分更优）"),
        FactorSpec("combo_dl_trend_call", "combo_dl_trend_call", False, "双低 + 趋势 + 强赎风险 叠加分数（高分更优）"),
        FactorSpec("combo_lp_trend", "combo_lp_trend", False, "低溢价 + 趋势 叠加分数（高分更优）"),
    ]

    rows: List[Dict[str, object]] = []
    for fac in combos:
        for h in (20, 60, 120):
            rows.append(run_decile_test(panel, fac, h, min_cross_section=args.min_cross_section))

    summary = pd.DataFrame(rows)
    summary_path = os.path.join(out_dir, "combo_decile_summary.csv")
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")

    pivot = summary.pivot_table(
        index=["factor", "description"],
        columns="horizon",
        values="spread_annualized",
        aggfunc="first",
    )
    pivot_path = os.path.join(out_dir, "combo_spread_annualized_pivot.csv")
    pivot.to_csv(pivot_path, encoding="utf-8-sig")

    print(f"组合研究完成 -> {out_dir}")
    print(f"摘要文件 -> {summary_path}")


if __name__ == "__main__":
    main()
