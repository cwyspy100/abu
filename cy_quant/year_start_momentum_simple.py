#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Simple monthly rotation backtest for YTD or monthly momentum leaders.

Rules:
- At each month end, rank symbols by configured momentum return.
- Buy next month on each symbol's first available open after the signal date.
- Hold to that holding month's last available close.
- Top N are equally allocated; missing next-month trades stay as cash.
- No transaction cost, no limit-up/down handling.
"""

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


@dataclass(frozen=True)
class BacktestConfig:
    csv_dir: Path
    output_dir: Path
    top_n: int = 10
    top_n_list: Tuple[int, ...] = ()
    max_symbols: Optional[int] = None
    market_prefix: str = ""
    market_prefixes: Tuple[str, ...] = ()
    benchmark_path: str = ""
    market_ma_window: int = 120
    rank_mode: str = "ytd"
    lookback_days: int = 0
    rebalance_days: int = 0
    hold_days: int = 0
    max_rank_ret: Optional[float] = None
    min_buy_open: Optional[float] = None
    require_buy_above_ma: Tuple[int, ...] = ()
    stop_loss: Optional[float] = None


def symbol_from_path(path: str) -> str:
    return os.path.basename(path).split("_", 1)[0]


def parse_date(raw: pd.Series) -> pd.Series:
    s = raw.astype(str).str.split(".").str[0]
    if s.str.fullmatch(r"\d{8}").mean() > 0.8:
        return pd.to_datetime(s, format="%Y%m%d", errors="coerce")
    return pd.to_datetime(s, errors="coerce")


def load_price_file(path: str) -> pd.DataFrame:
    try:
        df = pd.read_csv(path, usecols=lambda c: c in {"date", "open", "close", "low"})
    except Exception:
        return pd.DataFrame()
    if not {"date", "open", "close"}.issubset(df.columns):
        return pd.DataFrame()
    out = df.copy()
    out["dt"] = parse_date(out["date"])
    out["open"] = pd.to_numeric(out["open"], errors="coerce")
    out["close"] = pd.to_numeric(out["close"], errors="coerce")
    if "low" in out.columns:
        out["low"] = pd.to_numeric(out["low"], errors="coerce")
    else:
        out["low"] = out["close"]
    out = out.dropna(subset=["dt", "open", "close"])
    out = out[(out["open"] > 0) & (out["close"] > 0)]
    if out.empty:
        return out
    out["low"] = out["low"].fillna(out["close"])
    out = out[["dt", "open", "close", "low"]].sort_values("dt").drop_duplicates("dt", keep="last").reset_index(drop=True)
    for window in (20, 60):
        out[f"ma{window}"] = out["close"].rolling(window, min_periods=window).mean()
    return out


def load_benchmark(path: str, ma_window: int) -> pd.DataFrame:
    df = load_price_file(path)
    if df.empty:
        return df
    out = df[["dt", "close"]].copy()
    out["market_ma"] = out["close"].rolling(ma_window, min_periods=ma_window).mean()
    out["market_ok"] = out["close"] > out["market_ma"]
    return out


def market_state_on_or_before(benchmark: pd.DataFrame, dt: pd.Timestamp) -> Tuple[bool, str, float, float]:
    if benchmark.empty:
        return True, "", np.nan, np.nan
    rows = benchmark[benchmark["dt"] <= dt]
    if rows.empty:
        return False, "", np.nan, np.nan
    row = rows.iloc[-1]
    close = float(row["close"])
    ma = float(row["market_ma"]) if pd.notna(row["market_ma"]) else np.nan
    ok = bool(pd.notna(row["market_ma"]) and row["market_ok"])
    return ok, str(pd.Timestamp(row["dt"]).date()), close, ma


def scan_files(config: BacktestConfig) -> Dict[str, str]:
    files = sorted(glob.glob(str(config.csv_dir / "*")))
    out: Dict[str, str] = {}
    for path in files:
        if not os.path.isfile(path):
            continue
        symbol = symbol_from_path(path)
        if config.market_prefix and not symbol.lower().startswith(config.market_prefix.lower()):
            continue
        if config.market_prefixes and not any(symbol.lower().startswith(p.lower()) for p in config.market_prefixes):
            continue
        out[symbol] = path
        if config.max_symbols is not None and len(out) >= config.max_symbols:
            break
    return out


def monthly_rows_from_price(symbol: str, df: pd.DataFrame) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    if df.empty:
        return rows
    tmp = df.copy()
    tmp["year"] = tmp["dt"].dt.year
    tmp["month"] = tmp["dt"].dt.to_period("M")
    first_by_year = tmp.groupby("year", sort=True).first()["close"]
    first_by_month = tmp.groupby(["year", "month"], sort=True).first()["close"]
    month_last = tmp.groupby(["year", "month"], sort=True).last().reset_index()
    for _, row in month_last.iterrows():
        year = int(row["year"])
        month = row["month"]
        year_base = float(first_by_year.get(year, np.nan))
        month_base = float(first_by_month.get((year, month), np.nan))
        close = float(row["close"])
        if not np.isfinite(year_base) or year_base <= 0 or not np.isfinite(month_base) or month_base <= 0 or close <= 0:
            continue
        rows.append(
            {
                "symbol": symbol,
                "year": year,
                "signal_month": str(month),
                "signal_date": row["dt"],
                "signal_close": close,
                "year_start_close": year_base,
                "month_start_close": month_base,
                "ytd_ret": close / year_base - 1.0,
                "monthly_signal_ret": close / month_base - 1.0,
            }
        )
    return rows


def build_monthly_panel(files: Dict[str, str]) -> pd.DataFrame:
    rows: List[Dict[str, object]] = []
    for symbol, path in files.items():
        rows.extend(monthly_rows_from_price(symbol, load_price_file(path)))
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["signal_date", "symbol"]).reset_index(drop=True)


def build_monthly_lookback_panel(files: Dict[str, str], lookback_days: int) -> pd.DataFrame:
    rows: List[Dict[str, object]] = []
    for symbol, path in files.items():
        df = load_price_file(path)
        if df.empty or len(df) <= lookback_days:
            continue
        tmp = df.copy()
        tmp["year"] = tmp["dt"].dt.year
        tmp["month"] = tmp["dt"].dt.to_period("M")
        tmp["lookback_ret"] = tmp["close"] / tmp["close"].shift(lookback_days) - 1.0
        month_last = tmp.groupby(["year", "month"], sort=True).last().reset_index()
        month_last = month_last.dropna(subset=["lookback_ret"])
        for _, row in month_last.iterrows():
            rows.append(
                {
                    "symbol": symbol,
                    "year": int(row["year"]),
                    "signal_month": str(row["month"]),
                    "signal_date": row["dt"],
                    "signal_close": float(row["close"]),
                    "rank_ret": float(row["lookback_ret"]),
                }
            )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["signal_date", "symbol"]).reset_index(drop=True)


def build_nday_panel(files: Dict[str, str], lookback_days: int) -> pd.DataFrame:
    rows: List[Dict[str, object]] = []
    for symbol, path in files.items():
        df = load_price_file(path)
        if df.empty or len(df) <= lookback_days:
            continue
        tmp = df[["dt", "close"]].copy()
        tmp["rank_ret"] = tmp["close"] / tmp["close"].shift(lookback_days) - 1.0
        tmp = tmp.dropna(subset=["rank_ret"])
        if tmp.empty:
            continue
        tmp["symbol"] = symbol
        rows.extend(tmp[["symbol", "dt", "rank_ret"]].to_dict("records"))
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["dt", "symbol"]).reset_index(drop=True)


def next_month_period(period_text: str) -> pd.Period:
    return pd.Period(period_text, freq="M") + 1


def calc_n_day_trade_return(
    df: pd.DataFrame,
    signal_date: pd.Timestamp,
    hold_days: int,
    min_buy_open: Optional[float] = None,
    require_buy_above_ma: Tuple[int, ...] = (),
    stop_loss: Optional[float] = None,
) -> Tuple[float, str, str, float, float]:
    future = df[df["dt"] > signal_date]
    if future.empty:
        return 0.0, "", "", np.nan, np.nan
    buy = future.iloc[0]
    buy_idx = int(buy.name)
    end_pos = min(max(hold_days, 1) - 1, len(future) - 1)
    sell = future.iloc[end_pos]
    buy_open = float(buy["open"])
    sell_close = float(sell["close"])
    if buy_open <= 0 or sell_close <= 0:
        return 0.0, "", "", np.nan, np.nan
    if min_buy_open is not None and buy_open < min_buy_open:
        return 0.0, "", "", buy_open, sell_close
    if require_buy_above_ma:
        if buy_idx <= 0:
            return 0.0, "", "", buy_open, sell_close
        prev = df.iloc[buy_idx - 1]
        for window in require_buy_above_ma:
            ma_col = f"ma{window}"
            if ma_col not in df.columns or pd.isna(prev[ma_col]) or float(prev["close"]) <= float(prev[ma_col]):
                return 0.0, "", "", buy_open, sell_close
    if stop_loss is not None and stop_loss > 0:
        stop_price = buy_open * (1.0 - stop_loss)
        path = future.iloc[: end_pos + 1]
        stop_rows = path[path["low"] <= stop_price]
        if not stop_rows.empty:
            stop_row = stop_rows.iloc[0]
            return stop_price / buy_open - 1.0, str(buy["dt"].date()), str(stop_row["dt"].date()), buy_open, stop_price
    return sell_close / buy_open - 1.0, str(buy["dt"].date()), str(sell["dt"].date()), buy_open, sell_close


def calc_next_month_trade_return(
    df: pd.DataFrame,
    signal_date: pd.Timestamp,
    hold_month: pd.Period,
    min_buy_open: Optional[float] = None,
    require_buy_above_ma: Tuple[int, ...] = (),
    stop_loss: Optional[float] = None,
) -> Tuple[float, str, str, float, float]:
    future = df[(df["dt"] > signal_date) & (df["dt"].dt.to_period("M") == hold_month)]
    if future.empty:
        return 0.0, "", "", np.nan, np.nan
    buy = future.iloc[0]
    sell = future.iloc[-1]
    buy_idx = int(buy.name)
    buy_open = float(buy["open"])
    sell_close = float(sell["close"])
    if buy_open <= 0 or sell_close <= 0:
        return 0.0, "", "", np.nan, np.nan
    if min_buy_open is not None and buy_open < min_buy_open:
        return 0.0, "", "", buy_open, sell_close
    if require_buy_above_ma:
        if buy_idx <= 0:
            return 0.0, "", "", buy_open, sell_close
        prev = df.iloc[buy_idx - 1]
        for window in require_buy_above_ma:
            ma_col = f"ma{window}"
            if ma_col not in df.columns or pd.isna(prev[ma_col]) or float(prev["close"]) <= float(prev[ma_col]):
                return 0.0, "", "", buy_open, sell_close
    if stop_loss is not None and stop_loss > 0:
        stop_price = buy_open * (1.0 - stop_loss)
        stop_rows = future[future["low"] <= stop_price]
        if not stop_rows.empty:
            stop_row = stop_rows.iloc[0]
            return stop_price / buy_open - 1.0, str(buy["dt"].date()), str(stop_row["dt"].date()), buy_open, stop_price
    return sell_close / buy_open - 1.0, str(buy["dt"].date()), str(sell["dt"].date()), buy_open, sell_close


def run_backtest(config: BacktestConfig) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    files = scan_files(config)
    if config.rank_mode == "nday":
        return run_nday_backtest(config, files)
    if config.rank_mode == "lookback":
        panel = build_monthly_lookback_panel(files, config.lookback_days or 60)
    else:
        panel = build_monthly_panel(files)
    if panel.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    if config.rank_mode == "monthly":
        rank_col = "monthly_signal_ret"
    elif config.rank_mode == "lookback":
        rank_col = "rank_ret"
    else:
        rank_col = "ytd_ret"
    top_n_values = config.top_n_list or (config.top_n,)

    benchmark = load_benchmark(config.benchmark_path, config.market_ma_window) if config.benchmark_path else pd.DataFrame()
    monthly_rows: List[Dict[str, object]] = []
    pick_rows: List[Dict[str, object]] = []
    trade_cache: Dict[str, pd.DataFrame] = {}
    equity_by_top_n = {top_n: 1.0 for top_n in top_n_values}
    rank_months = sorted(panel["signal_month"].unique())
    for signal_month in rank_months:
        hold_month = next_month_period(signal_month)
        full_ranking = panel[panel["signal_month"] == signal_month].sort_values(rank_col, ascending=False)
        if config.max_rank_ret is not None:
            full_ranking = full_ranking[full_ranking[rank_col] <= config.max_rank_ret]
        if full_ranking.empty:
            continue
        signal_date = pd.Timestamp(full_ranking.iloc[0]["signal_date"])
        market_ok, market_date, market_close, market_ma = market_state_on_or_before(benchmark, signal_date)
        for top_n in top_n_values:
            ranking = full_ranking.head(top_n)
            if not market_ok:
                monthly_rows.append(
                    {
                        "top_n": top_n,
                        "rank_mode": config.rank_mode,
                        "signal_month": signal_month,
                        "hold_month": str(hold_month),
                        "year": hold_month.year,
                        "portfolio_ret": 0.0,
                        "equity": equity_by_top_n[top_n],
                        "selected": int(len(ranking)),
                        "traded": 0,
                        "cash_slots": top_n,
                        "market_ok": False,
                        "market_date": market_date,
                        "market_close": market_close,
                        "market_ma": market_ma,
                    }
                )
                for rank, item in enumerate(ranking.itertuples(index=False), start=1):
                    pick_rows.append(
                        {
                            "top_n": top_n,
                            "rank_mode": config.rank_mode,
                            "signal_month": signal_month,
                            "hold_month": str(hold_month),
                            "rank": rank,
                            "symbol": item.symbol,
                            "signal_date": str(pd.Timestamp(item.signal_date).date()),
                            "rank_ret": float(getattr(item, rank_col)),
                            "ytd_ret": float(getattr(item, "ytd_ret", np.nan)),
                            "monthly_signal_ret": float(getattr(item, "monthly_signal_ret", np.nan)),
                            "month_ret": 0.0,
                            "buy_date": "",
                            "sell_date": "",
                            "buy_open": np.nan,
                            "sell_close": np.nan,
                            "market_ok": False,
                        }
                    )
                continue
            weighted_ret = 0.0
            traded = 0
            for rank, item in enumerate(ranking.itertuples(index=False), start=1):
                if item.symbol not in trade_cache:
                    trade_cache[item.symbol] = load_price_file(files.get(item.symbol, ""))
                stock_df = trade_cache.get(item.symbol, pd.DataFrame())
                ret, buy_date, sell_date, buy_open, sell_close = calc_next_month_trade_return(
                    stock_df,
                    item.signal_date,
                    hold_month,
                    min_buy_open=config.min_buy_open,
                    require_buy_above_ma=config.require_buy_above_ma,
                    stop_loss=config.stop_loss,
                )
                if buy_date:
                    traded += 1
                weighted_ret += ret / top_n
                pick_rows.append(
                    {
                        "top_n": top_n,
                        "rank_mode": config.rank_mode,
                        "signal_month": signal_month,
                        "hold_month": str(hold_month),
                        "rank": rank,
                        "symbol": item.symbol,
                        "signal_date": str(pd.Timestamp(item.signal_date).date()),
                        "rank_ret": float(getattr(item, rank_col)),
                        "ytd_ret": float(getattr(item, "ytd_ret", np.nan)),
                        "monthly_signal_ret": float(getattr(item, "monthly_signal_ret", np.nan)),
                        "month_ret": ret,
                        "buy_date": buy_date,
                        "sell_date": sell_date,
                        "buy_open": buy_open,
                        "sell_close": sell_close,
                        "market_ok": True,
                    }
                )
            equity_by_top_n[top_n] *= 1.0 + weighted_ret
            monthly_rows.append(
                {
                    "top_n": top_n,
                    "rank_mode": config.rank_mode,
                    "signal_month": signal_month,
                    "hold_month": str(hold_month),
                    "year": hold_month.year,
                    "portfolio_ret": weighted_ret,
                    "equity": equity_by_top_n[top_n],
                    "selected": int(len(ranking)),
                    "traded": traded,
                    "cash_slots": int(top_n - traded),
                    "market_ok": True,
                    "market_date": market_date,
                    "market_close": market_close,
                    "market_ma": market_ma,
                }
            )

    monthly = pd.DataFrame(monthly_rows)
    picks = pd.DataFrame(pick_rows)
    summary = summarize(monthly)
    return monthly, picks, summary


def run_nday_backtest(config: BacktestConfig, files: Dict[str, str]) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    lookback_days = config.rebalance_days or 10
    hold_days = config.hold_days or lookback_days
    panel = build_nday_panel(files, lookback_days)
    if panel.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    top_n_values = config.top_n_list or (config.top_n,)
    all_dates = sorted(panel["dt"].drop_duplicates())
    signal_dates = all_dates[::lookback_days]
    monthly_rows: List[Dict[str, object]] = []
    pick_rows: List[Dict[str, object]] = []
    trade_cache: Dict[str, pd.DataFrame] = {}
    equity_by_top_n = {top_n: 1.0 for top_n in top_n_values}

    for signal_date in signal_dates:
        day_panel = panel[panel["dt"] == signal_date].sort_values("rank_ret", ascending=False)
        if config.max_rank_ret is not None:
            day_panel = day_panel[day_panel["rank_ret"] <= config.max_rank_ret]
        if day_panel.empty:
            continue
        for top_n in top_n_values:
            ranking = day_panel.head(top_n)
            weighted_ret = 0.0
            traded = 0
            for rank, item in enumerate(ranking.itertuples(index=False), start=1):
                if item.symbol not in trade_cache:
                    trade_cache[item.symbol] = load_price_file(files.get(item.symbol, ""))
                stock_df = trade_cache.get(item.symbol, pd.DataFrame())
                ret, buy_date, sell_date, buy_open, sell_close = calc_n_day_trade_return(
                    stock_df,
                    pd.Timestamp(item.dt),
                    hold_days,
                    min_buy_open=config.min_buy_open,
                    require_buy_above_ma=config.require_buy_above_ma,
                    stop_loss=config.stop_loss,
                )
                if buy_date:
                    traded += 1
                weighted_ret += ret / top_n
                pick_rows.append(
                    {
                        "top_n": top_n,
                        "rank_mode": config.rank_mode,
                        "signal_date": str(pd.Timestamp(item.dt).date()),
                        "hold_period": f"{buy_date}:{sell_date}",
                        "rank": rank,
                        "symbol": item.symbol,
                        "rank_ret": float(item.rank_ret),
                        "month_ret": ret,
                        "buy_date": buy_date,
                        "sell_date": sell_date,
                        "buy_open": buy_open,
                        "sell_close": sell_close,
                    }
                )
            equity_by_top_n[top_n] *= 1.0 + weighted_ret
            monthly_rows.append(
                {
                    "top_n": top_n,
                    "rank_mode": config.rank_mode,
                    "signal_month": pd.Timestamp(signal_date).strftime("%Y-%m-%d"),
                    "hold_month": pd.Timestamp(signal_date).strftime("%Y-%m-%d"),
                    "year": pd.Timestamp(signal_date).year,
                    "portfolio_ret": weighted_ret,
                    "equity": equity_by_top_n[top_n],
                    "selected": int(len(ranking)),
                    "traded": traded,
                    "cash_slots": int(top_n - traded),
                    "market_ok": True,
                }
            )

    period_returns = pd.DataFrame(monthly_rows)
    picks = pd.DataFrame(pick_rows)
    summary = summarize(period_returns)
    return period_returns, picks, summary


def max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return np.nan
    peak = equity.cummax()
    dd = equity / peak - 1.0
    return float(dd.min())


def summarize(monthly: pd.DataFrame) -> pd.DataFrame:
    if monthly.empty:
        return pd.DataFrame()
    rows: List[Dict[str, object]] = []
    groups = [((top_n, "all"), sub) for top_n, sub in monthly.groupby("top_n")]
    groups.extend([((top_n, str(year)), sub) for (top_n, year), sub in monthly.groupby(["top_n", "year"])])
    for (top_n, label), sub in groups:
        ret = pd.to_numeric(sub["portfolio_ret"], errors="coerce").dropna()
        eq = (1.0 + ret).cumprod()
        total = float(eq.iloc[-1] - 1.0) if not eq.empty else np.nan
        annualized = np.nan
        if not ret.empty and total > -1.0:
            annualized = float((1.0 + total) ** (12.0 / len(ret)) - 1.0)
        sharpe = np.nan
        if len(ret) > 1 and float(ret.std(ddof=1)) > 0:
            sharpe = float(ret.mean() / ret.std(ddof=1) * np.sqrt(12.0))
        rows.append(
            {
                "top_n": int(top_n),
                "rank_mode": str(sub["rank_mode"].iloc[0]) if "rank_mode" in sub and not sub.empty else "",
                "period": label,
                "months": int(len(ret)),
                "total_ret": total,
                "annualized_ret": annualized,
                "avg_month_ret": float(ret.mean()) if not ret.empty else np.nan,
                "win_rate": float((ret > 0).mean()) if not ret.empty else np.nan,
                "max_drawdown": max_drawdown(eq),
                "sharpe_monthly_ann": sharpe,
                "best_month": float(ret.max()) if not ret.empty else np.nan,
                "worst_month": float(ret.min()) if not ret.empty else np.nan,
                "avg_traded_slots": float(sub["traded"].mean()) if "traded" in sub else np.nan,
                "market_on_months": int(sub["market_ok"].sum()) if "market_ok" in sub else int(len(sub)),
            }
        )
    return pd.DataFrame(rows)


def save_outputs(config: BacktestConfig, monthly: pd.DataFrame, picks: pd.DataFrame, summary: pd.DataFrame) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = config.output_dir / f"year_start_momentum_simple_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    monthly.to_csv(out_dir / "monthly_returns.csv", index=False, encoding="utf-8-sig")
    picks.to_csv(out_dir / "monthly_picks.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(out_dir / "summary.csv", index=False, encoding="utf-8-sig")
    return out_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Simple YTD top10 monthly momentum backtest on csv_his.")
    parser.add_argument("--csv-dir", default="/Users/water/abu/csv_his")
    parser.add_argument("--output-dir", default="cy_quant/output")
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--top-n-list", default="", help="Optional comma-separated top N values, e.g. 10,20.")
    parser.add_argument("--max-symbols", type=int, default=None)
    parser.add_argument("--market-prefix", default="", help="Optional prefix filter, e.g. sh, sz, us, hk.")
    parser.add_argument("--market-prefixes", default="", help="Optional comma-separated prefix filter, e.g. sh,sz.")
    parser.add_argument("--benchmark-path", default="", help="Optional benchmark file for market MA filter.")
    parser.add_argument("--market-ma-window", type=int, default=120)
    parser.add_argument("--rank-mode", choices=["ytd", "monthly", "nday", "lookback"], default="ytd")
    parser.add_argument("--lookback-days", type=int, default=0, help="For rank-mode lookback: ranking lookback in trading days.")
    parser.add_argument("--rebalance-days", type=int, default=0, help="For rank-mode nday: lookback and rebalance interval in trading dates.")
    parser.add_argument("--hold-days", type=int, default=0, help="For rank-mode nday: per-symbol trading-day holding length.")
    parser.add_argument("--max-rank-ret", type=float, default=None, help="Exclude candidates above this ranking return, e.g. 1.0 for 100%.")
    parser.add_argument("--min-buy-open", type=float, default=None, help="Skip trades whose next-month buy open is below this price.")
    parser.add_argument("--require-buy-above-ma", default="", help="Comma-separated MA windows checked on the day before buy, e.g. 20,60.")
    parser.add_argument("--stop-loss", type=float, default=None, help="Stop loss from buy open, e.g. 0.10 for 10%.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = BacktestConfig(
        csv_dir=Path(args.csv_dir),
        output_dir=Path(args.output_dir),
        top_n=args.top_n,
        top_n_list=tuple(int(v.strip()) for v in args.top_n_list.split(",") if v.strip()),
        max_symbols=args.max_symbols,
        market_prefix=args.market_prefix,
        market_prefixes=tuple(p.strip() for p in args.market_prefixes.split(",") if p.strip()),
        benchmark_path=args.benchmark_path,
        market_ma_window=args.market_ma_window,
        rank_mode=args.rank_mode,
        lookback_days=args.lookback_days,
        rebalance_days=args.rebalance_days,
        hold_days=args.hold_days,
        max_rank_ret=args.max_rank_ret,
        min_buy_open=args.min_buy_open,
        require_buy_above_ma=tuple(int(v.strip()) for v in args.require_buy_above_ma.split(",") if v.strip()),
        stop_loss=args.stop_loss,
    )
    monthly, picks, summary = run_backtest(config)
    out_dir = save_outputs(config, monthly, picks, summary)
    print(f"output_dir: {out_dir}")
    if summary.empty:
        print("No result.")
    else:
        print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
