#!/usr/bin/env python3
"""
对 stock_pool_ma120 中 A股标的做千问打分并回写：
- score: 0~10
- remark: 优势+风险，<=500字
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
import warnings
from typing import Any, Dict, List, Optional, Tuple

import requests

try:
    from cy_ai.db import Database
    from cy_ai.qianwen_api import QianwenAPI, QianwenConfig
    from cy_ai.local_features import LocalFeatureBuilder
    from cy_ai.tushare_fetcher import TushareFetcher
    from cy_ai.minimax_api import MiniMaxConfig
except ModuleNotFoundError:
    # 兼容: python cy_ai/score_stock_pool_ma120_qianwen.py 直接运行
    sys.path.append(str(__file__).split("/cy_ai/")[0])
    from cy_ai.db import Database
    from cy_ai.qianwen_api import QianwenAPI, QianwenConfig
    from cy_ai.local_features import LocalFeatureBuilder
    from cy_ai.tushare_fetcher import TushareFetcher
    from cy_ai.minimax_api import MiniMaxConfig

logger = logging.getLogger(__name__)

DEFAULT_FINANCE_DIR = "/Users/water/abu/tushare/finance"
TARGET_FINANCE_END_DATE = "20260331"


def ensure_columns(db: Database) -> None:
    """确保 stock_pool_ma120 存在 score/remark/research_status 字段。"""
    cols = db.query_all(
        """
        SELECT COLUMN_NAME
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'stock_pool_ma120'
        """
    )
    colset = {c["COLUMN_NAME"] for c in cols}

    if "score" not in colset:
        db.execute("ALTER TABLE stock_pool_ma120 ADD COLUMN score DECIMAL(4,2) NULL COMMENT 'AI评分0-10'")
        logger.info("已新增字段 stock_pool_ma120.score")
    if "remark" not in colset:
        db.execute("ALTER TABLE stock_pool_ma120 ADD COLUMN remark VARCHAR(500) NULL COMMENT 'AI分析摘要'")
        logger.info("已新增字段 stock_pool_ma120.remark")
    if "research_status" not in colset:
        db.execute(
            "ALTER TABLE stock_pool_ma120 ADD COLUMN research_status TINYINT DEFAULT 0 COMMENT '研究状态：0未研究，1已研究'"
        )
        logger.info("已新增字段 stock_pool_ma120.research_status")
    if "raw_provider" not in colset:
        db.execute("ALTER TABLE stock_pool_ma120 ADD COLUMN raw_provider VARCHAR(20) NULL COMMENT '模型提供方'")
        logger.info("已新增字段 stock_pool_ma120.raw_provider")
    if "raw_model" not in colset:
        db.execute("ALTER TABLE stock_pool_ma120 ADD COLUMN raw_model VARCHAR(80) NULL COMMENT '模型名'")
        logger.info("已新增字段 stock_pool_ma120.raw_model")
    if "confidence" not in colset:
        db.execute("ALTER TABLE stock_pool_ma120 ADD COLUMN confidence DECIMAL(6,4) NULL COMMENT '置信度0-1'")
        logger.info("已新增字段 stock_pool_ma120.confidence")
    if "raw_response" not in colset:
        db.execute("ALTER TABLE stock_pool_ma120 ADD COLUMN raw_response TEXT NULL COMMENT '模型原始返回'")
        logger.info("已新增字段 stock_pool_ma120.raw_response")
    db.commit()


def fetch_targets(
    db: Database,
    only_unscored: bool,
    only_unresearched: bool,
    limit: int,
    test_stock: str = "",
) -> List[Dict[str, Any]]:
    where = ["market = 'A股'"]
    if test_stock:
        where.append("ts_code = %s")
    if only_unscored:
        where.append("(score IS NULL OR score = 0)")
    if only_unresearched:
        where.append("(research_status IS NULL OR research_status <> 1)")
    where_sql = " AND ".join(where)
    lim = f" LIMIT {int(limit)}" if limit > 0 else ""
    sql = f"""
        SELECT id, ts_code, name, industry, break_date, score, remark,
               industry_strength_score, industry_strength_raw, candidate_score
        FROM stock_pool_ma120
        WHERE {where_sql}
        ORDER BY id ASC
        {lim}
    """
    params = (test_stock,) if test_stock else None
    return db.query_all(sql, params)


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    s = text.strip()
    if s.startswith("```"):
        lines = s.split("\n")
        s = "\n".join(lines[1:] if lines else [])
        if s.endswith("```"):
            s = s[:-3]
    start = s.find("{")
    end = s.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(s[start : end + 1])
        except Exception:
            return None
    return None


def _extract_score_by_keywords(raw: Dict[str, Any]) -> Optional[float]:
    txt = " ".join(
        [
            str(raw.get("invest_status", "")),
            str(raw.get("action", "")),
            str(raw.get("reason", "")),
            str(raw.get("remark", "")),
        ]
    )
    mapping = [
        ("强烈推荐", 8.5),
        ("值得投资", 7.0),
        ("买入", 7.0),
        ("值得观察", 5.0),
        ("观察", 5.0),
        ("暂不投资", 3.0),
        ("放弃", 2.0),
    ]
    for k, v in mapping:
        if k in txt:
            return v
    return None


def normalize_result(raw: Dict[str, Any], fallback_name: str, fallback_code: str) -> Tuple[float, str, Optional[float]]:
    score = raw.get("score", 0)
    if score in [None, ""]:
        tenbagger = raw.get("tenbagger_potential_score")
        if tenbagger not in [None, ""]:
            score = tenbagger
    if isinstance(score, str):
        m = re.search(r"\d+(\.\d+)?", score)
        score = float(m.group()) if m else 0.0
    try:
        score = float(score)
    except Exception:
        score = -1.0
    if score > 10.0:
        score = score / 10.0
    if score < 0:
        kw_score = _extract_score_by_keywords(raw)
        score = kw_score if kw_score is not None else 0.0
    score = max(0.0, min(10.0, score))

    confidence = raw.get("confidence")
    if confidence in [None, ""] and raw.get("confidence_score") not in [None, ""]:
        confidence = raw.get("confidence_score")
    try:
        confidence = float(confidence) if confidence not in [None, ""] else None
    except Exception:
        confidence = None
    if confidence is not None:
        if confidence > 1.0:
            confidence = confidence / 100.0
        confidence = max(0.0, min(1.0, confidence))

    remark = str(raw.get("remark", "")).strip()
    if not remark:
        adv = str(raw.get("advantages", "")).strip()
        risk = str(raw.get("risks", "")).strip()
        if adv or risk:
            remark = f"优势：{adv}；风险：{risk}".strip("；")
    if not remark:
        remark = f"{fallback_name or fallback_code}：信息不足，建议结合基本面与趋势再判断。"

    # 控制在500字内
    if len(remark) > 500:
        remark = remark[:500]
    return score, remark, confidence


def build_prompt(stock: Dict[str, Any]) -> str:
    tech = stock.get("tech", {}) or {}
    finance = stock.get("finance_3y", {}) or {}
    income = stock.get("income_3y", {}) or {}
    balancesheet = stock.get("balancesheet_3y", {}) or {}
    cashflow = stock.get("cashflow_3y", {}) or {}
    news = stock.get("news_summary", "") or "暂无结构化消息摘要"
    tech_json = json.dumps(tech, ensure_ascii=False)
    finance_json = json.dumps(finance, ensure_ascii=False)
    income_json = json.dumps(income, ensure_ascii=False)
    bs_json = json.dumps(balancesheet, ensure_ascii=False)
    cf_json = json.dumps(cashflow, ensure_ascii=False)
    industry_strength_score = stock.get("industry_strength_score", None)
    industry_strength_raw = stock.get("industry_strength_raw", None)
    candidate_score = stock.get("candidate_score", None)
    return (
        "你是一个严格的金融分析师。请根据用户的提问和提供的公司财报信息，对公司的基本面进行0-10分的打分。"
        "请严格返回JSON，不要输出任何额外文本，格式如下：\n"
        '{"score": 0-10的小数或整数, "remark": "不超过500字，必须同时包含优势和风险"}\n\n'
        f"股票代码: {stock.get('ts_code','')}\n"
        f"股票名称: {stock.get('name','')}\n"
        f"行业: {stock.get('industry','')}\n"
        f"突破日期: {stock.get('break_date','')}\n"
        "要求：\n"
        "1) score满分10分；\n"
        "2) remark必须包含“优势”和“风险”两个部分；评分需考虑盈利能力、行业地位、风险因素；\n"
        "3) remark总长度不超过500字；\n"
        "4) 如果信息有限，明确说明不确定性。\n\n"
        f"行业强度分位(0-1): {industry_strength_score}\n"
        f"行业强度原始分: {industry_strength_raw}\n"
        f"候选评分(规则分): {candidate_score}\n"
        f"技术面摘要(压缩): {tech_json}\n"
        f"近三年财务指标摘要(压缩): {finance_json}\n"
        f"近三年利润表摘要(压缩): {income_json}\n"
        f"近三年资产负债表摘要(压缩): {bs_json}\n"
        f"近三年现金流量表摘要(压缩): {cf_json}\n"
        f"市场消息摘要(压缩): {news}"
    )


def _call_minimax(messages: List[Dict[str, str]], model_name: Optional[str] = None) -> Optional[str]:
    api_key = MiniMaxConfig.API_KEY
    if not api_key:
        raise ValueError("MiniMax API Key 未设置，请配置 MINIMAX_API_KEY 或 todolist/config.json")
    payload = {
        "model": model_name or MiniMaxConfig.MODEL_NAME,
        "messages": messages,
        "temperature": 0.2,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    for attempt in range(MiniMaxConfig.MAX_RETRIES):
        try:
            resp = requests.post(
                MiniMaxConfig.API_URL,
                headers=headers,
                json=payload,
                timeout=MiniMaxConfig.REQUEST_TIMEOUT,
            )
            if resp.status_code == 200:
                data = resp.json()
                choices = data.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "")
                return None
            logger.warning("MiniMax API 返回错误 %s: %s", resp.status_code, resp.text[:200])
        except Exception as e:
            logger.warning("MiniMax API 调用异常: %s", e)
        if attempt < MiniMaxConfig.MAX_RETRIES - 1:
            time.sleep(MiniMaxConfig.RETRY_DELAY)
    return None


def analyze_one(
    stock: Dict[str, Any],
    provider: str,
    qianwen_api: Optional[QianwenAPI] = None,
    minimax_model: Optional[str] = None,
    verbose: bool = False,
) -> Tuple[float, str, Optional[float], str]:
    prompt = build_prompt(stock)
    messages = [{"role": "user", "content": prompt}]
    if provider == "minimax":
        raw_text = _call_minimax(messages, model_name=minimax_model)
    else:
        if qianwen_api is None:
            raise ValueError("qianwen_api 不能为空")
        raw_text = qianwen_api._call_api(messages, temperature=0.2)
    if verbose:
        logger.info("raw response for %s: %s", stock.get("ts_code"), (raw_text or "")[:400])
    parsed = _extract_json(raw_text or "")
    if not parsed:
        parsed = {"score": 0, "remark": "优势：数据不足；风险：模型未返回结构化结果，建议人工复核。"}
    score, remark, conf = normalize_result(parsed, str(stock.get("name", "")), str(stock.get("ts_code", "")))
    return score, remark, conf, (raw_text or "")


def to_tushare_ts_code(ts_code: str) -> str:
    raw = str(ts_code or "").strip().upper()
    if raw.endswith(".SH") or raw.endswith(".SZ"):
        return raw
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) != 6:
        return raw
    if digits.startswith(("6", "9", "5")):
        return f"{digits}.SH"
    return f"{digits}.SZ"


def finance_cache_file(ts_code: str, finance_dir: str, suffix: str = "finance") -> str:
    tc = to_tushare_ts_code(ts_code)
    code, ex = tc.split(".") if "." in tc else (tc, "SZ")
    return os.path.join(finance_dir, f"{code}_{ex}_{suffix}.csv")


def _safe_num(v) -> Optional[float]:
    try:
        if v is None or (isinstance(v, float) and (v != v)):
            return None
        return float(v)
    except Exception:
        return None


def _parse_end_date_series(s):
    import pandas as pd

    if s is None:
        return pd.Series(dtype="datetime64[ns]")
    raw = s.astype(str).str.strip()

    # 先抽取8位日期数字，避免科学计数法/超长数值触发 pandas 的 remainder warning
    ymd = raw.str.extract(r"^\D*(\d{8})\D*$", expand=False)
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="invalid value encountered in remainder",
            category=RuntimeWarning,
        )
        out = pd.to_datetime(ymd, format="%Y%m%d", errors="coerce")

    # 对无法按 YYYYMMDD 解析的数据，再做一次受控兜底（仅 yyyy-mm-dd / yyyy/mm/dd）
    mask = out.isna()
    if mask.any():
        fallback = raw[mask].replace({"": None, "nan": None, "None": None, "NaT": None})
        safe_fmt = fallback.str.match(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}$", na=False)
        if safe_fmt.any():
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message="invalid value encountered in remainder",
                    category=RuntimeWarning,
                )
                out2 = pd.to_datetime(fallback[safe_fmt], errors="coerce")
            out.loc[out[mask].index[safe_fmt]] = out2
    return out


def _merge_finance_frames(old_df, new_df):
    import pandas as pd

    if old_df is None or old_df.empty:
        merged = new_df.copy() if new_df is not None else pd.DataFrame()
    elif new_df is None or new_df.empty:
        merged = old_df.copy()
    else:
        merged = pd.concat([old_df, new_df], ignore_index=True, sort=False)

    if merged.empty:
        return merged

    if "end_date" in merged.columns:
        merged["_end_date_dt"] = _parse_end_date_series(merged["end_date"])
        sort_cols = ["_end_date_dt"]
        if "ann_date" in merged.columns:
            merged["_ann_date_dt"] = _parse_end_date_series(merged["ann_date"])
            sort_cols.append("_ann_date_dt")
        merged = merged.sort_values(sort_cols, ascending=False)
        if "end_date" in merged.columns:
            merged = merged.drop_duplicates(subset=["end_date"], keep="first")
        merged = merged.drop(columns=[c for c in ["_end_date_dt", "_ann_date_dt"] if c in merged.columns], errors="ignore")
    else:
        merged = merged.drop_duplicates()

    return merged.reset_index(drop=True)


def _extract_3y_latest_rows(df: Optional["pd.DataFrame"]) -> Optional["pd.DataFrame"]:
    import pandas as pd

    if df is None or df.empty or "end_date" not in df.columns:
        return None
    d = df.copy()
    d["end_date"] = _parse_end_date_series(d["end_date"])
    d = d.dropna(subset=["end_date"])
    d = d[d["end_date"].dt.year.between(1990, 2100)]
    if d.empty:
        return None
    d["year"] = d["end_date"].dt.year
    d = d.sort_values("end_date", ascending=False).groupby("year", as_index=False).head(1)
    d = d.sort_values("end_date", ascending=False).head(3).reset_index(drop=True)
    return d


def compress_financial_3y(df: Optional["pd.DataFrame"]) -> Dict[str, Any]:
    import pandas as pd

    d = _extract_3y_latest_rows(df)
    if d is None or d.empty:
        return {"has_data": False}
    latest = d.iloc[0]

    def pick(col):
        return _safe_num(latest[col]) if col in d.columns else None

    # 优先使用财务指标表字段
    roe = pick("roe")
    roe_dt = pick("roe_dt")
    gross_margin = pick("grossprofit_margin") or pick("gross_margin")
    net_margin = pick("netprofit_margin") or pick("net_margin")
    debt_to_assets = pick("debt_to_assets")
    ocf_to_or = pick("ocf_to_or")
    yoy_rev = pick("q_sales_yoy") or pick("tr_yoy")
    yoy_np = pick("q_netprofit_yoy") or pick("netprofit_yoy")

    # 三年趋势（只对能取到的列）
    trend = {}
    for c in ["roe", "roe_dt", "grossprofit_margin", "netprofit_margin", "debt_to_assets", "ocf_to_or"]:
        if c in d.columns:
            vals = [v for v in d[c].map(_safe_num).tolist() if v is not None]
            if len(vals) >= 2:
                trend[c] = round(vals[0] - vals[-1], 4)

    return {
        "has_data": True,
        "years": [int(y) for y in d["year"].tolist()],
        "latest_end_date": latest["end_date"].date().isoformat() if pd.notnull(latest["end_date"]) else None,
        "roe": roe,
        "roe_dt": roe_dt,
        "gross_margin": gross_margin,
        "net_margin": net_margin,
        "debt_to_assets": debt_to_assets,
        "ocf_to_or": ocf_to_or,
        "yoy_revenue": yoy_rev,
        "yoy_netprofit": yoy_np,
        "trend_3y_delta": trend,
    }


def compress_income_3y(df: Optional["pd.DataFrame"]) -> Dict[str, Any]:
    d = _extract_3y_latest_rows(df)
    if d is None or d.empty:
        return {"has_data": False}
    latest = d.iloc[0]
    out = {
        "has_data": True,
        "years": [int(y) for y in d["year"].tolist()],
        "latest_end_date": latest["end_date"].date().isoformat(),
        "revenue": _safe_num(latest.get("revenue")),
        "operate_profit": _safe_num(latest.get("operate_profit")),
        "total_profit": _safe_num(latest.get("total_profit")),
        "n_income_attr_p": _safe_num(latest.get("n_income_attr_p")),
        "basic_eps": _safe_num(latest.get("basic_eps")),
        "revenue_yoy": _safe_num(latest.get("total_revenue_yoy") or latest.get("or_yoy")),
        "netprofit_yoy": _safe_num(latest.get("netprofit_yoy")),
    }
    return out


def compress_balancesheet_3y(df: Optional["pd.DataFrame"]) -> Dict[str, Any]:
    d = _extract_3y_latest_rows(df)
    if d is None or d.empty:
        return {"has_data": False}
    latest = d.iloc[0]
    total_assets = _safe_num(latest.get("total_assets"))
    total_liab = _safe_num(latest.get("total_liab"))
    total_hldr_eqy_exc_min_int = _safe_num(latest.get("total_hldr_eqy_exc_min_int"))
    debt_ratio = None
    if total_assets and total_liab is not None and total_assets != 0:
        debt_ratio = round(total_liab / total_assets * 100.0, 4)
    return {
        "has_data": True,
        "years": [int(y) for y in d["year"].tolist()],
        "latest_end_date": latest["end_date"].date().isoformat(),
        "total_assets": total_assets,
        "total_liab": total_liab,
        "equity_parent": total_hldr_eqy_exc_min_int,
        "money_cap": _safe_num(latest.get("money_cap")),
        "accounts_receiv": _safe_num(latest.get("accounts_receiv")),
        "inventories": _safe_num(latest.get("inventories")),
        "debt_to_assets_pct": debt_ratio,
    }


def compress_cashflow_3y(df: Optional["pd.DataFrame"]) -> Dict[str, Any]:
    d = _extract_3y_latest_rows(df)
    if d is None or d.empty:
        return {"has_data": False}
    latest = d.iloc[0]
    n_cashflow_act = _safe_num(latest.get("n_cashflow_act"))
    n_income = _safe_num(latest.get("n_income"))
    cf_to_np = None
    if n_income and n_income != 0 and n_cashflow_act is not None:
        cf_to_np = round(n_cashflow_act / n_income, 4)
    return {
        "has_data": True,
        "years": [int(y) for y in d["year"].tolist()],
        "latest_end_date": latest["end_date"].date().isoformat(),
        "n_cashflow_act": n_cashflow_act,
        "n_cashflow_inv_act": _safe_num(latest.get("n_cashflow_inv_act")),
        "n_cash_flows_fnc_act": _safe_num(latest.get("n_cash_flows_fnc_act")),
        "n_incr_cash_cash_equ": _safe_num(latest.get("n_incr_cash_cash_equ")),
        "cf_to_netprofit": cf_to_np,
    }


def _load_csv_or_none(path: str):
    import pandas as pd

    if not os.path.exists(path):
        return None
    try:
        return pd.read_csv(path)
    except Exception:
        return None


def load_or_fetch_finance_3y(
    ts_code: str,
    finance_dir: str,
    force_refresh: bool = False,
    target_end_date: str = TARGET_FINANCE_END_DATE,
) -> Dict[str, Any]:
    import pandas as pd
    from datetime import datetime

    os.makedirs(finance_dir, exist_ok=True)
    path = finance_cache_file(ts_code, finance_dir)
    target_dt = _parse_end_date_series(pd.Series([target_end_date])).iloc[0]

    cache_df = None
    if (not force_refresh) and os.path.exists(path):
        try:
            cache_df = pd.read_csv(path)
        except Exception:
            cache_df = None

    # 判断缓存是否覆盖到目标报告期（默认2026Q1）
    good_cache = False
    if cache_df is not None and (not cache_df.empty) and ("end_date" in cache_df.columns):
        ed = _parse_end_date_series(cache_df["end_date"])
        ed = ed[ed.dt.year.between(1990, 2100)]
        max_ed = ed.max()
        if pd.notnull(max_ed) and pd.notnull(target_dt):
            good_cache = max_ed >= target_dt

    if not good_cache:
        fetcher = TushareFetcher()
        ts_code_full = to_tushare_ts_code(ts_code)
        start_date = "20230101"
        end_date = target_end_date
        df = fetcher.fetch_fina_indicator(ts_code_full, start_date=start_date, end_date=end_date, days=7)
        if df is not None and not df.empty:
            merged = _merge_finance_frames(cache_df, df)
            try:
                merged.to_csv(path, index=False, encoding="utf-8-sig")
                cache_df = merged
            except Exception:
                cache_df = merged
        else:
            cache_df = cache_df if cache_df is not None else pd.DataFrame()

    return compress_financial_3y(cache_df)


def load_or_fetch_statement_3y(
    ts_code: str,
    finance_dir: str,
    statement: str,
    force_refresh: bool = False,
    target_end_date: str = TARGET_FINANCE_END_DATE,
):
    import pandas as pd

    fetch_map = {
        "income": "fetch_income",
        "balancesheet": "fetch_balancesheet",
        "cashflow": "fetch_cashflow",
    }
    if statement not in fetch_map:
        return {"has_data": False}

    os.makedirs(finance_dir, exist_ok=True)
    path = finance_cache_file(ts_code, finance_dir, suffix=statement)
    target_dt = _parse_end_date_series(pd.Series([target_end_date])).iloc[0]

    cache_df = None if force_refresh else _load_csv_or_none(path)
    good_cache = False
    if cache_df is not None and (not cache_df.empty) and ("end_date" in cache_df.columns):
        ed = _parse_end_date_series(cache_df["end_date"])
        ed = ed[ed.dt.year.between(1990, 2100)]
        max_ed = ed.max()
        if pd.notnull(max_ed) and pd.notnull(target_dt):
            good_cache = max_ed >= target_dt

    if not good_cache:
        fetcher = TushareFetcher()
        ts_code_full = to_tushare_ts_code(ts_code)
        start_date = "20230101"
        end_date = target_end_date
        fetch_fn = getattr(fetcher, fetch_map[statement], None)
        df = fetch_fn(ts_code_full, start_date=start_date, end_date=end_date, days=7) if fetch_fn else None
        if df is not None and not df.empty:
            merged = _merge_finance_frames(cache_df, df)
            try:
                merged.to_csv(path, index=False, encoding="utf-8-sig")
                cache_df = merged
            except Exception:
                cache_df = merged
        else:
            cache_df = cache_df if cache_df is not None else pd.DataFrame()

    if statement == "income":
        return compress_income_3y(cache_df)
    if statement == "balancesheet":
        return compress_balancesheet_3y(cache_df)
    return compress_cashflow_3y(cache_df)


def build_stock_context(stock: Dict[str, Any], finance_dir: str, force_refresh: bool = False) -> Dict[str, Any]:
    ts_code = str(stock.get("ts_code", ""))
    market = str(stock.get("market", "A股"))
    # 技术面压缩
    lf = LocalFeatureBuilder()
    tech = lf.build(ts_code)
    # 财务面压缩（近三年）
    finance_3y = load_or_fetch_finance_3y(ts_code, finance_dir=finance_dir, force_refresh=force_refresh)
    income_3y = load_or_fetch_statement_3y(ts_code, finance_dir=finance_dir, statement="income", force_refresh=force_refresh)
    balancesheet_3y = load_or_fetch_statement_3y(
        ts_code, finance_dir=finance_dir, statement="balancesheet", force_refresh=force_refresh
    )
    cashflow_3y = load_or_fetch_statement_3y(ts_code, finance_dir=finance_dir, statement="cashflow", force_refresh=force_refresh)
    # 消息先留接口，默认空摘要
    return {
        **stock,
        "market": market,
        "tech": tech,
        "finance_3y": finance_3y,
        "income_3y": income_3y,
        "balancesheet_3y": balancesheet_3y,
        "cashflow_3y": cashflow_3y,
        "news_summary": "暂无结构化消息摘要（可后续接入tushare/news接口增量摘要）",
    }


def update_one(
    db: Database,
    stock_id: int,
    score: float,
    remark: str,
    provider: str,
    model_name: str,
    confidence: Optional[float],
    raw_response: str,
) -> None:
    db.execute(
        """
        UPDATE stock_pool_ma120
        SET score = %s,
            remark = %s,
            raw_provider = %s,
            raw_model = %s,
            confidence = %s,
            raw_response = %s,
            research_status = 1,
            updated_at = NOW()
        WHERE id = %s
        """,
        (score, remark, provider, model_name, confidence, raw_response[:8000], stock_id),
    )


def run(
    only_unscored: bool,
    only_unresearched: bool,
    limit: int,
    delay: float,
    verbose: bool,
    test_stock: str = "",
    dry_run: bool = False,
    finance_dir: str = DEFAULT_FINANCE_DIR,
    force_refresh_finance: bool = False,
    provider: str = "qianwen",
    minimax_model: str = "",
) -> Dict[str, int]:
    stats = {"total": 0, "scored": 0, "failed": 0}
    with Database() as db:
        ensure_columns(db)
        targets = fetch_targets(
            db,
            only_unscored=only_unscored,
            only_unresearched=only_unresearched,
            limit=limit,
            test_stock=test_stock,
        )
        stats["total"] = len(targets)
        if not targets:
            logger.info("没有可分析的A股标的")
            return stats

        qianwen_api = QianwenAPI(model=QianwenConfig.MODEL_PLUS) if provider == "qianwen" else None
        for i, s in enumerate(targets, 1):
            try:
                payload = build_stock_context(s, finance_dir=finance_dir, force_refresh=force_refresh_finance)
                if verbose:
                    logger.info("financial_summary(%s): %s", s.get("ts_code"), json.dumps(payload.get("finance_3y", {}), ensure_ascii=False))
                    logger.info("income_summary(%s): %s", s.get("ts_code"), json.dumps(payload.get("income_3y", {}), ensure_ascii=False))
                    logger.info(
                        "balancesheet_summary(%s): %s",
                        s.get("ts_code"),
                        json.dumps(payload.get("balancesheet_3y", {}), ensure_ascii=False),
                    )
                    logger.info("cashflow_summary(%s): %s", s.get("ts_code"), json.dumps(payload.get("cashflow_3y", {}), ensure_ascii=False))
                    logger.info("tech_summary(%s): %s", s.get("ts_code"), json.dumps(payload.get("tech", {}), ensure_ascii=False))
                score, remark, confidence, raw_resp = analyze_one(
                    payload,
                    provider=provider,
                    qianwen_api=qianwen_api,
                    minimax_model=(minimax_model or None),
                    verbose=verbose,
                )
                if not dry_run:
                    model_name = QianwenConfig.MODEL_PLUS if provider == "qianwen" else (minimax_model or MiniMaxConfig.MODEL_NAME)
                    update_one(
                        db,
                        int(s["id"]),
                        score,
                        remark,
                        provider=provider,
                        model_name=model_name,
                        confidence=confidence,
                        raw_response=raw_resp,
                    )
                    db.commit()
                stats["scored"] += 1
                logger.info("[%d/%d] %s score=%.2f confidence=%s provider=%s", i, len(targets), s.get("ts_code"), score, confidence, provider)
                logger.info("analysis remark(%s): %s", s.get("ts_code"), remark)
            except Exception as e:
                db.rollback()
                stats["failed"] += 1
                logger.exception("[%d/%d] %s 分析失败: %s", i, len(targets), s.get("ts_code"), e)
            if i < len(targets) and delay > 0:
                time.sleep(delay)
    return stats


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    p = argparse.ArgumentParser(description="使用千问批量评分 stock_pool_ma120 的A股并回写 score/remark")
    p.add_argument("--limit", type=int, default=0, help="最多处理多少条，0表示不限制")
    p.add_argument("--only-unscored", action="store_true", help="仅处理 score 为空或0的记录")
    p.add_argument("--only-unresearched", action="store_true", help="仅处理 research_status != 1 的记录")
    p.add_argument("--delay", type=float, default=1.0, help="每次调用间隔秒数")
    p.add_argument("--verbose", action="store_true", help="打印模型原始返回片段")
    p.add_argument("--test-stock", default="", help="测试单只股票代码，如 600036")
    p.add_argument("--dry-run", action="store_true", help="只分析不写库（配合 --test-stock 使用）")
    p.add_argument("--finance-dir", default=DEFAULT_FINANCE_DIR, help="财务缓存目录")
    p.add_argument("--force-refresh-finance", action="store_true", help="强制刷新财务缓存")
    p.add_argument("--provider", choices=["qianwen", "minimax"], default="qianwen", help="评分模型提供方")
    p.add_argument("--minimax-model", default="", help="MiniMax 模型名，默认读配置")
    args = p.parse_args()

    if args.test_stock:
        logger.info("单股票测试模式: %s", args.test_stock)

    stats = run(
        only_unscored=args.only_unscored,
        only_unresearched=args.only_unresearched,
        limit=args.limit,
        delay=args.delay,
        verbose=args.verbose,
        test_stock=args.test_stock.strip(),
        dry_run=args.dry_run,
        finance_dir=args.finance_dir,
        force_refresh_finance=args.force_refresh_finance,
        provider=args.provider,
        minimax_model=args.minimax_model.strip(),
    )
    print(json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
    main()
    # python cy_ai/score_stock_pool_ma120_qianwen.py \
    #        --test-stock 600036 \
    #                     --verbose
