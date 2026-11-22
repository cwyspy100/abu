#!/usr/bin/env python3
"""QQQ/TQQQ MA120 ladder + trailing-stop backtest on local csv_his data.

Assumed strategy:
1) Portfolio starts with 50% QQQ core fully invested.
2) Remaining 50% is a tactical TQQQ sleeve, initially kept in cash.
3) When TQQQ closes below its own MA120 by 20% / 30% / 40%, deploy
   20% / 30% / 40% of the tactical sleeve.
4) Once TQQQ closes back above MA120, start a trailing-stop on the
   tactical TQQQ sleeve. If close falls 10% from the post-recovery
   highest close, sell 50% of current TQQQ sleeve and wait for the
   next below-MA120 buy cycle.

This is a low-frequency daily-bar research script and uses closing prices
for signal confirmation and execution.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class PerfRow:
    strategy: str
    cost_bps: float
    start_date: str
    end_date: str
    trading_days: int
    total_return: float
    cagr: float
    max_drawdown: float
    sharpe: float
    calmar: float
    final_value: float
    avg_tqqq_exposure: float
    avg_qqq_exposure: float
    buys: int
    sells: int


def _load_close(path: str, symbol: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["date_dt"] = pd.to_datetime(df["Unnamed: 0"], errors="coerce")
    df = df.dropna(subset=["date_dt", "close"]).sort_values("date_dt").reset_index(drop=True)
    out = df[["date_dt", "close"]].copy()
    out.rename(columns={"close": symbol}, inplace=True)
    return out


def load_pair(qqq_path: str, tqqq_path: str) -> pd.DataFrame:
    qqq = _load_close(qqq_path, "qqq")
    tqqq = _load_close(tqqq_path, "tqqq")
    df = qqq.merge(tqqq, on="date_dt", how="inner").sort_values("date_dt").reset_index(drop=True)
    df["tqqq_ma120"] = df["tqqq"].rolling(120, min_periods=120).mean()
    df["tqqq_vs_ma120"] = df["tqqq"] / df["tqqq_ma120"] - 1.0
    return df.dropna(subset=["tqqq_ma120"]).reset_index(drop=True)


def _max_drawdown(equity: pd.Series) -> float:
    peak = equity.cummax()
    return float((equity / peak - 1.0).min())


def _cagr(equity: pd.Series, dates: pd.Series, initial_capital: float = 1.0) -> float:
    years = (dates.iloc[-1] - dates.iloc[0]).days / 365.25
    if years <= 0 or initial_capital <= 0:
        return np.nan
    return float((equity.iloc[-1] / initial_capital) ** (1.0 / years) - 1.0)


def _sharpe(equity: pd.Series) -> float:
    ret = equity.pct_change().dropna()
    if ret.empty or ret.std(ddof=0) == 0:
        return np.nan
    return float(ret.mean() / ret.std(ddof=0) * np.sqrt(252))


def _perf_from_equity(
    equity: pd.DataFrame,
    strategy: str,
    cost_bps: float,
    buys: int,
    sells: int,
) -> PerfRow:
    eq = equity["equity"].astype(float)
    cagr = _cagr(eq, equity["date"])
    max_dd = _max_drawdown(eq)
    return PerfRow(
        strategy=strategy,
        cost_bps=cost_bps,
        start_date=equity["date"].iloc[0].date().isoformat(),
        end_date=equity["date"].iloc[-1].date().isoformat(),
        trading_days=len(equity),
        total_return=float(eq.iloc[-1] - 1.0),
        cagr=cagr,
        max_drawdown=max_dd,
        sharpe=_sharpe(eq),
        calmar=float(cagr / abs(max_dd)) if max_dd < 0 and pd.notna(cagr) else np.nan,
        final_value=float(eq.iloc[-1]),
        avg_tqqq_exposure=float(equity["tqqq_weight"].mean()),
        avg_qqq_exposure=float(equity["qqq_weight"].mean()),
        buys=buys,
        sells=sells,
    )


def run_buy_hold(df: pd.DataFrame, qqq_weight: float, tqqq_weight: float, cost_bps: float, strategy: str) -> tuple[PerfRow, pd.DataFrame]:
    cost = cost_bps / 10000.0
    qqq_shares = (qqq_weight * (1.0 - cost)) / float(df["qqq"].iloc[0]) if qqq_weight > 0 else 0.0
    tqqq_shares = (tqqq_weight * (1.0 - cost)) / float(df["tqqq"].iloc[0]) if tqqq_weight > 0 else 0.0
    out = df[["date_dt", "qqq", "tqqq"]].copy()
    out["qqq_value"] = qqq_shares * out["qqq"]
    out["tqqq_value"] = tqqq_shares * out["tqqq"]
    out["cash"] = 1.0 - qqq_weight - tqqq_weight
    out["equity"] = out["qqq_value"] + out["tqqq_value"] + out["cash"]
    out["qqq_weight"] = out["qqq_value"] / out["equity"]
    out["tqqq_weight"] = out["tqqq_value"] / out["equity"]
    out["date"] = out["date_dt"]
    equity = out[["date", "equity", "qqq_weight", "tqqq_weight"]]
    return _perf_from_equity(equity, strategy, cost_bps, 0, 0), equity


def run_ladder_strategy(
    df: pd.DataFrame,
    cost_bps: float,
    qqq_core_weight: float = 0.5,
    sleeve_weight: float = 0.5,
    buy_levels: tuple[float, ...] = (-0.20, -0.30, -0.40),
    buy_fracs: tuple[float, ...] = (0.20, 0.30, 0.40),
    trail_dd: float = 0.10,
    trail_sell_frac: float = 0.50,
) -> tuple[PerfRow, pd.DataFrame, pd.DataFrame]:
    cost = cost_bps / 10000.0
    qqq_shares = (qqq_core_weight * (1.0 - cost)) / float(df["qqq"].iloc[0])
    sleeve_cash = sleeve_weight
    tqqq_shares = 0.0
    buys = 0
    sells = 0

    tranche_filled = [False] * len(buy_levels)
    above_ma = False
    trailing_active = False
    trailing_peak = np.nan

    equity_rows = []
    trade_rows = []

    for _, r in df.iterrows():
        date = r["date_dt"]
        qqq_px = float(r["qqq"])
        tqqq_px = float(r["tqqq"])
        ma120 = float(r["tqqq_ma120"])
        vs_ma = float(r["tqqq_vs_ma120"])
        action = ""

        now_above = tqqq_px > ma120

        if now_above and not above_ma:
            trailing_active = True
            trailing_peak = tqqq_px
            tranche_filled = [False] * len(buy_levels)
        above_ma = now_above

        if not now_above:
            trailing_active = False
            trailing_peak = np.nan
            for i, (level, frac) in enumerate(zip(buy_levels, buy_fracs)):
                if (not tranche_filled[i]) and (vs_ma <= level):
                    deploy_cash = sleeve_weight * frac
                    deploy_cash = min(deploy_cash, sleeve_cash)
                    if deploy_cash > 0:
                        bought_shares = deploy_cash * (1.0 - cost) / tqqq_px
                        tqqq_shares += bought_shares
                        sleeve_cash -= deploy_cash
                        buys += 1
                        tranche_filled[i] = True
                        trade_rows.append(
                            {
                                "date": date,
                                "type": f"buy_{int(abs(level) * 100)}pct_below_ma120",
                                "price": tqqq_px,
                                "cash_amount": deploy_cash,
                                "vs_ma120": vs_ma,
                                "tqqq_shares_after": tqqq_shares,
                            }
                        )
                        action = f"buy_{int(abs(level) * 100)}"

        if trailing_active and tqqq_shares > 0:
            trailing_peak = max(float(trailing_peak), tqqq_px)
            if tqqq_px <= trailing_peak * (1.0 - trail_dd):
                shares_to_sell = tqqq_shares * trail_sell_frac
                proceeds = shares_to_sell * tqqq_px * (1.0 - cost)
                tqqq_shares -= shares_to_sell
                sleeve_cash += proceeds
                sells += 1
                trade_rows.append(
                    {
                        "date": date,
                        "type": "trail_sell_50pct",
                        "price": tqqq_px,
                        "cash_amount": proceeds,
                        "vs_ma120": vs_ma,
                        "tqqq_shares_after": tqqq_shares,
                    }
                )
                trailing_peak = tqqq_px
                action = "trail_sell_50"

        qqq_value = qqq_shares * qqq_px
        tqqq_value = tqqq_shares * tqqq_px
        equity = qqq_value + tqqq_value + sleeve_cash
        equity_rows.append(
            {
                "date": date,
                "qqq": qqq_px,
                "tqqq": tqqq_px,
                "tqqq_ma120": ma120,
                "tqqq_vs_ma120": vs_ma,
                "qqq_value": qqq_value,
                "tqqq_value": tqqq_value,
                "sleeve_cash": sleeve_cash,
                "equity": equity,
                "qqq_weight": qqq_value / equity if equity > 0 else np.nan,
                "tqqq_weight": tqqq_value / equity if equity > 0 else np.nan,
                "cash_weight": sleeve_cash / equity if equity > 0 else np.nan,
                "trailing_active": trailing_active,
                "trailing_peak": trailing_peak,
                "action": action or "hold",
            }
        )

    equity = pd.DataFrame(equity_rows)
    trades = pd.DataFrame(trade_rows)
    perf = _perf_from_equity(equity, "qqq50_tqqq_ladder_ma120_trail", cost_bps, buys, sells)
    return perf, equity, trades


def _write_report(out_dir: str, summary: pd.DataFrame, trades: pd.DataFrame, args: argparse.Namespace) -> None:
    lines = [
        "# QQQ/TQQQ MA120 Ladder Research",
        "",
        "## Config",
        "",
        f"- QQQ path: `{args.qqq_path}`",
        f"- TQQQ path: `{args.tqqq_path}`",
        f"- Core QQQ weight: `50%`",
        f"- Tactical TQQQ sleeve: `50%`",
        f"- Buy levels: `20% / 30% / 40% below MA120`",
        f"- Buy sleeve fractions: `20% / 30% / 40%`",
        f"- Trailing stop: `10% close drawdown, sell 50% of current TQQQ sleeve`",
        f"- Cost bps: `{args.cost_bps}`",
        "",
        "## Summary",
        "",
        summary.to_markdown(index=False),
    ]
    if not trades.empty:
        lines.extend(["", "## First 20 Trade Events", "", trades.head(20).to_markdown(index=False)])
    with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description="QQQ/TQQQ MA120 ladder backtest")
    parser.add_argument("--qqq-path", default="/Users/water/abu/csv_his/usQQQ_20110808_20170808")
    parser.add_argument("--tqqq-path", default="/Users/water/abu/csv_his/usTQQQ_20110808_20170808")
    parser.add_argument("--cost-bps", type=float, default=10.0)
    parser.add_argument("--output-dir", default="/Users/water/mylearn/PycharmProjects/abu-master/cy_quant/output")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    df = load_pair(args.qqq_path, args.tqqq_path)
    stamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S_%f")
    cost_tag = str(args.cost_bps).replace(".", "p")
    out_dir = os.path.join(args.output_dir, f"qqq_tqqq_ma120_ladder_cost{cost_tag}_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    ladder_perf, ladder_equity, ladder_trades = run_ladder_strategy(df, cost_bps=args.cost_bps)
    qqq_perf, qqq_equity = run_buy_hold(df, qqq_weight=1.0, tqqq_weight=0.0, cost_bps=args.cost_bps, strategy="qqq_buy_hold")
    tqqq_perf, tqqq_equity = run_buy_hold(df, qqq_weight=0.0, tqqq_weight=1.0, cost_bps=args.cost_bps, strategy="tqqq_buy_hold")
    mix_perf, mix_equity = run_buy_hold(df, qqq_weight=0.5, tqqq_weight=0.5, cost_bps=args.cost_bps, strategy="qqq50_tqqq50_buy_hold")

    summary = pd.DataFrame([ladder_perf.__dict__, qqq_perf.__dict__, tqqq_perf.__dict__, mix_perf.__dict__])
    summary = summary.sort_values(["strategy"]).reset_index(drop=True)

    ladder_equity.to_csv(os.path.join(out_dir, "equity_ladder.csv"), index=False, encoding="utf-8-sig")
    ladder_trades.to_csv(os.path.join(out_dir, "trades_ladder.csv"), index=False, encoding="utf-8-sig")
    qqq_equity.to_csv(os.path.join(out_dir, "equity_qqq_buy_hold.csv"), index=False, encoding="utf-8-sig")
    tqqq_equity.to_csv(os.path.join(out_dir, "equity_tqqq_buy_hold.csv"), index=False, encoding="utf-8-sig")
    mix_equity.to_csv(os.path.join(out_dir, "equity_qqq50_tqqq50_buy_hold.csv"), index=False, encoding="utf-8-sig")
    summary.to_csv(os.path.join(out_dir, "summary.csv"), index=False, encoding="utf-8-sig")
    _write_report(out_dir, summary, ladder_trades, args)

    print(out_dir)
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
