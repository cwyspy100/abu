#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage-3 A/B test on MA120 event panel.

目标：把阶段 C 的规则（初始仓位/加仓/止损/清仓）做成可复跑 A/B。
口径：
1) 月度组合收益（可重叠）
2) 非重叠组合收益（上一笔120天未结束，不开新仓）
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


def _perf_monthly(name: str, monthly: pd.DataFrame) -> Dict[str, float]:
    if monthly.empty:
        return {"strategy": name, "months": 0}
    r = monthly["net_ret"].fillna(0.0)
    eq = (1 + r).cumprod()
    years = len(r) / 12.0 if len(r) else 0.0
    vol = float(r.std(ddof=0) * np.sqrt(12)) if len(r) > 1 else 0.0
    return {
        "strategy": name,
        "months": int(len(r)),
        "total_return": float(eq.iloc[-1] - 1.0),
        "cagr": float(eq.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 and eq.iloc[-1] > 0 else np.nan,
        "annual_vol": vol,
        "sharpe_0rf": float((r.mean() * 12) / vol) if vol > 0 else np.nan,
        "max_drawdown": _max_dd(eq),
        "win_rate_monthly": float((r > 0).mean()),
        "avg_holdings": float(monthly["n"].mean()),
    }


def _perf_non_overlap(name: str, trades: pd.DataFrame) -> Dict[str, float]:
    if trades.empty:
        return {"strategy": name, "trades": 0}
    start = pd.to_datetime(trades["entry_date"].min())
    end = pd.to_datetime(trades["exit_date"].max())
    days = max((end - start).days, 1)
    years = days / 365.25
    r = trades["net_ret"].fillna(0.0)
    eq = (1 + r).cumprod()
    vol = float(r.std(ddof=0) * np.sqrt(12)) if len(r) > 1 else 0.0
    return {
        "strategy": name,
        "trades": int(len(trades)),
        "start_date": str(start.date()),
        "end_date": str(end.date()),
        "years": float(years),
        "total_return": float(eq.iloc[-1] - 1.0),
        "cagr": float(eq.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 and eq.iloc[-1] > 0 else np.nan,
        "annual_vol_est": vol,
        "sharpe_0rf_est": float((r.mean() * 12) / vol) if vol > 0 else np.nan,
        "max_drawdown": _max_dd(eq),
        "win_rate": float((r > 0).mean()),
        "avg_holdings": float(trades["n"].mean()),
    }


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
    add_ok = add_flag & (~full_stop)
    out["ret_full"] = np.where(add_ok, ret_full * add_mult, ret_full)
    return out


def _build_monthly(
    df: pd.DataFrame,
    strategy_col: str,
    top_n: int,
    cost_oneway: float,
) -> pd.DataFrame:
    rows: List[Dict[str, object]] = []
    for m, g in df.groupby("eval_month"):
        top = g.sort_values("total_score", ascending=False).head(top_n)
        if top.empty:
            continue
        gross = float(top[strategy_col].mean())
        net = gross - 2 * cost_oneway
        rows.append({"eval_month": m, "n": int(len(top)), "gross_ret": gross, "net_ret": net})
    out = pd.DataFrame(rows).sort_values("eval_month")
    if not out.empty:
        out["equity"] = (1 + out["net_ret"]).cumprod()
        out["drawdown"] = out["equity"] / out["equity"].cummax() - 1.0
    return out


def _build_non_overlap(
    df: pd.DataFrame,
    strategy_col: str,
    top_n: int,
    cost_oneway: float,
) -> pd.DataFrame:
    rows: List[Dict[str, object]] = []
    free_after = pd.Timestamp.min
    for m, g in df.groupby("eval_month"):
        g2 = g[g["buy_date"] > free_after]
        if g2.empty:
            continue
        top = g2.sort_values("total_score", ascending=False).head(top_n)
        if top.empty:
            continue
        gross = float(top[strategy_col].mean())
        net = gross - 2 * cost_oneway
        entry = pd.to_datetime(top["buy_date"].min())
        exit_date = pd.to_datetime(top["sell_date_120d"].max())
        rows.append(
            {
                "eval_month": m,
                "entry_date": entry,
                "exit_date": exit_date,
                "n": int(len(top)),
                "gross_ret": gross,
                "net_ret": net,
            }
        )
        free_after = exit_date
    out = pd.DataFrame(rows)
    if not out.empty:
        out["equity"] = (1 + out["net_ret"]).cumprod()
        out["drawdown"] = out["equity"] / out["equity"].cummax() - 1.0
    return out


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

    monthly_all: List[pd.DataFrame] = []
    monthly_perf: List[Dict[str, float]] = []
    non_overlap_all: List[pd.DataFrame] = []
    non_overlap_perf: List[Dict[str, float]] = []

    for s, col in strategies.items():
        monthly = _build_monthly(work, strategy_col=col, top_n=top_n, cost_oneway=cost_oneway)
        if not monthly.empty:
            monthly["strategy"] = s
            monthly_all.append(monthly)
        monthly_perf.append(_perf_monthly(s, monthly))

        nbt = _build_non_overlap(work, strategy_col=col, top_n=top_n, cost_oneway=cost_oneway)
        if not nbt.empty:
            nbt["strategy"] = s
            non_overlap_all.append(nbt)
        non_overlap_perf.append(_perf_non_overlap(s, nbt))

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(output_dir, f"stage3_trade_system_ab_{ts}")
    os.makedirs(out_dir, exist_ok=True)
    work.to_csv(os.path.join(out_dir, "panel_after_gate_and_rules.csv"), index=False, encoding="utf-8-sig")
    pd.concat(monthly_all, ignore_index=True).to_csv(
        os.path.join(out_dir, "monthly_returns_by_strategy.csv"), index=False, encoding="utf-8-sig"
    )
    pd.DataFrame(monthly_perf).to_csv(
        os.path.join(out_dir, "monthly_perf_summary.csv"), index=False, encoding="utf-8-sig"
    )
    pd.concat(non_overlap_all, ignore_index=True).to_csv(
        os.path.join(out_dir, "non_overlap_returns_by_strategy.csv"), index=False, encoding="utf-8-sig"
    )
    pd.DataFrame(non_overlap_perf).to_csv(
        os.path.join(out_dir, "non_overlap_perf_summary.csv"), index=False, encoding="utf-8-sig"
    )
    return out_dir


def main() -> None:
    p = argparse.ArgumentParser(description="Stage-3 trade-system A/B test on event panel")
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

