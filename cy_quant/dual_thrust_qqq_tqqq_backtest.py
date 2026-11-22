#!/usr/bin/env python3
"""Dual Thrust 20-day research on local QQQ/TQQQ csv_his data.

This is a low-frequency daily-bar experiment. Signals are generated from
prior 20 trading days only, then confirmed by the current day's high/low.
Trades are executed at the current day's close to avoid assuming exact
intraday fill prices, especially when QQQ is used as the signal instrument
and TQQQ is used as the traded instrument.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd


@dataclass
class PerfRow:
    strategy: str
    signal_symbol: str
    trade_symbol: str
    n: int
    k1: float
    k2: float
    cost_bps: float
    start_date: str
    end_date: str
    trading_days: int
    trades: int
    win_rate: float
    avg_trade_ret: float
    median_trade_ret: float
    total_return: float
    cagr: float
    max_drawdown: float
    sharpe: float
    calmar: float
    exposure: float
    final_value: float


def _load_ohlc(path: str, prefix: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["date_dt"] = pd.to_datetime(df["Unnamed: 0"], errors="coerce")
    needed = ["date_dt", "open", "close", "high", "low", "volume"]
    df = df.dropna(subset=["date_dt", "open", "close", "high", "low"])
    df = df[needed].sort_values("date_dt").reset_index(drop=True)
    return df.rename(
        columns={
            "open": f"{prefix}_open",
            "close": f"{prefix}_close",
            "high": f"{prefix}_high",
            "low": f"{prefix}_low",
            "volume": f"{prefix}_volume",
        }
    )


def load_pair(qqq_path: str, tqqq_path: str) -> pd.DataFrame:
    qqq = _load_ohlc(qqq_path, "qqq")
    tqqq = _load_ohlc(tqqq_path, "tqqq")
    df = qqq.merge(tqqq, on="date_dt", how="inner").sort_values("date_dt").reset_index(drop=True)
    return df


def add_dual_thrust_lines(df: pd.DataFrame, signal_symbol: str, n: int, k1: float, k2: float) -> pd.DataFrame:
    out = df.copy()
    high = out[f"{signal_symbol}_high"]
    low = out[f"{signal_symbol}_low"]
    close = out[f"{signal_symbol}_close"]
    open_ = out[f"{signal_symbol}_open"]

    hh = high.shift(1).rolling(n, min_periods=n).max()
    lc = close.shift(1).rolling(n, min_periods=n).min()
    hc = close.shift(1).rolling(n, min_periods=n).max()
    ll = low.shift(1).rolling(n, min_periods=n).min()
    range_ = pd.concat([hh - lc, hc - ll], axis=1).max(axis=1)

    out["dt_range"] = range_
    out["dt_buy_line"] = open_ + k1 * range_
    out["dt_sell_line"] = open_ - k2 * range_
    out["dt_buy_trigger"] = high >= out["dt_buy_line"]
    out["dt_sell_trigger"] = low <= out["dt_sell_line"]
    return out


def _max_drawdown(equity: pd.Series) -> float:
    peak = equity.cummax()
    dd = equity / peak - 1.0
    return float(dd.min())


def _cagr(equity: pd.Series, dates: pd.Series, initial_capital: float = 1.0) -> float:
    years = (dates.iloc[-1] - dates.iloc[0]).days / 365.25
    if years <= 0 or initial_capital <= 0:
        return np.nan
    return float((equity.iloc[-1] / initial_capital) ** (1.0 / years) - 1.0)


def _sharpe(equity: pd.Series) -> float:
    ret = equity.pct_change().dropna()
    if ret.std(ddof=0) == 0 or ret.empty:
        return np.nan
    return float(ret.mean() / ret.std(ddof=0) * np.sqrt(252))


def _perf(
    equity: pd.DataFrame,
    trades: pd.DataFrame,
    strategy: str,
    signal_symbol: str,
    trade_symbol: str,
    n: int,
    k1: float,
    k2: float,
    cost_bps: float,
) -> PerfRow:
    eq = equity["equity"].astype(float)
    cagr = _cagr(eq, equity["date"])
    max_dd = _max_drawdown(eq)
    trade_rets = trades["trade_ret"] if not trades.empty else pd.Series(dtype=float)
    return PerfRow(
        strategy=strategy,
        signal_symbol=signal_symbol,
        trade_symbol=trade_symbol,
        n=n,
        k1=k1,
        k2=k2,
        cost_bps=cost_bps,
        start_date=equity["date"].iloc[0].date().isoformat(),
        end_date=equity["date"].iloc[-1].date().isoformat(),
        trading_days=len(equity),
        trades=int(len(trades)),
        win_rate=float((trade_rets > 0).mean()) if not trade_rets.empty else np.nan,
        avg_trade_ret=float(trade_rets.mean()) if not trade_rets.empty else np.nan,
        median_trade_ret=float(trade_rets.median()) if not trade_rets.empty else np.nan,
        total_return=float(eq.iloc[-1] - 1.0),
        cagr=cagr,
        max_drawdown=max_dd,
        sharpe=_sharpe(eq),
        calmar=float(cagr / abs(max_dd)) if max_dd < 0 and pd.notna(cagr) else np.nan,
        exposure=float(equity["position"].mean()),
        final_value=float(eq.iloc[-1]),
    )


def run_dual_thrust(
    base: pd.DataFrame,
    signal_symbol: str,
    trade_symbol: str,
    n: int,
    k1: float,
    k2: float,
    cost_bps: float,
) -> tuple[PerfRow, pd.DataFrame, pd.DataFrame]:
    df = add_dual_thrust_lines(base, signal_symbol, n, k1, k2)
    df = df.dropna(subset=["dt_buy_line", "dt_sell_line"]).reset_index(drop=True)
    cost = cost_bps / 10000.0

    cash = 1.0
    shares = 0.0
    in_pos = False
    entry_date = None
    entry_px = np.nan
    entry_equity = np.nan
    equity_rows = []
    trade_rows = []

    for _, r in df.iterrows():
        date = r["date_dt"]
        px = float(r[f"{trade_symbol}_close"])
        action = "hold"

        if not in_pos and bool(r["dt_buy_trigger"]):
            shares = cash * (1.0 - cost) / px
            cash = 0.0
            in_pos = True
            entry_date = date
            entry_px = px
            entry_equity = shares * px
            action = "buy"
        elif in_pos and bool(r["dt_sell_trigger"]):
            exit_value = shares * px * (1.0 - cost)
            trade_ret = exit_value / entry_equity - 1.0 if entry_equity > 0 else np.nan
            trade_rows.append(
                {
                    "entry_date": entry_date,
                    "exit_date": date,
                    "entry_price": entry_px,
                    "exit_price": px,
                    "trade_ret": trade_ret,
                    "bars_held": len(equity_rows) - next(
                        (i for i, row in enumerate(equity_rows) if row["date"] == entry_date), len(equity_rows)
                    ),
                }
            )
            cash = exit_value
            shares = 0.0
            in_pos = False
            entry_date = None
            entry_px = np.nan
            entry_equity = np.nan
            action = "sell"

        equity = cash + shares * px
        equity_rows.append(
            {
                "date": date,
                "equity": equity,
                "position": int(in_pos),
                "action": action,
                f"{signal_symbol}_open": r[f"{signal_symbol}_open"],
                f"{signal_symbol}_close": r[f"{signal_symbol}_close"],
                f"{signal_symbol}_high": r[f"{signal_symbol}_high"],
                f"{signal_symbol}_low": r[f"{signal_symbol}_low"],
                f"{trade_symbol}_close": px,
                "dt_range": r["dt_range"],
                "dt_buy_line": r["dt_buy_line"],
                "dt_sell_line": r["dt_sell_line"],
                "buy_trigger": bool(r["dt_buy_trigger"]),
                "sell_trigger": bool(r["dt_sell_trigger"]),
            }
        )

    equity = pd.DataFrame(equity_rows)
    trades = pd.DataFrame(trade_rows)
    perf = _perf(equity, trades, "dual_thrust_close_confirm", signal_symbol, trade_symbol, n, k1, k2, cost_bps)
    return perf, equity, trades


def run_buy_hold(base: pd.DataFrame, symbol: str, start_idx: int, cost_bps: float) -> tuple[PerfRow, pd.DataFrame]:
    df = base.iloc[start_idx:].copy().reset_index(drop=True)
    cost = cost_bps / 10000.0
    first_px = float(df[f"{symbol}_close"].iloc[0])
    shares = (1.0 - cost) / first_px
    df["equity"] = shares * df[f"{symbol}_close"].astype(float)
    df["position"] = 1
    equity = df[["date_dt", "equity", "position"]].rename(columns={"date_dt": "date"})
    perf = _perf(
        equity,
        pd.DataFrame(),
        "buy_hold",
        symbol,
        symbol,
        0,
        0.0,
        0.0,
        cost_bps,
    )
    return perf, equity


def _parse_grid(raw: str) -> list[tuple[float, float]]:
    pairs = []
    for part in raw.split(","):
        left, right = part.split("/")
        pairs.append((float(left), float(right)))
    return pairs


def _write_report(out_dir: str, summary: pd.DataFrame, args: argparse.Namespace) -> None:
    best = summary[summary["strategy"] == "dual_thrust_close_confirm"].sort_values(
        ["calmar", "cagr"], ascending=False
    )
    lines = [
        "# QQQ/TQQQ Dual Thrust 20 Research",
        "",
        "## Config",
        "",
        f"- QQQ path: `{args.qqq_path}`",
        f"- TQQQ path: `{args.tqqq_path}`",
        f"- N: `{args.n}`",
        f"- Cost bps: `{args.cost_bps}`",
        f"- Execution: daily close confirmation",
        "",
        "## Top Dual Thrust Results",
        "",
    ]
    cols = [
        "signal_symbol",
        "trade_symbol",
        "k1",
        "k2",
        "trades",
        "total_return",
        "cagr",
        "max_drawdown",
        "sharpe",
        "calmar",
        "exposure",
    ]
    lines.append(best[cols].head(10).to_markdown(index=False))
    lines.extend(["", "## All Summary", "", summary.to_markdown(index=False)])
    with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    p = argparse.ArgumentParser(description="Dual Thrust 20-day QQQ/TQQQ research")
    p.add_argument("--qqq-path", default="/Users/water/abu/csv_his/usQQQ_20110808_20170808")
    p.add_argument("--tqqq-path", default="/Users/water/abu/csv_his/usTQQQ_20110808_20170808")
    p.add_argument("--n", type=int, default=20)
    p.add_argument("--k-grid", default="0.3/0.3,0.5/0.5,0.7/0.7,0.5/0.3,0.7/0.5")
    p.add_argument("--cost-bps", type=float, default=10.0)
    p.add_argument("--output-dir", default="/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output")
    args = p.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    base = load_pair(args.qqq_path, args.tqqq_path)
    start_idx = args.n

    stamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.output_dir, f"dual_thrust_qqq_tqqq_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    summary_rows = []
    qqq_bh, qqq_eq = run_buy_hold(base, "qqq", start_idx, args.cost_bps)
    tqqq_bh, tqqq_eq = run_buy_hold(base, "tqqq", start_idx, args.cost_bps)
    summary_rows.extend([qqq_bh.__dict__, tqqq_bh.__dict__])
    qqq_eq.to_csv(os.path.join(out_dir, "equity_buy_hold_qqq.csv"), index=False, encoding="utf-8-sig")
    tqqq_eq.to_csv(os.path.join(out_dir, "equity_buy_hold_tqqq.csv"), index=False, encoding="utf-8-sig")

    for signal_symbol in ["tqqq", "qqq"]:
        for k1, k2 in _parse_grid(args.k_grid):
            perf, equity, trades = run_dual_thrust(
                base,
                signal_symbol=signal_symbol,
                trade_symbol="tqqq",
                n=args.n,
                k1=k1,
                k2=k2,
                cost_bps=args.cost_bps,
            )
            summary_rows.append(perf.__dict__)
            suffix = f"signal_{signal_symbol}_trade_tqqq_n{args.n}_k{k1:g}_{k2:g}"
            equity.to_csv(os.path.join(out_dir, f"equity_{suffix}.csv"), index=False, encoding="utf-8-sig")
            trades.to_csv(os.path.join(out_dir, f"trades_{suffix}.csv"), index=False, encoding="utf-8-sig")

    summary = pd.DataFrame(summary_rows)
    summary = summary.sort_values(["strategy", "calmar", "cagr"], ascending=[True, False, False]).reset_index(drop=True)
    summary.to_csv(os.path.join(out_dir, "summary.csv"), index=False, encoding="utf-8-sig")
    _write_report(out_dir, summary, args)

    print(out_dir)
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
