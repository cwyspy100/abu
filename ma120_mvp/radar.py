"""Daily MA120 stock radar."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, List, Optional

import pandas as pd

from .kline_loader import KlineLoader, read_pool_codes
from .stock_meta import StockMeta


@dataclass
class RadarConfig:
    ma120_slope_lookback: int = 20
    max_price_vs_ma120_pct: float = 25.0
    chase_risk_pct: float = 35.0
    max_20d_drawdown_pct: float = 15.0
    breakout_lookback: int = 20
    min_breakout_volume_ratio: float = 1.2
    pullback_near_pct: float = 3.0


def _continuous_true_days(flags: pd.Series) -> int:
    days = 0
    for flag in reversed(flags.tolist()):
        if bool(flag):
            days += 1
        else:
            break
    return days


def analyze_one(ts_code: str, df: pd.DataFrame, config: Optional[RadarConfig] = None) -> Optional[dict]:
    """Analyze one stock and return a radar row when it is above MA120."""
    cfg = config or RadarConfig()
    need = max(121 + cfg.ma120_slope_lookback, cfg.breakout_lookback + 1, 60)
    if df is None or df.empty or len(df) < need:
        return None

    out = df.copy().sort_values("trade_date").reset_index(drop=True)
    close = pd.to_numeric(out["close"], errors="coerce")
    out["ma20"] = close.rolling(20, min_periods=20).mean()
    out["ma60"] = close.rolling(60, min_periods=60).mean()
    out["ma120"] = close.rolling(120, min_periods=120).mean()
    if "volume" in out.columns:
        out["vol_ma20"] = pd.to_numeric(out["volume"], errors="coerce").rolling(20, min_periods=20).mean()
    else:
        out["vol_ma20"] = pd.NA

    last = out.iloc[-1]
    prev = out.iloc[-2]
    if pd.isna(last["ma120"]) or float(last["ma120"]) <= 0:
        return None

    latest_close = float(last["close"])
    ma20 = float(last["ma20"]) if not pd.isna(last["ma20"]) else 0.0
    ma60 = float(last["ma60"]) if not pd.isna(last["ma60"]) else 0.0
    ma120 = float(last["ma120"])
    ma120_ref = out["ma120"].iloc[-1 - cfg.ma120_slope_lookback]
    if pd.isna(ma120_ref) or float(ma120_ref) <= 0:
        return None
    ma120_slope_pct = (ma120 / float(ma120_ref) - 1) * 100
    above_ma120 = latest_close > ma120
    if not above_ma120 or ma120_slope_pct <= 0:
        return None

    flags = close > out["ma120"]
    days_above = _continuous_true_days(flags)
    new_above_ma120 = bool(latest_close > ma120 and float(prev["close"]) <= float(prev["ma120"]))
    price_vs_ma120_pct = (latest_close / ma120 - 1) * 100
    ret_5d = (latest_close / float(out.iloc[-5]["close"]) - 1) * 100 if len(out) >= 5 and float(out.iloc[-5]["close"]) else 0.0
    ret_20d = (latest_close / float(out.iloc[-20]["close"]) - 1) * 100 if len(out) >= 20 and float(out.iloc[-20]["close"]) else 0.0

    high_col = "high" if "high" in out.columns else "close"
    low_col = "low" if "low" in out.columns else "close"
    recent_high_20 = float(out[high_col].iloc[-20:].max())
    drawdown_20d_pct = (latest_close / recent_high_20 - 1) * 100 if recent_high_20 else 0.0

    prior_high = float(out[high_col].iloc[-cfg.breakout_lookback - 1 : -1].max())
    volume_ratio = None
    if "volume" in out.columns and not pd.isna(last.get("vol_ma20")) and float(last["vol_ma20"]) > 0:
        volume_ratio = float(last["volume"]) / float(last["vol_ma20"])

    trend = "多头排列" if ma20 > ma60 > ma120 else "站上120日线"
    signals: List[str] = []
    risks: List[str] = []

    if new_above_ma120 and price_vs_ma120_pct <= 10:
        signals.append("新站上MA120观察")

    is_breakout = latest_close > prior_high and price_vs_ma120_pct <= cfg.max_price_vs_ma120_pct
    if is_breakout and (volume_ratio is None or volume_ratio >= cfg.min_breakout_volume_ratio):
        signals.append(f"突破{cfg.breakout_lookback}日高点观察")

    near_ma20 = ma20 > 0 and float(last[low_col]) <= ma20 * (1 + cfg.pullback_near_pct / 100) and latest_close >= ma20
    near_ma60 = ma60 > 0 and float(last[low_col]) <= ma60 * (1 + cfg.pullback_near_pct / 100) and latest_close >= ma60
    bullish_day = "open" not in out.columns or latest_close >= float(last["open"])
    if bullish_day and (near_ma20 or near_ma60) and price_vs_ma120_pct <= cfg.max_price_vs_ma120_pct:
        signals.append("回踩均线企稳观察")

    if latest_close < ma20:
        risks.append("跌破MA20")
    if ma60 > 0 and latest_close < ma60:
        risks.append("跌破MA60")
    if price_vs_ma120_pct > cfg.chase_risk_pct:
        risks.append("偏离MA120过大")
    if abs(drawdown_20d_pct) > cfg.max_20d_drawdown_pct:
        risks.append("20日回撤过大")

    action = "观察"
    if signals and not any(r in risks for r in ("跌破MA20", "跌破MA60", "20日回撤过大")):
        action = "买入观察"
    if risks and not signals:
        action = "风险观察"

    return {
        "ts_code": ts_code,
        "trade_date": str(last["trade_date"]),
        "close": round(latest_close, 4),
        "ma20": round(ma20, 4),
        "ma60": round(ma60, 4),
        "ma120": round(ma120, 4),
        "ma120_slope_lookback": cfg.ma120_slope_lookback,
        "ma120_slope_pct": round(ma120_slope_pct, 2),
        "trend": trend,
        "days_above_ma120": int(days_above),
        "price_vs_ma120_pct": round(price_vs_ma120_pct, 2),
        "ret_5d_pct": round(ret_5d, 2),
        "ret_20d_pct": round(ret_20d, 2),
        "drawdown_20d_pct": round(drawdown_20d_pct, 2),
        "volume_ratio": round(volume_ratio, 2) if volume_ratio is not None else "",
        "prior_high": round(prior_high, 4),
        "signals": ";".join(signals),
        "risks": ";".join(risks),
        "action": action,
    }


def scan(
    *,
    data_roots: Optional[Iterable[str]] = None,
    pool_csv: Optional[str] = None,
    limit: Optional[int] = None,
    max_stale_days: Optional[int] = 14,
    exclude_st: bool = True,
    basic_csv: Optional[str] = None,
    config: Optional[RadarConfig] = None,
) -> pd.DataFrame:
    loader = KlineLoader(data_roots=data_roots)
    stock_meta = StockMeta(basic_csv=basic_csv)
    rows = []
    if pool_csv:
        targets = [(code, loader.find_file(code)) for code in read_pool_codes(pool_csv)]
    else:
        targets = [(item.ts_code, item.path) for item in loader.iter_a_share_files()]
    if limit:
        targets = targets[:limit]

    for ts_code, path in targets:
        if not path:
            continue
        df = loader.load(path)
        if max_stale_days is not None and df is not None and not df.empty:
            last_date = datetime.strptime(str(df.iloc[-1]["trade_date"]), "%Y%m%d")
            if last_date.date() < (datetime.now().date() - timedelta(days=max_stale_days)):
                continue
        row = analyze_one(ts_code, df, config=config)
        if row:
            stock_meta.enrich(row)
            if exclude_st and row.get("is_st"):
                continue
            rows.append(row)

    result = pd.DataFrame(rows)
    if result.empty:
        return result
    action_order = {"买入观察": 0, "观察": 1, "风险观察": 2}
    result["_action_order"] = result["action"].map(action_order).fillna(9)
    result = result.sort_values(
        ["_action_order", "price_vs_ma120_pct", "days_above_ma120"],
        ascending=[True, True, False],
    ).drop(columns=["_action_order"])
    return result.reset_index(drop=True)


def save_report(df: pd.DataFrame, out_csv: Optional[str] = None) -> str:
    if out_csv is None:
        today = datetime.now().strftime("%Y%m%d")
        out_csv = os.path.join("ma120_mvp", "output", f"ma120_daily_{today}.csv")
    os.makedirs(os.path.dirname(os.path.abspath(out_csv)), exist_ok=True)
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    return out_csv
