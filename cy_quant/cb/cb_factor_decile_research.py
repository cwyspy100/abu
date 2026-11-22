"""可转债单因子分层研究（Decile Test）。

研究目标：
1) 用本地可转债日线数据做 10 分层
2) 评估未来 20/60/120 日收益
3) 输出可复现结果，供后续因子叠加与组合回测使用
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List

import numpy as np
import pandas as pd


@dataclass
class FactorSpec:
    name: str
    col: str
    ascending_better: bool
    description: str


def _parse_date_any(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce")


def _assign_decile(series: pd.Series, q: int = 10) -> pd.Series:
    """对单日截面因子做 10 分层，返回 1..10。"""
    if series.notna().sum() < q:
        return pd.Series(index=series.index, dtype="float")
    ranked = series.rank(method="first")
    try:
        dec = pd.qcut(ranked, q=q, labels=list(range(1, q + 1)))
        return dec.astype(float)
    except Exception:
        return pd.Series(index=series.index, dtype="float")


def build_panel(cb_daily_path: str, cb_basic_path: str) -> pd.DataFrame:
    daily = pd.read_csv(cb_daily_path, dtype={"trade_date": str, "ts_code": str})
    basic = pd.read_csv(cb_basic_path, dtype={"ts_code": str})

    daily["trade_date"] = pd.to_datetime(daily["trade_date"], format="%Y%m%d", errors="coerce")
    daily = daily.dropna(subset=["trade_date", "ts_code"]).copy()

    # 数值列转换
    num_cols = [
        "pre_close",
        "open",
        "high",
        "low",
        "close",
        "bond_over_rate",
        "cb_value",
        "cb_over_rate",
        "bond_value",
        "amount",
        "vol",
    ]
    for c in num_cols:
        if c in daily.columns:
            daily[c] = pd.to_numeric(daily[c], errors="coerce")

    daily = daily.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)

    # 前瞻收益
    for h in (20, 60, 120):
        daily[f"fwd_ret_{h}d"] = daily.groupby("ts_code")["close"].shift(-h) / daily["close"] - 1.0
        # 清理异常收益（如除零导致的 inf/-inf），避免污染分层均值
        daily[f"fwd_ret_{h}d"] = daily[f"fwd_ret_{h}d"].where(np.isfinite(daily[f"fwd_ret_{h}d"]))

    # 因子：低溢价、双低
    daily["double_low"] = daily["close"] + daily["bond_over_rate"]

    # 因子：正股趋势代理（用转股价值 cb_value 代替正股价格）
    ma120 = daily.groupby("ts_code")["cb_value"].transform(lambda s: s.rolling(120, min_periods=60).mean())
    daily["stock_trend_120"] = daily["cb_value"] / ma120 - 1.0

    # 因子：强赎风险代理（价格越高通常越接近触发强赎区）
    daily["call_risk_proxy"] = daily["close"]

    # 因子：剩余期限（用 delist_date 近似）
    basic = basic[["ts_code", "delist_date"]].copy()
    basic["delist_date"] = _parse_date_any(basic["delist_date"])
    daily = daily.merge(basic, on="ts_code", how="left")
    daily["remaining_term_days"] = (daily["delist_date"] - daily["trade_date"]).dt.days

    return daily


def run_decile_test(panel: pd.DataFrame, factor: FactorSpec, horizon: int, min_cross_section: int = 50) -> Dict[str, object]:
    col_ret = f"fwd_ret_{horizon}d"
    cols = ["trade_date", "ts_code", factor.col, col_ret]
    df = panel[cols].dropna(subset=[factor.col, col_ret]).copy()
    if df.empty:
        return {
            "factor": factor.name,
            "description": factor.description,
            "horizon": horizon,
            "obs": 0,
            "dates": 0,
            "best_decile": np.nan,
            "worst_decile": np.nan,
            "best_mean_ret": np.nan,
            "worst_mean_ret": np.nan,
            "spread": np.nan,
            "spread_annualized": np.nan,
            "signed_ic": np.nan,
            "best_minus_worst_sign": "N/A",
        }

    # 截面样本太少的交易日剔除
    sizes = df.groupby("trade_date")["ts_code"].size()
    valid_days = sizes[sizes >= min_cross_section].index
    df = df[df["trade_date"].isin(valid_days)].copy()
    if df.empty:
        return {
            "factor": factor.name,
            "description": factor.description,
            "horizon": horizon,
            "obs": 0,
            "dates": 0,
            "best_decile": np.nan,
            "worst_decile": np.nan,
            "best_mean_ret": np.nan,
            "worst_mean_ret": np.nan,
            "spread": np.nan,
            "spread_annualized": np.nan,
            "signed_ic": np.nan,
            "best_minus_worst_sign": "N/A",
        }

    df["decile"] = df.groupby("trade_date", group_keys=False)[factor.col].apply(_assign_decile)
    df = df.dropna(subset=["decile"]).copy()
    df["decile"] = df["decile"].astype(int)

    # 每日分层收益 -> 再对日期平均
    daily_dec = (
        df.groupby(["trade_date", "decile"], as_index=False)[col_ret]
        .mean()
        .rename(columns={col_ret: "ret"})
    )
    dec_mean = daily_dec.groupby("decile")["ret"].mean().reindex(range(1, 11))

    best_decile = 1 if factor.ascending_better else 10
    worst_decile = 10 if factor.ascending_better else 1

    best_mean = dec_mean.loc[best_decile]
    worst_mean = dec_mean.loc[worst_decile]
    spread = best_mean - worst_mean
    if pd.notna(spread) and spread > -0.999:
        spread_ann = (1.0 + spread) ** (252.0 / float(horizon)) - 1.0
    else:
        spread_ann = np.nan

    # 日度 rank IC（按方向统一符号）
    ic_rows: List[float] = []
    for d, g in df.groupby("trade_date"):
        if len(g) < 20:
            continue
        x = g[factor.col]
        if factor.ascending_better:
            x = -x
        ic = x.rank(pct=True).corr(g[col_ret].rank(pct=True), method="spearman")
        if pd.notna(ic):
            ic_rows.append(float(ic))
    signed_ic = float(np.mean(ic_rows)) if ic_rows else np.nan

    return {
        "factor": factor.name,
        "description": factor.description,
        "horizon": horizon,
        "obs": int(len(df)),
        "dates": int(df["trade_date"].nunique()),
        "best_decile": best_decile,
        "worst_decile": worst_decile,
        "best_mean_ret": float(best_mean) if pd.notna(best_mean) else np.nan,
        "worst_mean_ret": float(worst_mean) if pd.notna(worst_mean) else np.nan,
        "spread": float(spread) if pd.notna(spread) else np.nan,
        "spread_annualized": float(spread_ann) if pd.notna(spread_ann) else np.nan,
        "signed_ic": signed_ic,
        "best_minus_worst_sign": "positive" if pd.notna(spread) and spread > 0 else "non_positive",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="可转债单因子 Decile 分层研究")
    parser.add_argument("--cb-daily", default="/Users/water/abu/data/cb/cb_daily_20240527_20260527.csv")
    parser.add_argument("--cb-basic", default="/Users/water/abu/data/cb/cb_basic.csv")
    parser.add_argument("--out-dir", default="cy_quant/output")
    parser.add_argument("--min-cross-section", type=int, default=50)
    args = parser.parse_args()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.out_dir, f"cb_decile_research_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    panel = build_panel(args.cb_daily, args.cb_basic)

    factors = [
        FactorSpec("low_premium", "bond_over_rate", True, "低溢价（bond_over_rate，越低越好）"),
        FactorSpec("double_low", "double_low", True, "双低（close + bond_over_rate，越低越好）"),
        FactorSpec("stock_trend_proxy", "stock_trend_120", False, "正股趋势代理（cb_value/MA120-1，越高越好）"),
        FactorSpec("call_risk_proxy", "call_risk_proxy", True, "强赎风险代理（close，越低风险越小）"),
        FactorSpec("remaining_term", "remaining_term_days", False, "剩余期限（delist_date-trade_date，越长越好）"),
    ]

    results = []
    for fac in factors:
        for h in (20, 60, 120):
            res = run_decile_test(panel, fac, h, min_cross_section=args.min_cross_section)
            results.append(res)

    summary = pd.DataFrame(results)
    summary_path = os.path.join(out_dir, "factor_decile_summary.csv")
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")

    # 额外输出：可读的透视表
    pivot = summary.pivot_table(
        index=["factor", "description"],
        columns="horizon",
        values="spread_annualized",
        aggfunc="first",
    )
    pivot_path = os.path.join(out_dir, "spread_annualized_pivot.csv")
    pivot.to_csv(pivot_path, encoding="utf-8-sig")

    meta = {
        "out_dir": out_dir,
        "summary": summary_path,
        "pivot": pivot_path,
        "rows": len(summary),
        "trade_days": int(panel["trade_date"].nunique()),
        "bonds": int(panel["ts_code"].nunique()),
    }
    meta_path = os.path.join(out_dir, "run_meta.json")
    pd.Series(meta).to_json(meta_path, force_ascii=False, indent=2)

    print(f"研究完成 -> {out_dir}")
    print(f"摘要文件 -> {summary_path}")


if __name__ == "__main__":
    main()
