"""Forward test MA120 scored signals with historical K-line data."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List, Optional

import pandas as pd

from .kline_loader import KlineLoader, read_pool_codes
from .radar import RadarConfig, analyze_one
from .scorer import score_row
from .stock_meta import StockMeta


@dataclass
class ForwardTestConfig:
    min_total_score: int = 80
    horizon_days: int = 20
    recent_trade_days: int = 120
    min_level: str = "强候选"
    profit_targets: tuple[float, ...] = (10.0, 20.0)
    stop_loss_pct: float = -8.0
    signal_cooldown_days: int = 0


_LEVEL_RANK = {
    "强候选": 0,
    "重点观察": 1,
    "普通观察": 2,
    "剔除观察": 3,
}


def _level_allowed(level: str, min_level: str) -> bool:
    return _LEVEL_RANK.get(level, 9) <= _LEVEL_RANK.get(min_level, 9)


def evaluate_forward_window(
    df: pd.DataFrame,
    signal_idx: int,
    horizon_days: int,
    stop_loss_pct: float = -8.0,
    profit_targets: tuple[float, ...] = (10.0, 20.0),
) -> Optional[dict]:
    """Measure forward return/drawdown from the signal close."""
    if signal_idx >= len(df) - 1:
        return None
    end_idx = min(signal_idx + horizon_days, len(df) - 1)
    future = df.iloc[signal_idx + 1 : end_idx + 1].copy()
    if future.empty:
        return None

    entry_price = float(df.iloc[signal_idx]["close"])
    if entry_price <= 0:
        return None

    high_col = "high" if "high" in future.columns else "close"
    low_col = "low" if "low" in future.columns else "close"
    max_high = float(pd.to_numeric(future[high_col], errors="coerce").max())
    min_low = float(pd.to_numeric(future[low_col], errors="coerce").min())
    final_close = float(future.iloc[-1]["close"])

    max_gain_pct = (max_high / entry_price - 1) * 100
    max_drawdown_pct = (min_low / entry_price - 1) * 100
    final_return_pct = (final_close / entry_price - 1) * 100

    first_stop_date = ""
    first_stop_offset = None
    for offset, (_, row) in enumerate(future.iterrows(), start=1):
        low = float(row[low_col])
        drawdown = (low / entry_price - 1) * 100
        if drawdown <= stop_loss_pct:
            first_stop_date = str(row["trade_date"])
            first_stop_offset = offset
            break

    target_results = {}
    for target in profit_targets:
        target_int = int(target)
        first_target_date = ""
        first_target_offset = None
        trigger_price = entry_price * (1 + target / 100)
        for offset, (_, row) in enumerate(future.iterrows(), start=1):
            high = float(row[high_col])
            if high >= trigger_price:
                first_target_date = str(row["trade_date"])
                first_target_offset = offset
                break
        target_results[f"hit_{target_int}pct"] = bool(first_target_date)
        target_results[f"first_hit_{target_int}pct_date"] = first_target_date
        target_results[f"hit_{target_int}pct_before_stop"] = bool(
            first_target_offset is not None
            and (first_stop_offset is None or first_target_offset < first_stop_offset)
        )

    return {
        "entry_price": round(entry_price, 4),
        "future_days": int(len(future)),
        "max_gain_pct": round(max_gain_pct, 2),
        "max_drawdown_pct": round(max_drawdown_pct, 2),
        "final_return_pct": round(final_return_pct, 2),
        "hit_stop_loss": bool(first_stop_date),
        "first_stop_date": first_stop_date,
        **target_results,
    }


def _iter_signal_indices(total_len: int, horizon_days: int, recent_trade_days: int) -> range:
    last_signal_idx = total_len - 1 - horizon_days
    if last_signal_idx < 0:
        return range(0)
    first_signal_idx = max(0, last_signal_idx - recent_trade_days + 1)
    return range(first_signal_idx, last_signal_idx + 1)


def forward_test_one(
    ts_code: str,
    df: pd.DataFrame,
    *,
    radar_config: Optional[RadarConfig] = None,
    test_config: Optional[ForwardTestConfig] = None,
) -> List[dict]:
    """Collect historical scored signals and their forward outcomes for one stock."""
    radar_cfg = radar_config or RadarConfig()
    test_cfg = test_config or ForwardTestConfig()
    if df is None or df.empty:
        return []
    df = df.sort_values("trade_date").reset_index(drop=True)

    rows: List[dict] = []
    last_signal_idx: Optional[int] = None
    for idx in _iter_signal_indices(len(df), test_cfg.horizon_days, test_cfg.recent_trade_days):
        if last_signal_idx is not None and test_cfg.signal_cooldown_days > 0:
            if idx - last_signal_idx < test_cfg.signal_cooldown_days:
                continue
        window = df.iloc[: idx + 1].copy()
        signal = analyze_one(ts_code, window, config=radar_cfg)
        if not signal:
            continue
        scores = score_row(pd.Series(signal))
        if scores["total_score"] < test_cfg.min_total_score:
            continue
        if not _level_allowed(scores["candidate_level"], test_cfg.min_level):
            continue

        forward = evaluate_forward_window(
            df,
            idx,
            test_cfg.horizon_days,
            stop_loss_pct=test_cfg.stop_loss_pct,
            profit_targets=test_cfg.profit_targets,
        )
        if not forward:
            continue

        rec = {**signal, **scores, **forward}
        rec["signal_date"] = signal["trade_date"]
        rec["horizon_days"] = test_cfg.horizon_days
        rec["signal_cooldown_days"] = test_cfg.signal_cooldown_days
        rows.append(rec)
        last_signal_idx = idx
    return rows


def run_forward_test(
    *,
    data_roots: Optional[Iterable[str]] = None,
    pool_csv: Optional[str] = None,
    limit: Optional[int] = None,
    exclude_st: bool = True,
    basic_csv: Optional[str] = None,
    radar_config: Optional[RadarConfig] = None,
    test_config: Optional[ForwardTestConfig] = None,
) -> pd.DataFrame:
    loader = KlineLoader(data_roots=data_roots)
    stock_meta = StockMeta(basic_csv=basic_csv)
    if pool_csv:
        targets = [(code, loader.find_file(code)) for code in read_pool_codes(pool_csv)]
    else:
        targets = [(item.ts_code, item.path) for item in loader.iter_a_share_files()]
    if limit:
        targets = targets[:limit]

    rows: List[dict] = []
    for ts_code, path in targets:
        if exclude_st and stock_meta.is_st(ts_code):
            continue
        if not path:
            continue
        df = loader.load(path)
        rows.extend(
            forward_test_one(
                ts_code,
                df,
                radar_config=radar_config,
                test_config=test_config,
            )
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out = out.sort_values(
        ["total_score", "max_gain_pct", "max_drawdown_pct"],
        ascending=[False, False, False],
    ).reset_index(drop=True)
    return out


def summarize_forward_results(df: pd.DataFrame) -> pd.DataFrame:
    """Summarize forward-test results by candidate level."""
    if df is None or df.empty:
        return pd.DataFrame()
    agg = {
        "ts_code": "count",
        "max_gain_pct": "mean",
        "max_drawdown_pct": "mean",
        "final_return_pct": "mean",
        "hit_stop_loss": "mean",
    }
    for col in df.columns:
        if col.startswith("hit_") and col.endswith("pct"):
            agg[col] = "mean"
        if col.startswith("hit_") and col.endswith("pct_before_stop"):
            agg[col] = "mean"
    summary = df.groupby("candidate_level").agg(agg).rename(columns={"ts_code": "signals"})
    return summary.round(4).sort_values("signals", ascending=False)


def save_forward_report(df: pd.DataFrame, out_csv: Optional[str] = None) -> str:
    if out_csv is None:
        today = datetime.now().strftime("%Y%m%d")
        out_csv = os.path.join("ma120_mvp", "output", f"forward_test_{today}.csv")
    os.makedirs(os.path.dirname(os.path.abspath(out_csv)), exist_ok=True)
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    return out_csv
