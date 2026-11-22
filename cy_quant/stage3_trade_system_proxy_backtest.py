#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage-3 trading system proxy backtest on MA120 event panel.

Proxy components:
- Initial position: equal weight monthly top-N picks
- Add-on (pyramid): if 30d momentum strong, leverage trade return
- Stop loss: clip deep-loss trades by max_dd_120d threshold
- Clear: time-based 120d exit (ret_120d)
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
class Perf:
    strategy: str
    months: int
    total_return: float
    cagr: float
    annual_vol: float
    max_drawdown: float
    win_rate_monthly: float
    avg_monthly_ret: float
    pick_count: int


def _max_dd(equity: pd.Series) -> float:
    peak = equity.cummax()
    dd = equity / peak - 1.0
    return float(dd.min()) if len(dd) else 0.0


def _perf(name: str, monthly: pd.DataFrame) -> Perf:
    if monthly.empty:
        return Perf(name, 0, 0, 0, 0, 0, 0, 0, 0)
    r = monthly["ret"].fillna(0.0)
    eq = (1 + r).cumprod()
    n = len(r)
    years = n / 12.0 if n else 0.0
    return Perf(
        strategy=name,
        months=n,
        total_return=float(eq.iloc[-1] - 1.0),
        cagr=float(eq.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 and eq.iloc[-1] > 0 else np.nan,
        annual_vol=float(r.std(ddof=0) * np.sqrt(12)) if n > 1 else 0.0,
        max_drawdown=_max_dd(eq),
        win_rate_monthly=float((r > 0).mean()),
        avg_monthly_ret=float(r.mean()),
        pick_count=int(monthly["n"].sum()),
    )


def _prepare_panel(input_csv: str, top_n: int) -> pd.DataFrame:
    df = pd.read_csv(input_csv)
    need = ["ts_code", "eval_date", "total_score", "ret_120d", "ret_30d", "max_dd_120d"]
    miss = [c for c in need if c not in df.columns]
    if miss:
        raise ValueError(f"missing columns: {miss}")
    df = df.dropna(subset=["eval_date", "total_score", "ret_120d"]).copy()
    df["eval_date"] = pd.to_datetime(df["eval_date"], errors="coerce")
    df = df.dropna(subset=["eval_date"])
    df["eval_month"] = df["eval_date"].dt.to_period("M").astype(str)
    df = (
        df.sort_values(["eval_month", "total_score"], ascending=[True, False])
        .groupby("eval_month", as_index=False)
        .head(top_n)
        .copy()
    )
    return df


def _apply_rules(
    panel: pd.DataFrame,
    add_trigger_30d: float,
    add_mult: float,
    stop_loss_120d: float,
    stop_partial_120d: float,
) -> Dict[str, pd.DataFrame]:
    p = panel.copy()
    p["ret_base"] = p["ret_120d"]

    # Add-on: strong early momentum -> scale return by add_mult.
    add_flag = p["ret_30d"].fillna(-999) >= add_trigger_30d
    p["ret_add"] = np.where(add_flag, p["ret_120d"] * add_mult, p["ret_120d"])

    # Stop-only proxy:
    # If max drawdown breaches stop_loss_120d, force full stop to that loss.
    # If breaches partial stop, reduce tail loss/return by 50%.
    dd = p["max_dd_120d"].fillna(0.0)
    r = p["ret_120d"].fillna(0.0)
    ret_stop = r.copy()
    full = dd <= stop_loss_120d
    partial = (dd <= stop_partial_120d) & (~full)
    ret_stop = np.where(full, stop_loss_120d, ret_stop)
    ret_stop = np.where(partial, np.minimum(ret_stop, ret_stop * 0.5), ret_stop)
    p["ret_stop"] = ret_stop

    # Full system: stop first, then add-on only if not full-stopped.
    ret_full = p["ret_stop"].copy()
    full_stopped = dd <= stop_loss_120d
    add_ok = add_flag & (~full_stopped)
    ret_full = np.where(add_ok, ret_full * add_mult, ret_full)
    p["ret_full"] = ret_full

    out = {}
    for col, name in [
        ("ret_base", "S1_base"),
        ("ret_add", "S2_add_on"),
        ("ret_stop", "S3_stop_only"),
        ("ret_full", "S4_full_system"),
    ]:
        m = (
            p.groupby("eval_month", as_index=False)
            .agg(n=("ts_code", "count"), ret=(col, "mean"))
            .sort_values("eval_month")
        )
        m["strategy"] = name
        out[name] = m
    return out


def run(
    input_csv: str,
    output_dir: str,
    top_n: int,
    add_trigger_30d: float,
    add_mult: float,
    stop_loss_120d: float,
    stop_partial_120d: float,
) -> str:
    panel = _prepare_panel(input_csv, top_n=top_n)
    series = _apply_rules(
        panel,
        add_trigger_30d=add_trigger_30d,
        add_mult=add_mult,
        stop_loss_120d=stop_loss_120d,
        stop_partial_120d=stop_partial_120d,
    )

    all_monthly = pd.concat(series.values(), ignore_index=True)
    perf_rows = [_perf(k, v).__dict__ for k, v in series.items()]
    perf_df = pd.DataFrame(perf_rows)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(output_dir, f"stage3_trade_system_proxy_{ts}")
    os.makedirs(out_dir, exist_ok=True)
    panel.to_csv(os.path.join(out_dir, "base_panel_topn.csv"), index=False, encoding="utf-8-sig")
    all_monthly.to_csv(os.path.join(out_dir, "monthly_returns_by_strategy.csv"), index=False, encoding="utf-8-sig")
    perf_df.to_csv(os.path.join(out_dir, "overall_summary.csv"), index=False, encoding="utf-8-sig")
    return out_dir


def main() -> None:
    p = argparse.ArgumentParser(description="Stage-3 trade system proxy backtest")
    p.add_argument(
        "--input-csv",
        default="/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/verify_12345_20260516/event_panel_with_345_features.csv",
    )
    p.add_argument("--output-dir", default="/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output")
    p.add_argument("--top-n", type=int, default=30)
    p.add_argument("--add-trigger-30d", type=float, default=0.08)
    p.add_argument("--add-mult", type=float, default=1.3)
    p.add_argument("--stop-loss-120d", type=float, default=-0.12)
    p.add_argument("--stop-partial-120d", type=float, default=-0.08)
    args = p.parse_args()

    out = run(
        input_csv=args.input_csv,
        output_dir=args.output_dir,
        top_n=args.top_n,
        add_trigger_30d=args.add_trigger_30d,
        add_mult=args.add_mult,
        stop_loss_120d=args.stop_loss_120d,
        stop_partial_120d=args.stop_partial_120d,
    )
    print(out)


if __name__ == "__main__":
    main()
