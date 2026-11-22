#!/usr/bin/env python3
"""A-share weekly MA120 breakout / +5% confirmation backtest.

Signals are evaluated at the completed week's close.  An executable order is
therefore priced at the first available open in the following week; this avoids
using information not available at the time of the order.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime
from functools import partial
from multiprocessing import Pool
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


@dataclass
class Config:
    ma_weeks: int = 120
    confirmation_gain: float = 0.05
    buy_cost: float = 0.0005       # 5 bp: commission plus conservative slippage
    sell_cost: float = 0.0010      # 5 bp commission/slippage + 5 bp stamp duty


def parse_dates(values: pd.Series) -> pd.Series:
    text = values.astype(str).str.strip()
    ymd = pd.to_datetime(text.where(text.str.fullmatch(r"\d{8}")), format="%Y%m%d", errors="coerce")
    other = pd.to_datetime(text.where(~text.str.fullmatch(r"\d{8}")), errors="coerce")
    return ymd.fillna(other)


def load_weekly(path: Path, cfg: Config) -> pd.DataFrame:
    raw = pd.read_csv(path)
    date_col = "date" if "date" in raw.columns else "Unnamed: 0"
    required = {date_col, "open", "close"}
    if not required.issubset(raw.columns):
        return pd.DataFrame()
    daily = pd.DataFrame({
        "date": parse_dates(raw[date_col]),
        "open": pd.to_numeric(raw["open"], errors="coerce"),
        "close": pd.to_numeric(raw["close"], errors="coerce"),
    }).dropna().sort_values("date").drop_duplicates("date")
    daily = daily[(daily.open > 0) & (daily.close > 0)]
    if daily.empty:
        return pd.DataFrame()
    daily["week"] = daily.date.dt.to_period("W-FRI")
    weekly = daily.groupby("week", sort=True).agg(
        week_start=("date", "first"), week_end=("date", "last"), close=("close", "last"), first_open=("open", "first")
    ).reset_index(drop=True)
    weekly["next_open"] = weekly.first_open.shift(-1)
    weekly["next_week_date"] = weekly.week_start.shift(-1)
    weekly["ma120w"] = weekly.close.rolling(cfg.ma_weeks, min_periods=cfg.ma_weeks).mean()
    weekly["ma120w_slope_1w"] = weekly.ma120w / weekly.ma120w.shift(1) - 1.0
    return weekly


def simulate(symbol: str, weekly: pd.DataFrame, cfg: Config) -> list[dict]:
    rows: list[dict] = []
    if len(weekly) <= cfg.ma_weeks + 1:
        return rows
    closes = weekly.close.to_numpy(float); mas = weekly.ma120w.to_numpy(float)
    slopes = weekly.ma120w_slope_1w.to_numpy(float); next_opens = weekly.next_open.to_numpy(float)
    ends = weekly.week_end.to_numpy(); next_dates = weekly.next_week_date.to_numpy()
    candidate_idx: int | None = None
    position: dict | None = None
    for i in range(cfg.ma_weeks, len(weekly) - 1):
        close, ma = closes[i], mas[i]
        prior_close, prior_ma, slope = closes[i - 1], mas[i - 1], slopes[i]
        if position is not None:
            if close < ma:
                exit_open = next_opens[i]
                if pd.notna(exit_open) and exit_open > 0:
                    gross = exit_open / position["entry_price"] - 1.0
                    net = exit_open * (1 - cfg.sell_cost) / (position["entry_price"] * (1 + cfg.buy_cost)) - 1.0
                    rows.append({**position, "exit_signal_date": ends[i],
                                 "exit_date": next_dates[i], "exit_price": exit_open,
                                 "exit_reason": "weekly_close_below_ma120w", "gross_return": gross,
                                 "net_return": net, "holding_weeks": i - position["entry_week_index"]})
                    position = None
                    candidate_idx = None
            continue

        crossed_up = bool(close > ma and prior_close <= prior_ma)
        if crossed_up and slope > 0:
            candidate_idx = i
        if candidate_idx is None:
            continue
        # A failed hold above the average cancels the pending breakout.
        if close < ma:
            candidate_idx = None
            continue
        cross_close = closes[candidate_idx]
        if close >= cross_close * (1 + cfg.confirmation_gain) and slope > 0:
            entry_open = next_opens[i]
            if pd.notna(entry_open) and entry_open > 0:
                position = {
                    "symbol": symbol, "cross_date": ends[candidate_idx],
                    "confirm_date": ends[i], "entry_date": next_dates[i],
                    "entry_price": entry_open, "entry_week_index": i,
                    "ma120w_at_confirm": ma, "slope_1w_at_confirm": slope,
                }
                candidate_idx = None
    if position is not None:
        rows.append({**position, "exit_signal_date": pd.NaT, "exit_date": pd.NaT, "exit_price": np.nan,
                     "exit_reason": "open_end", "gross_return": np.nan, "net_return": np.nan,
                     "holding_weeks": len(weekly) - 1 - position["entry_week_index"]})
    return rows


def process_path(path_text: str, cfg: Config) -> tuple[int, list[dict]]:
    """Worker kept module-level so the full A-share universe can be parallelized."""
    path = Path(path_text)
    weekly = load_weekly(path, cfg)
    return (int(not weekly.empty), simulate(path.name.split("_", 1)[0], weekly, cfg) if not weekly.empty else [])


def summarize(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame(columns=["return_basis", "all_trades", "closed_trades", "open_end", "win_rate", "mean_return", "median_return", "profit_factor", "mean_holding_weeks", "median_holding_weeks", "p25_return", "p75_return", "max_return", "min_return"])
    closed = trades[trades.exit_reason != "open_end"].copy()
    if closed.empty:
        return pd.DataFrame()
    result = []
    for name in ("gross_return", "net_return"):
        values = closed[name]
        gain = values[values > 0].sum()
        loss = values[values < 0].sum()
        result.append({"return_basis": name, "all_trades": len(trades), "closed_trades": len(closed),
                       "open_end": int((trades.exit_reason == "open_end").sum()), "win_rate": (values > 0).mean(),
                       "mean_return": values.mean(), "median_return": values.median(),
                       "profit_factor": gain / abs(loss) if loss < 0 else np.inf,
                       "mean_holding_weeks": closed.holding_weeks.mean(), "median_holding_weeks": closed.holding_weeks.median(),
                       "p25_return": values.quantile(.25), "p75_return": values.quantile(.75),
                       "max_return": values.max(), "min_return": values.min()})
    return pd.DataFrame(result)


def main(csv_dir: str, output_root: str, cfg: Config, workers: int, shard_count: int, shard_index: int, run_id: str | None) -> Path:
    paths: Iterable[Path] = sorted(p for p in Path(csv_dir).iterdir() if p.is_file() and p.name.startswith(("sh", "sz")))
    paths = list(paths)
    if not 0 <= shard_index < shard_count:
        raise ValueError("shard-index must be in [0, shard-count)")
    all_file_count = len(paths)
    paths = paths[shard_index::shard_count]
    trades: list[dict] = []
    processed = 0
    worker = partial(process_path, cfg=cfg)
    if workers == 1:
        for path in paths:
            valid, item_trades = worker(str(path))
            processed += valid
            trades.extend(item_trades)
    else:
        with Pool(processes=workers) as pool:
            for valid, item_trades in pool.imap_unordered(worker, map(str, paths), chunksize=20):
                processed += valid
                trades.extend(item_trades)
    frame = pd.DataFrame(trades)
    stamp = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    out = Path(output_root) / f"weekly_ma120_breakout_a_{stamp}_shard{shard_index + 1}of{shard_count}"
    out.mkdir(parents=True, exist_ok=False)
    frame.to_csv(out / "trades.csv", index=False, encoding="utf-8-sig")
    summary = summarize(frame)
    summary.to_csv(out / "summary.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([{**asdict(cfg), "all_a_share_files": all_file_count, "source_files": len(paths), "processed_files": processed,
                   "data_directory": csv_dir, "rule": "weekly close crosses above 120-week MA; MA slope > 0; buy next-week open after >=5% from cross close; sell next-week open after weekly close < MA"}]).to_csv(out / "metadata.csv", index=False, encoding="utf-8-sig")
    print(out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="A-share weekly MA120 breakout backtest")
    parser.add_argument("--csv-dir", default="/Users/water/abu/csv_his")
    parser.add_argument("--output-root", default="cy_quant/output")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--run-id")
    args = parser.parse_args()
    main(args.csv_dir, args.output_root, Config(), args.workers, args.shard_count, args.shard_index, args.run_id)
