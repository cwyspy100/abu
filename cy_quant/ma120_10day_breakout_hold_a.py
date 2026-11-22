#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MA120 + 10-day momentum + 12-month breakout hold backtest."""

from __future__ import annotations

import argparse
import glob
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


TRADING_DAYS_PER_YEAR = 252.0


@dataclass(frozen=True)
class Config:
    csv_dir: Path
    output_dir: Path
    top_n_values: Tuple[int, ...]
    market_prefixes: Tuple[str, ...]
    rebalance_days: int = 10
    momentum_days: int = 10
    breakout_days: int = 252
    ma_window: int = 120


def symbol_from_path(path: str) -> str:
    return os.path.basename(path).split("_", 1)[0]


def parse_date(raw: pd.Series) -> pd.Series:
    s = raw.astype(str).str.split(".").str[0]
    if s.str.fullmatch(r"\d{8}").mean() > 0.8:
        return pd.to_datetime(s, format="%Y%m%d", errors="coerce")
    return pd.to_datetime(s, errors="coerce")


def scan_market_files(csv_dir: Path, market_prefixes: Tuple[str, ...]) -> Dict[str, str]:
    files = sorted(glob.glob(str(csv_dir / "*")))
    out: Dict[str, str] = {}
    for path in files:
        if not os.path.isfile(path):
            continue
        symbol = symbol_from_path(path)
        if symbol.startswith(market_prefixes):
            out[symbol] = path
    return out


def load_price_file(path: str, config: Config) -> pd.DataFrame:
    try:
        df = pd.read_csv(path, usecols=lambda c: c in {"date", "open", "close"})
    except Exception:
        return pd.DataFrame()
    if not {"date", "open", "close"}.issubset(df.columns):
        return pd.DataFrame()
    out = df.copy()
    out["dt"] = parse_date(out["date"])
    out["open"] = pd.to_numeric(out["open"], errors="coerce")
    out["close"] = pd.to_numeric(out["close"], errors="coerce")
    out = out.dropna(subset=["dt", "open", "close"])
    out = out[(out["open"] > 0) & (out["close"] > 0)]
    if out.empty:
        return out
    out = out[["dt", "open", "close"]].sort_values("dt").drop_duplicates("dt", keep="last").reset_index(drop=True)
    out["ma120"] = out["close"].rolling(config.ma_window, min_periods=config.ma_window).mean()
    out["ret_10d"] = out["close"] / out["close"].shift(config.momentum_days) - 1.0
    out["prev_12m_high"] = out["close"].shift(1).rolling(config.breakout_days, min_periods=config.breakout_days).max()
    out["above_ma120"] = out["close"] > out["ma120"]
    out["above_prev_12m_high"] = out["close"] > out["prev_12m_high"]
    return out


def build_signal_panel(price_cache: Dict[str, pd.DataFrame]) -> Tuple[pd.DataFrame, List[pd.Timestamp]]:
    rows: List[Dict[str, object]] = []
    all_dates: List[pd.Timestamp] = []
    for symbol, df in price_cache.items():
        if df.empty:
            continue
        all_dates.extend(df["dt"].tolist())
        tmp = df.dropna(subset=["ret_10d", "ma120", "prev_12m_high"]).copy()
        if tmp.empty:
            continue
        rows.extend(
            {
                "symbol": symbol,
                "dt": row.dt,
                "ret_10d": float(row.ret_10d),
                "close": float(row.close),
                "above_ma120": bool(row.above_ma120),
                "above_prev_12m_high": bool(row.above_prev_12m_high),
            }
            for row in tmp.itertuples(index=False)
        )
    panel = pd.DataFrame(rows).sort_values(["dt", "symbol"]).reset_index(drop=True) if rows else pd.DataFrame()
    uniq_dates = sorted(pd.Series(all_dates).drop_duplicates().tolist()) if all_dates else []
    return panel, uniq_dates


def next_open_and_period_return(df: pd.DataFrame, signal_date: pd.Timestamp, next_signal_date: pd.Timestamp) -> Tuple[float, str, str, float, float]:
    future = df[df["dt"] > signal_date]
    if future.empty:
        return 0.0, "", "", np.nan, np.nan
    buy = future.iloc[0]
    period_rows = future[future["dt"] <= next_signal_date]
    if period_rows.empty:
        period_rows = future.iloc[[0]]
    sell = period_rows.iloc[-1]
    buy_open = float(buy["open"])
    sell_close = float(sell["close"])
    if buy_open <= 0 or sell_close <= 0:
        return 0.0, "", "", np.nan, np.nan
    return sell_close / buy_open - 1.0, str(buy["dt"].date()), str(sell["dt"].date()), buy_open, sell_close


def annualized_return(total_ret: float, periods: int, periods_per_year: float) -> float:
    if periods <= 0 or total_ret <= -1.0:
        return np.nan
    return float((1.0 + total_ret) ** (periods_per_year / periods) - 1.0)


def max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return np.nan
    peak = equity.cummax()
    return float((equity / peak - 1.0).min())


def summarize(periods_df: pd.DataFrame, periods_per_year: float) -> pd.DataFrame:
    if periods_df.empty:
        return pd.DataFrame()
    rows: List[Dict[str, object]] = []
    groups = [((top_n, "all"), sub) for top_n, sub in periods_df.groupby("top_n")]
    groups.extend([((top_n, str(year)), sub) for (top_n, year), sub in periods_df.groupby(["top_n", "year"])])
    for (top_n, label), sub in groups:
        ret = pd.to_numeric(sub["period_ret"], errors="coerce").dropna()
        eq = (1.0 + ret).cumprod()
        total = float(eq.iloc[-1] - 1.0) if not eq.empty else np.nan
        sharpe = np.nan
        if len(ret) > 1 and float(ret.std(ddof=1)) > 0:
            sharpe = float(ret.mean() / ret.std(ddof=1) * np.sqrt(periods_per_year))
        rows.append(
            {
                "top_n": int(top_n),
                "period": label,
                "periods": int(len(ret)),
                "total_ret": total,
                "annualized_ret": annualized_return(total, len(ret), periods_per_year),
                "avg_period_ret": float(ret.mean()) if not ret.empty else np.nan,
                "win_rate": float((ret > 0).mean()) if not ret.empty else np.nan,
                "max_drawdown": max_drawdown(eq),
                "sharpe_ann": sharpe,
                "best_period": float(ret.max()) if not ret.empty else np.nan,
                "worst_period": float(ret.min()) if not ret.empty else np.nan,
                "avg_traded_slots": float(sub["traded"].mean()),
                "avg_held_slots": float(sub["held_positions"].mean()),
            }
        )
    return pd.DataFrame(rows)


def run_backtest(config: Config) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    files = scan_market_files(config.csv_dir, config.market_prefixes)
    price_cache = {symbol: load_price_file(path, config) for symbol, path in files.items()}
    panel, all_dates = build_signal_panel(price_cache)
    if panel.empty or not all_dates:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    signal_dates = all_dates[:: config.rebalance_days]
    if len(signal_dates) < 2:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    periods_per_year = TRADING_DAYS_PER_YEAR / config.rebalance_days
    period_rows: List[Dict[str, object]] = []
    pick_rows: List[Dict[str, object]] = []
    positions: Dict[int, List[str]] = {top_n: [] for top_n in config.top_n_values}
    equity: Dict[int, float] = {top_n: 1.0 for top_n in config.top_n_values}

    for idx in range(len(signal_dates) - 1):
        signal_date = signal_dates[idx]
        next_signal_date = signal_dates[idx + 1]
        day_panel = panel[(panel["dt"] == signal_date) & (panel["above_ma120"])].copy()
        if day_panel.empty:
            continue
        day_panel = day_panel.sort_values("ret_10d", ascending=False)
        day_state = day_panel.set_index("symbol")

        for top_n in config.top_n_values:
            prev_positions = positions[top_n]
            keep_positions = [
                symbol
                for symbol in prev_positions
                if symbol in day_state.index and bool(day_state.at[symbol, "above_prev_12m_high"])
            ]
            need = max(0, top_n - len(keep_positions))
            new_candidates = [sym for sym in day_panel["symbol"].tolist() if sym not in keep_positions]
            new_positions = keep_positions + new_candidates[:need]
            positions[top_n] = new_positions

            weighted_ret = 0.0
            traded = 0
            for rank, symbol in enumerate(new_positions, start=1):
                stock_df = price_cache.get(symbol, pd.DataFrame())
                ret, buy_date, sell_date, buy_open, sell_close = next_open_and_period_return(stock_df, signal_date, next_signal_date)
                if buy_date:
                    traded += 1
                weighted_ret += ret / top_n
                row = day_state.loc[symbol]
                pick_rows.append(
                    {
                        "top_n": top_n,
                        "signal_date": str(signal_date.date()),
                        "next_signal_date": str(next_signal_date.date()),
                        "rank": rank,
                        "symbol": symbol,
                        "ret_10d": float(row["ret_10d"]),
                        "signal_close": float(row["close"]),
                        "above_ma120": bool(row["above_ma120"]),
                        "above_prev_12m_high": bool(row["above_prev_12m_high"]),
                        "buy_date": buy_date,
                        "sell_date": sell_date,
                        "buy_open": buy_open,
                        "sell_close": sell_close,
                        "period_ret": ret,
                        "carried_from_prev": symbol in keep_positions,
                    }
                )

            equity[top_n] *= 1.0 + weighted_ret
            period_rows.append(
                {
                    "top_n": top_n,
                    "signal_date": str(signal_date.date()),
                    "next_signal_date": str(next_signal_date.date()),
                    "year": signal_date.year,
                    "period_ret": weighted_ret,
                    "equity": equity[top_n],
                    "traded": traded,
                    "held_positions": int(len(new_positions)),
                    "carried_positions": int(len(keep_positions)),
                    "new_positions": int(max(0, len(new_positions) - len(keep_positions))),
                }
            )

    periods_df = pd.DataFrame(period_rows)
    picks_df = pd.DataFrame(pick_rows)
    summary_df = summarize(periods_df, periods_per_year)
    return periods_df, picks_df, summary_df


def save_outputs(config: Config, periods_df: pd.DataFrame, picks_df: pd.DataFrame, summary_df: pd.DataFrame) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = config.output_dir / f"ma120_10day_breakout_hold_a_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    periods_df.to_csv(out_dir / "period_returns.csv", index=False, encoding="utf-8-sig")
    picks_df.to_csv(out_dir / "picks.csv", index=False, encoding="utf-8-sig")
    summary_df.to_csv(out_dir / "summary.csv", index=False, encoding="utf-8-sig")
    return out_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MA120 + 10-day momentum + 12-month breakout hold backtest.")
    parser.add_argument("--csv-dir", default="/Users/water/abu/data/csv")
    parser.add_argument("--output-dir", default="cy_quant/output")
    parser.add_argument("--top-n-list", default="10")
    parser.add_argument("--market-prefixes", default="sh60,sz00,sz30")
    parser.add_argument("--rebalance-days", type=int, default=10)
    parser.add_argument("--momentum-days", type=int, default=10)
    parser.add_argument("--breakout-days", type=int, default=252)
    parser.add_argument("--ma-window", type=int, default=120)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = Config(
        csv_dir=Path(args.csv_dir),
        output_dir=Path(args.output_dir),
        top_n_values=tuple(int(v.strip()) for v in args.top_n_list.split(",") if v.strip()),
        market_prefixes=tuple(v.strip() for v in args.market_prefixes.split(",") if v.strip()),
        rebalance_days=args.rebalance_days,
        momentum_days=args.momentum_days,
        breakout_days=args.breakout_days,
        ma_window=args.ma_window,
    )
    periods_df, picks_df, summary_df = run_backtest(config)
    out_dir = save_outputs(config, periods_df, picks_df, summary_df)
    print(f"output_dir: {out_dir}")
    if summary_df.empty:
        print("No result.")
    else:
        print(summary_df.to_string(index=False))


if __name__ == "__main__":
    main()
