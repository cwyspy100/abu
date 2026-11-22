#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage-3 real-path A/B backtest on MA120 event panel.

使用本地K线按真实日路径执行交易规则，不用等速收益展开：
- S1_base: 买入后持有120天窗口到 sell_date_120d
- S2_add_only: 若前30天收益>=阈值，在第30天收盘加仓（增量仓位持有至卖出）
- S3_stop_only: 若持仓收益<=stop_loss 立即清仓；若<=stop_partial 将仓位降为50%
- S4_full_system: 先执行止损/减仓，再执行加仓
"""

from __future__ import annotations

import argparse
import glob
import os
from datetime import datetime
from typing import Dict, List, Optional, Tuple

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


def _scan_csv_map(csv_dir: str) -> Dict[str, str]:
    mp: Dict[str, str] = {}
    for p in glob.glob(os.path.join(csv_dir, "*")):
        if os.path.isdir(p):
            continue
        b = os.path.basename(p)
        stem = b[:-4] if b.endswith(".csv") else b
        if "_" not in stem:
            continue
        code = stem.split("_", 1)[0]
        if len(code) < 3:
            continue
        prefix = code[:2].lower()
        num = code[2:]
        market = {"sh": "SH", "sz": "SZ", "bj": "BJ", "hk": "HK", "us": "US"}.get(prefix)
        if market is None:
            continue
        ts = f"{num}.{market}"
        mp[ts] = p
    return mp


def _load_kline(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, usecols=lambda c: c in {"date", "close"})
    if "date" not in df.columns or "close" not in df.columns:
        return pd.DataFrame()
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"].astype(str), format="%Y%m%d", errors="coerce")
    out["close"] = pd.to_numeric(out["close"], errors="coerce")
    out = out.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
    return out


def _daily_series_between(df: pd.DataFrame, buy_date: pd.Timestamp, sell_date: pd.Timestamp) -> Optional[pd.DataFrame]:
    seg = df[(df["date"] >= buy_date) & (df["date"] <= sell_date)].copy()
    if len(seg) < 2:
        return None
    return seg


def _simulate_trade(
    seg: pd.DataFrame,
    add_trigger_30d: float,
    add_mult: float,
    stop_loss: float,
    stop_partial: float,
    mode: str,
    cost_oneway: float,
) -> pd.DataFrame:
    # position_t 是当日收盘后持仓（用于下一个交易日收益）
    # day_ret_t = position_{t-1} * (close_t/close_{t-1}-1)
    close = seg["close"].to_numpy(dtype=float)
    dates = seg["date"].to_numpy()
    n = len(seg)
    base_w = 1.0
    add_w = max(add_mult - 1.0, 0.0)
    position = base_w
    added = False
    partial_done = False
    stopped = False
    rows: List[Dict[str, object]] = []

    buy_price = close[0]
    # 入场成本记到首日
    rows.append({"date": dates[0], "day_ret": -cost_oneway, "position": position})

    for i in range(1, n):
        ret_d = close[i] / close[i - 1] - 1.0
        day_ret = position * ret_d
        rows.append({"date": dates[i], "day_ret": day_ret, "position": position})

        if stopped:
            continue

        # 以当日收盘对买入价收益判断规则触发
        ret_from_buy = close[i] / buy_price - 1.0

        # Stop rules
        if mode in {"S3_stop_only", "S4_full_system"}:
            if ret_from_buy <= stop_loss:
                position = 0.0
                stopped = True
                # 出场成本
                rows[-1]["day_ret"] = float(rows[-1]["day_ret"]) - cost_oneway
                continue
            if (not partial_done) and (ret_from_buy <= stop_partial):
                position = min(position, 0.5)
                partial_done = True

        # Add-on at day 30 close (index 30 means about 30 trading bars from entry)
        if mode in {"S2_add_only", "S4_full_system"} and (not added) and i >= 30:
            if ret_from_buy >= add_trigger_30d:
                position = position + add_w
                added = True

    # 若未止损，末日视作卖出并扣除成本
    if not stopped and rows:
        rows[-1]["day_ret"] = float(rows[-1]["day_ret"]) - cost_oneway * position

    out = pd.DataFrame(rows)
    return out


def _perf(name: str, curve: pd.DataFrame) -> Dict[str, float]:
    if curve.empty:
        return {"strategy": name, "days": 0}
    r = curve["day_ret"].fillna(0.0)
    eq = (1 + r).cumprod()
    years = len(r) / 252.0 if len(r) else 0.0
    vol = float(r.std(ddof=0) * np.sqrt(252)) if len(r) > 1 else 0.0
    cagr = float(eq.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 and eq.iloc[-1] > 0 else np.nan
    return {
        "strategy": name,
        "days": int(len(r)),
        "start_date": str(pd.to_datetime(curve["date"].min()).date()),
        "end_date": str(pd.to_datetime(curve["date"].max()).date()),
        "years": float(years),
        "total_return": float(eq.iloc[-1] - 1.0),
        "cagr": cagr,
        "annual_vol": vol,
        "sharpe_0rf": float((r.mean() * 252) / vol) if vol > 0 else np.nan,
        "max_drawdown": _max_dd(eq),
        "avg_active_trades": float(curve["active_n"].mean()) if "active_n" in curve.columns else np.nan,
    }


def run(
    input_csv: str,
    csv_dir: str,
    output_dir: str,
    top_n: int,
    min_close_above_p0_days: int,
    min_ret_30d_from_p0: float,
    add_trigger_30d: float,
    add_mult: float,
    stop_loss: float,
    stop_partial: float,
    cost_oneway: float,
) -> str:
    panel = pd.read_csv(input_csv)
    ret30_col = _pick_col(panel, ["ret_30d_from_p0", "ret_30d"])
    need = ["ts_code", "eval_date", "buy_date", "sell_date_120d", "total_score", "close_above_p0_days", ret30_col]
    miss = [c for c in need if c not in panel.columns]
    if miss:
        raise ValueError(f"missing columns: {miss}")

    panel["eval_date"] = pd.to_datetime(panel["eval_date"], errors="coerce")
    panel["buy_date"] = pd.to_datetime(panel["buy_date"], errors="coerce")
    panel["sell_date_120d"] = pd.to_datetime(panel["sell_date_120d"], errors="coerce")
    panel = panel.dropna(subset=["ts_code", "eval_date", "buy_date", "sell_date_120d", "total_score"]).copy()
    panel = panel[
        (panel["close_above_p0_days"] >= min_close_above_p0_days) & (panel[ret30_col] > min_ret_30d_from_p0)
    ].copy()
    panel["eval_month"] = panel["eval_date"].dt.to_period("M").dt.to_timestamp("M")
    panel = (
        panel.sort_values(["eval_month", "total_score"], ascending=[True, False])
        .groupby("eval_month", as_index=False)
        .head(top_n)
        .copy()
    )
    panel["trade_id"] = np.arange(len(panel)).astype(str)

    path_map = _scan_csv_map(csv_dir)
    cache: Dict[str, pd.DataFrame] = {}
    modes = ["S1_base", "S2_add_only", "S3_stop_only", "S4_full_system"]
    day_rows: Dict[str, List[pd.DataFrame]] = {m: [] for m in modes}
    trade_logs: List[Dict[str, object]] = []

    for _, tr in panel.iterrows():
        ts_code = str(tr["ts_code"])
        path = path_map.get(ts_code)
        if path is None:
            continue
        if path not in cache:
            cache[path] = _load_kline(path)
        k = cache[path]
        seg = _daily_series_between(k, pd.Timestamp(tr["buy_date"]), pd.Timestamp(tr["sell_date_120d"]))
        if seg is None:
            continue
        trade_logs.append(
            {
                "trade_id": tr["trade_id"],
                "ts_code": ts_code,
                "eval_month": tr["eval_month"],
                "buy_date": tr["buy_date"],
                "sell_date_120d": tr["sell_date_120d"],
                "bars": int(len(seg)),
            }
        )
        for m in modes:
            td = _simulate_trade(
                seg=seg,
                add_trigger_30d=add_trigger_30d,
                add_mult=add_mult,
                stop_loss=stop_loss,
                stop_partial=stop_partial,
                mode=m,
                cost_oneway=cost_oneway,
            )
            td["trade_id"] = tr["trade_id"]
            td["strategy"] = m
            day_rows[m].append(td)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(output_dir, f"stage3_trade_system_realpath_ab_{ts}")
    os.makedirs(out_dir, exist_ok=True)

    pd.DataFrame(trade_logs).to_csv(os.path.join(out_dir, "trade_logs.csv"), index=False, encoding="utf-8-sig")
    panel.to_csv(os.path.join(out_dir, "selected_panel.csv"), index=False, encoding="utf-8-sig")

    perf_rows: List[Dict[str, float]] = []
    for m in modes:
        if not day_rows[m]:
            continue
        d = pd.concat(day_rows[m], ignore_index=True)
        daily = d.groupby("date", as_index=False).agg(day_ret=("day_ret", "mean"), active_n=("trade_id", "nunique"))
        daily = daily.sort_values("date").reset_index(drop=True)
        daily["equity"] = (1 + daily["day_ret"]).cumprod()
        daily["drawdown"] = daily["equity"] / daily["equity"].cummax() - 1.0
        daily.to_csv(os.path.join(out_dir, f"daily_curve_{m}.csv"), index=False, encoding="utf-8-sig")
        perf_rows.append(_perf(m, daily))

    pd.DataFrame(perf_rows).to_csv(os.path.join(out_dir, "realpath_perf_summary.csv"), index=False, encoding="utf-8-sig")
    return out_dir


def main() -> None:
    p = argparse.ArgumentParser(description="Stage-3 real-path A/B backtest")
    p.add_argument(
        "--input-csv",
        default="/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output/verify_12345_20260516/event_panel_with_345_features.csv",
    )
    p.add_argument("--csv-dir", default="/Users/water/abu/csv_his")
    p.add_argument("--output-dir", default="/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output")
    p.add_argument("--top-n", type=int, default=30)
    p.add_argument("--min-close-above-p0-days", type=int, default=15)
    p.add_argument("--min-ret-30d-from-p0", type=float, default=0.0)
    p.add_argument("--add-trigger-30d", type=float, default=0.06)
    p.add_argument("--add-mult", type=float, default=1.4)
    p.add_argument("--stop-loss", type=float, default=-0.08)
    p.add_argument("--stop-partial", type=float, default=-0.06)
    p.add_argument("--cost-oneway", type=float, default=0.0015)
    args = p.parse_args()

    out = run(
        input_csv=args.input_csv,
        csv_dir=args.csv_dir,
        output_dir=args.output_dir,
        top_n=args.top_n,
        min_close_above_p0_days=args.min_close_above_p0_days,
        min_ret_30d_from_p0=args.min_ret_30d_from_p0,
        add_trigger_30d=args.add_trigger_30d,
        add_mult=args.add_mult,
        stop_loss=args.stop_loss,
        stop_partial=args.stop_partial,
        cost_oneway=args.cost_oneway,
    )
    print(out)


if __name__ == "__main__":
    main()
