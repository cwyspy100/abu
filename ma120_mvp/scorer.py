"""Rule-based scoring for the MA120 daily radar."""

from __future__ import annotations

from typing import List

import pandas as pd


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


def _has_signal(signals: str, name: str) -> bool:
    return name in str(signals or "")


def _has_risk(risks: str, name: str) -> bool:
    return name in str(risks or "")


def score_row(row: pd.Series) -> dict:
    """Score one radar row into trend/entry/risk/quality buckets."""
    close = _to_float(row.get("close"))
    ma20 = _to_float(row.get("ma20"))
    ma60 = _to_float(row.get("ma60"))
    ma120 = _to_float(row.get("ma120"))
    slope = _to_float(row.get("ma120_slope_pct"))
    days = int(_to_float(row.get("days_above_ma120")))
    vs_ma120 = _to_float(row.get("price_vs_ma120_pct"))
    ret_20d = _to_float(row.get("ret_20d_pct"))
    drawdown_20d = _to_float(row.get("drawdown_20d_pct"))
    volume_ratio = _to_float(row.get("volume_ratio"), default=-1.0)
    signals = str(row.get("signals") or "")
    risks = str(row.get("risks") or "")

    reasons: List[str] = []

    trend_score = 0
    if slope >= 2:
        trend_score += 12
        reasons.append("MA120斜率强")
    elif slope >= 1:
        trend_score += 10
        reasons.append("MA120斜率良好")
    elif slope >= 0.5:
        trend_score += 7
        reasons.append("MA120温和上行")
    elif slope > 0:
        trend_score += 4

    if ma20 > ma60 > ma120:
        trend_score += 10
        reasons.append("均线多头排列")
    elif ma20 > ma60 and close > ma120:
        trend_score += 6
        reasons.append("短中期趋势改善")
    elif close > ma120:
        trend_score += 3

    if 11 <= days <= 20:
        trend_score += 8
        reasons.append("站上MA120黄金窗口")
    elif 21 <= days <= 60:
        trend_score += 7
        reasons.append("站上MA120天数适中")
    elif 1 <= days <= 3:
        trend_score += 3
        reasons.append("刚站上MA120")
    elif 4 <= days <= 5:
        trend_score += 2
    elif 6 <= days <= 10:
        trend_score += 1
        reasons.append("站上6-10天谨慎")
    elif 61 <= days <= 120:
        trend_score += 4
    elif days > 120:
        trend_score += 2

    if 8 <= vs_ma120 <= 15:
        trend_score += 8
        reasons.append("MA120偏离优势区间")
    elif 3 <= vs_ma120 < 8:
        trend_score += 6
        reasons.append("距离MA120较健康")
    elif 0 < vs_ma120 < 3:
        trend_score += 5
    elif 15 < vs_ma120 <= 25:
        trend_score += 3
        reasons.append("距离MA120偏高")
    elif 25 < vs_ma120 <= 35:
        trend_score += 2
    trend_score = min(trend_score, 35)

    entry_score = 0
    if _has_signal(signals, "新站上MA120观察"):
        entry_score += 8
        reasons.append("新站上MA120")
    if _has_signal(signals, "突破") and _has_signal(signals, "高点观察"):
        entry_score += 10
        reasons.append("突破近期高点")
    if _has_signal(signals, "回踩均线企稳观察"):
        entry_score += 10
        reasons.append("回踩均线企稳")
    if _has_signal(signals, "突破") and _has_signal(signals, "高点观察") and _has_signal(signals, "回踩均线企稳观察"):
        entry_score += 3
        reasons.append("突破回踩共振")
    if volume_ratio >= 1.2 and _has_signal(signals, "突破"):
        entry_score += 2
        reasons.append("突破伴随放量")
    if not signals and 5 <= vs_ma120 <= 15 and 0 <= ret_20d <= 20:
        entry_score += 5
        reasons.append("趋势健康待买点")
    entry_score = min(entry_score, 30)

    risk_score = 20
    if _has_risk(risks, "跌破MA20"):
        risk_score -= 6
    if _has_risk(risks, "跌破MA60"):
        risk_score -= 10
    if _has_risk(risks, "偏离MA120过大"):
        risk_score -= 8
    if _has_risk(risks, "20日回撤过大"):
        risk_score -= 8
    if drawdown_20d <= -15:
        risk_score -= 8
        reasons.append("20日回撤过深")
    elif drawdown_20d <= -10:
        risk_score -= 6
        reasons.append("20日回撤偏深")
    elif drawdown_20d <= -5:
        risk_score -= 2
    elif -5 <= drawdown_20d <= 0:
        risk_score += 2
        reasons.append("近期回撤可控")
    if volume_ratio > 3:
        risk_score -= 8
        reasons.append("量比过热")
    elif 2 < volume_ratio <= 3:
        risk_score -= 2
    if vs_ma120 > 15:
        risk_score -= 4
    if vs_ma120 > 25:
        risk_score -= 4
    risk_score = max(0, min(risk_score, 20))

    quality_score = 0
    if close >= 5:
        quality_score += 5
    else:
        reasons.append("低价股谨慎")
    if 0 <= ret_20d <= 35:
        quality_score += 5
    elif ret_20d > 35:
        reasons.append("20日涨幅偏热")
    if 1.2 <= volume_ratio <= 2:
        quality_score += 5
        reasons.append("量比优势区间")
    elif 0.8 <= volume_ratio < 1.2:
        quality_score += 4
    elif 2 < volume_ratio <= 3:
        quality_score += 3
    elif 0 <= volume_ratio < 0.8:
        quality_score += 2
    elif volume_ratio < 0:
        quality_score += 2
    elif volume_ratio > 3:
        reasons.append("量能异常放大")
    quality_score = min(quality_score, 15)

    total_score = trend_score + entry_score + risk_score + quality_score
    hard_risk = _has_risk(risks, "跌破MA60") or _has_risk(risks, "偏离MA120过大")
    if total_score >= 80 and not hard_risk:
        level = "强候选"
    elif total_score >= 70 and not hard_risk:
        level = "重点观察"
    elif total_score >= 60:
        level = "普通观察"
    else:
        level = "剔除观察"

    research_setups: List[str] = []
    if _has_signal(signals, "新站上MA120观察") and 0 <= vs_ma120 <= 3 and 1.2 <= volume_ratio <= 2:
        research_setups.append("低位新站上")
    if days > 120 and 2 <= slope <= 4:
        research_setups.append("长期趋势延续")
    if 8 <= vs_ma120 <= 15 and 11 <= days <= 20 and 1.2 <= volume_ratio <= 2:
        research_setups.append("进攻突破窗口")

    return {
        "trend_score": int(trend_score),
        "entry_score": int(entry_score),
        "risk_score": int(risk_score),
        "quality_score": int(quality_score),
        "total_score": int(total_score),
        "candidate_level": level,
        "research_setup": ";".join(research_setups),
        "score_reason": ";".join(reasons[:8]),
    }


def score_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Append scoring columns and sort best candidates first."""
    if df is None or df.empty:
        return df
    scored = df.copy()
    score_df = pd.DataFrame([score_row(row) for _, row in scored.iterrows()])
    scored = pd.concat([scored.reset_index(drop=True), score_df], axis=1)
    level_order = {"强候选": 0, "重点观察": 1, "普通观察": 2, "剔除观察": 3}
    scored["_level_order"] = scored["candidate_level"].map(level_order).fillna(9)
    scored = scored.sort_values(
        ["_level_order", "total_score", "risk_score", "entry_score", "ma120_slope_pct"],
        ascending=[True, False, False, False, False],
    ).drop(columns=["_level_order"])
    return scored.reset_index(drop=True)
