#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage-3 daily equity A/B from event panel trades.

基于事件面板中的 buy_date / sell_date_120d / ret_120d，构造逐日组合净值：
- 每笔交易在持有区间内按“等速复利”展开为日收益；
- 每日对所有在持仓交易等权汇总为组合日收益。
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime
from typing import Dict, List

import numpy as np
import pandas as pd


def _pick_col(df: pd.DataFrame, choices: List[str]) -> str:
    for c in choices:
        if c in df.columns:
            return c
    raise ValueError(f"missing columns, expected one of: {choices}")


def _max_dd(equity: pd.Series) -> float:
    peak = equity.cummax()
    dd = equity / peak - 1.0
    return float(dd.min()) if len(dd) else 0.0


def _apply_rules(
    df: pd.DataFrame,
    ret30_col: str,
    ret120_col: str,
    dd120_col: str,
    add_trigger_30d: float,
    add_mult: float,
    stop_loss_120d: float,
    stop_partial_120d: float,
) -> pd.DataFrame:
    out = df.copy()
    r120 = out[ret120_col].fillna(0.0).astype(float)
    r30 = out[ret30_col].fillna(-999.0).astype(float)
    dd = out[dd120_col].fillna(0.0).astype(float)

    out["ret_base"] = r120
    add_flag = r30 >= add_trigger_30d
    out["ret_add"] = np.where(add_flag, r120 * add_mult, r120)

    full_stop = dd <= stop_loss_120d
    partial_stop = (dd <= stop_partial_120d) & (~full_stop)
    ret_stop = r120.copy()
    ret_stop = np.where(full_stop, stop_loss_120d, ret_stop)
    ret_stop = np.where(partial_stop, np.minimum(ret_stop, ret_stop * 0.5), ret_stop)
    out["ret_stop"] = ret_stop

    ret_full = out["ret_stop"].copy()
    out["ret_full"] = np.where(add_flag & (~full_stop), ret_full * add_mult, ret_full)
    return out


def _select_topn_by_month(df: pd.DataFrame, top_n: int) -> pd.DataFrame:
    out = (
        df.sort_values(["eval_month", "total_score"], ascending=[True, False])
        .groupby("eval_month", as_index=False)
        .head(top_n)
        .copy()
    )
    return out


def _build_trade_daily_rows(trades: pd.DataFrame, ret_col: str, cost_oneway: float) -> pd.DataFrame:
    rows: List[Dict[str, object]] = []
    for _, r in trades.iterrows():
        s = pd.Timestamp(r["buy_date"])
        e = pd.Timestamp(r["sell_date_120d"])
        if pd.isna(s) or pd.isna(e) or e <= s:
            continue
        days = int((e - s).days)
        if days <= 0:
            continue
        gross = float(r[ret_col])
        # 近似一笔完整往返成本，分摊到持有期
        net = gross - 2 * cost_oneway
        day_ret = (1.0 + net) ** (1.0 / days) - 1.0
        for d in pd.date_range(s, e, freq="D", inclusive="left"):
            rows.append({"date": d, "trade_id": r["trade_id"], "day_ret": day_ret})
    return pd.DataFrame(rows)


def _portfolio_curve(trades: pd.DataFrame, ret_col: str, cost_oneway: float) -> pd.DataFrame:
    dr = _build_trade_daily_rows(trades, ret_col=ret_col, cost_oneway=cost_oneway)
    if dr.empty:
        return pd.DataFrame(columns=["date", "active_n", "day_ret", "equity", "drawdown"])
    daily = dr.groupby("date", as_index=False).agg(active_n=("trade_id", "nunique"), day_ret=("day_ret", "mean"))
    daily = daily.sort_values("date").reset_index(drop=True)
    daily["equity"] = (1.0 + daily["day_ret"]).cumprod()
    daily["drawdown"] = daily["equity"] / daily["equity"].cummax() - 1.0
    return daily


def _perf_daily(name: str, curve: pd.DataFrame) -> Dict[str, float]:
    if curve.empty:
        return {"strategy": name, "days": 0}
    eq = curve["equity"]
    days = len(curve)
    years = days / 365.25
    r = curve["day_ret"].fillna(0.0)
    ann_vol = float(r.std(ddof=0) * np.sqrt(252)) if days > 1 else 0.0
    cagr = float(eq.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 and eq.iloc[-1] > 0 else np.nan
    return {
        "strategy": name,
        "days": int(days),
        "start_date": str(pd.to_datetime(curve["date"].min()).date()),
        "end_date": str(pd.to_datetime(curve["date"].max()).date()),
        "years": float(years),
        "total_return": float(eq.iloc[-1] - 1.0),
        "cagr": cagr,
        "annual_vol": ann_vol,
        "sharpe_0rf": float((r.mean() * 252) / ann_vol) if ann_vol > 0 else np.nan,
        "max_drawdown": _max_dd(eq),
        "avg_active_trades": float(curve["active_n"].mean()),
        "max_active_trades": int(curve["active_n"].max()),
    }


def run(
    input_csv: str,
    output_dir: str,
    top_n: int,
    min_close_above_p0_days: int,
    min_ret_30d_from_p0: float,
    add_trigger_30d: float,
    add_mult: float,
    stop_loss_120d: float,
    stop_partial_120d: float,
    cost_oneway: float,
) -> str:
    df = pd.read_csv(input_csv)
    ret30_col = _pick_col(df, ["ret_30d_from_p0", "ret_30d"])
    ret120_col = _pick_col(df, ["ret_120d"])
    dd120_col = _pick_col(df, ["max_dd_120d"])
    need = ["eval_date", "buy_date", "sell_date_120d", "total_score", "close_above_p0_days", ret30_col, ret120_col, dd120_col]
    miss = [c for c in need if c not in df.columns]
    if miss:
        raise ValueError(f"missing columns: {miss}")

    work = df.copy()
    work["eval_date"] = pd.to_datetime(work["eval_date"], errors="coerce")
    work["buy_date"] = pd.to_datetime(work["buy_date"], errors="coerce")
    work["sell_date_120d"] = pd.to_datetime(work["sell_date_120d"], errors="coerce")
    work = work.dropna(subset=["eval_date", "buy_date", "sell_date_120d", "total_score"]).copy()
    work = work[
        (work["close_above_p0_days"] >= min_close_above_p0_days)
        & (work[ret30_col] > min_ret_30d_from_p0)
    ].copy()
    if work.empty:
        raise ValueError("empty panel after gate")
    work["eval_month"] = work["eval_date"].dt.to_period("M").dt.to_timestamp("M")
    work = _select_topn_by_month(work, top_n=top_n)
    work["trade_id"] = np.arange(len(work)).astype(str)
    work = _apply_rules(
        work,
        ret30_col=ret30_col,
        ret120_col=ret120_col,
        dd120_col=dd120_col,
        add_trigger_30d=add_trigger_30d,
        add_mult=add_mult,
        stop_loss_120d=stop_loss_120d,
        stop_partial_120d=stop_partial_120d,
    )

    strategies = {
        "S1_base": "ret_base",
        "S2_add_only": "ret_add",
        "S3_stop_only": "ret_stop",
        "S4_full_system": "ret_full",
    }
    perf_rows: List[Dict[str, float]] = []
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(output_dir, f"stage3_trade_system_daily_ab_{ts}")
    os.makedirs(out_dir, exist_ok=True)
    work.to_csv(os.path.join(out_dir, "selected_trades.csv"), index=False, encoding="utf-8-sig")

    for s, col in strategies.items():
        curve = _portfolio_curve(work, ret_col=col, cost_oneway=cost_oneway)
        curve.to_csv(os.path.join(out_dir, f"daily_curve_{s}.csv"), index=False, encoding="utf-8-sig")
        perf_rows.append(_perf_daily(s, curve))

    pd.DataFrame(perf_rows).to_csv(os.path.join(out_dir, "daily_perf_summary.csv"), index=False, encoding="utf-8-sig")
    return out_dir


def main() -> None:
    p = argparse.ArgumentParser(description="Stage-3 daily equity A/B from event panel")
    p.add_argument(
        "--input-csv",
        default="/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/verify_12345_20260516/event_panel_with_345_features.csv",
    )
    p.add_argument("--output-dir", default="/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output")
    p.add_argument("--top-n", type=int, default=30)
    p.add_argument("--min-close-above-p0-days", type=int, default=15)
    p.add_argument("--min-ret-30d-from-p0", type=float, default=0.0)
    p.add_argument("--add-trigger-30d", type=float, default=0.06)
    p.add_argument("--add-mult", type=float, default=1.4)
    p.add_argument("--stop-loss-120d", type=float, default=-0.08)
    p.add_argument("--stop-partial-120d", type=float, default=-0.06)
    p.add_argument("--cost-oneway", type=float, default=0.0015)
    args = p.parse_args()

    out = run(
        input_csv=args.input_csv,
        output_dir=args.output_dir,
        top_n=args.top_n,
        min_close_above_p0_days=args.min_close_above_p0_days,
        min_ret_30d_from_p0=args.min_ret_30d_from_p0,
        add_trigger_30d=args.add_trigger_30d,
        add_mult=args.add_mult,
        stop_loss_120d=args.stop_loss_120d,
        stop_partial_120d=args.stop_partial_120d,
        cost_oneway=args.cost_oneway,
    )
    print(out)


if __name__ == "__main__":
    main()

