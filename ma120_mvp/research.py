"""Grouped research reports for MA120 forward-test results."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Dict

import pandas as pd


def _contains(text: object, token: str) -> bool:
    return token in str(text or "")


def _bucket_series(series: pd.Series, bins, labels) -> pd.Series:
    return pd.cut(pd.to_numeric(series, errors="coerce"), bins=bins, labels=labels, include_lowest=True, right=True)


def add_research_factors(df: pd.DataFrame) -> pd.DataFrame:
    """Add reusable categorical factors for grouped research."""
    out = df.copy()
    signals = out.get("signals", pd.Series([""] * len(out)))
    out["signal_has_new_ma120"] = signals.apply(lambda x: _contains(x, "新站上MA120观察"))
    out["signal_has_breakout"] = signals.apply(lambda x: _contains(x, "突破") and _contains(x, "高点观察"))
    out["signal_has_pullback"] = signals.apply(lambda x: _contains(x, "回踩均线企稳观察"))

    def combo(row) -> str:
        parts = []
        if row["signal_has_new_ma120"]:
            parts.append("新站上")
        if row["signal_has_breakout"]:
            parts.append("突破")
        if row["signal_has_pullback"]:
            parts.append("回踩")
        return "+".join(parts) if parts else "无明确信号"

    out["signal_combo"] = out.apply(combo, axis=1)
    out["ma120_distance_bucket"] = _bucket_series(
        out["price_vs_ma120_pct"],
        bins=[-0.01, 3, 8, 15, 25, 35, 999],
        labels=["0-3%", "3-8%", "8-15%", "15-25%", "25-35%", ">35%"],
    )
    out["ma120_slope_bucket"] = _bucket_series(
        out["ma120_slope_pct"],
        bins=[-0.01, 0.5, 1, 2, 4, 999],
        labels=["0-0.5%", "0.5-1%", "1-2%", "2-4%", ">4%"],
    )
    out["days_above_bucket"] = _bucket_series(
        out["days_above_ma120"],
        bins=[0, 3, 5, 10, 20, 60, 120, 9999],
        labels=["1-3", "4-5", "6-10", "11-20", "21-60", "61-120", ">120"],
    )
    out["drawdown20_bucket"] = _bucket_series(
        out["drawdown_20d_pct"],
        bins=[-999, -20, -15, -10, -5, 0, 999],
        labels=["<-20%", "-20~-15%", "-15~-10%", "-10~-5%", "-5~0%", ">0%"],
    )
    vol = pd.to_numeric(out.get("volume_ratio", pd.Series([pd.NA] * len(out))), errors="coerce")
    out["volume_ratio_bucket"] = pd.cut(
        vol,
        bins=[-999, 0.8, 1.2, 2, 3, 999],
        labels=["<0.8", "0.8-1.2", "1.2-2", "2-3", ">3"],
        include_lowest=True,
    )
    out["score_bucket"] = _bucket_series(
        out["total_score"],
        bins=[0, 60, 70, 80, 90, 100],
        labels=["<=60", "60-70", "70-80", "80-90", "90-100"],
    )
    return out


def summarize_group(df: pd.DataFrame, group_col: str, min_signals: int = 5) -> pd.DataFrame:
    """Summarize forward-test performance by one factor."""
    if df is None or df.empty:
        return pd.DataFrame()
    hit_cols = [c for c in df.columns if c.startswith("hit_") and c.endswith("pct")]
    target_before_stop_cols = [c for c in df.columns if c.startswith("hit_") and c.endswith("pct_before_stop")]
    agg = {
        "ts_code": "count",
        "max_gain_pct": "mean",
        "max_drawdown_pct": "mean",
        "final_return_pct": "mean",
        "hit_stop_loss": "mean",
    }
    for col in hit_cols:
        agg[col] = "mean"
    for col in target_before_stop_cols:
        agg[col] = "mean"
    summary = df.groupby(group_col, dropna=False, observed=False).agg(agg).rename(columns={"ts_code": "signals"})
    summary = summary[summary["signals"] >= min_signals].copy()
    if summary.empty:
        return summary
    dd = summary["max_drawdown_pct"].abs().replace(0, pd.NA)
    summary["gain_drawdown_ratio"] = summary["max_gain_pct"] / dd
    if "hit_10pct_before_stop" in summary.columns:
        summary["manual_trade_score"] = summary["hit_10pct_before_stop"] - summary["hit_stop_loss"]
        sort_cols = ["manual_trade_score", "hit_10pct_before_stop", "hit_stop_loss", "gain_drawdown_ratio"]
        ascending = [False, False, True, False]
    else:
        sort_cols = ["gain_drawdown_ratio", "hit_stop_loss"]
        ascending = [False, True]
    return summary.round(4).sort_values(sort_cols, ascending=ascending)


def build_research_tables(df: pd.DataFrame, min_signals: int = 5) -> Dict[str, pd.DataFrame]:
    """Build all research group tables."""
    data = add_research_factors(df)
    factors = [
        "signal_combo",
        "ma120_distance_bucket",
        "ma120_slope_bucket",
        "days_above_bucket",
        "drawdown20_bucket",
        "volume_ratio_bucket",
        "score_bucket",
        "candidate_level",
    ]
    return {factor: summarize_group(data, factor, min_signals=min_signals) for factor in factors}


def save_research_tables(tables: Dict[str, pd.DataFrame], out_dir: str | None = None) -> str:
    """Save each research table to a CSV file."""
    if out_dir is None:
        today = datetime.now().strftime("%Y%m%d")
        out_dir = os.path.join("ma120_mvp", "output", f"research_{today}")
    os.makedirs(out_dir, exist_ok=True)
    for name, table in tables.items():
        table.to_csv(os.path.join(out_dir, f"{name}.csv"), encoding="utf-8-sig")
    return out_dir
