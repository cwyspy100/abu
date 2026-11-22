"""可转债指数均线风控过滤研究。"""

from __future__ import annotations

import argparse
import os
from datetime import datetime
from typing import Dict, Iterable

import numpy as np
import pandas as pd

from cy_quant.cb.cb_diversification_walkforward_compare import run_mode
from cy_quant.cb.cb_factor_combo_research import build_combo_factors
from cy_quant.cb.cb_factor_decile_research import build_panel
from cy_quant.cb.cb_real_call_filter_backtest import apply_real_call_filter, build_real_call_intervals


INDEX_SPECS: Dict[str, list[str]] = {
    "hs300": [
        "/Users/water/abu/data/csv/astock/sh000300_20140708_20250309",
        "/Users/water/abu/data/csv/sh000300_20240126_20260614",
    ],
    "csi500": [
        "/Users/water/abu/data/csv/astock/sz000905_20140708_20250309",
        "/Users/water/abu/data/csv/sz000905_20240126_20260614",
    ],
    "csi1000": [
        "/Users/water/abu/data/csv/astock/sh000852_20140708_20250309",
    ],
    "guozheng2000": [
        "/Users/water/abu/data/csv/astock/sz399303_20140708_20250309",
        "/Users/water/abu/data/csv/sz399303_20240126_20260314",
    ],
}


def load_index_series(paths: Iterable[str], ma_window: int) -> pd.DataFrame:
    parts = []
    for path in paths:
        if not os.path.exists(path):
            continue
        d = pd.read_csv(path)
        if d.empty:
            continue
        if "Unnamed: 0" in d.columns:
            d = d.rename(columns={"Unnamed: 0": "trade_date"})
        elif "trade_date" not in d.columns and "date" in d.columns:
            d["trade_date"] = pd.to_datetime(d["date"].astype(str), format="%Y%m%d", errors="coerce")
        else:
            d["trade_date"] = pd.to_datetime(d["trade_date"], errors="coerce")
        if d["trade_date"].dtype == object:
            d["trade_date"] = pd.to_datetime(d["trade_date"], errors="coerce")
        d["close"] = pd.to_numeric(d["close"], errors="coerce")
        d = d.dropna(subset=["trade_date", "close"]).copy()
        parts.append(d[["trade_date", "close"]])

    if not parts:
        return pd.DataFrame(columns=["trade_date", "close", "ma", "risk_on"])

    out = pd.concat(parts, ignore_index=True)
    out = out.sort_values("trade_date").drop_duplicates(subset=["trade_date"], keep="last").reset_index(drop=True)
    out["ma"] = out["close"].rolling(ma_window, min_periods=ma_window).mean()
    out["risk_on"] = out["close"] > out["ma"]
    return out


def summarize_periods(df: pd.DataFrame, ret_col: str = "ret") -> dict:
    if df.empty:
        return {
            "periods": 0,
            "ann_return": np.nan,
            "total_return": np.nan,
            "max_drawdown": np.nan,
            "win_rate": np.nan,
            "avg_exposure": np.nan,
        }
    eq = (1.0 + df[ret_col]).cumprod()
    total = float(eq.iloc[-1] - 1.0)
    ann = float((1.0 + total) ** ((252.0 / 20.0) / len(df)) - 1.0)
    mdd = float((eq / eq.cummax() - 1.0).min())
    wr = float((df[ret_col] > 0).mean())
    avg_exp = float(df["exposure"].mean()) if "exposure" in df.columns else np.nan
    return {
        "periods": len(df),
        "ann_return": ann,
        "total_return": total,
        "max_drawdown": mdd,
        "win_rate": wr,
        "avg_exposure": avg_exp,
    }


def apply_index_filter(perf: pd.DataFrame, index_df: pd.DataFrame) -> pd.DataFrame:
    out = perf.copy()
    if out.empty or index_df.empty:
        out["risk_on"] = True
        out["exposure"] = 1.0
        out["filtered_ret"] = out["ret"]
        return out

    idx = index_df[["trade_date", "close", "ma", "risk_on"]].sort_values("trade_date").copy()
    out = out.sort_values("rebalance_date").copy()
    merged = pd.merge_asof(
        out,
        idx,
        left_on="rebalance_date",
        right_on="trade_date",
        direction="backward",
    )
    merged["risk_on"] = merged["risk_on"].fillna(False)
    merged["exposure"] = merged["risk_on"].astype(float)
    merged["filtered_ret"] = merged["ret"] * merged["exposure"]
    return merged


def build_strategy_panel(cb_daily: str, cb_basic: str, cb_call: str, end_date: str | None = None) -> pd.DataFrame:
    panel = build_combo_factors(build_panel(cb_daily, cb_basic))
    panel["score"] = panel["combo_dl_trend"]
    panel = apply_real_call_filter(panel, build_real_call_intervals(cb_call))
    if end_date:
        panel = panel[panel["trade_date"] <= pd.to_datetime(end_date)].copy()
    return panel


def summarize_yearly(df: pd.DataFrame, ret_col: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["year", "periods", "year_return", "win_rate", "year_mdd", "avg_exposure"])
    out = df.copy()
    out["year"] = pd.to_datetime(out["rebalance_date"]).dt.year
    rows = []
    for year, g in out.groupby("year"):
        eq = (1.0 + g[ret_col]).cumprod()
        rows.append(
            {
                "year": int(year),
                "periods": int(len(g)),
                "start": str(pd.to_datetime(g["rebalance_date"]).min().date()),
                "end": str(pd.to_datetime(g["rebalance_date"]).max().date()),
                "year_return": float(eq.iloc[-1] - 1.0),
                "win_rate": float((g[ret_col] > 0).mean()),
                "year_mdd": float((eq / eq.cummax() - 1.0).min()),
                "avg_exposure": float(g["exposure"].mean()) if "exposure" in g.columns else np.nan,
            }
        )
    return pd.DataFrame(rows).sort_values("year").reset_index(drop=True)


def main() -> None:
    p = argparse.ArgumentParser(description="可转债指数均线过滤研究")
    p.add_argument("--cb-daily", default="/Users/water/abu/data/cb/cb_daily_20210527_20260527.csv")
    p.add_argument("--cb-basic", default="/Users/water/abu/data/cb/cb_basic.csv")
    p.add_argument("--cb-call", default="/Users/water/abu/data/cb/cb_call_20210527_20260527.csv")
    p.add_argument("--out-dir", default="cy_quant/output")
    p.add_argument("--top-n", type=int, default=25)
    p.add_argument("--min-amount-wan", type=float, default=2000)
    p.add_argument("--cost-bps", type=float, default=40)
    p.add_argument("--ma-window", type=int, default=200)
    p.add_argument("--common-end", default="2025-03-07", help="共同可比窗口的结束日期")
    args = p.parse_args()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.out_dir, f"cb_index_filter_ma{args.ma_window}_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    panel_full = build_strategy_panel(args.cb_daily, args.cb_basic, args.cb_call)
    base_full = run_mode(panel_full, "balanced_premium", args.top_n, args.min_amount_wan, args.cost_bps).copy()
    base_full = base_full.sort_values("rebalance_date").reset_index(drop=True)
    base_full["exposure"] = 1.0
    base_full["filtered_ret"] = base_full["ret"]

    panel_common = build_strategy_panel(args.cb_daily, args.cb_basic, args.cb_call, args.common_end)
    base_common = run_mode(panel_common, "balanced_premium", args.top_n, args.min_amount_wan, args.cost_bps).copy()
    base_common = base_common.sort_values("rebalance_date").reset_index(drop=True)
    base_common["exposure"] = 1.0
    base_common["filtered_ret"] = base_common["ret"]

    summary_rows = []
    details = []

    summary_rows.append({"scope": "full", "index": "baseline", **summarize_periods(base_full, "filtered_ret")})
    summary_rows.append({"scope": "common", "index": "baseline", **summarize_periods(base_common, "filtered_ret")})
    summarize_yearly(base_full, "filtered_ret").to_csv(os.path.join(out_dir, "yearly_full_baseline.csv"), index=False, encoding="utf-8-sig")
    summarize_yearly(base_common, "filtered_ret").to_csv(os.path.join(out_dir, "yearly_common_baseline.csv"), index=False, encoding="utf-8-sig")

    for name, paths in INDEX_SPECS.items():
        idx_df = load_index_series(paths, args.ma_window)
        if idx_df.empty:
            continue

        common_merged = apply_index_filter(base_common, idx_df)
        summary_rows.append({"scope": "common", "index": name, **summarize_periods(common_merged, "filtered_ret")})
        common_merged.to_csv(os.path.join(out_dir, f"periods_common_{name}.csv"), index=False, encoding="utf-8-sig")
        summarize_yearly(common_merged, "filtered_ret").to_csv(os.path.join(out_dir, f"yearly_common_{name}.csv"), index=False, encoding="utf-8-sig")
        details.append(
            {
                "scope": "common",
                "index": name,
                "start": str(idx_df["trade_date"].min().date()),
                "end": str(idx_df["trade_date"].max().date()),
                "risk_on_days": int(idx_df["risk_on"].fillna(False).sum()),
                "rows": len(idx_df),
                "ma_window": args.ma_window,
            }
        )

        # 仅对能覆盖到 2026 的指数再给一组 full 窗口结果
        if idx_df["trade_date"].max() >= base_full["rebalance_date"].max():
            full_merged = apply_index_filter(base_full, idx_df)
            summary_rows.append({"scope": "full", "index": name, **summarize_periods(full_merged, "filtered_ret")})
            full_merged.to_csv(os.path.join(out_dir, f"periods_full_{name}.csv"), index=False, encoding="utf-8-sig")
            summarize_yearly(full_merged, "filtered_ret").to_csv(os.path.join(out_dir, f"yearly_full_{name}.csv"), index=False, encoding="utf-8-sig")
            details.append(
                {
                    "scope": "full",
                    "index": name,
                    "start": str(idx_df["trade_date"].min().date()),
                    "end": str(idx_df["trade_date"].max().date()),
                    "risk_on_days": int(idx_df["risk_on"].fillna(False).sum()),
                    "rows": len(idx_df),
                    "ma_window": args.ma_window,
                }
            )

    summary = pd.DataFrame(summary_rows)
    summary.to_csv(os.path.join(out_dir, "index_filter_summary.csv"), index=False, encoding="utf-8-sig")
    pd.DataFrame(details).to_csv(os.path.join(out_dir, "index_filter_meta.csv"), index=False, encoding="utf-8-sig")

    print(f"指数过滤研究完成 -> {out_dir}")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
