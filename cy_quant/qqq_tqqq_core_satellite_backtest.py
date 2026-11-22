#!/usr/bin/env python3
"""QQQ(60%) + TQQQ(40%) core-satellite backtest on local CSV.

Strategy:
1) QQQ core 60%: DCA every month-end (always buy)
2) TQQQ satellite 40%: DCA only when QQQ signal is ON
   - ON when QQQ close > SMA200 * 1.04
   - OFF when QQQ close < SMA200 * 0.97 (sell all TQQQ to cash)
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class BacktestResult:
    start_date: str
    end_date: str
    months: int
    total_invested: float
    final_value: float
    total_return: float
    cagr: float
    max_drawdown: float
    max_value: float


def _load_price(path: str, symbol: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["date_dt"] = pd.to_datetime(df["Unnamed: 0"], errors="coerce")
    df = df.dropna(subset=["date_dt", "close"]).sort_values("date_dt").reset_index(drop=True)
    out = df[["date_dt", "close"]].copy()
    out.rename(columns={"close": symbol}, inplace=True)
    return out


def run_backtest(
    qqq_path: str,
    tqqq_path: str,
    monthly_invest: float = 1000.0,
    core_weight: float = 0.6,
    sat_weight: float = 0.4,
    buy_mult: float = 1.04,
    sell_mult: float = 0.97,
) -> tuple[BacktestResult, pd.DataFrame]:
    q = _load_price(qqq_path, "qqq")
    t = _load_price(tqqq_path, "tqqq")
    df = q.merge(t, on="date_dt", how="inner")
    df = df.sort_values("date_dt").reset_index(drop=True)

    # signal based on QQQ SMA200
    df["sma200"] = df["qqq"].rolling(200, min_periods=200).mean()
    df["buy_line"] = df["sma200"] * buy_mult
    df["sell_line"] = df["sma200"] * sell_mult
    df["month"] = df["date_dt"].dt.to_period("M").astype(str)
    # month-end bars for DCA operations
    m = df.groupby("month", as_index=False).tail(1).copy().reset_index(drop=True)

    qqq_shares = 0.0
    tqqq_shares = 0.0
    sat_cash = 0.0
    signal_on = False
    invested = 0.0

    rows = []
    for _, r in m.iterrows():
        date = r["date_dt"]
        qqq_px = float(r["qqq"])
        tqqq_px = float(r["tqqq"])
        sma200 = float(r["sma200"]) if pd.notna(r["sma200"]) else np.nan
        buy_line = float(r["buy_line"]) if pd.notna(r["buy_line"]) else np.nan
        sell_line = float(r["sell_line"]) if pd.notna(r["sell_line"]) else np.nan

        # signal transitions
        if pd.notna(sma200):
            if (not signal_on) and (qqq_px > buy_line):
                signal_on = True
            elif signal_on and (qqq_px < sell_line):
                # clear satellite position
                sat_cash += tqqq_shares * tqqq_px
                tqqq_shares = 0.0
                signal_on = False

        # monthly DCA
        core_cash = monthly_invest * core_weight
        sat_new_cash = monthly_invest * sat_weight
        invested += monthly_invest

        qqq_shares += core_cash / qqq_px
        if signal_on:
            sat_total_cash = sat_cash + sat_new_cash
            if sat_total_cash > 0:
                tqqq_shares += sat_total_cash / tqqq_px
                sat_cash = 0.0
        else:
            sat_cash += sat_new_cash

        core_val = qqq_shares * qqq_px
        sat_val = tqqq_shares * tqqq_px + sat_cash
        total_val = core_val + sat_val
        rows.append(
            {
                "date": date,
                "month": r["month"],
                "qqq": qqq_px,
                "tqqq": tqqq_px,
                "sma200": sma200,
                "signal_on": signal_on,
                "invested_cum": invested,
                "qqq_shares": qqq_shares,
                "tqqq_shares": tqqq_shares,
                "sat_cash": sat_cash,
                "core_value": core_val,
                "sat_value": sat_val,
                "total_value": total_val,
            }
        )

    bt = pd.DataFrame(rows)
    bt["equity_peak"] = bt["total_value"].cummax()
    bt["drawdown"] = bt["total_value"] / bt["equity_peak"] - 1.0

    start_date = bt["date"].iloc[0].date().isoformat()
    end_date = bt["date"].iloc[-1].date().isoformat()
    months = len(bt)
    final_value = float(bt["total_value"].iloc[-1])
    total_return = final_value / invested - 1.0 if invested > 0 else np.nan
    years = months / 12.0
    cagr = (final_value / invested) ** (1.0 / years) - 1.0 if invested > 0 and years > 0 else np.nan
    max_dd = float(bt["drawdown"].min())
    max_value = float(bt["total_value"].max())

    result = BacktestResult(
        start_date=start_date,
        end_date=end_date,
        months=months,
        total_invested=float(invested),
        final_value=final_value,
        total_return=float(total_return),
        cagr=float(cagr),
        max_drawdown=max_dd,
        max_value=max_value,
    )
    return result, bt


def main() -> None:
    p = argparse.ArgumentParser(description="QQQ/TQQQ core-satellite backtest")
    p.add_argument("--qqq-path", default="/Users/water/abu/csv_his/usQQQ_20110808_20170808")
    p.add_argument("--tqqq-path", default="/Users/water/abu/csv_his/usTQQQ_20110808_20170808")
    p.add_argument("--monthly-invest", type=float, default=1000.0)
    p.add_argument("--core-weight", type=float, default=0.6)
    p.add_argument("--sat-weight", type=float, default=0.4)
    p.add_argument("--buy-mult", type=float, default=1.04)
    p.add_argument("--sell-mult", type=float, default=0.97)
    p.add_argument("--output-dir", default="/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output")
    args = p.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    result, bt = run_backtest(
        qqq_path=args.qqq_path,
        tqqq_path=args.tqqq_path,
        monthly_invest=args.monthly_invest,
        core_weight=args.core_weight,
        sat_weight=args.sat_weight,
        buy_mult=args.buy_mult,
        sell_mult=args.sell_mult,
    )

    stamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.output_dir, f"qqq_tqqq_core_satellite_{stamp}")
    os.makedirs(out_dir, exist_ok=True)
    bt.to_csv(os.path.join(out_dir, "monthly_equity.csv"), index=False, encoding="utf-8-sig")
    pd.DataFrame([result.__dict__]).to_csv(os.path.join(out_dir, "summary.csv"), index=False, encoding="utf-8-sig")

    print(out_dir)
    print(pd.DataFrame([result.__dict__]).to_string(index=False))


if __name__ == "__main__":
    main()
