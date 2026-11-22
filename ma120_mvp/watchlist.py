"""Build a compact daily watchlist from the full MA120 radar."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Iterable, List, Optional

import pandas as pd


_LEVEL_RANK = {
    "强候选": 0,
    "重点观察": 1,
    "普通观察": 2,
    "剔除观察": 3,
}


@dataclass
class WatchlistConfig:
    """Selection rules for the human-sized daily watchlist."""

    setup_caps: Dict[str, int] = field(
        default_factory=lambda: {
            "低位新站上": 10,
            "进攻突破窗口": 10,
            "长期趋势延续": 5,
        }
    )
    max_total: int = 25
    min_level: str = "重点观察"
    min_price: float = 5.0
    max_volume_ratio: float = 3.0
    hard_risks: tuple[str, ...] = ("跌破MA20", "跌破MA60", "偏离MA120过大", "20日回撤过大")


def _to_float(value, default: float = 0.0) -> float:
    try:
        if value == "":
            return default
        val = float(value)
        if pd.isna(val):
            return default
        return val
    except Exception:
        return default


def _level_allowed(level: object, min_level: str) -> bool:
    return _LEVEL_RANK.get(str(level), 9) <= _LEVEL_RANK.get(min_level, 9)


def _has_any_risk(risks: object, hard_risks: Iterable[str]) -> bool:
    text = str(risks or "")
    return any(risk in text for risk in hard_risks)


def _has_setup(row: pd.Series, setup: str) -> bool:
    return setup in str(row.get("research_setup") or "")


def _watch_reason(row: pd.Series, setup: str) -> str:
    parts: List[str] = [setup]
    signals = str(row.get("signals") or "")
    if "新站上MA120观察" in signals:
        parts.append("新站上")
    if "突破" in signals:
        parts.append("突破")
    if "回踩均线企稳观察" in signals:
        parts.append("回踩企稳")
    return ";".join(parts)


def _base_filter(df: pd.DataFrame, cfg: WatchlistConfig) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    research_setup = out["research_setup"] if "research_setup" in out.columns else pd.Series([""] * len(out), index=out.index)
    out = out[research_setup.fillna("").astype(str).ne("")]
    out = out[out["candidate_level"].apply(lambda level: _level_allowed(level, cfg.min_level))]
    out = out[pd.to_numeric(out["close"], errors="coerce") >= cfg.min_price]
    volume_ratio = pd.to_numeric(out.get("volume_ratio", pd.Series([pd.NA] * len(out))), errors="coerce")
    out = out[(volume_ratio.isna()) | (volume_ratio <= cfg.max_volume_ratio)]
    risks = out["risks"] if "risks" in out.columns else pd.Series([""] * len(out), index=out.index)
    out = out[~risks.apply(lambda risk_text: _has_any_risk(risk_text, cfg.hard_risks))]
    return out


def select_watchlist(df: pd.DataFrame, config: Optional[WatchlistConfig] = None) -> pd.DataFrame:
    """Select a compact watchlist grouped by researched setup tags."""
    cfg = config or WatchlistConfig()
    base = _base_filter(df, cfg)
    if base.empty:
        return base

    rows = []
    for setup, cap in cfg.setup_caps.items():
        setup_df = base[base.apply(lambda row: _has_setup(row, setup), axis=1)].copy()
        if setup_df.empty:
            continue
        setup_df["watch_setup"] = setup
        setup_df["watch_reason"] = setup_df.apply(lambda row: _watch_reason(row, setup), axis=1)
        setup_df["_level_rank"] = setup_df["candidate_level"].map(_LEVEL_RANK).fillna(9)
        setup_df["_volume_ratio_num"] = setup_df["volume_ratio"].apply(lambda val: _to_float(val, default=0.0))
        setup_df = setup_df.sort_values(
            [
                "_level_rank",
                "total_score",
                "risk_score",
                "entry_score",
                "ma120_slope_pct",
                "_volume_ratio_num",
            ],
            ascending=[True, False, False, False, False, False],
        )
        rows.append(setup_df.head(cap))

    if not rows:
        return pd.DataFrame(columns=list(df.columns) + ["watch_setup", "watch_reason"])

    selected = pd.concat(rows, ignore_index=True)
    selected["_setup_order"] = selected["watch_setup"].map({name: i for i, name in enumerate(cfg.setup_caps)})
    selected["_level_rank"] = selected["candidate_level"].map(_LEVEL_RANK).fillna(9)
    selected = selected.sort_values(
        ["_setup_order", "_level_rank", "total_score", "risk_score", "entry_score"],
        ascending=[True, True, False, False, False],
    )
    selected = selected.drop_duplicates("ts_code", keep="first").head(cfg.max_total)
    return selected.drop(columns=[c for c in selected.columns if c.startswith("_")]).reset_index(drop=True)


def save_watchlist(df: pd.DataFrame, out_csv: Optional[str] = None) -> str:
    if out_csv is None:
        today = datetime.now().strftime("%Y%m%d")
        out_csv = os.path.join("ma120_mvp", "output", f"ma120_watchlist_{today}.csv")
    os.makedirs(os.path.dirname(os.path.abspath(out_csv)), exist_ok=True)
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    return out_csv
